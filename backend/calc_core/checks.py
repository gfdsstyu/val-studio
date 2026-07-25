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


# ── 복합금융(CB·RCPS) 게이트 — 근거: [[복합금융상품_평가]](Issue Paper 407·408, T-F 워크북 채록) ──
# 신용악화 질적분석 임계: 스프레드 ≥ 10% (408: B→CCC 급락 구간, 통상 스프레드의 수 배).
DISTRESSED_SPREAD_WARN = 0.10
# 상쇄효과 감지 임계: 스프레드 급등에도 CB 가치 변화율이 이 미만이면 "비현실적 안정" 신호.
CB_OFFSET_STABILITY_TOL = 0.05
# with-without 분해 항등식 허용오차(상대).
CB_DECOMP_TOL = 1e-6


def check_convertible_distress(
    credit_spread: float,
    value: float,
    *,
    baseline_value: float | None = None,
    spread_threshold: float = DISTRESSED_SPREAD_WARN,
    offset_tol: float = CB_OFFSET_STABILITY_TOL,
    report: ValidationReport | None = None,
) -> list[Finding]:
    """신용악화 CB 의 T-F 기계 산출값 게이트 (Issue Paper 408 승격).

    408 핵심 관찰: 스프레드가 급등해도 변동성이 전환가치를 떠받쳐 CB 총가치가 거의
    안 변하는 **상쇄효과** — 그러나 부실기업 주식은 휴지화 가능성이 크므로 이 안정성은
    비현실적일 수 있다. 두 겹 게이트:
      ① 스프레드 ≥ 임계 → 질적분석 필수 WARN(주가·변동성 동반 조정, Merton/Reduced-form
         DP·RR 하향조정 CB_adj = CB×(1−DP) + Bond×R×DP, 유사등급 시장가 교차검증).
      ② baseline_value(신용악화 전 가치)가 주어지고 가치 변화율 < offset_tol 이면
         상쇄효과 WARN — 모델이 신용위험을 충분히 반영하지 못했을 신호.
    """
    out: list[Finding] = []
    detail = {"credit_spread": credit_spread, "value": value,
              "baseline_value": baseline_value, "spread_threshold": spread_threshold}
    if credit_spread >= spread_threshold:
        out.append(Finding(
            "cb_distress", Severity.WARN,
            f"신용스프레드 {credit_spread:.0%} ≥ {spread_threshold:.0%} — 신용악화 구간. "
            f"T-F 기계 산출값을 회계 반영 전 질적분석 필수(DP·RR 하향조정, 유사등급 시장가 대조)",
            detail))
        if baseline_value is not None and baseline_value > 0:
            change = abs(value - baseline_value) / baseline_value
            d2 = dict(detail, change=round(change, 6), offset_tol=offset_tol)
            if change < offset_tol:
                out.append(Finding(
                    "cb_offset_effect", Severity.WARN,
                    f"스프레드 급등에도 CB 가치 변화 {change:.1%} < {offset_tol:.0%} — "
                    f"변동성이 채권가치 하락을 상쇄(408). 부실기업 주식 휴지화 가능성 미반영 의심",
                    d2))
            else:
                out.append(Finding(
                    "cb_offset_effect", Severity.PASS,
                    f"스프레드 반영 후 CB 가치 변화 {change:.1%} — 상쇄효과 신호 없음", d2))
    else:
        out.append(Finding(
            "cb_distress", Severity.PASS,
            f"신용스프레드 {credit_spread:.1%} < {spread_threshold:.0%} — 정상 신용 구간", detail))
    if report is not None:
        for f in out:
            report.add(f)
    return out


def check_cb_decomposition(
    total_value: float,
    bond_value: float,
    embedded_value: float,
    *,
    tol: float = CB_DECOMP_TOL,
    report: ValidationReport | None = None,
) -> Finding:
    """"CB 전체 = 일반사채 + 내재파생" 항등식 게이트 (T-F 워크북 반면교사 승격).

    with-without 분해는 **동일 모델·동일 가정** 안에서만 성립한다. 채록 실측:
    'TF_Model_CB_Valuation_Detailed_Steps' 는 연속할인·쿠폰無 트리(121.02)에서
    이산할인·쿠폰 4배 채권(119.67)을 차감해 'Residual 1.35' 를 내재옵션이라 표기 —
    이종 가정 차감이라 분해가 비정합이다. 외부 평가서·워크북 검증 시 이 게이트로 잡는다.
    """
    gap = total_value - bond_value - embedded_value
    scale = max(abs(total_value), 1e-12)
    detail = {"total": total_value, "bond": bond_value, "embedded": embedded_value,
              "gap": gap, "tol": tol}
    if abs(gap) / scale > tol:
        f = Finding("cb_decomposition", Severity.WARN,
                    f"CB 분해 비정합: 전체({total_value:,.2f}) − 채권({bond_value:,.2f}) − "
                    f"내재파생({embedded_value:,.2f}) = {gap:+,.4f} — 이종 가정 차감 의심"
                    f"(할인방식·쿠폰 규약이 양변 동일한지 확인)",
                    detail)
    else:
        f = Finding("cb_decomposition", Severity.PASS,
                    f"CB 분해 정합: 전체 = 채권 + 내재파생 (오차 {gap:+.2e})", detail)
    if report is not None:
        report.add(f)
    return f


# ── 공정가치(FV) 게이트 — 근거: [[공정가치_측정_FV]](IFRS Issue Paper 345/346/347/350/411/412/414) ──
# Backsolve 앵커 시점 괴리 경고 임계(일): 평가일과 최근 라운드가 반 년 이상 떨어지면 조정 필요.
BACKSOLVE_ANCHOR_STALE_DAYS = 180.0


def check_backsolve_anchor(
    is_arms_length: bool | None,
    days_gap: float | None,
    *,
    stale_days: float = BACKSOLVE_ANCHOR_STALE_DAYS,
    report: ValidationReport | None = None,
) -> list[Finding]:
    """Backsolve 앵커(최근 라운드 거래) 신뢰성 게이트 (Issue Paper 411/412 승격).

    Backsolve 는 "거래가액=공정가액" 전제 위에 서 있다 — 전제가 무너지는 두 축:
      ① Arm's Length 아님(특수관계·전략적 투자·강요) → 앵커 자체가 오염.
      ② 평가일과 거래 시점 괴리 → 그 사이 가치변동 미반영, 조정 필요.
    LLM 대원칙과 동일하게 미확인(None)은 임의 통과 금지 — 확인 요구 WARN.
    """
    out: list[Finding] = []
    if is_arms_length is None:
        out.append(Finding(
            "backsolve_anchor_arms_length", Severity.WARN,
            "앵커 거래의 Arm's Length 여부 미확인 — 투자계약서·거래상대방 확인 필요"
            "(특수관계·전략적 프리미엄이면 앵커 오염)", {"is_arms_length": None}))
    elif not is_arms_length:
        out.append(Finding(
            "backsolve_anchor_arms_length", Severity.WARN,
            "앵커 거래가 Arm's Length 아님 — 거래가액≠공정가액, 조정 없이는 Backsolve 부적합",
            {"is_arms_length": False}))
    else:
        out.append(Finding(
            "backsolve_anchor_arms_length", Severity.PASS,
            "앵커 거래 독립성(Arm's Length) 확인", {"is_arms_length": True}))

    if days_gap is not None:
        detail = {"days_gap": days_gap, "stale_days": stale_days}
        if days_gap > stale_days:
            out.append(Finding(
                "backsolve_anchor_staleness", Severity.WARN,
                f"평가일과 앵커 거래 시점 괴리 {days_gap:.0f}일 > {stale_days:.0f}일 — "
                f"그 사이 가치변동 조정 필요(411: 시점이 다르면 적절한 조정)", detail))
        else:
            out.append(Finding(
                "backsolve_anchor_staleness", Severity.PASS,
                f"앵커 거래 시점 괴리 {days_gap:.0f}일 ≤ {stale_days:.0f}일", detail))
    if report is not None:
        for f in out:
            report.add(f)
    return out


def check_fv_hierarchy(
    input_levels: dict[str, int],
    *,
    claimed_level: int | None = None,
    adjusted_level1: bool = False,
    report: ValidationReport | None = None,
) -> Finding:
    """공정가치 수준 판정 게이트 (Issue Paper 345/346 승격).

    핵심 규칙 2개의 결정론 인코딩:
      ① **가장 낮은 수준이 지배**: 공정가치 수준 = max(사용 변수들의 level 번호).
         (예: 주가 L1 + 역사적 변동성 L3 → 전체 L3. 대부분의 CB·RCPS 가 L3 인 이유.)
      ② **조정 = 강등**: Level 1 가격에 조정을 가하면(문단79 예외 포함) 수준이 내려간다.
    claimed_level 이 계산 수준보다 높으면(숫자가 작으면) WARN — 서열 과대표기.
    """
    if not input_levels:
        raise ValueError("input_levels 비어 있음 — 변수별 수준을 명시할 것")
    bad = {k: v for k, v in input_levels.items() if v not in (1, 2, 3)}
    if bad:
        raise ValueError(f"level 은 1/2/3 만 허용: {bad}")
    implied = max(input_levels.values())
    if adjusted_level1 and implied == 1:
        implied = 2                     # 조정 가한 L1 은 최소 L2 로 강등(345/346)
    detail = {"input_levels": input_levels, "implied_level": implied,
              "claimed_level": claimed_level, "adjusted_level1": adjusted_level1}
    worst = [k for k, v in input_levels.items() if v == max(input_levels.values())]
    if claimed_level is not None and claimed_level < implied:
        f = Finding("fv_hierarchy", Severity.WARN,
                    f"공정가치 수준 과대표기: 주장 Level {claimed_level} < 계산 Level {implied} "
                    f"(최저수준 변수 {worst} 가 지배 — 상쇄되어도 상향 불가)", detail)
    else:
        f = Finding("fv_hierarchy", Severity.PASS,
                    f"공정가치 수준 = Level {implied} (지배 변수 {worst})", detail)
    if report is not None:
        report.add(f)
    return f


def check_day_one_difference(
    transaction_price: float,
    fair_value: float,
    level: int,
    *,
    tol: float = 1e-6,
    report: ValidationReport | None = None,
) -> Finding:
    """day-one 차이 처리 게이트 (Issue Paper 347 승격).

    거래가격 ≠ 최초 공정가치이면:
      Level 1·2 → 즉시 당기손익 인식.
      Level 3   → 차이를 이연 → 만기 상각(한국 실무 정액법 다수).
    어느 쪽이든 **비금융요소 판단이 선행**(347/이슈8): 거래상대방이 주주·종업원·제3자면
    비용·배당·급여 처리 후보 — 이연상각으로 덮지 말 것.
    """
    if level not in (1, 2, 3):
        raise ValueError("level 은 1/2/3")
    diff = fair_value - transaction_price
    scale = max(abs(transaction_price), 1e-12)
    detail = {"transaction_price": transaction_price, "fair_value": fair_value,
              "level": level, "diff": diff}
    if abs(diff) / scale <= tol:
        f = Finding("day_one_difference", Severity.PASS,
                    "거래가격 ≈ 최초 공정가치 — day-one 차이 없음", detail)
    elif level == 3:
        f = Finding("day_one_difference", Severity.WARN,
                    f"day-one 차이 {diff:+,.0f} (Level 3) — 이연 후 상각 대상. "
                    f"이연 전 비금융요소(특수관계 저가양도 등) 여부 먼저 판단", detail)
    else:
        f = Finding("day_one_difference", Severity.WARN,
                    f"day-one 차이 {diff:+,.0f} (Level {level}) — 즉시 당기손익 인식 대상. "
                    f"비금융요소 여부 먼저 판단", detail)
    if report is not None:
        report.add(f)
    return f


def check_market_price_eligibility(
    level1_available: bool,
    method_used: str,
    *,
    report: ValidationReport | None = None,
) -> Finding:
    """활성시장 가격 우선 게이트 (Issue Paper 350/414 승격).

    "Level 1 정보가 이용가능하면 문단79 예외가 아닌 한 모델·matrix·broker 가격을
    쓸 수 없다"(350). method_used ∈ {'quoted','model','matrix','broker','consensus'}.
    ⚠️ 역도 성립: 활성시장 시가가 있는데 DCF 단독 채택이면 근거 요구
    (414: 공정가치 ≠ Level 1 공정가치 구분은 정당하나, L1 을 두고 하위를 쓰는 건 별개).
    """
    allowed = {"quoted", "model", "matrix", "broker", "consensus", "dcf"}
    if method_used not in allowed:
        raise ValueError(f"method_used 는 {sorted(allowed)} 중 하나")
    detail = {"level1_available": level1_available, "method_used": method_used}
    if level1_available and method_used != "quoted":
        f = Finding("market_price_eligibility", Severity.WARN,
                    f"활성시장 Level 1 가격이 이용가능한데 '{method_used}' 사용 — "
                    f"문단79 예외(대량 유사자산 매트릭스/종가 미대변/부채·자기지분)가 "
                    f"아니면 Level 1 우선", detail)
    else:
        f = Finding("market_price_eligibility", Severity.PASS,
                    f"가격 원천 '{method_used}' — Level 1 우선 규칙 위반 없음", detail)
    if report is not None:
        report.add(f)
    return f


# ── SBC·희석 게이트 — 근거: [[주식기준보상_희석_SBC]](Issue Paper 524/526/742/743) ──
def check_dilution_bridge(
    has_dilutive_instruments: bool,
    dilutive_claims_value: float,
    *,
    method: str = "value_deduction",
    report: ValidationReport | None = None,
) -> Finding:
    """희석 청구권 반영 게이트 (Issue Paper 526 다모다란 주당가치 승격).

    전환증권·옵션·워런트가 존재하는데 주당가치 브리지가 이를 무시하면 과대평가.
    method:
      'value_deduction' — 다모다란 가치차감법(권장): 모든 옵션 FV 를 분자에서 차감,
        분모=기본 주식수. 시간가치·OTM 옵션까지 반영.
      'treasury_stock'  — TSM(자기주식법): 분모 조정. **시간가치 미반영·OTM 완전 무시**
        한계(526 Case B: OTM 이면 희석 0 처리) → WARN 으로 한계 표면화.
      'none'            — 미처리.
    """
    allowed = {"value_deduction", "treasury_stock", "none"}
    if method not in allowed:
        raise ValueError(f"method 는 {sorted(allowed)} 중 하나")
    detail = {"has_dilutive_instruments": has_dilutive_instruments,
              "dilutive_claims_value": dilutive_claims_value, "method": method}
    if not has_dilutive_instruments:
        f = Finding("dilution_bridge", Severity.PASS,
                    "희석 청구권 없음 — 기본 주식수 브리지 정당", detail)
    elif method == "none" or (method == "value_deduction" and dilutive_claims_value <= 0):
        f = Finding("dilution_bridge", Severity.WARN,
                    "전환증권·옵션 존재하는데 희석 미반영 — 주당가치 과대. "
                    "옵션 FV 를 지분가치에서 차감(가치차감법)하거나 근거 제시", detail)
    elif method == "treasury_stock":
        f = Finding("dilution_bridge", Severity.WARN,
                    "TSM(자기주식법) 사용 — 시간가치 미반영·OTM 옵션 무시 한계. "
                    "가치차감법(옵션 FV 분자 차감 + 기본 주식수) 검토 권장", detail)
    else:
        f = Finding("dilution_bridge", Severity.PASS,
                    f"희석 청구권 FV {dilutive_claims_value:,.0f} 분자 차감(가치차감법)", detail)
    if report is not None:
        report.add(f)
    return f


def check_sbc_treatment(
    sbc_expense_positive: bool,
    added_back_to_fcf: bool,
    *,
    purpose: str = "valuation",
    cash_settled: bool = False,
    discount_rate_adjusted: bool = False,
    report: ValidationReport | None = None,
) -> Finding:
    """주식기준보상(SBC) 처리 게이트 (Issue Paper 742/743 승격).

    purpose='valuation' (계속기업 DCF·내재가치):
      다모다란 — SBC add-back 은 '공짜 점심'. 주식결제형도 현물(in-kind) 실질비용이므로
      FCF 에서 차감(add-back 금지). add-back 이면 FCF 과대 → WARN.
    purpose='viu' (IAS 36 손상 사용가치):
      현금결제형 → 현금유출이므로 포함(제외하면 WARN).
      주식결제형 → 문언상 현금흐름에서 제외가 원칙. 대신 경제적 희석은 **할인율 상향**으로
      반영 가능(BDO, 이중계산 방지 원칙과 정합). 현금흐름 차감(비인정 위험)이나
      제외+할인율 미조정(손상 은폐 위험) 모두 WARN — 전문판단·근거 요구.
    """
    if purpose not in {"valuation", "viu"}:
        raise ValueError("purpose 는 'valuation' | 'viu'")
    detail = {"sbc_expense_positive": sbc_expense_positive,
              "added_back_to_fcf": added_back_to_fcf, "purpose": purpose,
              "cash_settled": cash_settled,
              "discount_rate_adjusted": discount_rate_adjusted}
    if not sbc_expense_positive:
        f = Finding("sbc_treatment", Severity.PASS, "SBC 비용 없음", detail)
    elif purpose == "valuation":
        if added_back_to_fcf:
            f = Finding("sbc_treatment", Severity.WARN,
                        "SBC 를 FCF 에 add-back — 현물(in-kind) 실질비용 무시로 FCF 과대"
                        "(다모다란: malpractice). 차감 유지 + 옵션 FV 는 희석 브리지로", detail)
        else:
            f = Finding("sbc_treatment", Severity.PASS,
                        "SBC 를 비용으로 유지(add-back 안 함) — 경제적 실질 정합", detail)
    else:  # viu
        if cash_settled:
            if added_back_to_fcf:
                f = Finding("sbc_treatment", Severity.WARN,
                            "현금결제형 SBC 를 VIU 현금흐름에서 제외 — 실제 현금유출이므로 "
                            "CGU 배분비용에 포함해야 함", detail)
            else:
                f = Finding("sbc_treatment", Severity.PASS,
                            "현금결제형 SBC 를 VIU 현금유출에 포함", detail)
        elif not added_back_to_fcf:
            f = Finding("sbc_treatment", Severity.WARN,
                        "주식결제형 SBC 를 VIU 현금흐름에서 직접 차감 — IAS 36 문언"
                        "(비현금성 제외)과 충돌, 회계적 비인정 위험. 할인율 조정 경로 검토", detail)
        elif not discount_rate_adjusted:
            f = Finding("sbc_treatment", Severity.WARN,
                        "주식결제형 SBC 를 VIU 에서 제외했으나 할인율 미조정 — 경제적 희석 "
                        "미반영으로 VIU 과대(손상 은폐 위험). 할인율 상향+주석공시 검토", detail)
        else:
            f = Finding("sbc_treatment", Severity.PASS,
                        "주식결제형 SBC: VIU 현금흐름 제외 + 할인율 조정 반영"
                        "(이중계산 방지 정합)", detail)
    if report is not None:
        report.add(f)
    return f


# ── 손상(VIU) 게이트 — 근거: [[손상검사_impairment]](Issue Paper 234/235/745/746/747/413) ──
# 세전·세후 VIU 일치 허용오차(상대) — 유효세전율 역산 수렴 기준.
VIU_PRE_POST_TOL = 0.01


def check_viu_discount_rate(
    viu_pre_tax: float | None = None,
    viu_post_tax: float | None = None,
    *,
    simple_gross_up_used: bool = False,
    market_observed_rate_available: bool = False,
    used_capm_surrogate: bool = True,
    tol: float = VIU_PRE_POST_TOL,
    report: ValidationReport | None = None,
) -> list[Finding]:
    """VIU 할인율 게이트 (Issue Paper 234 승격).

    ① 시장관점 우선: 동일/유사 거래의 내재 할인율이 관측되면 CAPM WACC(대용치)
       자동적용 금지. ② 세전율은 세후율의 단순 Gross-Up 이 아니다 — 실무 정석은
       세후 기준 계산 후 **세전 VIU == 세후 VIU** 가 되는 유효세전율을 시행착오 역산.
    """
    out: list[Finding] = []
    if market_observed_rate_available and used_capm_surrogate:
        out.append(Finding(
            "viu_rate_market_first", Severity.WARN,
            "동일/유사 거래의 내재 할인율이 관측 가능한데 CAPM WACC(대용치) 사용 — "
            "시장관점 우선(234), 관측 할인율 채택 또는 미채택 근거 필요",
            {"market_observed_rate_available": True}))
    if simple_gross_up_used:
        out.append(Finding(
            "viu_rate_gross_up", Severity.WARN,
            "세전 할인율을 세후율의 단순 Gross-Up 으로 산출 — 정석은 세전 VIU == 세후 "
            "VIU 가 되는 유효세전율 역산(gross-up 은 우연히만 일치)",
            {"simple_gross_up_used": True}))
    if viu_pre_tax is not None and viu_post_tax is not None:
        scale = max(abs(viu_post_tax), 1e-12)
        gap = abs(viu_pre_tax - viu_post_tax) / scale
        detail = {"viu_pre_tax": viu_pre_tax, "viu_post_tax": viu_post_tax,
                  "rel_gap": round(gap, 6), "tol": tol}
        if gap > tol:
            out.append(Finding(
                "viu_pre_post_consistency", Severity.WARN,
                f"세전 VIU 와 세후 VIU 괴리 {gap:.1%} > {tol:.0%} — 유효세전율이 "
                f"수렴하지 않음(두 VIU 는 동일해야 함)", detail))
        else:
            out.append(Finding(
                "viu_pre_post_consistency", Severity.PASS,
                f"세전·세후 VIU 일치(괴리 {gap:.2%}) — 유효세전율 정합", detail))
    if not out:
        out.append(Finding("viu_discount_rate", Severity.PASS,
                           "VIU 할인율 위반 신호 없음", {}))
    if report is not None:
        for f in out:
            report.add(f)
    return out


def check_viu_cashflow_scope(
    *,
    includes_financing: bool = False,
    includes_tax: bool = False,
    includes_uncommitted_restructuring: bool = False,
    includes_enhancement_capex: bool = False,
    provision_double_counted: bool = False,
    forecast_years: int | None = None,
    forecast_justified: bool = False,
    report: ValidationReport | None = None,
) -> list[Finding]:
    """VIU 현금흐름 스코프 게이트 (Issue Paper 745/746 승격).

    IAS 36 '현금흐름 순수성': 금융활동(할인율에 기반영 — 이중계산)·법인세·미확정
    구조조정·성능 개선/향상 CAPEX 는 배제. 이미 인식된 복구충당부채 관련 유출을
    현금흐름과 장부금액 양쪽에 반영하면 중복차감. 예측기간 >5년은 정당화 필요.
    """
    out: list[Finding] = []
    viol = [
        (includes_financing, "viu_cf_financing",
         "금융활동(이자·차입) 현금흐름 포함 — 차입원가는 할인율에 기반영, 이중계산(745 Case 2)"),
        (includes_tax, "viu_cf_tax",
         "법인세 현금흐름 포함 — IAS 36 은 세전 기준(세후 병행 시 유효세전율 역산으로)"),
        (includes_uncommitted_restructuring, "viu_cf_restructuring",
         "IAS 37 요건(구체적·공표·임박) 미충족 구조조정 절감 포함 — 배제 대상"),
        (includes_enhancement_capex, "viu_cf_enhancement",
         "성능 개선/향상 CAPEX·효과 포함 — VIU 는 자산의 현재 상태 기준(현상유지만)"),
        (provision_double_counted, "viu_cf_provision_double",
         "복구충당부채 유출을 현금흐름·장부금액 양쪽에 반영 — 중복차감(746: 하나로만)"),
    ]
    for flag, rule, msg in viol:
        if flag:
            out.append(Finding(rule, Severity.WARN, msg, {}))
    if forecast_years is not None and forecast_years > 5 and not forecast_justified:
        out.append(Finding(
            "viu_forecast_horizon", Severity.WARN,
            f"예측기간 {forecast_years}년 > 5년 — 정당화 근거(장기계약·규제산업 등) 없이 "
            f"초과 금지(K-IFRS 1036.35)", {"forecast_years": forecast_years}))
    if not out:
        out.append(Finding("viu_cashflow_scope", Severity.PASS,
                           "VIU 현금흐름 스코프 위반 없음", {}))
    if report is not None:
        for f in out:
            report.add(f)
    return out


def check_impairment_trigger(
    market_cap: float,
    net_book_value: float,
    *,
    report: ValidationReport | None = None,
) -> Finding:
    """외부 손상징후 게이트 (Issue Paper 747 + IAS 36.12(d) 승격).

    시가총액 < 순자산 장부금액 = 명백한 외부 trigger. 단 전사 일괄감액이 아니라
    실질 영향을 받는 자산·CGU 를 판단으로 식별해 회수가능액 추정(영업권 배분 CGU 우선,
    IAS 36.90~96; 손상 시 영업권 먼저 차감, 36.104). ⚠️ 시총은 **자사주 제외
    유통주식수** 기준([[손상검사_impairment]] §9b — KRX 기본 시총은 자사주 포함 과대).
    """
    detail = {"market_cap": market_cap, "net_book_value": net_book_value}
    if net_book_value > 0 and market_cap < net_book_value:
        f = Finding("impairment_trigger", Severity.WARN,
                    f"시가총액({market_cap:,.0f}) < 순자산 장부금액({net_book_value:,.0f}) — "
                    f"외부 손상징후(IAS 36.12(d)). 전사 일괄감액 금지, 영향 CGU 식별 후 "
                    f"회수가능액 추정(영업권 CGU 우선)", detail)
    else:
        f = Finding("impairment_trigger", Severity.PASS,
                    "시가총액 ≥ 순자산 장부금액 — 외부 손상징후(12(d)) 없음", detail)
    if report is not None:
        report.add(f)
    return f


# ── 계속기업·FCFE 게이트 — 근거: [[실전평가_상장사_사례집]](홈플러스)·[[DCF_교육_정본]](FCFE 주의점) ──
# 홈플러스 실측 임계: Debt/EBITDA 8배(업계 3~4배 대비 과도), ICR<1 지속.
GOING_CONCERN_DEBT_EBITDA_WARN = 8.0


def check_going_concern(
    *,
    net_loss_with_positive_ocf: bool = False,
    current_ratio: float | None = None,
    icr_below_one_persistent: bool = False,
    debt_to_ebitda: float | None = None,
    debt_ebitda_threshold: float = GOING_CONCERN_DEBT_EBITDA_WARN,
    report: ValidationReport | None = None,
) -> list[Finding]:
    """계속기업 가정 게이트 (홈플러스 부실 사례 승격 — 실행 전 게이트 계열).

    계속기업 가정이 흔들리면 계속기업 DCF 자체가 무의미(청산가치 vs 계속기업가치 비교
    국면). 신호 4축:
      ① 당기순손실 + 영업현금흐름 큰 양수 = 미지급이자·미지급금 미지급으로 만든
         "흑자도산" 전형 — 비현금조정·운전자본 내역 확인 필수.
      ② 유동비율 < 100% — 단기 상환능력 결여.
      ③ ICR(이자보상배율) < 1 지속 — 이자도 못 갚는 구조.
      ④ Debt/EBITDA ≥ 임계(기본 8배) — 상환능력 과도 취약.
    """
    out: list[Finding] = []
    if net_loss_with_positive_ocf:
        out.append(Finding(
            "going_concern_ocf_paradox", Severity.WARN,
            "당기순손실인데 영업현금흐름 큰 (+) — 미지급이자·미지급금 내역 확인"
            "(흑자도산 신호: 지급할 것을 지급하지 않아 만든 현금흐름)", {}))
    if current_ratio is not None and current_ratio < 1.0:
        out.append(Finding(
            "going_concern_current_ratio", Severity.WARN,
            f"유동비율 {current_ratio:.0%} < 100% — 단기차입 상환능력 결여, "
            f"계속기업 불확실성 원인", {"current_ratio": current_ratio}))
    if icr_below_one_persistent:
        out.append(Finding(
            "going_concern_icr", Severity.WARN,
            "이자보상배율(ICR) < 1 지속 — 이자조차 감당 못 하는 구조", {}))
    if debt_to_ebitda is not None and debt_to_ebitda >= debt_ebitda_threshold:
        out.append(Finding(
            "going_concern_leverage", Severity.WARN,
            f"Debt/EBITDA {debt_to_ebitda:.1f}배 ≥ {debt_ebitda_threshold:.0f}배 — "
            f"부채상환능력 과도 취약(업계 통상 3~4배)", {"debt_to_ebitda": debt_to_ebitda}))
    if out:
        out.append(Finding(
            "going_concern", Severity.WARN,
            f"계속기업 신호 {len(out)}건 — 계속기업 DCF 전 청산가치 비교·감사인 "
            f"계속기업 검토 필요(신호 다수면 계속기업 DCF 자체가 무의미)", {"signals": len(out)}))
    else:
        out.append(Finding("going_concern", Severity.PASS, "계속기업 위험 신호 없음", {}))
    if report is not None:
        for f in out:
            report.add(f)
    return out


def check_fcfe_usage(
    *,
    uses_fcfe: bool,
    discounted_at_cost_of_equity: bool = False,
    levered_beta_used: bool = False,
    net_borrowing_included: bool = False,
    borrowing_nature_assessed: bool = False,
    stable_target_leverage: bool = False,
    report: ValidationReport | None = None,
) -> list[Finding]:
    """FCFE 사용 게이트 (FCFF 대신 FCFE 를 쓸 때의 주의점 승격).

    FCFE 는 핵심 변수를 영업성과 → 재무구조·차입정책으로 이동시킨다. 규칙:
      ① 반드시 자기자본비용(Ke)·레버리지드 베타로 할인(분자·분모 대응).
      ② 차입금 순증가 기계 포함 = "빚으로 만든 (+) 착시" — 구조적 조달인지
         일시 브릿지인지 판단 선행.
      ③ 부채비율 급변에 단일 Ke 적용 금지 — 장기 목표 레버리지 기준.
      ④ FCFF 음수라는 이유만으로 FCFE 전환 금지(성장기 음수는 '투자 중' 신호 —
         FCFF 유지 + PSR 등 병행이 정석).
    """
    out: list[Finding] = []
    if not uses_fcfe:
        out.append(Finding("fcfe_usage", Severity.PASS, "FCFF 사용 — FCFE 게이트 해당 없음", {}))
    else:
        if not discounted_at_cost_of_equity:
            out.append(Finding(
                "fcfe_discount_rate", Severity.FAIL,
                "FCFE 를 WACC 로 할인 — 주주귀속 현금흐름은 자기자본비용(Ke)으로"
                "(분자·분모 불일치 = 구조적 오류)", {}))
        if not levered_beta_used:
            out.append(Finding(
                "fcfe_levered_beta", Severity.WARN,
                "FCFE 인데 레버리지드 베타 미사용 — Ke 는 목표 자본구조의 levered β 로", {}))
        if net_borrowing_included and not borrowing_nature_assessed:
            out.append(Finding(
                "fcfe_borrowing_illusion", Severity.WARN,
                "차입금 순증가를 기계적으로 포함 — 구조적 조달 vs 일시 브릿지 판단 없이는 "
                "'빚으로 만든 양(+) 현금흐름 착시' 위험", {}))
        if not stable_target_leverage:
            out.append(Finding(
                "fcfe_target_leverage", Severity.WARN,
                "장기 목표 레버리지 미확정 — 부채비율 급변 구간에 단일 Ke 적용은 "
                "현금흐름-할인율 구조 불일치", {}))
        if not any(f.severity != Severity.PASS for f in out):
            out.append(Finding("fcfe_usage", Severity.PASS,
                               "FCFE 사용 규율 충족(Ke·levered β·차입 판단·목표 레버리지)", {}))
    if report is not None:
        for f in out:
            report.add(f)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 산업 벤치마크 이상치 게이트 (지식→규칙 승격)
#
# 근거: docs/reference/산업_프로파일.md · 벤치마크_{마진,운전자본,CAPEX}.md
#   내부 레퍼런스 코퍼스 횡단집계 → 산업별 지표 분포(p25/p50/p75).
#   rigor=참고 prior. 데이터=벤치마크 빌드 스크립트 생성(비공개).
# 판정: p25~p75 = 정상, [min,max]∩밖 = WARN(주의), min~max 밖 = WARN(이상치, 사업모델 질문).
#   n<3 = 저신뢰(참고만).
import json as _json
from pathlib import Path as _Path

# 산업 벤치마크 JSON 의 단일 정본 경로·로더·매칭 규칙. API·엔진 게이트가 공유해
# 세 표면(엔진·API·카드)이 조용히 어긋나지 않게 한다(경로/매칭 중복 제거).
_BENCH_PATH = _Path(__file__).parent / "data" / "industry_benchmarks.json"
_BENCH_CACHE: dict | None = None
_BENCH_MTIME: float | None = None

_METRIC_LABEL = {"opm": "영업이익률", "dso": "매출채권회전일",
                 "dio": "재고회전일", "capex_sales": "CAPEX/매출"}
_METRIC_UNIT = {"opm": "%", "dso": "일", "dio": "일", "capex_sales": "%"}


def load_benchmarks(*, fresh: bool = False) -> dict:
    """산업 벤치마크 JSON 로드(캐시). 파일 mtime 이 바뀌면 자동 무효화 —

    pre-commit 이 JSON 을 재생성해도 장수 프로세스(uvicorn)가 stale 캐시를 계속
    서빙하던 결함을 막는다. 로드 실패 시 {"industries": {}} 로 degrade(예외 없음).
    fresh=True 면 캐시를 무시하고 강제 재로드.
    """
    global _BENCH_CACHE, _BENCH_MTIME
    try:
        mtime = _BENCH_PATH.stat().st_mtime
    except OSError:
        return {"industries": {}}
    if fresh or _BENCH_CACHE is None or mtime != _BENCH_MTIME:
        try:
            _BENCH_CACHE = _json.loads(_BENCH_PATH.read_text(encoding="utf-8"))
            _BENCH_MTIME = mtime
        except Exception:
            return {"industries": {}}
    return _BENCH_CACHE


def match_industry(industries: dict, name: str) -> tuple[str, dict | None]:
    """산업명 → (매칭 산업명, 분포dict). 정확일치 우선, 없으면 부분일치.

    부분일치는 **결정적**으로 고른다 — 이름 길이가 입력에 가장 가까운(가장 구체적인)
    후보, 동률이면 사전순. 이전엔 dict 순회 첫 겹침을 채택해 JSON 키 순서에 따라
    같은 입력이 다른 코호트로 매칭되던 결함(감사 게이트가 엉뚱한 동종과 대조).
    매칭 없으면 (name, None).
    """
    if not name:
        return name, None
    if name in industries:
        return name, industries[name]
    cands = [ind for ind in industries if name in ind or ind in name]
    if not cands:
        return name, None
    best = min(cands, key=lambda ind: (abs(len(ind) - len(name)), ind))
    return best, industries[best]


def check_metric_vs_industry(
    industry: str,
    metric: str,
    value: float,
    *,
    report: ValidationReport | None = None,
) -> list[Finding]:
    """사용자 가정(OPM·DSO·DIO·CAPEX/매출)을 동종 산업 분포 대비 이상치 판정.

    metric ∈ {'opm','dso','dio','capex_sales'} (opm·capex_sales 는 %, dso·dio 는 일).
    - p25~p75 안        : PASS
    - min~max 안(밴드 밖): WARN  (동종 대비 이례 — 근거 확인)
    - min~max 밖         : WARN  (이상치 — 사업모델 재검토, 감사 red flag)
    - 데이터 없음/n<3    : PASS(정보)  참고 prior 부족

    산업명은 산업_프로파일.md 라벨과 일치해야 매칭(부분일치 fallback).
    """
    bench = load_benchmarks().get("industries", {})
    matched, d = match_industry(bench, industry)
    dist = d.get(metric) if d else None
    if dist:
        industry = matched
    lbl = _METRIC_LABEL.get(metric, metric)
    unit = _METRIC_UNIT.get(metric, "")
    fid = f"{metric}_vs_industry"

    if not dist:
        f = Finding(fid, Severity.PASS,
                    f"{lbl}: 산업 '{industry}' 벤치마크 없음 — 대조 생략", {"metric": metric})
        out = [f]
    elif dist["n"] < 3:
        f = Finding(fid, Severity.PASS,
                    f"{lbl} {value}{unit}: 산업 '{industry}' n={dist['n']}(저신뢰) "
                    f"참고 p50={dist['p50']}{unit}", {"metric": metric, "dist": dist, "value": value})
        out = [f]
    elif dist["p25"] <= value <= dist["p75"]:
        f = Finding(fid, Severity.PASS,
                    f"{lbl} {value}{unit} ∈ 정상대역 [{dist['p25']}~{dist['p75']}]{unit} "
                    f"(산업 '{industry}')", {"metric": metric, "dist": dist, "value": value})
        out = [f]
    elif dist["min"] <= value <= dist["max"]:
        f = Finding(fid, Severity.WARN,
                    f"{lbl} {value}{unit}: 동종 정상대역 [{dist['p25']}~{dist['p75']}]{unit} 밖 "
                    f"(min~max 안) — 근거 확인 (산업 '{industry}')",
                    {"metric": metric, "dist": dist, "value": value})
        out = [f]
    else:
        side = "상회" if value > dist["max"] else "하회"
        f = Finding(fid, Severity.WARN,
                    f"⚠️ {lbl} {value}{unit}: 동종 [{dist['min']}~{dist['max']}]{unit} {side} "
                    f"= 이상치 — 사업모델 재검토(감사 red flag) (산업 '{industry}')",
                    {"metric": metric, "dist": dist, "value": value})
        out = [f]

    if report is not None:
        for f in out:
            report.add(f)
    return out
