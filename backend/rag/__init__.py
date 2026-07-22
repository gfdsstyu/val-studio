"""rag — 밸류에이션 북 검색기(온톨로지 기반 lexical, stdlib).

임베딩 없이 4층 신호(canonical_questions·keywords·그래프확장·섹션청킹)로 검색.
임베딩 도입 시 hybrid 재랭킹 신호로 재사용.
"""
from .embedder import GeminiEmbedder, HashingEmbedder, cosine, default_embedder
from .searcher import BookSearcher, SearchHit

__all__ = [
    "BookSearcher", "SearchHit",
    "HashingEmbedder", "GeminiEmbedder", "cosine", "default_embedder",
]
