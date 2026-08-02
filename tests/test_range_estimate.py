"""범위추정(기준서 540 문단 28~29) 테스트 — 수렴·게이트·판정.

핵심 검증 3축:
  ① 수렴 — 구간을 점(low==high==base)으로 좁히면 점추정과 정확히 일치해야 한다.
     범위추정이 점추정의 일반화임을 골든(비올 8,413.38)으로 증명.
  ② 게이트 — 29(a) 근거 없는 구간·역전 구간·미허용 필드는 **계산 자체가 차단**된다.
  ③ 판정 — 주장값이 범위 밖이면 최소 조정액(가까운 경계까지)이 정확해야 한다(450 연결).

stdlib: `python tests/test_range_estimate.py`
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core import DcfSpineInput, run  # noqa: E402
from calc_core.range_estimate import (  # noqa: E402
    MAX_ASSUMPTIONS, RangeAssumption, range_estimate,
)

FX = ROOT / "fixtures" / "viol"


def _viol() -> DcfSpineInput:
    d = json.loads((FX / "inputs.json").read_text(encoding="utf-8"))
    return DcfSpineInput(
        wacc=d["wacc"], terminal_growth=d["terminal_growth"],
        revenue=d["revenue"], cogs=d["cogs"], sga=d["sga"],
        dep_amort=d["dep_amort"], capex=d["capex"],
        delta_nwc_cash_adj=d["delta_nwc_cash_adj"],
        non_operating_assets=d["non_operating_assets"], net_debt=d["net_debt"],
        shares_outstanding=d["shares_outstanding"],
        mid_year_periods=d.get("mid_year_periods"),
        terminal_discount_period=d.get("terminal_discount_period"),
    )


def _close(a, b, tol=1e-9):
    return math.isclose(a, b, rel_tol=tol, abs_tol=1e-9)


def test_point_interval_converges_to_point_estimate():
    """① 수렴: 전 구간을 base 값의 점으로 좁히면 범위 == 점추정(비올 골든)."""
    base = _viol()
    r = range_estimate(base, [
        RangeAssumption("wacc", base.wacc, base.wacc, basis_low="base 동일"),
        RangeAssumption("terminal_growth", base.terminal_growth, base.terminal_growth,
                        basis_low="base 동일"),
    ])
    assert not r.blocked, [f.message for f in r.findings]
    golden = run(base).per_share
    assert _close(r.low, golden) and _close(r.high, golden)
    assert _close(r.base_per_share, golden)
    assert r.n_evaluations == 1                    # 점 구간 2개 → 조합 1개


def test_range_brackets_and_extreme_combos():
    """구간이 실제 극값 조합을 찾는다 — WACC↓·g↑ 가 상한, WACC↑·g↓ 가 하한."""
    base = _viol()
    r = range_estimate(base, [
        RangeAssumption("wacc", base.wacc - 0.01, base.wacc + 0.01,
                        basis_low="peer β 하위", basis_high="peer β 상위"),
        RangeAssumption("terminal_growth", 0.01, 0.03,
                        basis_low="보수 시나리오", basis_high="산업 CAGR 상단"),
    ])
    assert not r.blocked
    assert r.n_evaluations == 4                    # 2^2 전 조합
    assert r.low < r.base_per_share < r.high       # base 가 범위 안(구간이 base 를 포함하므로)
    # 가치 극대 = 할인율 최소 × 성장률 최대 (이 케이스에선 단조)
    assert r.combo_high == {"wacc": base.wacc - 0.01, "terminal_growth": 0.03}
    assert r.combo_low == {"wacc": base.wacc + 0.01, "terminal_growth": 0.01}


def test_series_scale_assumption():
    """시계열 스케일(revenue ±5%)이 실제로 시계열 전체에 곱해진다."""
    base = _viol()
    r = range_estimate(base, [
        RangeAssumption("revenue_scale", 0.95, 1.05,
                        basis_low="수주 지연 시나리오", basis_high="컨센서스 상단"),
    ])
    assert not r.blocked
    # 상한 조합 = 매출 +5% — 직접 계산과 일치해야 함
    import dataclasses
    up = dataclasses.replace(base, revenue=[x * 1.05 for x in base.revenue])
    assert _close(r.high, run(up).per_share)


def test_basis_missing_blocks():
    """② 29(a): 상한 근거가 없으면 차단 — 근거 없는 범위는 증거 부재다."""
    base = _viol()
    r = range_estimate(base, [
        RangeAssumption("wacc", 0.10, 0.13, basis_low="Kd 스프레드 하위"),  # 상한 근거 없음
    ])
    assert r.blocked
    assert any(f.rule == "range_basis_missing" for f in r.findings)
    assert r.low is None and r.high is None        # 반쪽 결과를 내지 않는다


def test_point_interval_needs_one_basis_only():
    """점 구간(low==high)은 근거 하나로 족하다 — 과잉 요구로 사용성 죽이지 않기."""
    base = _viol()
    r = range_estimate(base, [
        RangeAssumption("wacc", base.wacc, base.wacc, basis_low="실측 WACC"),
    ])
    assert not r.blocked


def test_inverted_unknown_duplicate_and_too_many_block():
    """② 역전 구간·미허용 필드·중복 필드·개수 초과 전부 차단."""
    base = _viol()
    r = range_estimate(base, [
        RangeAssumption("wacc", 0.13, 0.10, "a", "b"),            # 역전
        RangeAssumption("shares_outstanding", 1, 2, "a", "b"),    # 미허용(화이트리스트 밖)
        RangeAssumption("wacc", 0.10, 0.11, "a", "b"),            # 중복
    ])
    assert r.blocked
    rules = {f.rule for f in r.findings}
    assert {"range_inverted", "range_unknown_field", "range_duplicate_field"} <= rules

    many = [RangeAssumption(f, 0.9, 1.1, "a", "b") for f in
            ["revenue_scale", "cogs_scale", "sga_scale", "dep_amort_scale",
             "capex_scale", "delta_nwc_cash_adj_scale"]] + [
        RangeAssumption(f, 0.01, 0.02, "a", "b") for f in
        ["wacc", "terminal_growth", "net_debt", "non_operating_assets",
         "non_controlling_interest"]]
    assert len(many) == MAX_ASSUMPTIONS + 1
    r2 = range_estimate(base, many)
    assert r2.blocked and any(f.rule == "range_too_many" for f in r2.findings)


def test_claimed_outside_yields_min_adjustment():
    """③ 판정: 주장값이 상한 위면 최소 조정액 = 주장값 − 상한(과대)."""
    base = _viol()
    # 먼저 범위를 구해 상한보다 1,000원 높은 주장값으로 재판정
    r0 = range_estimate(base, [
        RangeAssumption("wacc", base.wacc - 0.005, base.wacc + 0.005, "a", "b"),
    ])
    claimed = r0.high + 1000.0
    r = range_estimate(base, [
        RangeAssumption("wacc", base.wacc - 0.005, base.wacc + 0.005, "a", "b"),
    ], claimed_per_share=claimed)
    assert r.claimed_within is False
    assert _close(r.min_adjustment, 1000.0, tol=1e-6)
    assert any(f.rule == "claimed_outside_range" for f in r.findings)
    # 범위 안이면 조정액 0
    r_in = range_estimate(base, [
        RangeAssumption("wacc", base.wacc - 0.005, base.wacc + 0.005, "a", "b"),
    ], claimed_per_share=r0.base_per_share)
    assert r_in.claimed_within is True and r_in.min_adjustment == 0.0


def test_wide_range_warns():
    """A124-A125 취지: 지나치게 넓은 범위는 WARN — 넓음 = 증거 부족 신호."""
    base = _viol()
    r = range_estimate(base, [
        RangeAssumption("wacc", base.wacc - 0.03, base.wacc + 0.03,
                        "극단 하한", "극단 상한"),
        RangeAssumption("terminal_growth", 0.0, 0.04, "0 성장", "고성장"),
    ])
    assert not r.blocked
    assert any(f.rule == "range_too_wide" for f in r.findings)


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
