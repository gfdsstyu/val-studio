"""VIU 제약 모드 테스트 — TV 없는 유한 DCF + 유효세전율 역산 + 회수가능액.

근거: [[손상검사_impairment]] §6(234 유효세전율)·§7b(746 복구충당). stdlib.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core.viu import ViuInputs, compute_viu, _pv  # noqa: E402


def test_no_terminal_finite_horizon():
    # TV 없음: 5개 현금흐름의 유한 현가 그대로(성장 영구 없음)
    cfs = [100.0] * 5
    r = compute_viu(ViuInputs(post_tax_cashflows=cfs, post_tax_rate=0.10, tax_rate=0.0))
    expected = _pv(cfs, 0.10, mid_year=True)
    assert math.isclose(r.viu_post_tax, expected, rel_tol=1e-12)


def test_effective_pre_tax_rate_equalizes_viu():
    # 핵심(234): 세전 현금흐름을 유효세전율로 할인하면 세후 VIU 와 일치
    cfs = [120.0, 130.0, 140.0, 150.0, 160.0]
    r = compute_viu(ViuInputs(post_tax_cashflows=cfs, post_tax_rate=0.09, tax_rate=0.22))
    assert math.isclose(r.viu_pre_tax, r.viu_post_tax, rel_tol=1e-8)
    # 유효세전율 > 세후율(세전 현금흐름이 더 크므로)
    assert r.effective_pre_tax_rate > 0.09


def test_effective_rate_differs_from_simple_gross_up():
    # 유효세전율 ≠ 단순 gross-up(r/(1−t)) — 경고 표면화
    cfs = [50.0, 100.0, 150.0, 200.0, 250.0]   # 시점 분포 비균등
    r = compute_viu(ViuInputs(post_tax_cashflows=cfs, post_tax_rate=0.10, tax_rate=0.25))
    simple = 0.10 / (1.0 - 0.25)
    assert not math.isclose(r.effective_pre_tax_rate, simple, rel_tol=1e-4)
    assert any("gross-up" in w for w in r.warnings)


def test_recoverable_amount_max_and_impairment():
    cfs = [100.0] * 5
    # VIU ≈ 379, FVLCD 500 → 회수가능액 500, 장부 600 → 손상 100
    r = compute_viu(ViuInputs(post_tax_cashflows=cfs, post_tax_rate=0.10, tax_rate=0.0,
                              fvlcd=500.0, carrying_amount=600.0))
    assert math.isclose(r.recoverable_amount, 500.0)
    assert math.isclose(r.impairment_loss, 100.0)
    assert any("손상차손" in w for w in r.warnings)


def test_no_impairment_when_headroom():
    cfs = [200.0] * 5
    r = compute_viu(ViuInputs(post_tax_cashflows=cfs, post_tax_rate=0.08, tax_rate=0.0,
                              carrying_amount=100.0))
    assert r.impairment_loss == 0.0


def test_provision_carrying_deducted_from_viu():
    # 746: 복구충당부채 장부액을 VIU 에서 차감(FVLCD 와 동일 척도)
    cfs = [100.0] * 5
    base = compute_viu(ViuInputs(post_tax_cashflows=cfs, post_tax_rate=0.10, tax_rate=0.0))
    prov = compute_viu(ViuInputs(post_tax_cashflows=cfs, post_tax_rate=0.10, tax_rate=0.0,
                                 provision_carrying=50.0))
    assert math.isclose(base.viu_post_tax - prov.viu_post_tax, 50.0, rel_tol=1e-9)


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
