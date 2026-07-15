"""가정 타당성 검사(checks.py) 단위테스트 — PGR·TV비중·β provenance.

근거: docs/reference/영구성장률_PGR_적합성.md, 베타_Bloomberg_vs_KICPA.md.
stdlib: `python tests/test_checks.py` 또는 pytest.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core.checks import (  # noqa: E402
    audit_dcf, check_beta_erp_consistency, check_beta_provenance,
    check_terminal_growth, check_terminal_value_weight,
)
from calc_core.models import DcfResult, DcfSpineInput  # noqa: E402
from calc_core.wacc import WaccInputs, kroll_size_decile, kroll_size_premium  # noqa: E402
from ingest.validators import Severity  # noqa: E402


def _sev(findings, rule):
    return next(f.severity for f in findings if f.rule == rule)


# ── PGR vs WACC (Gordon 수렴) ────────────────────────────────────────────────
def test_pgr_ge_wacc_fails():
    fs = check_terminal_growth(pgr=0.10, wacc=0.08)
    assert _sev(fs, "pgr_vs_wacc") is Severity.FAIL


def test_pgr_lt_wacc_passes():
    fs = check_terminal_growth(pgr=0.01, wacc=0.09)
    assert _sev(fs, "pgr_vs_wacc") is Severity.PASS


def test_narrow_spread_warns():
    # WACC−PGR < 1%p → 극도 민감 경고
    fs = check_terminal_growth(pgr=0.075, wacc=0.08)
    assert _sev(fs, "pgr_vs_wacc") is Severity.WARN


# ── PGR vs GDP (경제성 상한) ─────────────────────────────────────────────────
def test_pgr_above_gdp_warns():
    fs = check_terminal_growth(pgr=0.04, wacc=0.10, long_term_gdp=0.02)
    assert _sev(fs, "pgr_vs_gdp") is Severity.WARN


def test_pgr_within_gdp_passes():
    fs = check_terminal_growth(pgr=0.01, wacc=0.10, long_term_gdp=0.02)
    assert _sev(fs, "pgr_vs_gdp") is Severity.PASS


# ── F1: terminal 재투자 정합성 ───────────────────────────────────────────────
def test_high_pgr_reinvestment_warns():
    # PGR 3% > 2% + 재투자모델無 → TV 과대 경고
    fs = check_terminal_growth(pgr=0.03, wacc=0.10)
    assert _sev(fs, "terminal_reinvestment") is Severity.WARN


def test_low_pgr_no_reinvestment_finding():
    # PGR 1% ≤ 2% → 재투자 경고 없음(한국 관행 안전대)
    fs = check_terminal_growth(pgr=0.01, wacc=0.10)
    assert not any(f.rule == "terminal_reinvestment" for f in fs)


# ── F2: Kroll size premium ───────────────────────────────────────────────────
def test_kroll_large_cap_low_premium():
    label, prem = kroll_size_decile(20000.0)  # $20B → decile 1
    assert prem == 0.0052 and label.startswith("1")


def test_kroll_micro_cap_high_premium():
    label, prem = kroll_size_decile(100.0)  # $100M → micro
    assert prem == 0.0522 and "Micro" in label


def test_kroll_monotonic_decreasing():
    # 시가총액 ↑ → premium ↓ (단조)
    caps = [50, 500, 1500, 3000, 8000, 20000]
    prems = [kroll_size_premium(c) for c in caps]
    assert prems == sorted(prems, reverse=True)


# ── F3: β↔ERP 시장정합 ───────────────────────────────────────────────────────
def test_beta_erp_market_mismatch_warns():
    inp = _wacc_inp(beta_market="KOSPI", erp_market="SP500")
    assert check_beta_erp_consistency(inp).severity is Severity.WARN


def test_beta_erp_market_match_passes():
    inp = _wacc_inp(beta_market="KOSPI", erp_market="KOSPI")
    assert check_beta_erp_consistency(inp).severity is Severity.PASS


# ── TV 비중 ──────────────────────────────────────────────────────────────────
def _result(pv_explicit: float, pv_tv: float) -> DcfResult:
    ev = pv_explicit + pv_tv
    return DcfResult(
        ebit=[], tax=[], noplat=[], fcff=[], pv_factor=[], pv_fcff=[],
        terminal_fcff=0.0, terminal_value=0.0, terminal_value_pv=pv_tv,
        pv_explicit_sum=pv_explicit, enterprise_value=ev,
        non_operating_assets=0.0, net_debt=0.0, equity_value=ev,
        shares_outstanding=1, per_share=0.0,
    )


def test_tv_weight_typical_passes():
    # 25:75 관행 → PASS + 비중 detail
    f = check_terminal_value_weight(_result(25.0, 75.0))
    assert f.severity is Severity.PASS
    assert abs(f.detail["tv_weight"] - 0.75) < 1e-9


def test_tv_weight_overreliance_warns():
    f = check_terminal_value_weight(_result(5.0, 95.0))  # 95% > 90%
    assert f.severity is Severity.WARN


# ── β provenance ─────────────────────────────────────────────────────────────
def _wacc_inp(**kw) -> WaccInputs:
    base = dict(risk_free=0.03, equity_risk_premium=0.08, unlevered_beta=1.0,
                target_debt_to_equity=0.3, tax_rate=0.22, pre_tax_cost_of_debt=0.05)
    base.update(kw)
    return WaccInputs(**base)


def test_beta_provenance_missing_warns():
    f = check_beta_provenance(_wacc_inp())
    assert f.severity is Severity.WARN


def test_beta_provenance_present_passes():
    f = check_beta_provenance(_wacc_inp(beta_source="kicpa", beta_market="KOSPI"))
    assert f.severity is Severity.PASS


# ── 종합 audit_dcf ──────────────────────────────────────────────────────────
def test_audit_dcf_gate():
    inp = DcfSpineInput(
        wacc=0.09, terminal_growth=0.01,
        revenue=[100.0], cogs=[40.0], sga=[20.0], dep_amort=[5.0],
        capex=[5.0], delta_nwc_cash_adj=[0.0],
        non_operating_assets=0.0, net_debt=0.0, shares_outstanding=1,
    )
    rep = audit_dcf(inp, _result(25.0, 75.0),
                    wacc_inputs=_wacc_inp(beta_source="kicpa", beta_market="KOSPI"))
    assert rep.ok  # 정상 가정 → fail 없음


def test_audit_dcf_catches_divergence():
    inp = DcfSpineInput(
        wacc=0.05, terminal_growth=0.06,  # PGR > WACC → FAIL
        revenue=[100.0], cogs=[40.0], sga=[20.0], dep_amort=[5.0],
        capex=[5.0], delta_nwc_cash_adj=[0.0],
        non_operating_assets=0.0, net_debt=0.0, shares_outstanding=1,
    )
    rep = audit_dcf(inp, _result(25.0, 75.0))
    assert not rep.ok  # Gordon 발산 → 게이트 차단


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            passed += 1
        except Exception:
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(fns)} passed")
