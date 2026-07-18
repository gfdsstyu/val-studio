"""W8 민감도 그리드 검증 — 중심==base, 내부 3×3==엔진 민감도, 수식 구조.

backend 모듈 직접 검증(순수) + 스킬 래퍼 emit 스모크. calc_core 의존이라 backend on path.
`python tests/skill/test_sensitivity_grid.py` 또는 pytest.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
SKILL = ROOT / ".claude" / "skills" / "excel-valuation-workbook" / "scripts"
FX = ROOT / "fixtures" / "viol"

from calc_core import DcfSpineInput, run  # noqa: E402
from excel.sensitivity_grid import add_sensitivity_sheet, build_sensitivity  # noqa: E402


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


def _sens(inp):
    wb = build_sensitivity(inp)
    sens = next(s for s in wb.sheets if s.name == "Sens")
    return wb, sens


def test_center_equals_base_per_share():
    """중심 셀(F7) 캐시 == 엔진 base 주당가치(8,413.38)."""
    inp = _viol()
    base = run(inp)
    _, sens = _sens(inp)
    assert _close(sens.cells["F7"].cached, base.per_share)
    assert _close(sens.cells["F7"].cached, 8413.380552, tol=1e-6)


def test_inner_3x3_matches_engine_sensitivity():
    """5×5 내부 3×3(±1%p) 캐시 == 엔진 run() 자체 민감도(독립 코드경로 교차검증)."""
    inp = _viol()
    base = run(inp)
    _, sens = _sens(inp)
    eng = base.sensitivity["per_share"]        # 3×3, [wacc][g]
    inner_cols = ["E", "F", "G"]               # g index 1,2,3
    inner_rows = [6, 7, 8]                      # wacc index 1,2,3
    for a, row in enumerate(inner_rows):
        for b, col in enumerate(inner_cols):
            assert _close(sens.cells[f"{col}{row}"].cached, eng[a][b]), f"{col}{row}"


def test_grid_cells_are_live_formulas():
    """25개 그리드 셀이 살아있는 수식(SUMPRODUCT·크로스시트·터미널 항 포함)."""
    inp = _viol()
    _, sens = _sens(inp)
    f = sens.cells["F7"].formula
    assert f.startswith("=") and "SUMPRODUCT(DCF!" in f
    assert "DCF!$C$21:DCF!$G$21" in f          # FCFF 행 참조(고정)
    assert "$B$7" in f and "F$4" in f          # w=행헤더, g=열헤더
    assert "/($B$7-F$4)/" in f                 # 터미널 /(w-g)/
    # 모든 그리드 셀이 수식
    grid = [f"{c}{r}" for c in "DEFGH" for r in (5, 6, 7, 8, 9)]
    assert all(sens.cells[ref].formula is not None for ref in grid)


def test_axes_centered_on_base():
    """축값: WACC·PGR 각 base±2×1%p, 중심=base."""
    inp = _viol()
    _, sens = _sens(inp)
    wacc_col = [sens.cells[f"B{r}"].value for r in range(5, 10)]
    pgr_row = [sens.cells[f"{c}4"].value for c in "DEFGH"]
    assert _close(wacc_col[2], inp.wacc) and _close(pgr_row[2], inp.terminal_growth)
    assert _close(wacc_col[0], inp.wacc - 0.02) and _close(wacc_col[4], inp.wacc + 0.02)
    assert _close(pgr_row[0], inp.terminal_growth - 0.02)


def test_override_model_uses_constant_terminal():
    """terminal_fcff_override 모델(클래시스류): 터미널 항이 상수셀($C$38) 참조."""
    d = json.loads((ROOT / "fixtures" / "classys" / "inputs.json").read_text(encoding="utf-8"))
    kw = {k: v for k, v in d.items() if not k.startswith("_")}
    inp = DcfSpineInput(**kw)
    base = run(inp)
    _, sens = _sens(inp)
    # 중심 == base(오버라이드 경로도 tie-out)
    assert _close(sens.cells["F7"].cached, base.per_share, tol=1e-4)
    # 터미널 항이 override 셀 참조(구간세 IF 없음)
    f = sens.cells["F7"].formula
    assert "DCF!$C$38" in f and "IF(" not in f


def test_nci_in_closed_form():
    """NCI(비지배지분) 모델: 그리드 closed-form 이 -DCF!$C$8 반영, 중심 여전히 == base(-NCI 포함)."""
    import dataclasses
    inp = dataclasses.replace(_viol(), non_controlling_interest=300.0)
    base = run(inp)
    _, sens = _sens(inp)
    assert "-DCF!$C$8" in sens.cells["F7"].formula      # 브리지 -NCI
    assert _close(sens.cells["F7"].cached, base.per_share)   # 중심 == base(NCI 차감 반영)


def test_skill_wrapper_emits_sens_only():
    """스킬 래퍼 --emit-cells: Sens 셀만(DCF 는 라이브 워크북)."""
    inp = json.dumps(json.loads((FX / "inputs.json").read_text(encoding="utf-8")))
    r = subprocess.run([sys.executable, str(SKILL / "sensitivity.py"), "--emit-cells"],
                       input=inp, capture_output=True, text=True, encoding="utf-8",
                       cwd=tempfile.gettempdir())
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert {c["sheet"] for c in out["cells"]} == {"Sens"}
    assert _close(out["center_per_share"], 8413.380552, tol=1e-6)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed.")
