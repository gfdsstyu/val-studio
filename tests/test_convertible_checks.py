"""복합금융 승격 3종 테스트 — with_without 분해·신용악화 게이트·분해 항등식 게이트.

근거: 북 [[복합금융상품_평가]] (Issue Paper 407 with-without · 408 신용악화 상쇄효과 ·
T-F 워크북 3종 채록 tests/golden/test_tf_workbooks.py).
stdlib: `python tests/test_convertible_checks.py`
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core.checks import (  # noqa: E402
    check_cb_decomposition, check_convertible_distress,
)
from calc_core.convertible import (  # noqa: E402
    ConvertibleInputs, price_convertible, with_without,
)
from ingest.validators import Severity  # noqa: E402


def _base(**over) -> ConvertibleInputs:
    kw = dict(face=100.0, stock_price=60.0, conversion_ratio=2.0,
              maturity_years=3.0, volatility=0.2, risk_free=0.03,
              credit_spread=0.02, coupon_rate=0.03, put_price=100.0, steps=200)
    kw.update(over)
    return ConvertibleInputs(**kw)


# ── with_without 분해 ────────────────────────────────────────────────────────
def test_with_without_identity_and_nonnegative_embedded():
    ww = with_without(_base())
    # 항등식은 구성상 성립, 내재파생(홀더 옵션 패키지) ≥ 0
    assert math.isclose(ww.with_value - ww.without_value, ww.embedded_value, rel_tol=1e-12)
    assert ww.embedded_value >= 0.0
    assert math.isclose(ww.with_value, price_convertible(_base()).value, rel_tol=1e-12)


def test_with_without_deep_otm_no_options_embedded_vanishes():
    # 전환 극외가격 + 풋 없음 → 옵션 무가치 → 내재파생 ≈ 0 (전체 → straight bond 수렴)
    inp = _base(stock_price=0.01, put_price=None)
    ww = with_without(inp)
    # 격자 쿠폰 안분(노드 시점)과 straight_bond 폐형(스텝 말) 타이밍 규약 차이만 잔존
    assert abs(ww.embedded_value) / ww.without_value < 2e-3


# ── check_convertible_distress (408 상쇄효과) ────────────────────────────────
def test_distress_pass_at_normal_spread():
    fs = check_convertible_distress(0.02, 121.0)
    assert [f.severity for f in fs] == [Severity.PASS]


def test_distress_warn_and_offset_effect_reproduces_408():
    # 408 재현: 스프레드 2%→50% 급등에도 깊은 ITM+변동성이 전환가치를 떠받쳐
    # CB 총가치가 거의 안 변한다(121→120 수준, 워크북 B 계열이라 쿠폰 0).
    # 엔진 실측: 123.53 → 120.00 (변화 2.9%) — 스트레스 값은 즉시 전환가치(2×60)로 바닥.
    base = price_convertible(_base(coupon_rate=0.0)).value
    stressed = price_convertible(_base(coupon_rate=0.0, credit_spread=0.50)).value
    change = abs(stressed - base) / base
    assert change < 0.05                       # 상쇄효과 실재(엔진 실측)

    fs = check_convertible_distress(0.50, stressed, baseline_value=base)
    names = {f.rule: f.severity for f in fs}
    assert names["cb_distress"] == Severity.WARN
    assert names["cb_offset_effect"] == Severity.WARN


def test_distress_offset_pass_when_value_actually_drops():
    # 가치가 실제로 크게 하락(예: 주가 동반 폭락 반영)이면 상쇄효과 신호 없음
    fs = check_convertible_distress(0.50, 60.0, baseline_value=121.0)
    names = {f.rule: f.severity for f in fs}
    assert names["cb_distress"] == Severity.WARN
    assert names["cb_offset_effect"] == Severity.PASS


# ── check_cb_decomposition (분해 항등식) ─────────────────────────────────────
def test_decomposition_pass_with_engine_with_without():
    ww = with_without(_base())
    f = check_cb_decomposition(ww.with_value, ww.without_value, ww.embedded_value)
    assert f.severity == Severity.PASS


def test_decomposition_warn_on_407_inconsistent_numbers():
    # Issue Paper 407 실측 비정합: T-F 전체차감 파생 = 1,020,000,000 − 918,264,000
    # = 101,736,000 인데 별도평가 합(30,000,000+51,736,000=81,736,000)을 갖다 붙이면
    # 20,000,000 갭 — 서로 다른 평가경로의 수치를 한 분해에 섞은 사례.
    f = check_cb_decomposition(1_020_000_000, 918_264_000, 81_736_000)
    assert f.severity == Severity.WARN
    assert abs(f.detail["gap"] - 20_000_000) < 1


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
