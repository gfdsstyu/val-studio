"""KSIC 로컬 조회 테스트 — 실데이터(2,000코드) 기반.

stdlib: `python tests/test_ksic.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ingest import ksic  # noqa: E402
from ingest.peer_selection import PeerCandidate, codes_from_seed_peers  # noqa: E402


def test_full_table_loaded():
    assert len(ksic._load()) == 2000


def test_exact_lookup():
    assert ksic.name("2719") == "기타 의료용 기기 제조업"
    assert ksic.name("00000") is None


def test_keyword_search_multi_term_and():
    hits = ksic.search("의료용 기기")
    assert ("2719", "기타 의료용 기기 제조업") in hits
    assert all("의료용" in n and "기기" in n for _, n in hits)


def test_parents_chain():
    p = ksic.parents("27192")
    assert [c for c, _ in p] == ["27", "271", "2719"]


def test_children_of_prefix():
    ch = ksic.children("2719")
    assert all(c.startswith("2719") and c != "2719" for c, _ in ch)
    assert any(c == "27192" for c, _ in ch)


def test_population_codes_generalizes_seeds():
    # 시드 세세분류(5자리) → 세분류(4자리) union — Step1a 실무 기본
    seeds = {"27192", "27199", "21210"}
    assert ksic.population_codes(seeds) == {"2719", "2121"}
    # 이미 4자리 이하는 그대로
    assert ksic.population_codes({"2719"}) == {"2719"}


def test_bridges_with_peer_selection_seed_flow():
    # 시드 회사(DART induty_code) → 역산 → 모집단 코드 → 이름 확인 전 과정
    seeds = [PeerCandidate("1", "시드A", "27192"), PeerCandidate("2", "시드B", "27199")]
    pop = ksic.population_codes(codes_from_seed_peers(seeds))
    assert pop == {"2719"}
    assert ksic.name(next(iter(pop))) == "기타 의료용 기기 제조업"


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
