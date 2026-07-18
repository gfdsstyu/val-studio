"""W8 민감도 그리드 — WACC×PGR 5×5 살아있는 Excel 수식(셀마다 독립 DCF 재계산).

핵심: 명시연도 FCFF 는 WACC·g 와 무관(고정)하므로 `DCF!FCFF` 행을 그대로 참조하고,
할인(1/(1+w)^기간)과 터미널(TF(g)/(w−g))만 축값에 반응하는 **closed-form**으로 각 셀을
쓴다. 엔진(_compute)과 동일 대수:

    per_share(w,g) = [ Σ_j FCFF_j/(1+w)^period_j
                       + TF(g)/(w−g)/(1+w)^term_period
                       + 비영업자산 − 순차입부채 ] / 주식수 × 1e6

    TF(g) = terminal_fcff. 표준=ebit_last×(1+g) − 구간세(그 EBIT);
            terminal_fcff_override 면 상수($C$38); effective_tax_rate/reinvestment 는 해당 식.

축: WACC(행)·PGR(열) 각 ±steps×step(기본 ±2×1%p), 중심=base. 중심 셀 == 엔진 base
per_share == 엔진 3×3 중심(3자 일치 게이트). 셀 캐시값은 엔진 재계산으로 채워 오프라인
표시 + tie-out 타깃. 수식 문자열은 이 closed-form 에서 생성(엔진 미러 == 엔진으로 검증됨).
외곽 셀의 Excel 문법 충실성은 recalc 게이트(scripts/recalc_gate.py)가 확인.

셀 주소는 template_schema(ROW·ASSUMP·RESULT·META) SSOT. 구간세 IF 는 dcf_export._tax_formula 재사용.
"""
from __future__ import annotations

import dataclasses

from calc_core import run
from calc_core.models import DcfSpineInput

from .dcf_export import _tax_formula
from .template_schema import ASSUMP, META, RESULT, ROW, YEAR_COLS, abs_cell, label_cell
from .xlsx_writer import Sheet, Workbook

DCF = "DCF"                         # 참조 대상 시트명
_GRID_COLS = ["D", "E", "F", "G", "H"]   # PGR 열(5)
_AXIS_ROW = 4                        # PGR 헤더 행
_ROW0 = 5                            # WACC 첫 행


def _dref(ref: str) -> str:
    """DCF 시트 절대참조. 예: _dref('C21') == 'DCF!$C$21'."""
    return f"{DCF}!{abs_cell(ref)}"


def _terminal_fcff_expr(inp: DcfSpineInput, cols: list[str], g_ref: str) -> str:
    """g 셀 참조 기준 terminal_fcff Excel 식(엔진 _compute 터미널 로직 1:1)."""
    if inp.terminal_fcff_override is not None:
        return _dref(META["terminal_fcff_override"])          # 상수 주입($C$38)
    last = cols[-1]
    ebit_last = _dref(f"{last}{ROW['ebit']}")                 # DCF!$G$15
    term_ebit = f"{ebit_last}*(1+{g_ref})"
    if inp.effective_tax_rate is not None:
        noplat = f"({term_ebit})*(1-{_dref(META['effective_tax_rate'])})"
    elif inp.tax_override is not None:
        # 마지막 유효세율(=마지막 세금/EBIT)을 성장 EBIT 에 적용(엔진 _tax_on 터미널)
        last_tax = _dref(f"{last}{ROW['tax']}")
        noplat = f"({term_ebit})*(1-{last_tax}/{ebit_last})"
    else:
        noplat = f"({term_ebit}-{_tax_formula('(' + term_ebit + ')')})"   # 구간세율(IF)
    if inp.terminal_reinvestment_rate is not None:
        return f"({noplat})*(1-{_dref(META['terminal_reinvestment_rate'])})"
    return noplat


def _cell_formula(inp: DcfSpineInput, cols: list[str], w_ref: str, g_ref: str) -> str:
    """(w,g) 셀의 살아있는 per_share 수식. FCFF·기간은 DCF 행 참조(고정)."""
    fcff_rng = f"{_dref(cols[0] + str(ROW['fcff']))}:{_dref(cols[-1] + str(ROW['fcff']))}"
    per_rng = f"{_dref(cols[0] + str(ROW['period']))}:{_dref(cols[-1] + str(ROW['period']))}"
    term_period = _dref(f"{cols[-1]}{ROW['period']}")
    tf = _terminal_fcff_expr(inp, cols, g_ref)
    noa, nd, sh = _dref(ASSUMP["non_operating_assets"]), _dref(ASSUMP["net_debt"]), _dref(ASSUMP["shares_outstanding"])
    nci = _dref(ASSUMP["non_controlling_interest"])
    explicit = f"SUMPRODUCT({fcff_rng},1/(1+{w_ref})^{per_rng})"
    tv_pv = f"({tf})/({w_ref}-{g_ref})/(1+{w_ref})^{term_period}"
    return f"=({explicit}+{tv_pv}+{noa}-{nd}-{nci})/{sh}*1000000"


def _axis(center: float, steps: int, step: float) -> list[float]:
    return [round(center + (i - steps) * step, 10) for i in range(2 * steps + 1)]


def add_sensitivity_sheet(wb: Workbook, inp: DcfSpineInput, *,
                          steps: int = 2, step: float = 0.01) -> Sheet:
    """wb 에 `Sens` 시트(WACC×PGR 살아있는 그리드) 추가. DCF 시트가 같은 wb 에 있어야 참조 성립.

    steps=2 → 5×5(중심=base). 각 셀=살아있는 수식 + 엔진 캐시값. 중심 셀 == base per_share.
    """
    n = inp.n_years()
    cols = YEAR_COLS[:n]
    if len(_GRID_COLS) != 2 * steps + 1:
        raise ValueError(f"steps={steps} 는 현재 열 정의(5)와 불일치")

    wacc_axis = _axis(inp.wacc, steps, step)
    g_axis = _axis(inp.terminal_growth, steps, step)

    s = wb.add_sheet("Sens")
    s.text("B1", "Sens — 민감도(WACC×PGR) · 살아있는 수식, 셀마다 독립 DCF 재계산")
    s.text("B2", "행=WACC · 열=영구성장률(PGR). 중심 셀 == base 주당가치(엔진 3×3 중심과 일치).")
    s.text(f"C{_AXIS_ROW}", "WACC\\PGR")
    # PGR 열 헤더
    for k, g in enumerate(g_axis):
        s.num(f"{_GRID_COLS[k]}{_AXIS_ROW}", g)
    # 행별: WACC 헤더(B) + 5개 셀
    for i, w in enumerate(wacc_axis):
        row = _ROW0 + i
        s.num(f"B{row}", w)
        w_ref = f"$B${row}"
        for k, g in enumerate(g_axis):
            col = _GRID_COLS[k]
            g_ref = f"{col}${_AXIS_ROW}"
            cached = run(dataclasses.replace(inp, wacc=w, terminal_growth=g)).per_share
            s.formula(f"{col}{row}", _cell_formula(inp, cols, w_ref, g_ref), round(cached, 6))
    # 중심 좌표 메모(게이트 참조)
    center = _ROW0 + steps
    s.text(f"B{_ROW0 + 2 * steps + 2}",
           f"중심={_GRID_COLS[steps]}{center} == base 주당가치(tie-out 게이트)")
    return s


def build_sensitivity(inp: DcfSpineInput, *, steps: int = 2, step: float = 0.01) -> Workbook:
    """DCF 스파인 + Sens 그리드를 함께 담은 워크북(Sens 가 DCF 를 참조하므로 동봉)."""
    from .dcf_export import build_dcf_sheet
    wb = build_dcf_sheet(inp, run(inp))
    add_sensitivity_sheet(wb, inp, steps=steps, step=step)
    return wb
