"""주가 커넥터 테스트 — 베타 회귀·조정베타·look-ahead 가드·시가총액.

stdlib: `python tests/test_price_client.py` (fdr 미설치여도 SyntheticProvider 로 전부 통과)
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ingest.price_client import (  # noqa: E402
    SyntheticProvider, beta_from_prices, bloomberg_adjusted_beta,
    compute_beta, market_cap,
)


def _closes_from_returns(returns: list[float], start: float = 100.0):
    c = [start]
    for r in returns:
        c.append(c[-1] * (1 + r))
    return c


# 시장 수익률(주별 가정) — 임의 변동
MRET = [0.012, -0.021, 0.015, 0.004, -0.010, 0.022, -0.006, 0.018, -0.013, 0.009,
        0.005, -0.017, 0.011, 0.003, -0.008]


def test_compute_beta_recovers_known_slope():
    beta = 1.3
    m = _closes_from_returns(MRET)
    s = _closes_from_returns([beta * r for r in MRET])   # 주식수익률 = 1.3×시장
    res = compute_beta(s, m)
    assert abs(res.raw - beta) < 1e-9
    assert res.r_squared > 0.999                          # 완전선형 → R²≈1
    assert res.n == len(MRET)


def test_adjusted_beta_formula():
    assert abs(bloomberg_adjusted_beta(1.3) - 1.201) < 1e-12   # 0.67·1.3+0.33
    assert abs(bloomberg_adjusted_beta(1.0) - 1.0) < 1e-12     # 시장평균은 불변
    m = _closes_from_returns(MRET)
    s = _closes_from_returns([1.3 * r for r in MRET])
    assert abs(compute_beta(s, m).adjusted - 1.201) < 1e-9


def test_insufficient_points_raises():
    try:
        compute_beta([100.0, 101.0], [100.0])
        raise AssertionError("관측치 부족인데 통과")
    except ValueError as e:
        assert "부족" in str(e)


# ── look-ahead 가드: 평가기준일 이후 가격은 회귀에서 제외 ──────────────────
def _weekly_series(returns, first="2023-03-17"):
    d = datetime.date.fromisoformat(first)
    closes = _closes_from_returns(returns)
    out = []
    for c in closes:
        out.append((d.isoformat(), c))
        d += datetime.timedelta(days=7)
    return out


def test_beta_from_prices_excludes_future():
    base = "2023-06-30"
    # 기준일까지 β=1.3, 기준일 이후는 β=3.0(포함되면 결과가 크게 달라짐)
    pre_m, pre_s = MRET, [1.3 * r for r in MRET]
    post_m, post_s = [0.02, -0.03, 0.04], [3.0 * 0.02, 3.0 * -0.03, 3.0 * 0.04]
    m_series = _weekly_series(pre_m + post_m)
    s_series = _weekly_series(pre_s + post_s)
    prov = SyntheticProvider({"005930": s_series, "KS11": m_series})
    res = beta_from_prices(prov, "005930", "KS11", base, freq="W", years=1)
    assert res.window_end == base
    # 기준일 이후(β=3.0) 데이터가 새면 raw 가 1.3 에서 크게 벗어남 → 가드가 작동해야 ≈1.3
    assert abs(res.raw - 1.3) < 0.05
    assert all(d <= base for d, _ in prov.closes("005930", "2000-01-01", base))


def test_market_cap_picks_latest_on_or_before_base():
    series = [("2023-06-28", 70000.0), ("2023-06-29", 71000.0),
              ("2023-06-30", 72000.0), ("2023-07-03", 99999.0)]  # 기준일 이후는 무시
    prov = SyntheticProvider({"005930": series})
    mc = market_cap(prov, "005930", shares=5_000_000, base_date="2023-06-30")
    assert mc.price == 72000.0 and mc.price_date == "2023-06-30"
    assert mc.value == 72000.0 * 5_000_000


def test_synthetic_provider_date_filter():
    prov = SyntheticProvider({"A": [("2023-01-01", 1.0), ("2023-06-01", 2.0), ("2023-12-01", 3.0)]})
    assert prov.closes("A", "2023-05-01", "2023-07-01") == [("2023-06-01", 2.0)]


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
