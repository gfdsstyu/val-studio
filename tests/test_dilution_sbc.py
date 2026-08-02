"""P3 SBC·희석 테스트 — dcf 희석 브리지(다모다란 가치차감법) + 게이트 2종.

근거: 북 [[주식기준보상_희석_SBC]] (Issue Paper 524/526/742/743).
stdlib: `python tests/test_dilution_sbc.py`
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core.checks import check_dilution_bridge, check_sbc_treatment  # noqa: E402
from calc_core.dcf import run as dcf_run  # noqa: E402
from calc_core.models import DcfSpineInput  # noqa: E402
from ingest.validators import Severity  # noqa: E402


def _spine(**over) -> DcfSpineInput:
    kw = dict(
        wacc=0.10, terminal_growth=0.01,
        revenue=[1000.0] * 5, cogs=[400.0] * 5, sga=[200.0] * 5,
        dep_amort=[50.0] * 5, capex=[50.0] * 5, delta_nwc_cash_adj=[0.0] * 5,
        non_operating_assets=0.0, net_debt=0.0, shares_outstanding=1_000_000,
    )
    kw.update(over)
    return DcfSpineInput(**kw)


# ── 희석 브리지 (엔진) ───────────────────────────────────────────────────────
def test_dilution_default_zero_preserves_golden_behavior():
    base = dcf_run(_spine())
    withf = dcf_run(_spine(dilutive_claims_value=0.0))
    assert math.isclose(base.per_share, withf.per_share, rel_tol=1e-15)
    assert base.dilutive_claims_value == 0.0


def test_dilution_deducts_from_numerator_not_denominator():
    base = dcf_run(_spine())
    dil = dcf_run(_spine(dilutive_claims_value=100.0))    # 백만원 단위
    # 분자 차감: per_share 감소분 = 100 / 주식수 × 1e6 (분모=기본 주식수 유지)
    expected_drop = 100.0 / 1_000_000 * 1_000_000
    assert math.isclose(base.per_share - dil.per_share, expected_drop, rel_tol=1e-12)
    # equity_value(총 지분)는 불변 — 보통주 귀속만 감소(감사추적 필드 분리)
    assert math.isclose(base.equity_value, dil.equity_value, rel_tol=1e-15)
    assert dil.dilutive_claims_value == 100.0


# ── check_dilution_bridge ────────────────────────────────────────────────────
def test_dilution_gate_warn_when_ignored_or_tsm():
    ignored = check_dilution_bridge(True, 0.0, method="none")
    unvalued = check_dilution_bridge(True, 0.0, method="value_deduction")
    tsm = check_dilution_bridge(True, 50.0, method="treasury_stock")
    assert ignored.severity == Severity.WARN
    assert unvalued.severity == Severity.WARN          # 존재하는데 FV 미평가
    assert tsm.severity == Severity.WARN and "OTM" in tsm.message


def test_dilution_gate_pass_paths():
    assert check_dilution_bridge(False, 0.0).severity == Severity.PASS
    assert check_dilution_bridge(True, 80.0, method="value_deduction").severity == Severity.PASS


# ── check_sbc_treatment ──────────────────────────────────────────────────────
def test_sbc_valuation_addback_is_warn():
    # 다모다란: add-back = 공짜 점심 → WARN, 차감 유지 → PASS
    assert check_sbc_treatment(True, True, purpose="valuation").severity == Severity.WARN
    assert check_sbc_treatment(True, False, purpose="valuation").severity == Severity.PASS
    assert check_sbc_treatment(False, True, purpose="valuation").severity == Severity.PASS


def test_sbc_viu_three_way():
    # 현금결제형: 포함=PASS / 제외=WARN
    assert check_sbc_treatment(True, False, purpose="viu",
                               cash_settled=True).severity == Severity.PASS
    assert check_sbc_treatment(True, True, purpose="viu",
                               cash_settled=True).severity == Severity.WARN
    # 주식결제형: 현금흐름 직접차감=WARN(문언 충돌) / 제외+할인율 미조정=WARN(손상 은폐) /
    # 제외+할인율 조정=PASS(BDO 경로)
    assert check_sbc_treatment(True, False, purpose="viu").severity == Severity.WARN
    assert check_sbc_treatment(True, True, purpose="viu").severity == Severity.WARN
    ok = check_sbc_treatment(True, True, purpose="viu", discount_rate_adjusted=True)
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
