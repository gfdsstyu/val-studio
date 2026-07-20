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


def add_scenario_sheet(wb: Workbook, analysis, *, switch: bool = False) -> Sheet:
    """wb 에 `Scenario` 시트 추가. analysis = calc_core.scenario.ScenarioAnalysis.

    가중치 완비(전 케이스 + 합=1) 시 가중합·가중주당가치 살아있는 수식, 아니면 N/A 표기.

    switch=True 면 **CHOOSE 단일선택 스위치 블록**을 함께 찍는다(R13). 두 패러다임은
    배타적이지 않다:
      · 가중 SUMPRODUCT — 기대값 산출(확률가중 혼합)
      · CHOOSE 스위치   — "약세 시나리오를 보여줘" 서사·발표용(한 번에 한 케이스만 live)
    근거: 모델러스_통합모델_5.4 §2.5 — 선택 셀 하나(`G13=IF(E13="BULL",1,…)`)로
    전 드라이버가 `CHOOSE($G$13, …)` 를 통해 한꺼번에 바뀐다.
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
    if switch:
        _add_switch_block(s, [r["name"] for r in rows], cols, row=12)
    return s


def _add_switch_block(s: Sheet, names: list[str], cols: list[str], row: int) -> None:
    """CHOOSE 단일선택 스위치(R13) — 선택 셀 하나로 어느 케이스가 live 인지 전환.

    선택 인덱스는 중첩 IF 로 케이스명을 번호에 매핑하고(모델러스 `G13`), 값은
    `CHOOSE(인덱스, 케이스1, 케이스2, …)` 로 뽑는다. 하류 시트가 이 '선택된 값' 셀
    하나만 참조하면 시나리오 전환이 워크북 전체에 파급된다.
    """
    s.text(f"B{row}", "── 시나리오 스위치 (CHOOSE 단일선택 — 발표·서사용) ──")
    s.text(f"B{row + 1}", "선택 시나리오 [입력]")
    s.text(f"C{row + 1}", names[0])
    # 케이스명 → 인덱스(1-base). 중첩 IF 로 매핑(엑셀 하위호환 — SWITCH 는 2019+).
    expr = str(len(names))
    for i in range(len(names) - 1, 0, -1):
        expr = f'IF($C${row + 1}="{names[i - 1]}",{i},{expr})'
    if len(names) == 1:
        expr = "1"
    s.text(f"B{row + 2}", "선택 인덱스")
    s.formula(f"C{row + 2}", expr)
    s.text(f"B{row + 3}", "선택된 주당가치 (→ 하류가 이 셀만 참조)")
    s.formula(f"C{row + 3}",
              f"CHOOSE($C${row + 2}," + ",".join(f"{c}5" for c in cols) + ")")
    s.text(f"B{row + 4}",
           "⚠️ 가중 종합(C8)과 병행 — 스위치는 '한 케이스만 live', 가중은 '기대값'. 목적이 다르다.")


def build_scenario(cases: dict, weights: dict | None = None, *,
                   switch: bool = False) -> Workbook:
    """cases(name→DcfSpineInput) → Scenario 시트만 담은 워크북(자기완결)."""
    from calc_core.scenario import run_scenarios
    wb = Workbook()
    add_scenario_sheet(wb, run_scenarios(cases, weights), switch=switch)
    return wb
