"""터미널 정규화 WC 재조정 테스트 — 참고 모델 정본 §Normalized CF 과대계상 방어.

정본 예시: 추정말매출 1,100, g=3%, WC/매출=30% → 옳은 터미널 WC 투자 = 1,100×3%×30% = 9.9.
기본값(ΔWC=0)은 이 투자를 안 빼 FCFF·TV 과대계상. terminal_wc_ratio 로 정본 공식 반영.

stdlib: `python tests/test_terminal_wc_normalization.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core import wc  # noqa: E402
from calc_core.checks import check_terminal_growth  # noqa: E402
from calc_core.dcf import run  # noqa: E402
from calc_core.models import DcfSpineInput  # noqa: E402
from ingest.validators import Severity  # noqa: E402


def close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) < tol


def _inp(**over) -> DcfSpineInput:
    # 단순 1년 명시기간: 매출 1,100 · EBIT=매출·마진, 세금 무시(effective 0)로 NOPLAT=EBIT
    kw = dict(
        wacc=0.10, terminal_growth=0.03,
        revenue=[1100.0], cogs=[0.0], sga=[0.0],
        dep_amort=[0.0], capex=[0.0], delta_nwc_cash_adj=[0.0],
        non_operating_assets=0.0, net_debt=0.0, shares_outstanding=1_000_000,
        effective_tax_rate=0.0,        # NOPLAT_T = EBIT_T = 1100·1.03 = 1133
    )
    kw.update(over)
    return DcfSpineInput(**kw)


def test_default_overstates_vs_normalized():
    # NOPLAT_T = 1100×1.03 = 1133. WACC−g = 7%.
    base_default = run(_inp())                       # ΔWC=0
    base_norm = run(_inp(terminal_wc_ratio=0.30))    # 정본: ΔWC = 1100×3%×30% = 9.9
    # 터미널 FCFF: 기본 1133 vs 정규화 1133−9.9 = 1123.1
    assert close(base_default.terminal_fcff, 1133.0)
    assert close(base_norm.terminal_fcff, 1133.0 - 9.9)
    # 기본값이 TV·EV 를 과대계상(더 큼)
    assert base_default.terminal_value > base_norm.terminal_value
    # TV = FCFF_T/0.07
    assert close(base_norm.terminal_value, (1133.0 - 9.9) / 0.07)


def test_wc_normalization_matches_reference_formula():
    # 정본 공식 직접 확인: 터미널 WC 투자 = 추정말매출 × g × 비율
    inp = _inp(terminal_wc_ratio=0.30)
    expected_wc = 1100.0 * 0.03 * 0.30              # = 9.9
    noplat_t = 1100.0 * 1.03                        # 세율0 → NOPLAT=EBIT
    assert close(run(inp).terminal_fcff, noplat_t - expected_wc)


def test_normalized_wc_ratio_helper():
    # 추정말 순운전자본 330 / 매출 1100 = 0.30
    assert close(wc.normalized_wc_ratio(330.0, 1100.0), 0.30)
    assert wc.normalized_wc_ratio(330.0, 0.0) is None     # 매출0 → 산출불가


def test_reinvestment_rate_takes_precedence_over_wc_ratio():
    # reinvestment_rate 가 있으면 WC 를 이미 번들 → wc_ratio 무시(중복차감 방지)
    inp = _inp(terminal_reinvestment_rate=0.20, terminal_wc_ratio=0.30)
    noplat_t = 1100.0 * 1.03
    assert close(run(inp).terminal_fcff, noplat_t * (1.0 - 0.20))


def test_f1_warns_without_wc_model():
    # g=3% > 2%, 재투자 미반영 → F1 과대계상 WARN
    fs = check_terminal_growth(0.03, 0.10, reinvestment_modeled=False)
    f1 = [f for f in fs if f.rule == "terminal_reinvestment"]
    assert f1 and f1[0].severity is Severity.WARN


def test_f1_passes_when_wc_modeled():
    # 정규화 WC/재투자 반영됐다고 알리면 F1 이 PASS 로 승격
    fs = check_terminal_growth(0.03, 0.10, reinvestment_modeled=True)
    f1 = [f for f in fs if f.rule == "terminal_reinvestment"]
    assert f1 and f1[0].severity is Severity.PASS


def test_audit_dcf_wires_flag():
    # audit_dcf 가 inp.terminal_wc_ratio 를 보고 F1 을 PASS 로 넘기는지(end-to-end)
    from calc_core.checks import audit_dcf
    inp = _inp(terminal_wc_ratio=0.30)
    result = run(inp)
    rpt = audit_dcf(inp, result)
    f1 = [f for f in rpt.findings if f.rule == "terminal_reinvestment"]
    assert f1 and f1[0].severity is Severity.PASS


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
