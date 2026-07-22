"""상대가치 배수 테스트 — 통계(양수만)·PER/PBR/EV-EBITDA 내재가치·5-10 Rule.

stdlib: `python tests/test_multiples.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core.multiples import (  # noqa: E402
    PeerMultiple, multiple_stats, relative_valuation,
)


def test_stats_excludes_nonpositive_and_none():
    s = multiple_stats([10.0, 20.0, None, -5.0, 30.0])
    assert s["n"] == 3 and s["median"] == 20.0 and s["mean"] == 20.0


def test_per_pbr_implied():
    peers = [PeerMultiple("A", per=10, pbr=1.0), PeerMultiple("B", per=12, pbr=1.2),
             PeerMultiple("C", per=14, pbr=1.4), PeerMultiple("D", per=16, pbr=1.6),
             PeerMultiple("E", per=18, pbr=1.8)]
    r = relative_valuation(peers, target_eps=1000, target_bps=8000, use="median")
    assert r.per["stats"]["median"] == 14 and r.per["implied_per_share"] == 14000
    assert r.pbr["stats"]["median"] == 1.4 and abs(r.pbr["implied_per_share"] - 11200) < 1e-6
    assert not r.warnings                         # 5개 = OK


def test_ev_ebitda_bridge():
    peers = [PeerMultiple("A", ev_ebitda=8), PeerMultiple("B", ev_ebitda=10),
             PeerMultiple("C", ev_ebitda=12), PeerMultiple("D", ev_ebitda=6),
             PeerMultiple("E", ev_ebitda=14)]
    r = relative_valuation(peers, target_ebitda=1000, net_debt=2000, shares_outstanding=100)
    # median EV/EBITDA=10 → EV=10000, (−순차입2000)/100주 = 80
    assert r.ev_ebitda["stats"]["median"] == 10
    assert abs(r.ev_ebitda["implied_per_share"] - 80) < 1e-6


def test_size_rule_warnings():
    few = [PeerMultiple("A", per=10), PeerMultiple("B", per=12)]
    assert any("< 5" in w for w in relative_valuation(few, target_eps=1000).warnings)
    many = [PeerMultiple(f"P{i}", per=10 + i) for i in range(11)]
    assert any("> 10" in w for w in relative_valuation(many, target_eps=1000).warnings)


def test_missing_multiple_warning():
    peers = [PeerMultiple("A", per=10), PeerMultiple("B", per=None),
             PeerMultiple("C", per=14), PeerMultiple("D", per=16), PeerMultiple("E", per=18)]
    r = relative_valuation(peers, target_eps=1000)
    assert any("결측" in w for w in r.warnings)   # PER 1개 결측


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
