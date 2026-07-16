"""임베딩 백엔드 — pluggable(OCR TextExtractor 와 동일 패턴).

3단 사다리:
  ① HashingEmbedder(기본, stdlib): char n-gram → 해싱트릭 → 정규화 dense 벡터.
     '연속화된 lexical' — 부분어·오타에 강하나 진짜 시맨틱은 아님. 의존성 0, 즉시 작동.
  ② GeminiEmbedder: GEMINI_API_KEY 있으면 REST(urllib)로 시맨틱 임베딩 + 파일캐시.
  ③ (향후) sentence-transformers 등 — 프로토콜만 맞추면 교체 코드 변경 0.

벡터는 list[float](L2 정규화) → cosine = dot.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


class EmbeddingBackend(Protocol):
    name: str
    semantic: bool      # True=진짜 의미 임베딩(z-정규화 융합 허용) / False=lexical 연속화
    def embed(self, texts: list[str]) -> list[list[float]]:
        """텍스트들 → L2 정규화 벡터들."""
        ...


def cosine(a: list[float], b: list[float]) -> float:
    """정규화 벡터 가정 → dot. 길이 불일치·영벡터는 0."""
    if len(a) != len(b) or not a:
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def _l2(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n > 0 else v


# ── ① 해싱 임베더 (기본, stdlib) ─────────────────────────────────────────────
@dataclass
class HashingEmbedder:
    """char n-gram(2·3) 해싱트릭 벡터. 한국어 친화(공백·기호 제거 후 문자 단위)."""
    dim: int = 512
    name: str = "hashing-512"
    semantic: bool = False      # 해싱 cosine 은 노이즈성 — z-증폭 금지

    def _grams(self, text: str):
        t = re.sub(r"[^0-9A-Za-z가-힣]", "", text.lower())
        for n in (2, 3):
            for i in range(max(len(t) - n + 1, 0)):
                yield t[i:i + n]

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            v = [0.0] * self.dim
            for g in self._grams(text):
                h = int(hashlib.md5(g.encode("utf-8")).hexdigest()[:8], 16)
                idx = h % self.dim
                sign = 1.0 if (h >> 31) & 1 == 0 else -1.0   # 부호 해싱(충돌 상쇄)
                v[idx] += sign
            out.append(_l2(v))
        return out


# ── ② Gemini 임베더 (API 키 있으면) ─────────────────────────────────────────
@dataclass
class GeminiEmbedder:
    """Google embedding REST. GEMINI_API_KEY 필요. 파일캐시로 재호출 절약.

    2026-07 실측: text-embedding-004 는 v1beta 에서 퇴역(404) — gemini-embedding-001 이
    현행(기본 3072dim, output_dimensionality 로 절단 가능·절단 시 재정규화 필요).
    """
    model: str = "gemini-embedding-001"
    api_key: str | None = None
    cache_path: Path | None = None
    output_dim: int = 768               # 캐시·연산 절약(3072→768, MRL 절단)
    name: str = "gemini-emb-001"
    semantic: bool = True
    _cache: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.api_key = self.api_key or os.environ.get("GEMINI_API_KEY")
        if self.cache_path and Path(self.cache_path).exists():
            try:
                self._cache = json.loads(Path(self.cache_path).read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._cache = {}

    def _key(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]

    _BATCH = 100          # batchEmbedContents 요청당 최대 콘텐츠 수
    _RETRIES = 4          # 429/503 지수 백오프 횟수

    def _post_batch(self, texts: list[str]) -> list[list[float]]:
        """batchEmbedContents 1회 호출(+429/503 백오프). 낱개 embedContent 는 북 인덱싱
        (섹션 수십 개)에서 무료티어 RPM 을 즉시 소진(실측 429) — 배치가 필수."""
        import time
        import urllib.error
        import urllib.request
        reqs = [{"model": f"models/{self.model}",
                 "content": {"parts": [{"text": t[:8000]}]},
                 "outputDimensionality": self.output_dim} for t in texts]
        body = json.dumps({"requests": reqs}).encode()
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:batchEmbedContents",
            data=body,
            headers={"Content-Type": "application/json",
                     "x-goog-api-key": self.api_key})   # 키는 헤더로(URL 로그 유출 방지)
        for attempt in range(self._RETRIES + 1):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
                    embs = json.loads(r.read())["embeddings"]
                return [_l2(e["values"]) for e in embs]  # MRL 절단 후 재정규화 필수
            except urllib.error.HTTPError as e:
                if e.code in (429, 503) and attempt < self._RETRIES:
                    time.sleep(5.0 * (2 ** attempt))   # 5+10+20+40s > RPM 60초 창
                    continue
                raise

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY 없음 — HashingEmbedder(기본)를 쓰거나 키 설정.")
        out: list[list[float] | None] = [None] * len(texts)
        misses: list[int] = []
        for i, text in enumerate(texts):
            cached = self._cache.get(self._key(text))
            if cached is not None:
                out[i] = cached
            else:
                misses.append(i)
        for start in range(0, len(misses), self._BATCH):
            idxs = misses[start:start + self._BATCH]
            vecs = self._post_batch([texts[i] for i in idxs])
            for i, vec in zip(idxs, vecs):
                self._cache[self._key(texts[i])] = vec
                out[i] = vec
        if misses and self.cache_path:
            Path(self.cache_path).write_text(json.dumps(self._cache), encoding="utf-8")
        return out  # type: ignore[return-value]


def default_embedder(cache_dir: Path | None = None) -> EmbeddingBackend:
    """GEMINI_API_KEY 있으면 Gemini(+캐시), 없으면 Hashing(즉시 작동)."""
    if os.environ.get("GEMINI_API_KEY"):
        cache = (cache_dir / "emb_cache.json") if cache_dir else None
        return GeminiEmbedder(cache_path=cache)
    return HashingEmbedder()
