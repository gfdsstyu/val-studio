"""K-IFRS 1116 리스 스케줄 테스트 — PV·이자원금분리·ROU 감가상각·상환완료.

stdlib: `python tests/test_lease.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core.lease import annuity_payment, annuity_pv, lease_schedule  # noqa: E402


def test_annuity_pv_roundtrip():
    pv = annuity_pv(1000, 5, 0.05)
    pay = annuity_payment(pv, 5, 0.05)
    assert abs(pay - 1000) < 1e-6                    # PV→payment 왕복


def test_schedule_from_payment():
    r = lease_schedule(3, 0.05, annual_payment=1000)
    # 리스부채 = PV(1000, 3, 5%) ≈ 2723.25
    assert abs(r.liability_open[0] - 2723.248) < 0.01
    # 이자 = 기초 × 5%
    assert abs(r.interest[0] - r.liability_open[0] * 0.05) < 1e-6
    # 원금 = 리스료 − 이자
    assert abs(r.principal[0] - (1000 - r.interest[0])) < 1e-6


def test_liability_amortizes_to_zero():
    r = lease_schedule(5, 0.06, annual_payment=500)
    assert abs(r.liability_close[-1]) < 1e-6         # 마지막 기말 리스부채 ≈ 0


def test_rou_depreciation_straightline():
    r = lease_schedule(4, 0.05, initial_liability=4000)
    # 사용권자산 4000 / 4년 = 1000 정액
    assert all(abs(d - 1000) < 1e-9 for d in r.rou_depreciation)


def test_from_liability_derives_payment():
    r = lease_schedule(3, 0.05, initial_liability=2723.248)
    assert abs(r.payment[0] - 1000) < 0.01           # 리스부채→균등 리스료


def test_interest_declines():
    r = lease_schedule(5, 0.06, annual_payment=500)
    assert all(r.interest[i] > r.interest[i + 1] for i in range(4))  # 이자 체감


def test_zero_rate():
    r = lease_schedule(4, 0.0, annual_payment=1000)
    assert abs(r.liability_open[0] - 4000) < 1e-9 and all(i == 0 for i in r.interest)


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
