"""밸류에이션 가정 타당성 검사 (assumption sanity gates).

ingest/validators.py 의 tie-out(데이터가 원본과 일치하나? — 라운드트립 정합)과 달리,
여기서는 *가정의 경제적 타당성*(가정이 말이 되나? — 판단 게이트)을 결정론적으로 검사한다.
같은 ValidationReport/Finding/Severity 인프라를 재사용하되 관심사를 분리한다.

근거 문서(docs/reference/):
  - 영구성장률_PGR_적합성.md  : TV 비중 ~75%, PGR ≤ GDP 철칙, PGR < WACC(Gordon 수렴)
  - 베타_Bloomberg_vs_KICPA.md : β provenance(source·market) 필수
  - 감사인검토_WACC방법론.md : 감사인 검토 체크리스트

감사인 트랙 자동 경고:
  ① PGR ≥ WACC           → FAIL (Gordon 발산: TV 음수/무한대, 수학적 무효)
  ② PGR > 장기 GDP성장률  → WARN (영구히 경제 추월 = 비현실)
  ③ TV 비중 과다           → WARN (관행 ~75% 초과·과대평가 편중)
  ④ β provenance 부재      → WARN (시장선택 근거 추적 불가)
"""
from __future__ import annotations

import math

from ingest.validators import Finding, Severity, ValidationReport

from .models import DcfResult, DcfSpineInput
from .wacc import WaccInputs

# 장기 실질 경제성장 전망(한국 성숙경제 관행치). 글로벌·고성장국이면 상위에서 조정.
DEFAULT_LONG_TERM_GDP = 0.02
# TV(영구가치) 비중 관행 상단. 관행 최빈 ~75%, anthropic audit-xls 도 75% yellow flag
# → 0.90 에서 하향(2026-07-17, 벤치마크 채택).
TV_WEIGHT_WARN = 0.75
# 재투자 모델 없이(D&A=CAPEX, ΔNWC=0) 이 값을 넘는 PGR 은 TV 과대계상 위험.
# 근거: FCFF_T = NOPLAT_T·(1−g/ROIC) 이나 엔진은 재투자율 0 가정 → g 클수록 왜곡↑.
REINVESTMENT_FREE_PGR = 0.02


def check_terminal_growth(
    pgr: float,
    wacc: float,
    *,
    long_term_gdp: float = DEFAULT_LONG_TERM_GDP,
    reinvestment_modeled: bool = False,
    report: ValidationReport | None = None,
) -> list[Finding]:
    """영구성장률 타당성: Gordon 수렴(PGR<WACC) + 경제성 상한(PGR≤GDP).

    - PGR ≥ WACC : FAIL. TV = FCFF_T/(WACC−g) 가 음수/무한대 → 수학적 무효.
    - PGR > GDP  : WARN. 기업이 영구히 경제성장률을 추월한다는 비현실적 가정.

    reinvestment_modeled: 터미널 재투자/정규화 WC(terminal_wc_ratio·reinvestment_rate·
        fcff_override)가 반영됐으면 True → F1 과대계상 WARN 을 PASS 로 승격.
    """
    out: list[Finding] = []
    if pgr >= wacc:
        out.append(Finding(
            "pgr_vs_wacc", Severity.FAIL,
            f"PGR({pgr:.2%}) ≥ WACC({wacc:.2%}) — Gordon 발산(TV 무효)",
            {"pgr": pgr, "wacc": wacc},
        ))
    elif wacc - pgr < 0.01:
        out.append(Finding(
            "pgr_vs_wacc", Severity.WARN,
            f"WACC−PGR 스프레드 {wacc - pgr:.2%} < 1%p — TV 극도로 민감",
            {"pgr": pgr, "wacc": wacc, "spread": wacc - pgr},
        ))
    else:
        out.append(Finding(
            "pgr_vs_wacc", Severity.PASS,
            f"PGR({pgr:.2%}) < WACC({wacc:.2%}) 수렴 OK",
            {"pgr": pgr, "wacc": wacc},
        ))

    if pgr > long_term_gdp:
        out.append(Finding(
            "pgr_vs_gdp", Severity.WARN,
            f"PGR({pgr:.2%}) > 장기 GDP({long_term_gdp:.2%}) — 영구 경제추월 비현실, 근거 필요",
            {"pgr": pgr, "long_term_gdp": long_term_gdp},
        ))
    else:
        out.append(Finding(
            "pgr_vs_gdp", Severity.PASS,
            f"PGR({pgr:.2%}) ≤ 장기 GDP({long_term_gdp:.2%})",
            {"pgr": pgr, "long_term_gdp": long_term_gdp},
        ))

    # F1: 재투자 모델 없이 PGR 이 높으면 terminal FCFF(=NOPLAT) 과대 → TV 과대계상.
    if pgr > REINVESTMENT_FREE_PGR:
        if reinvestment_modeled:
            out.append(Finding(
                "terminal_reinvestment", Severity.PASS,
                f"PGR({pgr:.2%}) > {REINVESTMENT_FREE_PGR:.0%} 이나 터미널 재투자/정규화 WC "
                f"반영됨 — 과대계상 방어",
                {"pgr": pgr, "threshold": REINVESTMENT_FREE_PGR, "modeled": True},
            ))
        else:
            out.append(Finding(
                "terminal_reinvestment", Severity.WARN,
                f"PGR({pgr:.2%}) > {REINVESTMENT_FREE_PGR:.0%} 이나 재투자 미반영(D&A=CAPEX, "
                f"ΔWC=0) — TV 과대계상 위험(terminal_wc_ratio 또는 재투자율 g/ROIC 필요)",
                {"pgr": pgr, "threshold": REINVESTMENT_FREE_PGR, "modeled": False},
            ))

    if report is not None:
        for f in out:
            report.add(f)
    return out


def check_terminal_value_weight(
    result: DcfResult,
    *,
    warn_threshold: float = TV_WEIGHT_WARN,
    report: ValidationReport | None = None,
) -> Finding:
    """TV 비중 = PV(TV) / EV 표기 + 과다편중 경고.

    영구가치가 전체가치의 대부분을 차지하면(관행 ~75%, 초과 시) 결과가 PGR·WACC 두
    파라미터에 과도하게 의존 → 과대평가 위험. 항상 비중을 detail 에 남긴다.
    """
    ev = result.enterprise_value
    weight = result.terminal_value_pv / ev if ev else float("nan")
    detail = {
        "tv_weight": weight,
        "pv_tv": result.terminal_value_pv,
        "pv_explicit": result.pv_explicit_sum,
        "enterprise_value": ev,
    }
    if ev <= 0:
        f = Finding("tv_weight", Severity.WARN, f"EV({ev:.0f}) ≤ 0 — TV 비중 산정 불가", detail)
    elif weight > warn_threshold:
        f = Finding("tv_weight", Severity.WARN,
                    f"TV 비중 {weight:.1%} > {warn_threshold:.0%} — 영구가치 과다편중(PGR·WACC 민감)",
                    detail)
    else:
        f = Finding("tv_weight", Severity.PASS, f"TV 비중 {weight:.1%}", detail)
    if report is not None:
        report.add(f)
    return f


def check_beta_provenance(
    inp: WaccInputs,
    *,
    report: ValidationReport | None = None,
) -> Finding:
    """β 출처·기준시장 provenance 존재 검사.

    β 는 "어느 시장(S&P500 vs KOSPI)의 체계적위험인가"의 선택이므로, source/market 이
    없으면 감사인이 시장선택 근거를 추적할 수 없다 → WARN.
    """
    missing = [k for k in ("beta_source", "beta_market") if getattr(inp, k) is None]
    if missing:
        f = Finding("beta_provenance", Severity.WARN,
                    f"β provenance 부재: {', '.join(missing)} — 시장선택 근거 추적 불가",
                    {"missing": missing})
    else:
        f = Finding("beta_provenance", Severity.PASS,
                    f"β provenance: {inp.beta_source}/{inp.beta_market}"
                    + (" (adjusted)" if inp.beta_adjusted else ""),
                    {"source": inp.beta_source, "market": inp.beta_market,
                     "adjusted": inp.beta_adjusted})
    if report is not None:
        report.add(f)
    return f


def check_beta_mrp_consistency(
    inp: WaccInputs,
    *,
    report: ValidationReport | None = None,
) -> Finding:
    """β 기준시장 == MRP 기준시장 정합 검사.

    핵심 원칙(베타 문서): β 와 그에 곱해질 MRP 는 **같은 시장**에서 와야 한다.
    KOSPI β 에 S&P500 MRP 를 곱하는 혼용은 체계적위험 이중기준 → WARN.
    두 market 이 모두 명시된 경우에만 판정(하나라도 없으면 provenance 검사가 담당).
    """
    bm, em = inp.beta_market, inp.mrp_market
    if bm is None or em is None:
        f = Finding("beta_mrp_consistency", Severity.PASS,
                    "β/MRP 시장 정합 판정보류(provenance 부족)",
                    {"beta_market": bm, "mrp_market": em})
    elif bm != em:
        f = Finding("beta_mrp_consistency", Severity.WARN,
                    f"β 시장({bm}) ≠ MRP 시장({em}) — 체계적위험 이중기준 혼용",
                    {"beta_market": bm, "mrp_market": em})
    else:
        f = Finding("beta_mrp_consistency", Severity.PASS,
                    f"β/MRP 시장 일치({bm})", {"beta_market": bm, "mrp_market": em})
    if report is not None:
        report.add(f)
    return f


def diagnose_dcf_gap(
    inp: DcfSpineInput,
    result: DcfResult,
    claimed_per_share: float,
    *,
    tol: float = 0.01,
    report: ValidationReport | None = None,
) -> Finding:
    """주장 주당가치와의 괴리를 **구조 버그 가설**로 진단 (audit-xls DCF 버그목록 승격).

    독립 재계산값과 주장값이 다를 때, 흔한 구조 오류 각각을 가정해 재계산해보고
    주장값이 어느 가설과 맞아떨어지는지 지목한다([[앤트로픽_금융스킬_벤치마크]] §2):
      end_year_discounting — mid-year 미적용(전 기간 0.5년 과다할인)
      tv_undiscounted      — 터미널가치를 현재가치로 안 끌어옴
      tv_missing           — 터미널가치 누락(명시기간만)
      nonop_missing        — 비영업자산 누락
      netdebt_ignored      — 순차입부채 미차감
    어느 가설도 안 맞으면 구조가 아닌 **가정 차이** → 민감도로 추적하라는 신호.
    """
    # ⚠️ n 은 **확장된 시계**(페이드 포함)여야 한다 — inp.revenue 는 미확장이라
    # 페이드 사용 시 (1+w)^(n−0.5) 역산이 (1+w)^fade_years 만큼 어긋난다.
    w, n = inp.wacc, len(result.pv_fcff)
    shares = inp.shares_outstanding or 1.0
    ev, pv_exp, pv_tv = (result.enterprise_value, result.pv_explicit_sum,
                         result.terminal_value_pv)

    def ps(ev_h: float, nonop: float | None = None, debt: float | None = None) -> float:
        """가설 EV → 주당가치. `_compute` 와 **동일한 브리지·단위**여야 비교가 성립한다
        (NCI 차감 + 백만원→원 환산 1e6). 둘 중 하나라도 빠지면 가설이 실제 주당가치와
        스케일이 달라 어떤 가설도 영원히 매칭되지 않는다."""
        nonop = inp.non_operating_assets if nonop is None else nonop
        debt = inp.net_debt if debt is None else debt
        return ((ev_h + nonop - debt - inp.non_controlling_interest)
                / shares * 1_000_000)

    # 할인 전 TV 는 result 에 이미 있다 — 역산(부동소수·기간 가정 이중오류)보다 정확하다.
    tv_undisc = result.terminal_value
    hypotheses = {
        "end_year_discounting": ps(ev / (1.0 + w) ** 0.5),
        "tv_undiscounted": ps(pv_exp + tv_undisc),
        "tv_missing": ps(pv_exp),
        "nonop_missing": ps(ev, nonop=0.0),
        "netdebt_ignored": ps(ev, debt=0.0),
    }
    base = result.per_share
    detail = {"claimed": claimed_per_share, "independent": base,
              "hypotheses": {k: round(v, 4) for k, v in hypotheses.items()}}

    if claimed_per_share and abs(base - claimed_per_share) / abs(claimed_per_share) <= tol:
        f = Finding("dcf_gap_diagnosis", Severity.PASS,
                    f"주장 {claimed_per_share:,.0f} ≈ 독립 {base:,.0f} (±{tol:.0%}) — 구조 일치",
                    detail)
    else:
        matches = {k: v for k, v in hypotheses.items()
                   if claimed_per_share and abs(v - claimed_per_share) / abs(claimed_per_share) <= tol}
        if matches:
            best = min(matches.items(),
                       key=lambda kv: abs(kv[1] - claimed_per_share))
            f = Finding("dcf_gap_diagnosis", Severity.WARN,
                        f"주장 {claimed_per_share:,.0f} 이 구조버그 가설 '{best[0]}' "
                        f"재계산({best[1]:,.0f})과 ±{tol:.0%} 일치 — 해당 구조 오류 의심",
                        {**detail, "matched": sorted(matches)})
        else:
            f = Finding("dcf_gap_diagnosis", Severity.WARN,
                        f"주장 {claimed_per_share:,.0f} vs 독립 {base:,.0f} — 구조 가설"
                        f" 전부 불일치 → 가정 차이(WACC·PGR·매출), 민감도로 추적",
                        detail)
    if report is not None:
        report.add(f)
    return f


# 추정 시계열 YoY 급변 경고 임계. 근거: 모델링_워크플로우_기초 "일부 연도 값·비중·YoY
# 가 튀는 경우 재검토" — 오류 발견 장치의 정본 규율을 결정론 검사로 승격.
YOY_JUMP_WARN = 0.50


def check_projection_smoothness(
    series: list[float],
    *,
    name: str = "revenue",
    jump_threshold: float = YOY_JUMP_WARN,
    report: ValidationReport | None = None,
) -> Finding:
    """추정 시계열의 YoY 급변(절대 |YoY| > 임계) 감지 — '튀는 연도' 재검토 신호.

    key-in 오류(0 하나 더)·driver 배선 실수가 흔히 특정 연도만 튀는 형태로 드러난다.
    급변이 실제 사업 이벤트(신제품 출시 등)라면 근거를 남기고 무시하면 됨(WARN).
    직전값이 0/음수인 구간은 YoY 정의 불가 — 건너뛴다.
    """
    jumps = []
    for i in range(1, len(series)):
        prev, cur = series[i - 1], series[i]
        if prev <= 0:
            continue
        yoy = cur / prev - 1.0
        if abs(yoy) > jump_threshold:
            jumps.append({"index": i, "prev": prev, "cur": cur, "yoy": yoy})
    if jumps:
        worst = max(jumps, key=lambda j: abs(j["yoy"]))
        f = Finding("projection_smoothness", Severity.WARN,
                    f"{name} 추정 YoY 급변 {len(jumps)}건(최대 {worst['yoy']:+.0%}, "
                    f"t={worst['index']}) — key-in/driver 오류 재검토 또는 사업 근거 기재",
                    {"series": name, "jumps": jumps, "threshold": jump_threshold})
    else:
        f = Finding("projection_smoothness", Severity.PASS,
                    f"{name} 추정 YoY 급변 없음(|YoY| ≤ {jump_threshold:.0%})",
                    {"series": name, "threshold": jump_threshold})
    if report is not None:
        report.add(f)
    return f


# WARA↔IRR↔WACC 정합 허용폭(±1%p). 근거: 감사인검토 — PPA calibration 에서
# 세 수익률의 reconciliation 은 감사인 검토 체크리스트 항목.
WARA_RECON_TOL = 0.01


def check_wara_irr_wacc(
    wara: float,
    irr: float,
    wacc: float,
    *,
    tol: float = WARA_RECON_TOL,
    report: ValidationReport | None = None,
) -> Finding:
    """WARA ↔ 거래 IRR ↔ WACC ±1%p reconciliation (감사인 체크리스트 승격).

    세 수익률이 벌어지면 무형자산 배분(WARA)·거래가격(IRR)·할인율(WACC) 중 하나가
    비정합 — Apple-to-Apple 위반 신호. WARA 산출 자체는 PPA 트랙(⏳), 이 검사는
    세 값이 주어지면 언제든 작동한다.
    """
    pairs = {"WARA-IRR": wara - irr, "IRR-WACC": irr - wacc, "WARA-WACC": wara - wacc}
    offenders = {k: d for k, d in pairs.items() if abs(d) > tol}
    detail = {"wara": wara, "irr": irr, "wacc": wacc, "tol": tol,
              "diffs": {k: round(d, 6) for k, d in pairs.items()}}
    if offenders:
        worst = max(offenders.items(), key=lambda kv: abs(kv[1]))
        f = Finding("wara_irr_wacc", Severity.WARN,
                    f"수익률 비정합 {worst[0]} {worst[1]:+.2%} (> ±{tol:.0%}) — "
                    f"무형배분/거래가/할인율 중 하나 재검토(Apple-to-Apple)",
                    detail)
    else:
        f = Finding("wara_irr_wacc", Severity.PASS,
                    f"WARA({wara:.2%})≈IRR({irr:.2%})≈WACC({wacc:.2%}) ±{tol:.0%} 내",
                    detail)
    if report is not None:
        report.add(f)
    return f


# 계절성 경고 임계: 최대 분기 비중 ≥40% (상대가치_계절성_LTM 보고서 문구 예시 기준).
SEASONALITY_WARN_SHARE = 0.40


def check_peer_seasonality(
    quarterly: list[float],
    *,
    name: str = "peer",
    threshold: float = SEASONALITY_WARN_SHARE,
    report: ValidationReport | None = None,
) -> Finding:
    """유사회사 분기 실적 계절성 검사 — 연환산(분기×4) 사용 가능 여부 게이트.

    최대 분기 비중 ≥ 임계(기본 40%) → WARN: 연환산 왜곡 위험, LTM 보정 또는
    peer 제외 권고. 합≤0(적자 등)이면 판정 불가 → WARN(유저 판단 큐 — LLM
    판단보조 원칙과 동일하게 자동 통과시키지 않는다).
    """
    from .relative import max_quarter_share
    share = max_quarter_share(quarterly)
    detail = {"peer": name, "max_quarter_share": share, "threshold": threshold,
              "last4": quarterly[-4:]}
    if share != share:                          # nan — 합≤0
        f = Finding("peer_seasonality", Severity.WARN,
                    f"{name}: 분기 합 ≤ 0 — 계절성 판정 불가(유저 확인 필요)", detail)
    elif share >= threshold:
        f = Finding("peer_seasonality", Severity.WARN,
                    f"{name}: 최대 분기 비중 {share:.0%} ≥ {threshold:.0%} — 계절성 강함, "
                    f"연환산(×4) 금지·LTM 보정 또는 peer 제외 검토", detail)
    else:
        f = Finding("peer_seasonality", Severity.PASS,
                    f"{name}: 최대 분기 비중 {share:.0%} < {threshold:.0%} — 연환산 허용",
                    detail)
    if report is not None:
        report.add(f)
    return f


# 운전자본 현금유출이 매출 대비 이 비중을 넘고 계속 악화하면 흑자도산 신호.
# 근거: DCF_교육_정본 §2.4 — 매출 성장에도 회전기일 악화로 FCFF 마이너스 전환.
WC_BURN_WARN_SHARE = 0.05


def check_working_capital_burn(
    revenue: list[float],
    delta_nwc_cash_adj: list[float],
    *,
    warn_share: float = WC_BURN_WARN_SHARE,
    report: ValidationReport | None = None,
) -> Finding:
    """운전자본 급증(흑자도산) 감지 — 매출은 성장하나 운전자본이 현금을 잠식하는 패턴.

    delta_nwc_cash_adj 는 FCFF 에 더해지는 현금조정(음수 = 운전자본 증가 = 현금유출).
    각 연도 drag[i] = −ΔNWC/매출 (양수 = 매출 대비 현금유출 비중). drag 가 매 연도
    악화(단조 증가)하고 최근값이 임계 초과면 WARN(회전기일 악화·분식·흑자도산 검토).
    매출 ≤ 0 구간은 건너뛴다.
    """
    drags = [(-delta_nwc_cash_adj[i] / revenue[i])
             for i in range(min(len(revenue), len(delta_nwc_cash_adj)))
             if revenue[i] > 0]
    detail = {"wc_drag": [round(d, 4) for d in drags], "warn_share": warn_share}
    worsening = len(drags) >= 2 and all(drags[i] > drags[i - 1] for i in range(1, len(drags)))
    if drags and worsening and drags[-1] > warn_share:
        f = Finding("working_capital_burn", Severity.WARN,
                    f"운전자본 현금유출 비중이 매 연도 악화({drags[0]:.1%}→{drags[-1]:.1%}, "
                    f"임계 {warn_share:.0%} 초과) — 회전기일 악화·흑자도산 신호, 회전율 가정 재검토",
                    detail)
    else:
        f = Finding("working_capital_burn", Severity.PASS,
                    "운전자본 현금유출 지속 악화 없음", detail)
    if report is not None:
        report.add(f)
    return f


# PGR 출처 유형(R2). derived=거시 앵커링(권장) / research=문서근거 / user=평가인 확정 /
# 없음=무근거 하드코드(감사 방어 불가).
PGR_SOURCE_KINDS = frozenset({"derived", "research", "user"})


def check_pgr_provenance(
    pgr: float,
    source: str | None = None,
    *,
    basis: str | None = None,
    report: ValidationReport | None = None,
) -> Finding:
    """영구성장률의 **출처** 검사(R2) — 값 자체가 아니라 근거의 존재를 본다.

    기존 `check_terminal_growth` 는 PGR 이 GDP 상한·WACC 수렴을 지키는지만 본다.
    그러나 PGR 은 TV 최고민감 파라미터라 **"어디서 온 숫자인가"** 가 별도로 중요하다.

    근거: 모델러스_통합모델_5.4 §2.3(e)·§4 D6 — 그 모델은 가정 5개 중 4개를 수식 파생
    (PGR = 장기 물가평균)으로 만들었으나 정작 WACC 만 무근거 하드코드였다. 우리는
    PGR 에 같은 함정이 생기지 않도록 출처를 게이트한다.

    `derived`(거시 앵커링, `macro_client.suggest_pgr_from_inflation`) 를 권장한다.
    """
    detail = {"pgr": pgr, "source": source, "basis": basis}
    if source is None:
        f = Finding("pgr_provenance", Severity.WARN,
                    f"PGR({pgr:.2%}) 출처 미기재 — 무근거 하드코드는 감사 방어 불가"
                    f"(권장: 장기 물가평균 앵커링)", detail)
    elif source not in PGR_SOURCE_KINDS:
        f = Finding("pgr_provenance", Severity.WARN,
                    f"PGR 출처유형 '{source}' 미인식 — {sorted(PGR_SOURCE_KINDS)} 중 하나여야",
                    detail)
    elif source == "derived" and not basis:
        f = Finding("pgr_provenance", Severity.WARN,
                    "PGR 출처가 derived 이나 산출식(basis) 부재 — 재현 불가", detail)
    else:
        f = Finding("pgr_provenance", Severity.PASS,
                    f"PGR({pgr:.2%}) 출처 {source}" + (f" — {basis}" if basis else ""),
                    detail)
    if report is not None:
        report.add(f)
    return f


def check_terminal_discount_convention(
    inp: DcfSpineInput,
    result: DcfResult,
    *,
    report: ValidationReport | None = None,
) -> Finding:
    """터미널 할인기간 컨벤션 **명시 선언** 검사(R15) + 대안의 금액 영향 정량.

    TV 는 명시기간 말 시점 가치이므로 `t = n`(기말) 로 할인하는 것도, 최종 명시연도
    현금흐름과 같은 mid-year 계수 `t = n−0.5` 를 재사용하는 것도 모두 통용된다
    (모델러스 정본은 후자 — `F39 = F40 × X10`, t=9.5). **어느 쪽도 틀리지 않지만
    선택은 반드시 밝혀야 한다** — 실측 영향이 주당 −2.1% 로 무시할 수 없다.

    미선언(`terminal_discount_period is None`)이면 WARN 하되, **대안 컨벤션을 적용했을
    때의 주당가치를 함께 계산해** 붙인다(잔소리가 아니라 판단 재료가 되도록).
    """
    # ⚠️ inp.n_years() 는 **페이드 확장 전** 명시 길이라 시계로 쓰면 안 된다
    # (페이드 5 + 명시 5 인데 5 로 잡혀 대안 기간이 틀어짐). 실제 시계·할인기간은
    # result 에서 역산한다 — _expand_fade 의 확장 로직을 여기서 재구현하지 않는 이점도 있다.
    n_eff = len(result.pv_fcff)
    explicit = inp.terminal_discount_period is not None
    if explicit:
        eff = float(inp.terminal_discount_period)
    else:
        last_factor = result.pv_factor[-1] if result.pv_factor else 1.0
        eff = (-math.log(last_factor) / math.log(1.0 + inp.wacc)
               if last_factor > 0 and inp.wacc > -1.0 else float(n_eff))
        # log/exp 왕복 노이즈 정리(2.5000000000000004 → 2.5). 표시·비교 양쪽에 쓰이므로
        # 여기서 한 번 정규화한다 — 정확일치 비교의 함정(§D1)을 우리가 반복하지 않도록.
        eff = round(eff, 6)
    # 대안: mid-year(소수) ↔ 기말(정수) 반대편
    alt = float(n_eff) if abs(eff - round(eff)) > 1e-9 else eff - 0.5

    shares = inp.shares_outstanding or 1
    if inp.wacc <= -1.0:
        # 검증 게이트가 잘못된 입력에 **예외를 던지면 audit 전체가 중단**된다
        # (WACC=-1 → 0 나눗셈, WACC<-1 → (음수)^소수 = complex → 포맷 단계 폭발).
        f = Finding("terminal_discount_convention", Severity.FAIL,
                    f"WACC({inp.wacc:.2%}) ≤ −100% — 할인계수 정의 불가",
                    {"wacc": inp.wacc, "terminal_discount_period": eff})
        if report is not None:
            report.add(f)
        return f
    pv_tv_alt = result.terminal_value * (1.0 / (1.0 + inp.wacc) ** alt)
    ev_alt = result.pv_explicit_sum + pv_tv_alt
    ps_alt = (ev_alt + inp.non_operating_assets - inp.net_debt
              - inp.non_controlling_interest) / shares * 1_000_000
    delta = (ps_alt / result.per_share - 1.0) if result.per_share else float("nan")

    # 시계와의 정합 — 명시 선언이 **확장된 전체 시계**를 반영하는가.
    # 통용되는 두 컨벤션은 t=n(기말)·t=n−0.5(mid-year) 뿐이다. 그 밖의 값은
    # 페이드를 켜기 전 시계 기준으로 선언해 놓고 잊은 경우가 대부분 —
    # 실측: 명시 5년 기준 4.5 선언 + 페이드 5년 → TV 를 t=4.5 로 할인해 **주당 +36%** 과대.
    sane = (float(n_eff), float(n_eff) - 0.5)
    consistent = any(abs(eff - c) < 1e-6 for c in sane)

    detail = {"terminal_discount_period": eff, "explicit": explicit,
              "alternative_period": alt, "per_share": result.per_share,
              "per_share_alternative": ps_alt, "delta_pct": delta,
              "horizon": n_eff, "consistent_with_horizon": consistent}
    if explicit and not consistent:
        ps_fix = ((result.pv_explicit_sum
                   + result.terminal_value / (1.0 + inp.wacc) ** (n_eff - 0.5)
                   + inp.non_operating_assets - inp.net_debt
                   - inp.non_controlling_interest) / shares * 1_000_000)
        detail["per_share_at_horizon_midyear"] = ps_fix
        f = Finding("terminal_discount_convention", Severity.WARN,
                    f"터미널 할인기간 t={eff:g} 가 시계 {n_eff}년과 불일치 — 통용 컨벤션은 "
                    f"t={n_eff:g}(기말)·t={n_eff - 0.5:g}(mid-year) 뿐. 페이드를 켜기 전 "
                    f"시계로 선언해 두지 않았는지 확인(t={n_eff - 0.5:g} 이면 주당 "
                    f"{ps_fix / result.per_share - 1:+.1%})", detail)
    elif explicit:
        f = Finding("terminal_discount_convention", Severity.PASS,
                    f"터미널 할인기간 t={eff:g} 명시 선언됨(시계 {n_eff}년 정합, "
                    f"대안 t={alt:g} 이면 주당 {delta:+.1%})", detail)
    else:
        f = Finding("terminal_discount_convention", Severity.WARN,
                    f"터미널 할인기간 미선언(암묵 t={eff:g}) — 대안 t={alt:g} 적용 시 "
                    f"주당 {delta:+.1%}. terminal_discount_period 로 명시하라", detail)
    if report is not None:
        report.add(f)
    return f


# 브리지 항목 상대 허용오차(R3). 같은 대상의 같은 항목이므로 사실상 완전일치여야 한다.
BRIDGE_RECON_TOL = 0.01


def check_bridge_consistency(
    dcf_bridge: dict,
    relative_bridge: dict,
    *,
    tol: float = BRIDGE_RECON_TOL,
    report: ValidationReport | None = None,
) -> Finding:
    """DCF ↔ 상대가치의 **지분 브리지 정의 일치** 검사(R3).

    두 방법이 같은 대상회사를 평가하면서 EV→지분 브리지를 다르게 잡으면, 두 결과의
    차이가 *밸류에이션 관점 차이*인지 *브리지 정의 차이*인지 분간할 수 없다 →
    교차검증 자체가 무의미해진다.

    근거(실측): 모델러스_통합모델_5.4 §4 D3 — 같은 워크북에서 DCF 는 단기금융자산
    392B 를 이자부자산에 포함하고 NCI 를 미차감(순현금 426B), Trading 은 vendor
    `CASH_LTM`(단기금융자산 제외)에 NCI 가산(순부채 27B). **지분가치 25% 차이.**

    비교 키(있는 것만): cash·short_term_investments·interest_bearing_debt·
    non_controlling_interest·preferred_stock·net_debt·non_operating_assets.
    한쪽에만 있는 키는 **누락**으로 본다(0 으로 간주하지 않는다 — 0 과 미정의는 다르다).
    """
    keys = sorted(set(dcf_bridge) | set(relative_bridge))
    mismatches: dict[str, dict] = {}
    missing: dict[str, str] = {}
    for k in keys:
        in_d, in_r = k in dcf_bridge, k in relative_bridge
        if not in_d or not in_r:
            missing[k] = "relative" if in_d else "dcf"
            continue
        a, b = float(dcf_bridge[k]), float(relative_bridge[k])
        scale = max(abs(a), abs(b), 1.0)
        if abs(a - b) / scale > tol:
            mismatches[k] = {"dcf": a, "relative": b, "delta": a - b}

    detail = {"mismatches": mismatches, "missing_in": missing, "tol": tol}
    if mismatches or missing:
        parts = [f"{k}(DCF {v['dcf']:,.0f} vs 상대 {v['relative']:,.0f}, Δ{v['delta']:+,.0f})"
                 for k, v in mismatches.items()]
        parts += [f"{k}(→{side} 누락)" for k, side in missing.items()]
        f = Finding("bridge_consistency", Severity.WARN,
                    "교차방법 지분브리지 불일치 — " + " · ".join(parts)
                    + " → 브리지 정의를 SSOT 로 통일해야 교차검증이 유효",
                    detail)
    else:
        f = Finding("bridge_consistency", Severity.PASS,
                    f"DCF·상대가치 지분브리지 정의 일치({len(keys)}항목)", detail)
    if report is not None:
        report.add(f)
    return f


_BRIDGE_COMPONENTS = ("net_debt", "non_operating_assets", "non_controlling_interest")


# 브리지 단위 — 두 방법이 서로 다른 스케일을 쓰므로 **선언 없이 비교하면 무조건 오탐**이다.
# DCF 스파인은 백만원(`per_share` 에 ×1e6), 상대가치 EV/EBITDA 경로는
# `(EV−net_debt)/shares` 에 환산이 없어 **원**을 전제한다(multiples.py:77-78).
_BRIDGE_UNIT_SCALE = {"KRW_mn": 1.0, "KRW": 1e-6}      # → 백만원 기준으로 정규화


def bridge_unit_scale(unit: str | None) -> float:
    """브리지 단위 → 백만원 환산계수. 미지정은 백만원(엔진 기본 단위)으로 본다."""
    u = (unit or "KRW_mn").strip()
    if u not in _BRIDGE_UNIT_SCALE:
        raise ValueError(f"알 수 없는 브리지 단위: {unit!r} "
                         f"({sorted(_BRIDGE_UNIT_SCALE)} 중 하나)")
    return _BRIDGE_UNIT_SCALE[u]


def bridge_net_position(bridge: dict) -> float:
    """지분브리지 **순포지션** = EV 에서 차감되는 총액.

        순포지션 = 순차입부채 − 비영업자산 + 비지배지분
        지분가치 = EV − 순포지션

    항목 분해 방식이 달라도(DCF 는 3분해, 상대가치는 net_debt 스칼라 1개) 이 스칼라는
    **항상 비교 가능**하다 → 오탐 없는 1차 신호.
    """
    scale = bridge_unit_scale(bridge.get("unit"))
    return (float(bridge.get("net_debt", 0.0))
            - float(bridge.get("non_operating_assets", 0.0))
            + float(bridge.get("non_controlling_interest", 0.0))) * scale


def check_cross_method_bridge(
    dcf_bridge: dict,
    relative_bridge: dict,
    *,
    tol: float = BRIDGE_RECON_TOL,
    report: ValidationReport | None = None,
) -> list[Finding]:
    """DCF ↔ 상대가치 **교차방법 정합**(R3 실배선) — 순포지션 + 주식수.

    두 방법의 주당가치를 나란히 놓고 비교하려면 **EV→지분 브리지와 주식수가 같아야**
    한다. 다르면 결과 차이가 밸류에이션 관점 차이인지 브리지 정의 차이인지 분간 불가
    → 교차검증이 무의미(모델러스 §4 D3: 같은 워크북에서 순현금 426B vs 순부채 27B).

    **판정 설계(오탐 방지)**: 상대가치는 보통 `net_debt` 스칼라 하나만 쓰고 비영업자산을
    거기에 접어 넣는다. 항목별로 곧장 대조하면 "비영업자산 누락" 오탐이 상시 발생하므로,
    1차 신호는 **순포지션 스칼라**로 잡는다. 상대가치가 항목을 명시 선언한 경우에만
    항목별 엄격 대조(`check_bridge_consistency`)를 추가로 돌린다.
    """
    out: list[Finding] = []

    # 단위를 백만원으로 정규화한 뒤 비교한다(선언 없으면 백만원 가정).
    a, b = bridge_net_position(dcf_bridge), bridge_net_position(relative_bridge)
    scale = max(abs(a), abs(b), 1.0)
    detail = {"dcf_net_position": a, "relative_net_position": b, "delta": a - b,
              "tol": tol, "dcf": dcf_bridge, "relative": relative_bridge,
              "unit": "KRW_mn",
              "dcf_unit": dcf_bridge.get("unit") or "KRW_mn",
              "relative_unit": relative_bridge.get("unit") or "KRW_mn"}
    if abs(a - b) / scale > tol:
        out.append(Finding(
            "cross_method_bridge", Severity.WARN,
            f"지분브리지 순포지션 불일치 — DCF {a:,.0f} vs 상대가치 {b:,.0f} "
            f"(Δ{a - b:+,.0f}) → 두 방법의 주당가치 비교가 무의미. 브리지 정의를 통일하라",
            detail))
    else:
        out.append(Finding(
            "cross_method_bridge", Severity.PASS,
            f"지분브리지 순포지션 일치({a:,.0f})", detail))

    # 주식수 — 브리지가 같아도 주식수가 다르면 주당가치가 어긋난다(자기주식·희석 처리 차이).
    ds, rs = dcf_bridge.get("shares_outstanding"), relative_bridge.get("shares_outstanding")
    # `if ds and rs` (truthiness) 로 쓰면 **0 주가 조용히 스킵**된다 — 미입력·0 은 가장
    # 흔한 불량 입력인데 정작 그때 게이트가 침묵하면 안 된다. None(미선언)만 판정보류.
    if ds is not None and rs is not None:
        ds, rs = float(ds), float(rs)
        if ds <= 0 or rs <= 0:
            out.append(Finding(
                "cross_method_shares", Severity.WARN,
                f"주식수 0/음수 — DCF {ds:,.0f}주 vs 상대가치 {rs:,.0f}주 "
                f"(미입력 확인 — 주당가치 산정 불가)",
                {"dcf_shares": ds, "relative_shares": rs}))
        elif abs(ds - rs) / max(abs(ds), abs(rs), 1.0) > tol:
            out.append(Finding(
                "cross_method_shares", Severity.WARN,
                f"주식수 불일치 — DCF {ds:,.0f}주 vs 상대가치 {rs:,.0f}주 "
                f"(자기주식 차감·희석 처리 차이 확인)",
                {"dcf_shares": ds, "relative_shares": rs}))
        else:
            out.append(Finding("cross_method_shares", Severity.PASS,
                               f"주식수 일치({ds:,.0f}주)",
                               {"dcf_shares": ds, "relative_shares": rs}))

    # 상대가치가 항목을 명시 선언했을 때만 항목별 엄격 대조(선언 안 했으면 오탐 방지 위해 생략)
    if any(k in relative_bridge for k in _BRIDGE_COMPONENTS[1:]):
        out.append(check_bridge_consistency(
            {k: dcf_bridge.get(k, 0.0) for k in _BRIDGE_COMPONENTS},
            {k: relative_bridge.get(k, 0.0) for k in _BRIDGE_COMPONENTS},
            tol=tol))

    if report is not None:
        for f in out:
            report.add(f)
    return out


# 3표 정합 허용오차(백만원 단위 0.001 = 1천원).
# ⚠️ 정확일치 비교 금지: 모델링 교재의 예시조차 `=IF(A−B=0,"OK","ERROR")` 인데, 이는
# 부동소수 노이즈로 맞는 연도를 ERROR 로 만든다(모델러스 §4 D1 실측 -7.1e-14).
#
# 워크북 CHECK 행의 `excel.template_schema.CHECK_TOL` 과 **같은 값**이어야 한다(같은 개념).
# 그런데 import 로 묶지는 않는다 — `excel → calc_core` 가 확립된 의존 방향이고
# (excel/dcf_export·dcf_import·sensitivity_grid 가 calc_core 를 참조), 순수 엔진이
# 워크북 레이아웃 모듈을 역참조하면 방향이 뒤집힌다. 값이 갈라지지 않게 테스트로 고정한다.
THREE_STATEMENT_TOL = 0.001


def check_three_statement_integrity(
    result,
    *,
    tol: float = None,
    report: ValidationReport | None = None,
) -> list[Finding]:
    """3표 무결성 종합 — 대차·현금연결·이익잉여금 롤포워드·순환 해결.

    사양 정본: 앤트로픽_금융스킬_벤치마크 §2 audit-xls "모델 스코프 무결성".

    ⭐ **심각도 순서 원칙**(같은 문서): "**BS 안 맞으면 그것부터 — 나머지는 전부 의심**".
    대차가 깨지면 이하 finding 의 detail 에 `bs_unreliable=True` 를 달아, 현금연결이
    PASS 여도 그걸 근거로 안심하지 않게 한다(대차가 깨진 모델의 부분 PASS 는 무의미).

    잔차는 **플러그 없이** 원본 그대로 읽는다 — 엔진이 차액을 메우지 않는 것이 전제다.
    """
    tol = THREE_STATEMENT_TOL if tol is None else tol
    out: list[Finding] = []

    def _worst(seq: list[float]) -> tuple[int, float]:
        """최대 |잔차| 의 (연도 인덱스, 값). 빈 리스트는 (-1, 0.0)."""
        if not seq:
            return -1, 0.0
        i = max(range(len(seq)), key=lambda k: abs(seq[k]))
        return i, seq[i]

    # ── ⓪ 기초 BS 자체 대차(사전조건) ──
    op_res = getattr(result, "opening_balance_residual", 0.0)
    if abs(op_res) > tol:
        out.append(Finding(
            "ts_opening_balance", Severity.FAIL,
            f"기초 BS 대차 불일치 {op_res:+,.4f} — 이 불균형이 전 추정기간에 상수로 "
            f"지속된다(추정 로직이 아니라 기초 자료를 먼저 고쳐야 함)",
            {"opening_balance_residual": op_res, "tol": tol}))
    else:
        out.append(Finding("ts_opening_balance", Severity.PASS,
                           "기초 BS 대차 일치", {"opening_balance_residual": op_res}))

    # ── ① 대차(전 기간) — 최우선 ──
    bi, bv = _worst(result.balance_residual)
    bs_ok = abs(bv) <= tol
    if not bs_ok:
        out.append(Finding(
            "ts_balance_sheet", Severity.FAIL,
            f"대차 불일치 — 최대 잔차 {bv:+,.4f} (t={bi}). 자산 ≠ 부채+자본이면 조립 "
            f"배관이 틀린 것(기초 BS·D&A↔FA 롤·ΔNWC↔NWC 잔액 중 하나)",
            {"worst_year": bi, "worst_residual": bv,
             "residuals": list(result.balance_residual), "tol": tol}))
    else:
        out.append(Finding("ts_balance_sheet", Severity.PASS,
                           f"대차 일치(최대 잔차 {bv:+.2e})",
                           {"worst_residual": bv, "tol": tol}))

    def _add(f: Finding) -> None:
        """대차가 깨졌으면 하위 finding 을 신뢰불가로 표시(audit-xls 순서 원칙)."""
        if not bs_ok:
            f.detail["bs_unreliable"] = True
        out.append(f)

    # ── ② 현금연결: Δ현금 = CFO+CFI+CFF ──
    ci, cv = _worst(result.cash_tie_residual)
    if abs(cv) > tol:
        _add(Finding(
            "ts_cash_tie", Severity.FAIL,
            f"현금연결 불일치 — 최대 잔차 {cv:+,.4f} (t={ci}). CF 순증감이 BS 현금 변화와 "
            f"어긋난다",
            {"worst_year": ci, "worst_residual": cv,
             "residuals": list(result.cash_tie_residual), "tol": tol}))
    else:
        _add(Finding("ts_cash_tie", Severity.PASS,
                     f"현금연결 일치(최대 잔차 {cv:+.2e})", {"worst_residual": cv}))

    # ── ③ 이익잉여금 롤포워드: 기초 + NI − 배당 = 기말 ──
    ri, rv = _worst(result.re_rollforward_residual)
    if abs(rv) > tol:
        _add(Finding(
            "ts_re_rollforward", Severity.FAIL,
            f"이익잉여금 롤포워드 불일치 — 최대 잔차 {rv:+,.4f} (t={ri})",
            {"worst_year": ri, "worst_residual": rv, "tol": tol}))
    else:
        _add(Finding("ts_re_rollforward", Severity.PASS,
                     f"이익잉여금 롤포워드 일치(최대 잔차 {rv:+.2e})",
                     {"worst_residual": rv}))

    # ── ④ 순환 해결 상태(R14) ──
    basis = getattr(result, "interest_basis", "opening")
    enabled = getattr(result, "circularity_enabled", True)
    iters = list(getattr(result, "iterations", []))
    detail = {"interest_basis": basis, "circularity_enabled": enabled,
              "iterations": iters, "converged": result.converged}
    if not enabled:
        # Circuit Switch OFF 를 **조용히 지나가면 안 된다** — 이자수익 0이라 NI 과소.
        _add(Finding(
            "ts_circularity", Severity.WARN,
            "순환 스위치 OFF — 이자수익을 0으로 강제해 고리를 끊었다. 순이익이 과소되므로 "
            "진단·대조 용도로만 쓰고 최종 산출에는 쓰지 말 것", detail))
    elif not result.converged:
        _add(Finding(
            "ts_circularity", Severity.FAIL,
            f"순환 반복 미수렴(basis={basis}, 최대 {max(iters) if iters else 0}회) — "
            f"결과 무효. 이자율·배당성향이 비현실적이지 않은지 확인",
            detail))
    elif basis == "opening":
        _add(Finding("ts_circularity", Severity.PASS,
                     "기초잔액 기준 — 순환 미발생(1패스 결정론)", detail))
    else:
        _add(Finding("ts_circularity", Severity.PASS,
                     f"평균잔액 기준 — 고정점 반복 수렴(최대 {max(iters)}회)", detail))

    if report is not None:
        for f in out:
            report.add(f)
    return out


def check_three_statement_vs_spine(
    spine: DcfSpineInput,
    result,
    *,
    tol: float = None,
    report: ValidationReport | None = None,
) -> Finding:
    """3표가 **DCF 스파인과 같은 영업 벡터**로 조립됐는지 대사 — 검증의 전제조건.

    ⚠️ 왜 필요한가: 대차 항등식은 D&A·CAPEX 불일치를 **흡수한다**. `ΔAssets` 유도에서
    D&A 는 CFO(+)와 FA 롤(−)에 같은 크기로 들어가 상쇄되기 때문이다. 즉 D&A 를 잘못
    넣어도 대차는 여전히 0이다(실측 확인). 그래서 audit-xls 가 'D&A(CF=IS)'·
    'CapEx(CF=PP&E 롤포워드)' 를 **별도 항목**으로 둔 것이다.

    3표를 스파인과 다른 숫자로 만들면 "다른 모델을 검증하는" 꼴이라 전체가 무의미해진다.
    이 검사가 그 전제를 지킨다: ebit(=매출−원가−판관비)·dep_amort·capex·ΔNWC 4계열 대사.
    """
    tol = THREE_STATEMENT_TOL if tol is None else tol
    n = min(len(spine.revenue), len(result.ebit))
    spine_ebit = [spine.revenue[t] - spine.cogs[t] - spine.sga[t] for t in range(n)]
    # 스파인의 delta_nwc_cash_adj 는 현금조정 부호(−ΔNWC) → 3표의 ΔNWC 와 부호 반대.
    spine_dnwc = [-spine.delta_nwc_cash_adj[t] for t in range(n)]

    series = {
        "ebit": (spine_ebit, result.ebit[:n]),
        "dep_amort": (list(spine.dep_amort[:n]), result._dep_amort[:n]),
        "capex": (list(spine.capex[:n]), [result.capex_at(t) for t in range(n)]),
        "delta_nwc": (spine_dnwc, result.delta_nwc[:n]),
    }
    mismatches = {}
    for key, (a, b) in series.items():
        if len(a) != len(b):
            mismatches[key] = {"reason": "길이 불일치", "spine_n": len(a), "ts_n": len(b)}
            continue
        worst = max(range(len(a)), key=lambda k: abs(a[k] - b[k])) if a else -1
        if a and abs(a[worst] - b[worst]) > tol:
            mismatches[key] = {"year": worst, "spine": a[worst], "three_statement": b[worst],
                               "delta": b[worst] - a[worst]}

    detail = {"mismatches": mismatches, "tol": tol, "n_years": n}
    if mismatches:
        parts = [f"{k}(t={v.get('year','?')}, Δ{v.get('delta', 0):+,.4f})"
                 for k, v in mismatches.items()]
        f = Finding("ts_vs_spine", Severity.FAIL,
                    "3표가 DCF 스파인과 다른 영업 벡터로 조립됨 — " + " · ".join(parts)
                    + " → 다른 모델을 검증하는 셈이라 3표 정합 결과 전체가 무의미",
                    detail)
    else:
        f = Finding("ts_vs_spine", Severity.PASS,
                    f"3표 ↔ 스파인 영업 벡터 일치({n}개년 · ebit·D&A·CAPEX·ΔNWC)", detail)
    if report is not None:
        report.add(f)
    return f


def check_fcff_vs_cashflow(
    spine_fcff: list[float],
    result,
    *,
    tax_rate: float | None = None,
    tol: float = 0.01,
    report: ValidationReport | None = None,
) -> Finding:
    """DCF 스파인 FCFF ↔ CF표 역산 FCFF 대사 — **unlevered 위반 탐지**.

        FCFF = CFO − (이자수익 − 이자비용)×(1−τ) − CAPEX

    FCFF 는 무차입 기준이라 이자 손익이 섞이면 안 된다. 두 값이 어긋나면 스파인의
    FCF 에 금융효과가 새어들었다는 신호 — audit-xls "DCF 특화 버그 5종" 중
    *FCF 에 이자 포함(unlevered 위반)* 을 자동 검사로 승격한 것이다.

    ⚠️ **구간세율 caveat**: 정률(`effective_tax_rate`)이면 정확히 대사되지만, 구간세율은
    스파인이 `corporate_tax(EBIT)`·3표가 `corporate_tax(EBT)` 로 **과세표준이 달라**
    잔차가 남는다(모델 오류가 아니라 세제 비선형성). 그 경우 finding 에 명시한다.
    """
    cf_fcff = result.fcff_from_cashflow(tax_rate)
    n = min(len(spine_fcff), len(cf_fcff))
    diffs = [cf_fcff[t] - spine_fcff[t] for t in range(n)]
    scale = max([abs(x) for x in spine_fcff[:n]] + [1.0])
    worst = max(range(n), key=lambda k: abs(diffs[k])) if n else -1
    detail = {"spine_fcff": list(spine_fcff[:n]), "cashflow_fcff": cf_fcff[:n],
              "diffs": diffs, "worst_year": worst, "tol": tol,
              "bracket_tax": tax_rate is None}
    if n == 0:
        f = Finding("fcff_vs_cashflow", Severity.WARN, "비교할 FCFF 계열 없음", detail)
    elif abs(diffs[worst]) / scale <= tol:
        f = Finding("fcff_vs_cashflow", Severity.PASS,
                    f"FCFF ↔ CF표 대사 일치(최대 편차 {diffs[worst]:+,.2f})", detail)
    else:
        f = Finding("fcff_vs_cashflow", Severity.WARN,
                    f"FCFF ↔ CF표 편차 {diffs[worst]:+,.2f} (t={worst}, 허용 {tol:.0%}) — "
                    f"FCF 에 이자 손익이 섞였는지(unlevered 위반) 확인"
                    + ("; 구간세율은 과세표준(EBIT vs EBT) 차이로 잔차가 정상"
                       if tax_rate is None else ""),
                    detail)
    if report is not None:
        report.add(f)
    return f


def audit_dcf(
    inp: DcfSpineInput,
    result: DcfResult,
    *,
    wacc_inputs: WaccInputs | None = None,
    long_term_gdp: float = DEFAULT_LONG_TERM_GDP,
    pgr_source: str | None = None,
    pgr_basis: str | None = None,
) -> ValidationReport:
    """DCF 입력·산출·(선택)WACC 입력에 대한 가정 타당성 종합 검사.

    ingest 게이트(validators)와 별개인 valuation 게이트. warn 은 통과시키되
    감사인에게 노출, fail(PGR≥WACC 등)은 결과 무효로 취급한다.

    pgr_source/pgr_basis 를 주면 PGR 출처 게이트(R2)도 함께 돈다.
    """
    report = ValidationReport()
    # 터미널에서 재투자가 실제로 반영되는 경로들.
    # ⚠️ fade_years 는 여기 포함되지 **않는다** — 페이드는 명시구간의 현실성을 높이고
    # TV 비중을 낮출 뿐, 터미널 FCFF 자체는 여전히 NOPLAT_T(D&A=CAPEX, ΔWC=0)로
    # 재구축되기 때문. 반면 terminal_from_last_fcff 는 마지막 연도의 실제 CAPEX·ΔWC 를
    # 승계하므로 재투자 반영으로 인정한다.
    # ⚠️ terminal_from_last_fcff 는 **조건부**로만 인정한다. 마지막 연도 FCFF 를 성장시키면
    # 그 해의 재투자 강도가 영구히 승계되는데, 그 해가 재투자 부족(CAPEX < D&A)이었다면
    # **부족분을 영원히 승계**해 FCFF 를 과대계상한다(자산기반이 줄면서 매출이 g 로 영구
    # 성장하는 것은 불가능). 무조건 인정하면 게이트 방향이 뒤집힌다 — 실측: CAPEX 1 < D&A 10
    # 인 입력에서 기본(WARN) 대비 EV 가 23% 더 큰데 PASS 가 붙었다.
    last_reinvestment_ok = (
        bool(inp.capex) and bool(inp.dep_amort)
        and inp.capex[-1] >= inp.dep_amort[-1]
    )
    reinvestment_modeled = (
        inp.terminal_wc_ratio is not None
        or inp.terminal_reinvestment_rate is not None
        or inp.terminal_fcff_override is not None
        or (inp.terminal_from_last_fcff and last_reinvestment_ok)
    )
    if inp.terminal_from_last_fcff and not last_reinvestment_ok:
        report.add(Finding(
            "terminal_from_last_fcff", Severity.WARN,
            f"마지막 연도 CAPEX({inp.capex[-1] if inp.capex else 0:,.0f}) < "
            f"D&A({inp.dep_amort[-1] if inp.dep_amort else 0:,.0f}) 인데 그 해 FCFF 를 "
            f"영구 성장 — 재투자 부족을 영원히 승계해 TV 과대계상",
            {"capex_last": inp.capex[-1] if inp.capex else None,
             "dep_amort_last": inp.dep_amort[-1] if inp.dep_amort else None}))
    check_terminal_growth(inp.terminal_growth, inp.wacc,
                          long_term_gdp=long_term_gdp,
                          reinvestment_modeled=reinvestment_modeled, report=report)
    check_pgr_provenance(inp.terminal_growth, pgr_source, basis=pgr_basis, report=report)
    check_terminal_discount_convention(inp, result, report=report)
    check_terminal_value_weight(result, report=report)
    check_projection_smoothness(list(inp.revenue), name="revenue", report=report)
    check_working_capital_burn(list(inp.revenue), list(inp.delta_nwc_cash_adj), report=report)
    if wacc_inputs is not None:
        check_beta_provenance(wacc_inputs, report=report)
        check_beta_mrp_consistency(wacc_inputs, report=report)
    return report
