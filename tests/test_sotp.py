"""SOTP(다개체·다통화 합산) 테스트 — 다산네트웍스 자산양수도 구조 근거.

stdlib: `python tests/test_sotp.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core import dcf  # noqa: E402
from calc_core.models import DcfSpineInput  # noqa: E402
from calc_core.sotp import SotpPart, run_sotp  # noqa: E402


def _mk(rev0: float, g_ppt: float = 0.0) -> DcfSpineInput:
    """간단 1개체 입력(로컬 통화 백만)."""
    return DcfSpineInput(
        wacc=0.10, terminal_growth=0.01,   # 외부의견서 실측 영구성장률 1%
        revenue=[rev0], cogs=[rev0 * 0.4], sga=[rev0 * 0.2],
        dep_amort=[rev0 * 0.05], capex=[rev0 * 0.05], delta_nwc_cash_adj=[0.0],
        non_operating_assets=0.0, net_debt=0.0, shares_outstanding=1,
        mid_year_periods=[0.5], terminal_discount_period=0.5,
    )


def test_single_part_matches_plain_dcf():
    inp = _mk(1000.0)
    sotp = run_sotp([SotpPart("A", inp)])
    assert abs(sotp.total_equity_base - dcf.run(inp).equity_value) < 1e-9


def test_multi_currency_conversion():
    # KRW 본사 + JPY 자회사(환율 9 KRW/JPY 가정)
    krw = SotpPart("본사", _mk(1000.0), currency="KRW", fx_to_base=1.0)
    jpy = SotpPart("DZS Japan", _mk(500.0), currency="JPY", fx_to_base=9.0)
    r = run_sotp([krw, jpy], base_currency="KRW")
    eq_krw = dcf.run(krw.dcf_input).equity_value
    eq_jpy = dcf.run(jpy.dcf_input).equity_value * 9.0
    assert abs(r.total_equity_base - (eq_krw + eq_jpy)) < 1e-6
    # JPY 파트는 환산 후 더 큰 기여
    assert r.parts[1].attributable_base == eq_jpy


def test_ownership_scaling():
    full = run_sotp([SotpPart("A", _mk(1000.0))]).total_equity_base
    half = run_sotp([SotpPart("A", _mk(1000.0), ownership=0.5)]).total_equity_base
    assert abs(half - full * 0.5) < 1e-9


def test_weights_sum_to_one():
    r = run_sotp([
        SotpPart("DNS", _mk(2000.0)),
        SotpPart("DZS Japan", _mk(500.0), currency="JPY", fx_to_base=9.0),
        SotpPart("DZS Vietnam", _mk(300.0), currency="VND", fx_to_base=0.05),
    ])
    total_w = sum(r.weight_of(p.name) for p in r.parts)
    assert abs(total_w - 1.0) < 1e-9
    assert len(r.parts) == 3


def test_invalid_inputs():
    for bad in (
        lambda: SotpPart("x", _mk(100.0), ownership=1.5),
        lambda: SotpPart("x", _mk(100.0), fx_to_base=0.0),
        lambda: run_sotp([]),
    ):
        try:
            bad(); assert False, "검증 실패"
        except (ValueError,):
            pass


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
