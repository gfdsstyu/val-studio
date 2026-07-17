"""밸류에이션 가정 타당성 검사 (assumption sanity gates).

ingest/validators.py 의 tie-out(데이터가 원본과 일치하나? — 라운드트립 정합)과 달리,
여기서는 *가정의 경제적 타당성*(가정이 말이 되나? — 판단 게이트)을 결정론적으로 검사한다.
같은 ValidationReport/Finding/Severity 인프라를 재사용하되 관심사를 분리한다.

근거 문서(docs/reference/):
  - 영구성장률_PGR_적합성.md  : TV 비중 ~75%, PGR ≤ GDP 철칙, PGR < WACC(Gordon 수렴)
  - 베타_Bloomberg_vs_KICPA.md : β provenance(source·market) 필수
  - deloitte_감사인검토_WACC방법론.md : 감사인 검토 체크리스트

감사인 트랙 자동 경고:
  ① PGR ≥ WACC           → FAIL (Gordon 발산: TV 음수/무한대, 수학적 무효)
  ② PGR > 장기 GDP성장률  → WARN (영구히 경제 추월 = 비현실)
  ③ TV 비중 과다           → WARN (관행 ~75% 초과·과대평가 편중)
  ④ β provenance 부재      → WARN (시장선택 근거 추적 불가)
"""
from __future__ import annotations

from ingest.validators import Finding, Severity, ValidationReport

from .models import DcfResult, DcfSpineInput
from .wacc import WaccInputs

# 장기 실질 경제성장 전망(한국 성숙경제 관행치). 글로벌·고성장국이면 상위에서 조정.
DEFAULT_LONG_TERM_GDP = 0.02
# TV(영구가치) 비중 관행 상단. 초과 시 과대평가 편중 경고(문서상 최빈 ~75%).
TV_WEIGHT_WARN = 0.90
# 재투자 모델 없이(D&A=CAPEX, ΔNWC=0) 이 값을 넘는 PGR 은 TV 과대계상 위험.
# 근거: FCFF_T = NOPLAT_T·(1−g/ROIC) 이나 엔진은 재투자율 0 가정 → g 클수록 왜곡↑.
REINVESTMENT_FREE_PGR = 0.02


def check_terminal_growth(
    pgr: float,
    wacc: float,
    *,
    long_term_gdp: float = DEFAULT_LONG_TERM_GDP,
    report: ValidationReport | None = None,
) -> list[Finding]:
    """영구성장률 타당성: Gordon 수렴(PGR<WACC) + 경제성 상한(PGR≤GDP).

    - PGR ≥ WACC : FAIL. TV = FCFF_T/(WACC−g) 가 음수/무한대 → 수학적 무효.
    - PGR > GDP  : WARN. 기업이 영구히 경제성장률을 추월한다는 비현실적 가정.
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
        out.append(Finding(
            "terminal_reinvestment", Severity.WARN,
            f"PGR({pgr:.2%}) > {REINVESTMENT_FREE_PGR:.0%} 이나 재투자 미반영(D&A=CAPEX) "
            f"— TV 과대계상 위험(재투자율 g/ROIC 필요)",
            {"pgr": pgr, "threshold": REINVESTMENT_FREE_PGR},
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


def check_beta_erp_consistency(
    inp: WaccInputs,
    *,
    report: ValidationReport | None = None,
) -> Finding:
    """β 기준시장 == ERP 기준시장 정합 검사.

    핵심 원칙(베타 문서): β 와 그에 곱해질 MRP 는 **같은 시장**에서 와야 한다.
    KOSPI β 에 S&P500 ERP 를 곱하는 혼용은 체계적위험 이중기준 → WARN.
    두 market 이 모두 명시된 경우에만 판정(하나라도 없으면 provenance 검사가 담당).
    """
    bm, em = inp.beta_market, inp.erp_market
    if bm is None or em is None:
        f = Finding("beta_erp_consistency", Severity.PASS,
                    "β/ERP 시장 정합 판정보류(provenance 부족)",
                    {"beta_market": bm, "erp_market": em})
    elif bm != em:
        f = Finding("beta_erp_consistency", Severity.WARN,
                    f"β 시장({bm}) ≠ ERP 시장({em}) — 체계적위험 이중기준 혼용",
                    {"beta_market": bm, "erp_market": em})
    else:
        f = Finding("beta_erp_consistency", Severity.PASS,
                    f"β/ERP 시장 일치({bm})", {"beta_market": bm, "erp_market": em})
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


def audit_dcf(
    inp: DcfSpineInput,
    result: DcfResult,
    *,
    wacc_inputs: WaccInputs | None = None,
    long_term_gdp: float = DEFAULT_LONG_TERM_GDP,
) -> ValidationReport:
    """DCF 입력·산출·(선택)WACC 입력에 대한 가정 타당성 종합 검사.

    ingest 게이트(validators)와 별개인 valuation 게이트. warn 은 통과시키되
    감사인에게 노출, fail(PGR≥WACC 등)은 결과 무효로 취급한다.
    """
    report = ValidationReport()
    check_terminal_growth(inp.terminal_growth, inp.wacc,
                          long_term_gdp=long_term_gdp, report=report)
    check_terminal_value_weight(result, report=report)
    check_projection_smoothness(list(inp.revenue), name="revenue", report=report)
    if wacc_inputs is not None:
        check_beta_provenance(wacc_inputs, report=report)
        check_beta_erp_consistency(wacc_inputs, report=report)
    return report
