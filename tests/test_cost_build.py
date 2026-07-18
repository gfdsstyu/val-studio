"""성격별 원가 빌드업 테스트 — 5개 투영법·카테고리 합산·감가상각 배분.

stdlib: `python tests/test_cost_build.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core.cost_build import CostLine, project_costs  # noqa: E402


def test_growth_method():
    ln = CostLine("원재료", "cogs", "growth", base=1000, growth=[0.1, 0.1, 0.1])
    v = ln.project(3)
    assert abs(v[0] - 1100) < 1e-6 and abs(v[1] - 1210) < 1e-6 and abs(v[2] - 1331) < 1e-6


def test_headcount_method():
    # 노무비 = 인원수 × 인당급여 × (1 + 상여율 + 퇴직급여율)
    ln = CostLine("노무비", "cogs", "headcount", headcount=[100, 110],
                  wage_per_head=[50, 52], bonus_rate=0.1, severance_rate=0.08)
    v = ln.project(2)
    assert abs(v[0] - 100 * 50 * 1.18) < 1e-6
    assert abs(v[1] - 110 * 52 * 1.18) < 1e-6


def test_cpi_method():
    # 외주비 = base × CPI 누적
    ln = CostLine("외주비", "cogs", "cpi", base=500)
    res = project_costs([ln], 2, cpi=[0.02, 0.03])
    # 누적: 1.02, 1.0506 → 510, 525.3
    assert abs(res.cogs[0] - 510) < 1e-6 and abs(res.cogs[1] - 525.3) < 1e-6


def test_ratio_method():
    ln = CostLine("변동경비", "cogs", "ratio", driver=[1000, 1100], pct=[0.05, 0.05])
    v = ln.project(2)
    assert v == [50.0, 55.0]


def test_fa_dep_allocation():
    # 감가상각 총 300 을 COGS 70% / SGA 30% 배분
    cogs_dep = CostLine("제조감가", "cogs", "fa_dep", fa_share=0.7)
    sga_dep = CostLine("판관감가", "sga", "fa_dep", fa_share=0.3)
    res = project_costs([cogs_dep, sga_dep], 1, fa_dep=[300])
    assert abs(res.cogs[0] - 210) < 1e-6 and abs(res.sga[0] - 90) < 1e-6


def test_category_sum_and_detail():
    lines = [
        CostLine("원재료", "cogs", "growth", base=1000, growth=[0.1]),
        CostLine("노무비", "cogs", "headcount", headcount=[10], wage_per_head=[100]),
        CostLine("급여", "sga", "growth", base=200, growth=[0.05]),
    ]
    res = project_costs(lines, 1)
    assert abs(res.cogs[0] - (1100 + 1000)) < 1e-6      # 원재료 1100 + 노무비 1000
    assert abs(res.sga[0] - 210) < 1e-6
    assert "노무비" in res.detail and res.detail["급여"][0] == 210


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    ok = 0
    for fn in fns:
        try:
            fn(); ok += 1; print(f"  ok  {fn.__name__}")
        except Exception:
            print(f"  FAIL {fn.__name__}"); traceback.print_exc()
    print(f"\n{ok}/{len(fns)} passed")
