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
    if wacc_inputs is not None:
        check_beta_provenance(wacc_inputs, report=report)
    return report
