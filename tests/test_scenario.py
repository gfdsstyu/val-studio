"""시나리오 분석(Upside/Base/Downside) 테스트 — 리포트 3-시나리오 구조 재현.

stdlib: `python tests/test_scenario.py`
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core.dcf import run  # noqa: E402
from calc_core.models import DcfSpineInput  # noqa: E402
from calc_core.scenario import run_scenarios  # noqa: E402


def _inp(growth: float) -> DcfSpineInput:
    """단순 5년 입력세트 — 매출 성장률만 시나리오 차등."""
    rev = [100.0 * (1 + growth) ** t for t in range(5)]
    return DcfSpineInput(
        wacc=0.10, terminal_growth=0.01,
        revenue=rev, cogs=[r * 0.4 for r in rev], sga=[r * 0.2 for r in rev],
        dep_amort=[5.0] * 5, capex=[5.0] * 5, delta_nwc_cash_adj=[0.0] * 5,
        non_operating_assets=0.0, net_debt=0.0, shares_outstanding=1_000,
    )


CASES = {"downside": _inp(0.00), "base": _inp(0.05), "upside": _inp(0.10)}


def test_scenarios_ordered_and_match_single_runs():
    a = run_scenarios(CASES)
    by = {s.name: s.per_share for s in a.scenarios}
    assert by["downside"] < by["base"] < by["upside"]
    # 각 시나리오 = 단독 dcf.run 과 동일(래퍼가 수치를 건드리지 않음)
    assert math.isclose(by["base"], run(CASES["base"]).per_share, rel_tol=1e-12)
    lo, hi = a.spread
    assert (lo, hi) == (by["downside"], by["upside"])


def test_weighted_per_share():
    w = {"downside": 0.25, "base": 0.50, "upside": 0.25}
    a = run_scenarios(CASES, weights=w)
    by = {s.name: s.per_share for s in a.scenarios}
    expect = sum(w[k] * by[k] for k in w)
    assert math.isclose(a.weighted_per_share, expect, rel_tol=1e-12)


def test_weights_must_sum_to_one_and_match_names():
    try:
        run_scenarios(CASES, weights={"downside": 0.3, "base": 0.3, "upside": 0.3})
        raise AssertionError("가중치 합 0.9 가 통과됨")
    except ValueError as e:
        assert "≠ 1" in str(e)
    try:
        run_scenarios(CASES, weights={"down": 0.5, "base": 0.5})
        raise AssertionError("이름 불일치 가중치가 통과됨")
    except ValueError as e:
        assert "불일치" in str(e)


def test_no_weights_means_no_weighted_value():
    a = run_scenarios(CASES)
    assert a.weighted_per_share is None            # 암묵 균등가중 금지
    rows = a.to_rows()
    assert len(rows) == 3 and all("tv_weight" in r for r in rows)


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
