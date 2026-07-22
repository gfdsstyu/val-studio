"""전환사채 이항+TF 엔진 테스트 — 극한 수렴·경계·옵션 방향성.

방법론 근거는 북 [[복합금융상품_평가]](TF 분리할인·강제전환 필수).
stdlib: `python tests/test_convertible.py`
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core.convertible import (  # noqa: E402
    ConvertibleInputs, price_convertible, straight_bond_value,
)


def _base(**over) -> ConvertibleInputs:
    kw = dict(face=100.0, stock_price=100.0, conversion_ratio=1.0,
              maturity_years=3.0, volatility=0.35, risk_free=0.03,
              credit_spread=0.04, steps=300)
    kw.update(over)
    return ConvertibleInputs(**kw)


# ── 극한 수렴 ────────────────────────────────────────────────────────────────
def test_deep_otm_converges_to_straight_bond():
    # 주가가 액면 대비 극소 → 전환 무가치 → straight bond 수렴
    inp = _base(stock_price=1.0, volatility=0.2)
    r = price_convertible(inp)
    assert abs(r.value - r.straight_bond) / r.straight_bond < 0.01
    assert r.equity_component < 0.5           # 사실상 전액 채권성분


def test_deep_itm_converges_to_conversion_value():
    # 전환가치가 액면의 5배 → 즉시전환 가치 수렴(주식성분 지배)
    inp = _base(stock_price=500.0)
    r = price_convertible(inp)
    assert abs(r.value - r.conversion_value_now) / r.conversion_value_now < 0.02
    assert r.debt_component < r.value * 0.02


def test_zero_vol_no_conversion_equals_bond():
    # σ→0 + OTM → 결정론적으로 상환 → straight bond 와 일치
    inp = _base(stock_price=50.0, volatility=1e-6)
    r = price_convertible(inp)
    assert abs(r.value - r.straight_bond) / r.straight_bond < 0.005


# ── 경계·지배 관계 ───────────────────────────────────────────────────────────
def test_value_at_least_max_of_floors():
    # CB ≥ max(straight bond, 전환가치) (콜 없음)
    r = price_convertible(_base())
    floor = max(r.straight_bond, r.conversion_value_now)
    assert r.value >= floor * 0.999


def test_more_volatility_more_value():
    lo = price_convertible(_base(volatility=0.15)).value
    hi = price_convertible(_base(volatility=0.55)).value
    assert hi > lo


def test_components_sum():
    r = price_convertible(_base())
    assert math.isclose(r.value, r.equity_component + r.debt_component, rel_tol=1e-12)


# ── 옵션 방향성 ─────────────────────────────────────────────────────────────
def test_issuer_call_reduces_value():
    plain = price_convertible(_base()).value
    called = price_convertible(_base(call_price=105.0)).value
    assert called < plain                     # 콜=발행자 옵션 → 보유자 가치 감소
    # 강제전환 하한: 콜 있어도 전환가치 밑으론 안 내려감
    assert called >= _base().conversion_value(100.0) * 0.999


def test_investor_put_increases_value():
    plain = price_convertible(_base(stock_price=60.0)).value
    put = price_convertible(_base(stock_price=60.0, put_price=100.0)).value
    assert put > plain                        # 풋=투자자 옵션 → 가치 증가


def test_forced_conversion_not_overvalue_call():
    # 강제전환 규칙(북): 깊은 ITM + 콜 → 가치는 전환가치 근처(콜가로 눌리지 않음)
    inp = _base(stock_price=300.0, call_price=105.0)
    r = price_convertible(inp)
    assert r.value >= r.conversion_value_now * 0.98


# ── 쿠폰·스프레드 ────────────────────────────────────────────────────────────
def test_coupon_increases_bond_component():
    no_c = price_convertible(_base(stock_price=50.0)).value
    with_c = price_convertible(_base(stock_price=50.0, coupon_rate=0.05)).value
    assert with_c > no_c


def test_higher_spread_lowers_debt_component():
    lo = price_convertible(_base(stock_price=50.0, credit_spread=0.02)).value
    hi = price_convertible(_base(stock_price=50.0, credit_spread=0.10)).value
    assert hi < lo                            # 신용위험↑ → 채권성분↓ (TF 분리할인 작동)


def test_straight_bond_closed_form():
    # 무쿠폰 straight bond = face·e^{-(rf+cs)T}
    inp = _base(coupon_rate=0.0)
    expect = 100.0 * math.exp(-(0.03 + 0.04) * 3.0)
    assert abs(straight_bond_value(inp) - expect) < 1e-9


# ── RCPS 상환권(보장수익률 스케줄) ──────────────────────────────────────────
def test_accrual_zero_equals_fixed_put_at_face():
    # 보장수익률 0% 스케줄 = 고정 put_price=face 와 동치(스케줄 배선 검증)
    fixed = price_convertible(_base(stock_price=60.0, put_price=100.0)).value
    accr0 = price_convertible(_base(stock_price=60.0, put_accrual_rate=0.0)).value
    assert math.isclose(fixed, accr0, rel_tol=1e-9)


def test_guaranteed_rate_monotonic_value():
    # 보장수익률↑ → 상환가 스케줄 전체↑ → RCPS 가치 단조 증가
    vals = [price_convertible(_base(stock_price=60.0, put_accrual_rate=r)).value
            for r in (0.0, 0.04, 0.08)]
    assert vals[0] < vals[1] < vals[2]


def test_otm_rcps_floor_is_accrued_redemption():
    # 깊은 OTM RCPS: 전환 무가치 → 가치 하한 = 보장상환액의 risky 현가
    # (조기 풋 최적행사로 그 이상일 수 있으나 미만은 불가)
    inp = _base(stock_price=5.0, volatility=0.2, put_accrual_rate=0.06)
    r = price_convertible(inp)
    accrued_floor = 100.0 * (1.06 ** 3.0) * math.exp(-(0.03 + 0.04) * 3.0)
    assert r.value >= accrued_floor * 0.999
    assert r.equity_component < 0.5           # 사실상 전액 채권성분
    # straight_bond 도 만기 보장상환액 기준으로 계산돼야 함
    assert straight_bond_value(inp) > 100.0 * math.exp(-0.07 * 3.0)


def test_early_put_exercised_when_optimal():
    # 스프레드가 보장수익률보다 훨씬 크면(위험 할인 > 상환가 증가) 조기 풋이 유리
    # → 가치가 '만기 보장상환 현가'보다 커진다(조기행사 프리미엄)
    inp = _base(stock_price=5.0, volatility=0.2,
                credit_spread=0.15, put_accrual_rate=0.03)
    r = price_convertible(inp)
    hold_to_maturity = 100.0 * (1.03 ** 3.0) * math.exp(-(0.03 + 0.15) * 3.0)
    assert r.value > hold_to_maturity * 1.05


def test_call_accrual_schedule_binds():
    # 발행자 콜 스케줄: 고정 105 콜과 5% accrual 콜(3년 후 ~115.8)은 다른 값
    fixed = price_convertible(_base(call_price=105.0)).value
    accr = price_convertible(_base(call_accrual_rate=0.05)).value
    assert not math.isclose(fixed, accr, rel_tol=1e-6)
    # 콜은 여전히 보유자 가치를 깎는 방향
    plain = price_convertible(_base()).value
    assert accr < plain


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
