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
    """Google text-embedding REST. GEMINI_API_KEY 필요. 파일캐시로 재호출 절약."""
    model: str = "text-embedding-004"
    api_key: str | None = None
    cache_path: Path | None = None
    name: str = "gemini-te004"
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

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY 없음 — HashingEmbedder(기본)를 쓰거나 키 설정.")
        import urllib.request
        out: list[list[float]] = []
        dirty = False
        for text in texts:
            k = self._key(text)
            if k in self._cache:
                out.append(self._cache[k]); continue
            body = json.dumps({"model": f"models/{self.model}",
                               "content": {"parts": [{"text": text[:8000]}]}}).encode()
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:embedContent?key={self.api_key}",
                data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
                vec = json.loads(r.read())["embedding"]["values"]
            vec = _l2(vec)
            self._cache[k] = vec
            out.append(vec)
            dirty = True
        if dirty and self.cache_path:
            Path(self.cache_path).write_text(
                json.dumps(self._cache), encoding="utf-8")
        return out


def default_embedder(cache_dir: Path | None = None) -> EmbeddingBackend:
    """GEMINI_API_KEY 있으면 Gemini(+캐시), 없으면 Hashing(즉시 작동)."""
    if os.environ.get("GEMINI_API_KEY"):
        cache = (cache_dir / "emb_cache.json") if cache_dir else None
        return GeminiEmbedder(cache_path=cache)
    return HashingEmbedder()
