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
    audit_dcf, check_beta_mrp_consistency, check_beta_provenance,
    check_projection_smoothness, check_terminal_growth, check_terminal_value_weight,
    check_wara_irr_wacc, check_working_capital_burn, diagnose_dcf_gap,
)
from calc_core.dcf import run  # noqa: E402
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


# ── F3: β↔MRP 시장정합 ───────────────────────────────────────────────────────
def test_beta_mrp_market_mismatch_warns():
    inp = _wacc_inp(beta_market="KOSPI", mrp_market="SP500")
    assert check_beta_mrp_consistency(inp).severity is Severity.WARN


def test_beta_mrp_market_match_passes():
    inp = _wacc_inp(beta_market="KOSPI", mrp_market="KOSPI")
    assert check_beta_mrp_consistency(inp).severity is Severity.PASS


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
    base = dict(risk_free=0.03, market_risk_premium=0.08, unlevered_beta=1.0,
                target_debt_to_equity=0.3, tax_rate=0.22, pre_tax_cost_of_debt=0.05)
    base.update(kw)
    return WaccInputs(**base)


def test_beta_provenance_missing_warns():
    f = check_beta_provenance(_wacc_inp())
    assert f.severity is Severity.WARN


def test_beta_provenance_present_passes():
    f = check_beta_provenance(_wacc_inp(beta_source="kicpa", beta_market="KOSPI"))
    assert f.severity is Severity.PASS


# ── 추정 시계열 YoY 급변 (모델링_워크플로우_기초 '튀는 연도 재검토' 승격) ───────
def test_smooth_series_passes():
    f = check_projection_smoothness([100, 110, 121, 133, 146])
    assert f.severity is Severity.PASS


def test_yoy_jump_warns_with_location():
    # t=2 에서 +100% 급변(key-in 오류 패턴) → WARN + 위치·크기 detail
    f = check_projection_smoothness([100, 110, 220, 230], name="revenue")
    assert f.severity is Severity.WARN
    assert f.detail["jumps"][0]["index"] == 2
    assert abs(f.detail["jumps"][0]["yoy"] - 1.0) < 1e-9


def test_yoy_skips_nonpositive_base():
    # 직전값 0/음수 → YoY 정의불가 구간은 건너뜀(허위 경고 방지)
    f = check_projection_smoothness([0.0, 50.0, 60.0])
    assert f.severity is Severity.PASS


def test_audit_dcf_includes_smoothness():
    inp = DcfSpineInput(
        wacc=0.09, terminal_growth=0.01,
        revenue=[100.0, 400.0], cogs=[40.0, 40.0], sga=[20.0, 20.0],
        dep_amort=[5.0, 5.0], capex=[5.0, 5.0], delta_nwc_cash_adj=[0.0, 0.0],
        non_operating_assets=0.0, net_debt=0.0, shares_outstanding=1,
    )
    rep = audit_dcf(inp, _result(25.0, 75.0))
    assert any(f.rule == "projection_smoothness" and f.severity is Severity.WARN
               for f in rep.findings)


# ── 괴리 구조버그 가설 진단 (anthropic audit-xls DCF 버그목록 승격) ──────────
def _diag_base():
    inp = DcfSpineInput(
        wacc=0.10, terminal_growth=0.01,
        revenue=[100.0, 110.0, 121.0, 133.1, 146.4],
        cogs=[40.0] * 5, sga=[20.0] * 5, dep_amort=[5.0] * 5, capex=[5.0] * 5,
        delta_nwc_cash_adj=[0.0] * 5,
        non_operating_assets=50.0, net_debt=30.0, shares_outstanding=100.0,
    )
    return inp, run(inp)


def test_diagnosis_pass_when_matching():
    inp, res = _diag_base()
    f = diagnose_dcf_gap(inp, res, res.per_share)
    assert f.severity is Severity.PASS


def test_diagnosis_names_end_year_bug():
    inp, res = _diag_base()
    # ⚠️ per_share 는 백만원→원 환산(×1e6)을 거친다. 이 스케일을 빼먹으면 가설이
    # 실제 주당가치와 100만배 어긋나 어떤 가설도 매칭되지 않는다(선행 결함, 8fbd8b8).
    claimed = ((res.enterprise_value / 1.10 ** 0.5) + 50.0 - 30.0) / 100.0 * 1_000_000
    f = diagnose_dcf_gap(inp, res, claimed)
    assert f.severity is Severity.WARN and "end_year_discounting" in f.message


def test_diagnosis_names_netdebt_ignored():
    inp, res = _diag_base()
    claimed = (res.enterprise_value + 50.0) / 100.0 * 1_000_000   # 순차입 미차감
    f = diagnose_dcf_gap(inp, res, claimed)
    assert "netdebt_ignored" in f.message


def test_diagnosis_assumption_gap_when_no_match():
    inp, res = _diag_base()
    f = diagnose_dcf_gap(inp, res, res.per_share * 1.9)  # 어떤 구조가설과도 무관
    assert f.severity is Severity.WARN and "가정 차이" in f.message


# ── 흑자도산: 운전자본 급증 (참고 모델 교육 §2.4 승격) ─────────────────────────
def test_wc_burn_warns_when_worsening():
    # 매출 성장에도 운전자본 현금유출 비중이 매년 악화 → 흑자도산 WARN (교육 예시 패턴)
    rev = [1000.0, 1200.0, 1440.0, 1728.0, 2074.0]
    dnwc = [-56.0, -87.0, -136.0, -213.0, -332.0]   # 음수=현금유출, 매출 대비 심화
    f = check_working_capital_burn(rev, dnwc)
    assert f.severity is Severity.WARN and "흑자도산" in f.message


def test_wc_burn_pass_when_stable():
    rev = [1000.0, 1100.0, 1210.0]
    dnwc = [-20.0, -22.0, -24.2]                      # 매출 대비 2% 유지 → 악화 아님
    f = check_working_capital_burn(rev, dnwc)
    assert f.severity is Severity.PASS


def test_wc_burn_needs_both_worsening_and_threshold():
    # 매년 악화하나 임계(5%) 미만 → PASS
    rev = [1000.0, 1000.0, 1000.0]
    dnwc = [-10.0, -20.0, -30.0]                      # 1%→2%→3%, 악화지만 5% 미만
    assert check_working_capital_burn(rev, dnwc).severity is Severity.PASS


# ── WARA↔IRR↔WACC reconciliation (감사인 검토 체크리스트 승격) ─────────────────
def test_wara_recon_within_tolerance_passes():
    f = check_wara_irr_wacc(wara=0.095, irr=0.10, wacc=0.092)
    assert f.severity is Severity.PASS


def test_wara_recon_flags_worst_pair():
    f = check_wara_irr_wacc(wara=0.13, irr=0.10, wacc=0.095)
    assert f.severity is Severity.WARN
    assert "WARA-WACC" in f.message                # 최대 괴리쌍 3.5%p 지목


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
