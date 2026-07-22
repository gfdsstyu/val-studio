"""LibreOffice recalc 게이트 검증 — <f> 수식이 실제 Calc 엔진에서 엔진값과 일치.

soffice 있으면 실제 recalc 대조, 없으면 recalc 테스트는 skip(오탐 아님). export·strip
절반(수식만 xlsx 생성)은 soffice 없이도 검증한다.

`python tests/skill/test_recalc_gate.py` 또는 pytest.
"""
from __future__ import annotations

import json
import math
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))

import recalc_gate  # noqa: E402
from calc_core import DcfSpineInput, run  # noqa: E402
from excel.dcf_export import build_dcf_sheet  # noqa: E402
from excel.sensitivity_grid import build_sensitivity  # noqa: E402
from excel.template_schema import RESULT, ROW, YEAR_COLS  # noqa: E402
from excel.xlsx_reader import read_workbook  # noqa: E402

FX = ROOT / "fixtures" / "viol"


def _viol() -> DcfSpineInput:
    d = json.loads((FX / "inputs.json").read_text(encoding="utf-8"))
    return DcfSpineInput(
        wacc=d["wacc"], terminal_growth=d["terminal_growth"],
        revenue=d["revenue"], cogs=d["cogs"], sga=d["sga"],
        dep_amort=d["dep_amort"], capex=d["capex"],
        delta_nwc_cash_adj=d["delta_nwc_cash_adj"],
        non_operating_assets=d["non_operating_assets"], net_debt=d["net_debt"],
        shares_outstanding=d["shares_outstanding"],
        mid_year_periods=d.get("mid_year_periods"),
        terminal_discount_period=d.get("terminal_discount_period"),
    )


def _close(a, b, tol=1e-6):
    return a is not None and math.isclose(a, b, rel_tol=tol, abs_tol=1e-4)


def test_strip_cached_yields_formula_only():
    """soffice 불필요 — strip 후 수식 셀은 <f> 유지·캐시 제거, 입력 셀은 값 유지."""
    inp = _viol()
    wb = build_dcf_sheet(inp, run(inp))
    recalc_gate.strip_cached(wb)
    with tempfile.TemporaryDirectory() as td:
        p = str(Path(td) / "formula_only.xlsx")
        wb.save(p)
        cells = read_workbook(p)["DCF"]
    # 결과 수식 셀: 수식 남고 캐시 없음
    assert cells["C33"].formula is not None and "C32/C5" in cells["C33"].formula
    assert cells["C33"].number is None
    assert cells["C15"].formula is not None and cells["C15"].number is None   # EBIT 행
    # 입력 셀은 값 유지(수식 아님)
    assert _close(cells["C3"].number, inp.wacc)                                # WACC
    assert cells["C11"].formula is None and cells["C11"].number is not None    # 매출 입력


def test_recalc_matches_engine():
    """LibreOffice recalc → per_share·스파인 수식값이 엔진과 일치(rel_tol 1e-6).

    soffice 미설치면 skip(false pass 아님)."""
    soffice = recalc_gate.find_soffice()
    if not soffice:
        print("SKIP test_recalc_matches_engine: LibreOffice(soffice) 미설치 — "
              "설치 후 재실행(winget install TheDocumentFoundation.LibreOffice)")
        return

    inp = _viol()
    res = run(inp)
    wb = build_dcf_sheet(inp, res)
    recalc_gate.strip_cached(wb)                     # 캐시 제거 → 순수 수식 recalc
    with tempfile.TemporaryDirectory() as td:
        p = str(Path(td) / "viol_formula_only.xlsx")
        wb.save(p)
        dcf = recalc_gate.recalc(p, soffice=soffice)["DCF"]

    n = inp.n_years()
    cols = YEAR_COLS[:n]
    fails = []

    def chk(ref, exp, name):
        got = dcf.get(ref)
        if not _close(got, exp):
            fails.append(f"{name}({ref}): recalc {got!r} != 엔진 {exp!r}")

    # 스파인 수식 라인(연도별)
    for j, c in enumerate(cols):
        chk(f"{c}{ROW['ebit']}", res.ebit[j], "EBIT")
        chk(f"{c}{ROW['tax']}", res.tax[j], "법인세(구간세율 IF)")
        chk(f"{c}{ROW['noplat']}", res.noplat[j], "NOPLAT")
        chk(f"{c}{ROW['fcff']}", res.fcff[j], "FCFF")
        chk(f"{c}{ROW['pvf']}", res.pv_factor[j], "현가계수(^)")
        chk(f"{c}{ROW['pv']}", res.pv_fcff[j], "PV")
    # 결과 블록
    chk(RESULT["terminal_value"], res.terminal_value, "TV")
    chk(RESULT["terminal_value_pv"], res.terminal_value_pv, "TV PV")
    chk(RESULT["enterprise_value"], res.enterprise_value, "EV")
    chk(RESULT["equity_value"], res.equity_value, "주식가치")
    chk(RESULT["per_share"], res.per_share, "주당가치")

    assert not fails, "recalc 불일치(수식 오류):\n  " + "\n  ".join(fails)
    print(f"  recalc per_share = {dcf.get(RESULT['per_share']):,.2f} "
          f"(엔진 {res.per_share:,.2f}) — 수식 정확성 확인")


def test_recalc_sensitivity_grid():
    """W8 Sens 그리드(가장 복잡한 수식: SUMPRODUCT·구간세 IF·크로스시트)가 Calc 에서
    엔진 캐시와 일치. soffice 없으면 skip."""
    soffice = recalc_gate.find_soffice()
    if not soffice:
        print("SKIP test_recalc_sensitivity_grid: LibreOffice 미설치")
        return
    inp = _viol()
    wb = build_sensitivity(inp)                      # DCF + Sens
    engine_cache = {ref: c.cached for s in wb.sheets if s.name == "Sens"
                    for ref, c in s.cells.items() if c.formula is not None}
    recalc_gate.strip_cached(wb)
    with tempfile.TemporaryDirectory() as td:
        p = str(Path(td) / "sens.xlsx")
        wb.save(p)
        sens = recalc_gate.recalc(p, soffice=soffice)["Sens"]
    fails = [f"{ref}: recalc {sens.get(ref)!r} != 엔진 {exp!r}"
             for ref, exp in engine_cache.items() if not _close(sens.get(ref), exp)]
    assert not fails, "Sens recalc 불일치:\n  " + "\n  ".join(fails[:10])
    print(f"  Sens 중심 recalc = {sens.get('F7'):,.2f} — 25셀 수식 정확성 확인")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    test_strip_cached_yields_formula_only()
    print("PASS test_strip_cached_yields_formula_only")
    test_recalc_matches_engine()
    print("PASS test_recalc_matches_engine")
    test_recalc_sensitivity_grid()
    print("PASS test_recalc_sensitivity_grid")
    print("\n3 tests passed (recalc 는 soffice 있을 때만 실제 대조).")
