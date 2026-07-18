"""W7 시나리오 시트 — 케이스 세트별 주당가치 + 가중 종합(살아있는 수식).

민감도(W8)가 'WACC×g 파라미터 2개의 국소 요동'이라면, 시나리오는 '가정 세트 전체
(매출·마진·CAPEX…)의 대안 세계'다. 각 케이스는 독립 DcfSpineInput → 독립 per_share
이므로 단일 DCF 시트를 참조하지 않고 케이스별 값을 하드로 싣되, **가중 종합은 살아있는
SUMPRODUCT**, **가중합=1은 살아있는 게이트 셀**로 둔다(엔진도 합=1 완전일치를 요구).

케이스 구성(무엇을 낙관/비관으로)은 평가인 판단, 계산·집계는 결정론(run_scenarios).
"""
from __future__ import annotations

from .xlsx_writer import Sheet, Workbook

_CASE_COLS = list("CDEFGHIJ")   # 최대 8 케이스


def add_scenario_sheet(wb: Workbook, analysis) -> Sheet:
    """wb 에 `Scenario` 시트 추가. analysis = calc_core.scenario.ScenarioAnalysis.

    가중치 완비(전 케이스 + 합=1) 시 가중합·가중주당가치 살아있는 수식, 아니면 N/A 표기.
    """
    s = wb.add_sheet("Scenario")
    rows = analysis.to_rows()
    n = len(rows)
    if n > len(_CASE_COLS):
        raise ValueError(f"케이스 {n}개 > 지원 {len(_CASE_COLS)}")
    cols = _CASE_COLS[:n]

    s.text("B1", "Scenario — 시나리오 종합(케이스 세트별 대안 세계)")
    s.text("B2", "케이스 구성=평가인 판단. 가중치 합=1 완전일치 게이트(부분·잔여배분 금지).")

    s.text("B4", "시나리오")
    s.text("B5", "주당가치(원)")
    s.text("B6", "가중치")
    for c, r in zip(cols, rows):
        s.text(f"{c}4", r["name"])
        s.num(f"{c}5", round(r["per_share"], 2))

    has_w = all(r["weight"] is not None for r in rows)
    if has_w:
        for c, r in zip(cols, rows):
            s.num(f"{c}6", r["weight"])
        wsum = round(sum(r["weight"] for r in rows), 6)
        s.text("B7", "가중합 (=1 게이트)")
        s.formula("C7", f"SUM({cols[0]}6:{cols[-1]}6)", wsum)
        s.text("B8", "가중 주당가치")
        s.formula("C8", f"SUMPRODUCT({cols[0]}5:{cols[-1]}5,{cols[0]}6:{cols[-1]}6)",
                  round(analysis.weighted_per_share, 2))
    else:
        s.text("B7", "가중치 미완비 — 가중 종합 N/A (전 케이스 가중치 + 합=1 필요)")

    lo, hi = analysis.spread
    s.text("B10", f"밸류 레인지(스프레드): {round(lo, 2):,.0f} ~ {round(hi, 2):,.0f} 원")
    return s


def build_scenario(cases: dict, weights: dict | None = None) -> Workbook:
    """cases(name→DcfSpineInput) → Scenario 시트만 담은 워크북(자기완결)."""
    from calc_core.scenario import run_scenarios
    wb = Workbook()
    add_scenario_sheet(wb, run_scenarios(cases, weights))
    return wb
