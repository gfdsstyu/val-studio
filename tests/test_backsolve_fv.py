"""Backsolve/OPM 엔진 + 공정가치(FV) 게이트 4종 테스트.

골든: IFRS Issue Paper 201/412 두 클래스 예제 — Equity FV $5,022,875
(= 1,000,000 + Call(1.2M) − 0.1×Call(2.4M); σ80%·r4%·6y·div0).
stdlib: `python tests/test_backsolve_fv.py`
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core.backsolve import (  # noqa: E402
    BacksolveResult, OpmParams, PreferredClass, WaterfallTranche, allocate_equity,
    backsolve_equity, bs_call, common_per_share, price_rcps,
)
from calc_core.checks import (  # noqa: E402
    check_backsolve_anchor, check_day_one_difference, check_fv_hierarchy,
    check_market_price_eligibility,
)
from ingest.validators import Severity  # noqa: E402

P = OpmParams(term_years=6.0, volatility=0.8, risk_free=0.04)
TRANCHES = [
    WaterfallTranche(0.0, 1_200_000.0, {"preferred": 1.0}),
    WaterfallTranche(1_200_000.0, 2_400_000.0, {"common": 1.0}),
    WaterfallTranche(2_400_000.0, None, {"preferred": 0.1, "common": 0.9}),
]
GOLDEN_EQUITY = 5_022_875.0     # 412 시행착오 결과(달러 반올림 워크페이퍼)
GOLDEN_CALL1 = 4_430_673.0
GOLDEN_CALL2 = 4_077_981.0


# ── 골든 재현 ────────────────────────────────────────────────────────────────
def test_golden_call_options_reproduce():
    # 워크페이퍼가 달러 단위 반올림이라 절대오차 1달러 이내면 완전재현
    assert abs(bs_call(GOLDEN_EQUITY, 1_200_000.0, P) - GOLDEN_CALL1) < 1.0
    assert abs(bs_call(GOLDEN_EQUITY, 2_400_000.0, P) - GOLDEN_CALL2) < 1.0


def test_golden_allocation_and_identity():
    alloc = allocate_equity(GOLDEN_EQUITY, TRANCHES, P)
    # 워터폴: preferred = E − Call(1.2M) + 0.1×Call(2.4M) = 1,000,000(발행가액)
    assert abs(alloc["preferred"] - 1_000_000.0) < 1.0
    # 최종 방정식 재배열: common = Call(1.2M) − 0.1×Call(2.4M)
    assert abs(alloc["common"] - (GOLDEN_EQUITY - 1_000_000.0)) < 1.0
    # 배분 항등식: Σ클래스 = 총 지분 FV
    assert math.isclose(sum(alloc.values()), GOLDEN_EQUITY, rel_tol=1e-12)


def test_golden_backsolve_converges():
    res = backsolve_equity(TRANCHES, P, "preferred", 1_000_000.0)
    assert isinstance(res, BacksolveResult)
    assert abs(res.equity_value - GOLDEN_EQUITY) < 5.0      # 워크페이퍼 반올림 대역
    assert abs(res.anchor_error) < 1.0
    # 주당가치 헬퍼(411 최종 산출물 형태)
    assert common_per_share(res, "common", 1_000.0) > 0


def test_backsolve_monotone_in_anchor():
    # 앵커 발행가액↑ → 역산 총 지분 FV↑ (단조성 — 이분탐색 전제 검증)
    lo = backsolve_equity(TRANCHES, P, "preferred", 500_000.0).equity_value
    hi = backsolve_equity(TRANCHES, P, "preferred", 2_000_000.0).equity_value
    assert lo < GOLDEN_EQUITY < hi


def test_waterfall_validation_rejects_bad_tranches():
    bad_share = [WaterfallTranche(0.0, None, {"a": 0.7})]          # 합≠1
    gap = [WaterfallTranche(0.0, 100.0, {"a": 1.0}),
           WaterfallTranche(200.0, None, {"a": 1.0})]              # 불연속
    for tr in (bad_share, gap):
        try:
            allocate_equity(1000.0, tr, P)
            assert False, "ValueError 기대"
        except ValueError:
            pass


# ── FV 게이트 4종 ────────────────────────────────────────────────────────────
def test_anchor_gate_uncertain_and_stale():
    fs = check_backsolve_anchor(None, 400.0)
    rules = {f.rule: f.severity for f in fs}
    assert rules["backsolve_anchor_arms_length"] == Severity.WARN   # 미확인=통과금지
    assert rules["backsolve_anchor_staleness"] == Severity.WARN
    ok = check_backsolve_anchor(True, 30.0)
    assert all(f.severity == Severity.PASS for f in ok)


def test_fv_hierarchy_lowest_level_dominates():
    # 주가 L1 + 역사적 변동성 L3 → 전체 L3 (CB/RCPS 가 L3 인 이유)
    f = check_fv_hierarchy({"주가": 1, "변동성(역사적)": 3}, claimed_level=2)
    assert f.severity == Severity.WARN
    assert f.detail["implied_level"] == 3
    # 조정 가한 L1 은 최소 L2 로 강등
    f2 = check_fv_hierarchy({"종가": 1}, adjusted_level1=True)
    assert f2.detail["implied_level"] == 2


def test_day_one_difference_by_level():
    # Level 3 → 이연·상각 / Level 1 → 즉시손익, 무차이 → PASS
    f3 = check_day_one_difference(1_000.0, 1_100.0, 3)
    f1 = check_day_one_difference(1_000.0, 1_100.0, 1)
    f0 = check_day_one_difference(1_000.0, 1_000.0, 3)
    assert f3.severity == Severity.WARN and "이연" in f3.message
    assert f1.severity == Severity.WARN and "즉시" in f1.message
    assert f0.severity == Severity.PASS


def test_market_price_eligibility():
    # 활성시장 L1 가격이 있는데 모델/DCF 사용 → WARN (350: L1 두고 L2 불가)
    assert check_market_price_eligibility(True, "model").severity == Severity.WARN
    assert check_market_price_eligibility(True, "dcf").severity == Severity.WARN
    assert check_market_price_eligibility(True, "quoted").severity == Severity.PASS
    assert check_market_price_eligibility(False, "model").severity == Severity.PASS


# ═══════════════ RCPS/CPS 노드변동 격자 (411) ═══════════════
def test_rcps_deep_liquidation_floor():
    # 기업가치가 청산우선권 대비 극소 → 우선주 ≈ 청산우선권 현가, 보통주 ≈ 0
    pref = PreferredClass("SeriesC", liquidation_preference=450.0, conversion_fraction=0.28)
    r = price_rcps(50.0, pref, OpmParams(term_years=3, volatility=0.4, risk_free=0.05))
    # V0(50) < LP(450): 우선주가 사실상 전액, 보통주 음수 아님(잔여)
    assert r.preferred_value > r.common_value
    assert r.common_value <= 50.0


def test_rcps_deep_conversion():
    # 기업가치가 청산우선권 대비 극대 → 전환 유리 → 우선주 ≈ V×frac
    pref = PreferredClass("SeriesC", liquidation_preference=450.0, conversion_fraction=0.28)
    V0 = 5000.0
    r = price_rcps(V0, pref, OpmParams(term_years=3, volatility=0.2, risk_free=0.05))
    # 전환가치 지배 → 우선주 ≈ V0×frac 근처(성장·할인 상쇄), 보통주 ≈ V0×(1−frac)
    assert r.preferred_value > pref.liquidation_preference
    assert math.isclose(r.preferred_value + r.common_value, V0, rel_tol=1e-9)


def test_rcps_conversion_boundary():
    pref = PreferredClass("B", liquidation_preference=300.0, conversion_fraction=0.2)
    r = price_rcps(1000.0, pref, OpmParams(term_years=3, volatility=0.3, risk_free=0.05))
    # 전환 경계 = LP/frac = 300/0.2 = 1500 (그 이상이면 전환 유리)
    assert math.isclose(r.conversion_boundary, 1500.0)


def test_rcps_value_conservation():
    # 우선주 + 보통주 = V0 (잔여 항등식)
    pref = PreferredClass("A", liquidation_preference=200.0, conversion_fraction=0.15)
    for V0 in (300.0, 800.0, 2000.0):
        r = price_rcps(V0, pref, OpmParams(term_years=4, volatility=0.35, risk_free=0.04))
        assert math.isclose(r.preferred_value + r.common_value, V0, rel_tol=1e-9)


def test_rcps_american_redemption_ge_european():
    # 조기 청산/전환 허용(american, 상환권 성격) → 우선주 가치 ≥ 유럽형
    pref = PreferredClass("RCPS", liquidation_preference=450.0, conversion_fraction=0.3)
    p = OpmParams(term_years=3, volatility=0.4, risk_free=0.05)
    eur = price_rcps(400.0, pref, p, american=False).preferred_value
    ame = price_rcps(400.0, pref, p, american=True).preferred_value
    assert ame >= eur - 1e-9


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
