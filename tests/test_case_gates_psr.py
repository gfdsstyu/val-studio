"""P5 사례 승격 테스트 — PSR 배수 + 계속기업 게이트 + FCFE 게이트.

근거: 북 [[실전평가_상장사_사례집]] (알테오젠 PSR·홈플러스 흑자도산·FCFE 주의점).
stdlib: `python tests/test_case_gates_psr.py`
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core.checks import check_fcfe_usage, check_going_concern  # noqa: E402
from calc_core.multiples import PeerMultiple, relative_valuation  # noqa: E402
from ingest.validators import Severity  # noqa: E402


def _rules(findings):
    return {f.rule: f.severity for f in findings}


# ── PSR (multiples.py) ───────────────────────────────────────────────────────
def test_psr_implied_per_share():
    # 적자 바이오: PER·EBITDA 결측, PSR 만 존재(알테오젠×Halozyme 패턴)
    peers = [PeerMultiple("H1", psr=6.0), PeerMultiple("H2", psr=7.0),
             PeerMultiple("H3", psr=8.0), PeerMultiple("H4", psr=6.5),
             PeerMultiple("H5", psr=7.5)]
    res = relative_valuation(peers, target_sps=1000.0)
    assert res.psr["stats"]["n"] == 5
    assert math.isclose(res.psr["stats"]["median"], 7.0)
    assert math.isclose(res.psr["implied_per_share"], 7000.0)
    # PER 은 타깃 미제공 → implied 없음·결측 경고도 없음(사용 방식만 경고 원칙)
    assert res.per["implied_per_share"] is None
    assert not any("PER" in w for w in res.warnings)


def test_psr_missing_warning_only_when_used():
    peers = [PeerMultiple("A", psr=6.0), PeerMultiple("B")]  # B 는 PSR 결측
    res = relative_valuation(peers, target_sps=100.0)
    assert any("PSR" in w and "결측" in w for w in res.warnings)


# ── check_going_concern (홈플러스) ───────────────────────────────────────────
def test_going_concern_homeplus_pattern():
    fs = check_going_concern(
        net_loss_with_positive_ocf=True,    # 순손실 + 영업CF 큰 (+) = 흑자도산 신호
        current_ratio=0.6,
        icr_below_one_persistent=True,
        debt_to_ebitda=9.0,
    )
    r = _rules(fs)
    for rule in ("going_concern_ocf_paradox", "going_concern_current_ratio",
                 "going_concern_icr", "going_concern_leverage", "going_concern"):
        assert r[rule] == Severity.WARN, rule


def test_going_concern_clean():
    fs = check_going_concern(current_ratio=1.5, debt_to_ebitda=2.0)
    assert _rules(fs)["going_concern"] == Severity.PASS


# ── check_fcfe_usage ─────────────────────────────────────────────────────────
def test_fcfe_wacc_discount_is_fail():
    fs = check_fcfe_usage(uses_fcfe=True, discounted_at_cost_of_equity=False)
    r = _rules(fs)
    assert r["fcfe_discount_rate"] == Severity.FAIL     # 분자·분모 불일치 = 구조 오류


def test_fcfe_borrowing_illusion_and_clean():
    warn = check_fcfe_usage(uses_fcfe=True, discounted_at_cost_of_equity=True,
                            levered_beta_used=True, net_borrowing_included=True,
                            borrowing_nature_assessed=False,
                            stable_target_leverage=True)
    assert _rules(warn)["fcfe_borrowing_illusion"] == Severity.WARN
    ok = check_fcfe_usage(uses_fcfe=True, discounted_at_cost_of_equity=True,
                          levered_beta_used=True, net_borrowing_included=True,
                          borrowing_nature_assessed=True,
                          stable_target_leverage=True)
    assert all(f.severity == Severity.PASS for f in ok)
    off = check_fcfe_usage(uses_fcfe=False)
    assert _rules(off)["fcfe_usage"] == Severity.PASS


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
