"""P4 손상(VIU) 게이트 3종 테스트.

근거: 북 [[손상검사_impairment]] (Issue Paper 234/235/745/746/747 + FSS 2020-33).
stdlib: `python tests/test_impairment_gates.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core.checks import (  # noqa: E402
    check_impairment_trigger, check_viu_cashflow_scope, check_viu_discount_rate,
)
from ingest.validators import Severity  # noqa: E402


def _rules(findings):
    return {f.rule: f.severity for f in findings}


# ── check_viu_discount_rate (234) ────────────────────────────────────────────
def test_viu_rate_market_first_and_gross_up():
    fs = check_viu_discount_rate(simple_gross_up_used=True,
                                 market_observed_rate_available=True)
    r = _rules(fs)
    assert r["viu_rate_market_first"] == Severity.WARN     # 관측 할인율 두고 CAPM
    assert r["viu_rate_gross_up"] == Severity.WARN         # 단순 gross-up 금지


def test_viu_pre_post_consistency():
    # 유효세전율 정합: 세전 VIU == 세후 VIU
    ok = check_viu_discount_rate(viu_pre_tax=1000.0, viu_post_tax=1002.0)
    bad = check_viu_discount_rate(viu_pre_tax=1000.0, viu_post_tax=1100.0)
    assert _rules(ok)["viu_pre_post_consistency"] == Severity.PASS
    assert _rules(bad)["viu_pre_post_consistency"] == Severity.WARN


def test_viu_rate_clean_pass():
    fs = check_viu_discount_rate()
    assert all(f.severity == Severity.PASS for f in fs)


# ── check_viu_cashflow_scope (745/746) ───────────────────────────────────────
def test_viu_scope_flags_each_violation():
    fs = check_viu_cashflow_scope(
        includes_financing=True, includes_tax=True,
        includes_uncommitted_restructuring=True,
        includes_enhancement_capex=True, provision_double_counted=True,
        forecast_years=10, forecast_justified=False,
    )
    r = _rules(fs)
    for rule in ("viu_cf_financing", "viu_cf_tax", "viu_cf_restructuring",
                 "viu_cf_enhancement", "viu_cf_provision_double",
                 "viu_forecast_horizon"):
        assert r[rule] == Severity.WARN, rule


def test_viu_scope_horizon_justified_and_clean():
    ok = check_viu_cashflow_scope(forecast_years=10, forecast_justified=True)
    assert all(f.severity == Severity.PASS for f in ok)
    clean = check_viu_cashflow_scope()
    assert _rules(clean)["viu_cashflow_scope"] == Severity.PASS


# ── check_impairment_trigger (747) ───────────────────────────────────────────
def test_impairment_trigger_market_cap_below_book():
    warn = check_impairment_trigger(800.0, 1000.0)
    ok = check_impairment_trigger(1200.0, 1000.0)
    assert warn.severity == Severity.WARN and "CGU" in warn.message
    assert ok.severity == Severity.PASS


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
