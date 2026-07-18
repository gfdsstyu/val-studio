"""W7 시나리오 시트 검증 — 케이스별 per_share + 가중 SUMPRODUCT(live) + 가중합=1 게이트.

backend 직접 + 스킬 래퍼 emit 스모크. calc_core 의존이라 backend on path.
"""
from __future__ import annotations

import dataclasses
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
from calc_core.scenario import run_scenarios  # noqa: E402
from excel.scenario_sheet import add_scenario_sheet, build_scenario  # noqa: E402
from excel.xlsx_writer import Workbook  # noqa: E402


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
    return a is not None and math.isclose(a, b, rel_tol=tol, abs_tol=1e-2)


def _cases():
    base = _viol()
    return {
        "Base": base,
        "Up": dataclasses.replace(base, wacc=base.wacc - 0.01),      # 낮은 WACC=상향
        "Down": dataclasses.replace(base, wacc=base.wacc + 0.01),
    }


def _sheet(cases, weights):
    wb = build_scenario(cases, weights)
    return next(s for s in wb.sheets if s.name == "Scenario")


def test_weighted_live_aggregation():
    """가중치 완비 → 가중합 SUM(=1)·가중주당가치 SUMPRODUCT 살아있는 수식, 캐시=엔진."""
    cases = _cases()
    weights = {"Base": 0.5, "Up": 0.25, "Down": 0.25}
    analysis = run_scenarios(cases, weights)
    s = _sheet(cases, weights)
    # 케이스 3개 → C,D,E
    assert s.cells["C4"].value == "Base"
    assert _close(s.cells["C5"].cached if s.cells["C5"].formula else s.cells["C5"].value,
                  run(cases["Base"]).per_share)
    # 가중합 = SUM(C6:E6) live, 캐시 1
    assert s.cells["C7"].formula == "SUM(C6:E6)" and _close(s.cells["C7"].cached, 1.0)
    # 가중 주당가치 = SUMPRODUCT live, 캐시 == 엔진 weighted
    assert s.cells["C8"].formula == "SUMPRODUCT(C5:E5,C6:E6)"
    assert _close(s.cells["C8"].cached, analysis.weighted_per_share)


def test_unweighted_no_aggregation():
    """가중치 미지정 → 가중 종합 N/A(가중 셀 없음)."""
    cases = _cases()
    s = _sheet(cases, None)
    assert "C7" not in s.cells and "C8" not in s.cells       # 가중합·가중주당 없음
    assert any("미완비" in str(c.value) for c in s.cells.values())


def test_spread_range():
    cases = _cases()
    analysis = run_scenarios(cases, None)
    lo, hi = analysis.spread
    s = _sheet(cases, None)
    b10 = s.cells["B10"].value
    assert "레인지" in b10
    # Down(고WACC) 최소, Up(저WACC) 최대
    assert lo == run(cases["Down"]).per_share and hi == run(cases["Up"]).per_share


def test_skill_wrapper_emit_cells():
    """스킬 scenario.py --emit-cells → Scenario 셀(가중 SUMPRODUCT 포함)."""
    d = json.loads((FX / "inputs.json").read_text(encoding="utf-8"))
    payload = {"cases": {"Base": d, "Up": {**d, "wacc": d["wacc"] - 0.01}},
               "weights": {"Base": 0.6, "Up": 0.4}}
    r = subprocess.run([sys.executable, str(SKILL / "scenario.py"), "--emit-cells"],
                       input=json.dumps(payload), capture_output=True, text=True,
                       encoding="utf-8", cwd=tempfile.gettempdir())
    assert r.returncode == 0, r.stderr
    cells = json.loads(r.stdout)["cells"]
    assert {c["sheet"] for c in cells} == {"Scenario"}
    assert any(c.get("formula", "").startswith("SUMPRODUCT(") for c in cells)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed.")
