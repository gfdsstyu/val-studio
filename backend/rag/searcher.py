"""BookSearcher — 밸류에이션 북 lexical 검색기(온톨로지 4층 신호, stdlib).

점수 합성:
  ① canonical_questions 유사도(한국어 bigram Jaccard) — 사전예측 질문 직매칭(최강 신호)
  ② keywords 적중(부분포함) — 엔티티 필터
  ③ topic/title 유사도
  ④ 그래프 1-hop 확장([[링크]] edges + 위계 parent/children) — 감쇠 가중

청킹: 챕터를 `## 섹션` 단위로 분할해 질의와 가장 맞는 섹션을 반환(챕터 통째 아님).
임베딩 도입 시 이 lexical 점수는 hybrid 재랭킹 신호로 재사용.

CLI: python backend/rag/searcher.py "영구성장률 몇 퍼센트?"
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_REF = Path(__file__).resolve().parents[2] / "docs" / "reference"
_ONT = _REF / "ontology"


def _bigrams(s: str) -> set[str]:
    """한국어 친화 문자 bigram(공백·기호 제거). 짧은 텍스트 유사도용."""
    t = re.sub(r"[^0-9A-Za-z가-힣]", "", s.lower())
    return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) > 1 else {t} if t else set()


def _sim(a: str, b: str) -> float:
    """bigram Jaccard 유사도 0~1."""
    A, B = _bigrams(a), _bigrams(b)
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


@dataclass
class Section:
    heading: str
    text: str


@dataclass
class Chapter:
    id: str
    path: str
    title: str
    topic: str
    layer: str
    parent: str | None
    keywords: list[str]
    canonical_questions: list[str]
    links: list[str]
    sections: list[Section] = field(default_factory=list)


@dataclass
class SearchHit:
    chapter_id: str
    path: str
    score: float
    why: str                      # 어떤 신호로 잡혔나(감사·디버깅)
    best_section: str | None      # 가장 맞는 섹션 헤딩
    snippet: str                  # 그 섹션 앞부분


def _split_sections(body: str) -> list[Section]:
    """`## ` 헤딩 기준 분할(자기완결 청크). 헤딩 전 서두는 '(서두)'."""
    parts = re.split(r"^##\s+", body, flags=re.M)
    out: list[Section] = []
    if parts and parts[0].strip():
        out.append(Section("(서두)", parts[0].strip()))
    for p in parts[1:]:
        lines = p.split("\n", 1)
        out.append(Section(lines[0].strip(), (lines[1] if len(lines) > 1 else "").strip()))
    return out


class BookSearcher:
    """rag_index.json + graph.json + 챕터 본문을 로드해 검색.

    embedder 주면 hybrid: 섹션 임베딩 인덱스(lazy)를 만들고 lexical 점수에
    cosine 을 합성한다. 기본 None = 순수 lexical(하위호환).
    """

    def __init__(self, ref_dir: Path | str = _REF, *, embedder=None) -> None:
        self.embedder = embedder
        self._sec_index: list[tuple[str, int, list[float]]] | None = None  # (chapter, sec_i, vec)
        self.ref = Path(ref_dir)
        ont = self.ref / "ontology"
        idx = json.loads((ont / "rag_index.json").read_text(encoding="utf-8"))
        graph = json.loads((ont / "graph.json").read_text(encoding="utf-8"))
        self.chapters: dict[str, Chapter] = {}
        for r in idx["chapters"]:
            body = ""
            p = self.ref / Path(r["path"]).name
            if p.exists():
                txt = p.read_text(encoding="utf-8")
                end = txt.find("\n---\n", 4)
                body = txt[end + 5:] if txt.startswith("---\n") and end != -1 else txt
            self.chapters[r["id"]] = Chapter(
                id=r["id"], path=r["path"], title=r["title"], topic=r.get("topic", ""),
                layer=r.get("layer", ""), parent=r.get("parent"),
                keywords=r.get("keywords", []),
                canonical_questions=r.get("canonical_questions", []),
                links=r.get("links", []),
                sections=_split_sections(body),
            )
        # 인접(그래프 + 위계) 맵
        self.neighbors: dict[str, set[str]] = {cid: set() for cid in self.chapters}
        for e in graph.get("edges", []):
            if e["from"] in self.neighbors and e["to"] in self.chapters:
                self.neighbors[e["from"]].add(e["to"])
                self.neighbors[e["to"]].add(e["from"])
        for cid, ch in self.chapters.items():
            if ch.parent and ch.parent in self.chapters:
                self.neighbors[cid].add(ch.parent)
                self.neighbors[ch.parent].add(cid)

    # ── 챕터 점수(직접 신호) ────────────────────────────────────────────────
    def _direct_score(self, query: str, ch: Chapter) -> tuple[float, str]:
        q = query.lower()
        why = []
        # ① canonical question(최강)
        cq = max((_sim(query, c) for c in ch.canonical_questions), default=0.0)
        if cq > 0.25:
            why.append(f"질문매칭 {cq:.2f}")
        # ② keywords 적중(질의에 키워드 포함 or 키워드에 질의어 포함)
        terms = [w for w in re.split(r"\s+", q) if len(w) >= 2]
        kw_hits = sum(
            1 for k in ch.keywords
            if k.lower() in q or any(t in k.lower() for t in terms)
        )
        kw = min(kw_hits / 3.0, 1.0)
        if kw_hits:
            why.append(f"키워드 {kw_hits}개")
        # ③ topic/title
        tp = max(_sim(query, ch.topic), _sim(query, ch.title))
        score = 1.0 * cq + 0.6 * kw + 0.4 * tp
        return score, ", ".join(why) or "본문유사"

    # ── hybrid: 섹션 임베딩 인덱스(lazy) + cosine 합성 ──────────────────────
    def _ensure_sec_index(self) -> None:
        if self.embedder is None or self._sec_index is not None:
            return
        entries: list[tuple[str, int, str]] = []
        for cid, ch in self.chapters.items():
            for i, sec in enumerate(ch.sections):
                entries.append((cid, i, f"{sec.heading}\n{sec.text[:800]}"))
        vecs = self.embedder.embed([e[2] for e in entries])
        self._sec_index = [(cid, i, v) for (cid, i, _), v in zip(entries, vecs)]

    def _embed_scores(self, query: str) -> dict[tuple[str, int], float]:
        """(chapter, sec_i) → cosine. embedder 없으면 빈 dict."""
        if self.embedder is None:
            return {}
        from .embedder import cosine
        self._ensure_sec_index()
        qv = self.embedder.embed([query])[0]
        return {(cid, i): cosine(qv, v) for cid, i, v in self._sec_index}

    def _best_section(self, query: str, ch: Chapter,
                      emb: dict[tuple[str, int], float] | None = None
                      ) -> tuple[str | None, str]:
        best, best_s = None, 0.0
        for i, sec in enumerate(ch.sections):
            s = _sim(query, sec.heading) * 1.5 + _sim(query, sec.text[:600])
            if emb:
                s += 0.8 * emb.get((ch.id, i), 0.0)      # hybrid: cosine 합성
            if s > best_s:
                best, best_s = sec, s
        if best is None:
            return None, ""
        snippet = re.sub(r"\s+", " ", best.text)[:220]
        return best.heading, snippet

    def search(self, query: str, *, top_k: int = 5, expand: bool = True) -> list[SearchHit]:
        """질의 → 상위 top_k 히트(그래프 확장 + embedder 있으면 hybrid)."""
        emb = self._embed_scores(query)                       # hybrid cosine(섹션별)
        # 챕터별 best cosine → z-정규화. 시맨틱 임베딩의 cosine 은 좁게 뭉쳐 분포(실측
        # 0.45~0.72)해 절대값 가중으로는 변별력이 죽는다 — "다른 챕터 대비 유독 높은가"
        # (z>0)에 보너스를 줘야 어휘 안 겹치는 질의에서 정답이 범용 키워드 노이즈를 이긴다.
        best_cos_by: dict[str, float] = {}
        if emb:
            for cid, ch in self.chapters.items():
                best_cos_by[cid] = max(
                    (emb.get((cid, i), 0.0) for i in range(len(ch.sections))), default=0.0)
            vals = list(best_cos_by.values())
            mean = sum(vals) / len(vals)
            var = sum((v - mean) ** 2 for v in vals) / len(vals)
            std = var ** 0.5 or 1.0
        direct: dict[str, tuple[float, str]] = {}
        for cid, ch in self.chapters.items():
            s, w = self._direct_score(query, ch)
            if emb:
                best_cos = best_cos_by[cid]
                if best_cos > 0.15:
                    if getattr(self.embedder, "semantic", False):
                        z = (best_cos - mean) / std
                        s += 0.25 * best_cos + 0.35 * max(z, 0.0)
                    else:                       # 해싱 등 lexical 연속화 — 절대값만
                        s += 0.5 * best_cos
                    w = (w + ", " if w != "본문유사" else "") + f"임베딩 {best_cos:.2f}"
            direct[cid] = (s, w)

        scores = {cid: s for cid, (s, _) in direct.items()}
        why = {cid: w for cid, (_, w) in direct.items()}
        if expand:
            # 1-hop: 이웃의 직접점수 40% 전파(관련 지식 동반 회수)
            for cid, (s, _) in direct.items():
                if s <= 0.1:
                    continue
                for nb in self.neighbors.get(cid, ()):  # noqa: B007
                    bonus = s * 0.4
                    if bonus > scores.get(nb, 0):
                        # 이웃이 자체점수보다 전파점수가 크면 근거 표기
                        if bonus > direct[nb][0]:
                            why[nb] = f"인접({cid})"
                        scores[nb] = max(scores[nb], bonus)

        ranked = sorted(scores.items(), key=lambda x: -x[1])[:top_k]
        hits: list[SearchHit] = []
        for cid, s in ranked:
            if s <= 0.05:
                continue
            ch = self.chapters[cid]
            heading, snippet = self._best_section(query, ch, emb or None)
            hits.append(SearchHit(chapter_id=cid, path=ch.path, score=round(s, 3),
                                  why=why[cid], best_section=heading, snippet=snippet))
        return hits


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    if len(sys.argv) < 2:
        raise SystemExit('사용: python searcher.py "질의"')
    from .embedder import default_embedder
    searcher = BookSearcher(embedder=default_embedder(cache_dir=_ONT))
    hits = searcher.search(" ".join(sys.argv[1:]))
    print(json.dumps([h.__dict__ for h in hits], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
