"""밸류에이션 북 검색기 테스트 — 4층 신호(질문·키워드·그래프확장·섹션청킹).

stdlib: `python tests/test_rag_search.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from rag.searcher import BookSearcher, _sim  # noqa: E402

S = BookSearcher()


def _top(query: str, k: int = 5):
    return [h.chapter_id for h in S.search(query, top_k=k)]


# ── 핵심 질의 → 정답 챕터 top ────────────────────────────────────────────────
def test_pgr_query():
    top = _top("영구성장률 몇 퍼센트로 잡아야 하나")
    assert top[0] == "영구성장률_PGR_적합성", top


def test_rcps_query():
    top = _top("RCPS 상환전환우선주 평가 방법")
    assert "복합금융상품_평가" in top[:2], top


def test_impairment_query():
    top = _top("CGU 영업권 손상검사는 어떻게 하나")
    assert top[0] == "손상검사_impairment", top


def test_wacc_audit_query():
    top = _top("감사인은 WACC를 어떻게 검토하나")
    assert "감사인검토_WACC방법론" in top[:2], top


def test_meem_query():
    top = _top("고객관계 무형자산 MEEM 평가")
    assert "PPA_무형자산평가" in top[:2], top


def test_beta_query():
    top = _top("블룸버그 베타와 KICPA 베타 차이")
    assert top[0] == "베타_Bloomberg_vs_KICPA", top


# ── 신호별 동작 ──────────────────────────────────────────────────────────────
def test_graph_expansion_pulls_neighbors():
    # PGR 강질의 → 인접(모델링/고정양식 등)이 '인접(...)' 근거로 동반 회수
    hits = S.search("영구성장률 몇 퍼센트", top_k=8)
    assert any(h.why.startswith("인접(") for h in hits), [h.why for h in hits]


def test_best_section_is_specific():
    hits = S.search("손상차손 인식 순서", top_k=3)
    h = next(x for x in hits if x.chapter_id == "손상검사_impairment")
    assert h.best_section and "순서" in h.best_section  # '8. 손상차손 인식 순서'
    assert "영업권" in h.snippet


def test_expand_off_no_neighbor_why():
    hits = S.search("영구성장률 몇 퍼센트", top_k=8, expand=False)
    assert not any(h.why.startswith("인접(") for h in hits)


def test_bigram_sim_korean():
    assert _sim("영구성장률", "영구성장률은 몇 %로 잡나?") > 0.3
    assert _sim("영구성장률", "전환사채 콜옵션") < 0.1


def test_all_chapters_loaded_with_sections():
    assert len(S.chapters) >= 20
    assert all(len(c.sections) >= 1 for c in S.chapters.values())


# ── 임베딩 hybrid ────────────────────────────────────────────────────────────
from rag.embedder import HashingEmbedder, cosine  # noqa: E402

H = BookSearcher(embedder=HashingEmbedder())


def test_hashing_embedder_normalized_and_similar():
    e = HashingEmbedder()
    v1, v2, v3 = e.embed(["영구성장률은 몇 퍼센트", "영구성장률 몇 %로 잡나", "전환사채 콜옵션 평가"])
    import math
    assert abs(math.sqrt(sum(x * x for x in v1)) - 1.0) < 1e-9   # L2 정규화
    assert cosine(v1, v2) > cosine(v1, v3)                        # 유사 > 비유사
    assert cosine(v1, v1) > 0.999


def test_hybrid_keeps_lexical_winners():
    # hybrid 도 기존 정답 유지(품질 회귀 없음)
    assert H.search("영구성장률 몇 퍼센트로 잡아야 하나")[0].chapter_id == "영구성장률_PGR_적합성"
    assert H.search("CGU 영업권 손상검사는 어떻게 하나")[0].chapter_id == "손상검사_impairment"


def test_hybrid_adds_embedding_signal():
    hits = H.search("영구성장률 몇 퍼센트", top_k=3)
    assert any("임베딩" in h.why for h in hits)      # cosine 신호가 근거에 표기


def test_hybrid_partial_word_robustness():
    # 부분어·붙여쓰기 변형(해싱 n-gram 강점) — lexical 키워드 미스에도 회수
    hits = H.search("전환사채콜옵션 강제전환", top_k=3)
    assert any(h.chapter_id == "복합금융상품_평가" for h in hits)


def test_gemini_embedder_requires_key():
    import os
    from rag.embedder import GeminiEmbedder
    if os.environ.get("GEMINI_API_KEY"):
        print("  (키 있음 — skip)"); return
    try:
        GeminiEmbedder().embed(["x"])
        assert False
    except RuntimeError as e:
        assert "GEMINI_API_KEY" in str(e)


def test_default_embedder_fallback():
    import os
    from rag.embedder import default_embedder
    e = default_embedder()
    expected = "gemini-emb-001" if os.environ.get("GEMINI_API_KEY") else "hashing-512"
    assert e.name == expected


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
