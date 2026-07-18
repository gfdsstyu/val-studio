"""razor-and-blades 매출 연동 테스트 — 설치base 누적·소모품 연동·트리 합계검증·후방호환.

stdlib: `python tests/test_revenue_razor.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core import revenue  # noqa: E402


def close(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) < tol


def test_installed_base_accumulates():
    # 신규 [10,20,30], 폐기 0 → 누적 [10,30,60]
    ib = revenue.installed_base_path([10, 20, 30])
    assert ib == [10, 30, 60]


def test_installed_base_with_retirement_and_base0():
    # 기초 100, 신규 [10,10], 폐기 20% → t0:100·0.8+10=90, t1:90·0.8+10=82
    ib = revenue.installed_base_path([10, 10], base0=100, retirement_rate=0.2)
    assert close(ib[0], 90.0) and close(ib[1], 82.0)


def test_consumables_track_installed_base():
    # 설치base [10,30,60] × 대당 소모품 2 → [20,60,120]
    rev = revenue.consumables_revenue([10, 20, 30], [2, 2, 2])
    assert rev == [20, 60, 120]


def test_razor_and_blades_tree():
    # 장비: 대당 50 × [10,20,30]대 = [500,1000,1500] (razor 판매매출)
    equip = revenue.RevenueNode("장비", price=[50, 50, 50], qty=[10, 20, 30])
    # 소모품: 누적 설치base [10,30,60] × 대당 3 = [30,90,180] (blade)
    blade = revenue.RevenueNode("소모품", equipment_new=[10, 20, 30],
                                consumable_per_unit=[3, 3, 3])
    root = revenue.RevenueNode("총매출", children=[equip, blade])
    out = revenue.bottom_up(root, years=3)
    assert out[0] == 500 + 30
    assert out[1] == 1000 + 90
    assert out[2] == 1500 + 180
    # 소모품이 장비 설치base 에 연동(장비 판매 늘수록 소모품 가속) — 합계검증도 통과
    assert revenue.validate_tree_sums(root, years=3) == []


def test_razor_leaf_with_existing_fleet():
    # 기초 설치대수 100(과거 판매) → 소모품이 즉시 base 반영
    blade = revenue.RevenueNode("소모품", equipment_new=[0, 0],
                                consumable_per_unit=[3, 3], installed_base0=100)
    out = blade.revenue(2)
    assert close(out[0], 300.0) and close(out[1], 300.0)   # 신규0이어도 기존 fleet 매출


def test_backward_compat_plain_leaves():
    # 기존 price×qty·base+growth 리프는 razor 필드 없으면 동작 불변
    equip = revenue.RevenueNode("장비", price=[10, 10], qty=[5, 6])
    consum = revenue.RevenueNode("소모품", base=30, growth=[0.1, 0.1])
    root = revenue.RevenueNode("총매출", children=[equip, consum])
    out = revenue.bottom_up(root, years=2)
    assert close(out[0], 50 + 33) and close(out[1], 60 + 36.3)


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
