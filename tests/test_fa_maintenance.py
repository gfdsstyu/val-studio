"""FA CAPEX 신규/유지보수 분리 테스트 — 후방호환·현금유출·감가옵션·detail·terminal 정규화.

stdlib: `python tests/test_fa_maintenance.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core import fa  # noqa: E402


def close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) < tol


def _ac():
    return fa.AssetClass(name="기계", opening_net_book=100, remaining_life=5, useful_life=10)


def test_backward_compat_no_maintenance():
    # 유지보수 미지정 → 기존 동작과 셀 단위 동일(골든 불변 보장)
    res = fa.project_fixed_assets([_ac()], {"기계": [200, 0, 0]})
    assert close(res.dep_amort[0], 40.0) and close(res.dep_amort[1], 40.0)
    assert close(res.capex[0], 200.0) and close(res.capex[1], 0.0)


def test_maintenance_adds_capex_and_depreciates():
    # 유지보수 50 → 총 CAPEX = 신규200 + 유지50 = 250, 감가도 새 빈티지로 +5(50/10)
    res = fa.project_fixed_assets(
        [_ac()], {"기계": [200, 0, 0]}, {"기계": [50, 0, 0]})
    assert close(res.capex[0], 250.0)
    assert close(res.dep_amort[0], 45.0)          # 기존20 + 신규20 + 유지5
    assert close(res.detail["maintenance_capex"][0], 50.0)
    assert close(res.detail["new_capex"][0], 200.0)
    assert close(res.detail["maint_dep"][0], 5.0)


def test_maintenance_non_depreciating():
    # maintenance_depreciates=False → 현금유출만, 감가 미증가(마모상쇄 단순모델)
    res = fa.project_fixed_assets(
        [_ac()], {"기계": [200, 0, 0]}, {"기계": [50, 0, 0]},
        maintenance_depreciates=False)
    assert close(res.capex[0], 250.0)
    assert close(res.dep_amort[0], 40.0)          # 유지보수 감가 없음
    assert close(res.detail["maint_dep"][0], 0.0)


def test_detail_splits_reconcile():
    # detail 분해가 총계와 정합: new_dep+maint_dep+existing_dep = dep_amort
    res = fa.project_fixed_assets(
        [_ac()], {"기계": [200, 0, 0]}, {"기계": [50, 0, 0]})
    d = res.detail
    for t in range(3):
        assert close(d["existing_dep"][t] + d["new_dep"][t] + d["maint_dep"][t],
                     res.dep_amort[t])
        assert close(d["new_capex"][t] + d["maintenance_capex"][t], res.capex[t])


def test_terminal_maintenance_matches_dep():
    # 신규만으로 1차 투영 → D&A 를 유지보수 CAPEX 로 재주입(terminal 자본유지 정규화)
    base = fa.project_fixed_assets([_ac()], {"기계": [200, 0, 0]})
    maint = fa.maintenance_capex_matching_dep(base)
    assert maint == base.dep_amort
    # 재주입 시 총 CAPEX[t] = 신규 + D&A(t)
    res2 = fa.project_fixed_assets(
        [_ac()], {"기계": [200, 0, 0]}, {"기계": maint},
        maintenance_depreciates=False)          # 정규화용이라 감가 재증가 방지
    assert close(res2.capex[0], 200.0 + base.dep_amort[0])


def test_maintenance_as_ratio():
    # 유지보수 CAPEX = 매출 × pct (비올식 매출연동)
    out = fa.maintenance_capex_as_ratio([1000, 1100, 1210], 0.03)
    assert close(out[0], 30.0) and close(out[2], 36.3)


def test_years_inferred_from_maintenance_only():
    # 신규 없이 유지보수만 있어도 연수 추론(빈 new dict 안전)
    res = fa.project_fixed_assets([_ac()], {}, {"기계": [10, 10, 10, 10]})
    assert len(res.capex) == 4 and close(res.capex[0], 10.0)


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
