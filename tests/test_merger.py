"""합병·주식교환 산식 테스트 — 두산 실측 골든 재현.

stdlib: `python tests/test_merger.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core.merger import (  # noqa: E402
    ExchangeTerms, base_share_price, intrinsic_value, vwap,
)


# ── 두산 골든 (합병_주식교환_방법론, 기준일 2024-07-10) ─────────────────────
def test_doosan_base_price_golden():
    robotics = base_share_price(82_859, 77_482, 80_000)
    bobcat = base_share_price(50_543, 50_292, 51_000)
    assert round(robotics) == 80_114
    assert round(bobcat) == 50_612


def test_doosan_exchange_ratio_golden():
    terms = ExchangeTerms(acquirer_value_ps=80_114, target_value_ps=50_612)
    assert abs(terms.ratio - 0.6318) < 1e-4       # 북: ≈0.6318(소수4자리 반올림 공시)


def test_exchange_ratio_guards_nonpositive():
    try:
        ExchangeTerms(0.0, 50_612).ratio
        raise AssertionError("0 주당가액으로 비율이 계산됨")
    except ValueError:
        pass


# ── VWAP ────────────────────────────────────────────────────────────────────
def test_vwap_weights_by_volume():
    # 고가일수록 거래량 크면 단순평균보다 높아야
    assert vwap([100.0, 200.0], [1.0, 3.0]) == 175.0
    assert vwap([100.0, 200.0], [3.0, 1.0]) == 125.0


def test_vwap_zero_volume_rejected():
    try:
        vwap([100.0], [0.0])
        raise AssertionError("거래량 0 인데 VWAP 통과")
    except ValueError as e:
        assert "거래정지" in str(e)


# ── 본질가치 (자산 1 : 수익 1.5) ────────────────────────────────────────────
def test_intrinsic_value_weights():
    # (10000×1 + 20000×1.5) / 2.5 = 16000
    assert intrinsic_value(10_000, 20_000) == 16_000
    # 자산=수익이면 그 값 그대로
    assert intrinsic_value(5_000, 5_000) == 5_000


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
