#!/usr/bin/env python
"""밸류에이션 북 → 온톨로지 + RAG 인덱스 컴파일러.

SSOT = docs/reference/*.md (frontmatter + [[wikilink]]). 이 스크립트가 컴파일:
  - rag_index.json : 청크 검색 레코드(topic·keywords·canonical_questions·track·links)
  - graph.json     : 개념 그래프(nodes=챕터, edges=[[링크]], concepts=keyword→챕터)
  - CONCEPTS.md    : 사람이 읽는 개념·트랙·링크 색인

문서만 편집하면 온톨로지가 자동 동기화(컴파일). 수작업 그래프 관리 안 함.
의존 없음(stdlib). 실행: python docs/reference/ontology/build.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REF = Path(__file__).resolve().parent.parent          # docs/reference
OUT = Path(__file__).resolve().parent                 # docs/reference/ontology

# 키워드 → 트랙 매핑(대략). 스코프 로드맵의 4트랙 + 방법론/파서/검증.
_TRACK_HINTS = [
    ("복합금융상품", ("전환사채", "RCPS", "신주인수권", "이항모형", "TF모형", "OPM", "복합금융")),
    ("손상·FV", ("손상", "impairment", "CGU", "VIU", "PPA", "MEEM", "RFRM", "공정가치")),
    ("실사·정상화", ("FDD", "재무실사", "QOE", "정상화", "NWC")),
    ("파서·인제스트", ("파서", "XBRL", "PDF", "OCR", "DART", "계정분류", "provenance")),
    ("검증·감사인", ("검증", "감사인", "audit", "골든", "WARA")),
    ("거래평가·DCF", ("WACC", "베타", "영구성장", "DCF", "매출추정", "peer", "합병", "리포트")),
]


def _track(keywords: list[str], topic: str) -> str:
    blob = " ".join(keywords) + " " + topic
    for track, hints in _TRACK_HINTS:
        if any(h in blob for h in hints):
            return track
    return "기타"


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """--- ... --- 블록 파싱(수작업, yaml 불요). (meta, body)."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    block, body = text[4:end], text[end + 5:]
    meta: dict = {}
    cur_list_key = None
    for line in block.splitlines():
        if re.match(r"^\s+-\s", line) and cur_list_key:                 # 리스트 항목
            meta[cur_list_key].append(line.strip()[1:].strip().strip('"'))
            continue
        m = re.match(r"^(\w+):\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val == "":                                                   # 리스트 시작
            meta[key] = []
            cur_list_key = key
        elif val.startswith("[") and val.endswith("]"):                 # 인라인 배열
            meta[key] = [x.strip() for x in val[1:-1].split(",") if x.strip()]
            cur_list_key = None
        else:
            meta[key] = val
            cur_list_key = None
    return meta, body


def main() -> None:
    records = []
    concepts: dict[str, list[str]] = {}
    edges: list[dict] = []
    stems = {p.stem for p in REF.glob("*.md") if p.name != "README.md"}

    for path in sorted(REF.glob("*.md")):
        if path.name == "README.md":
            continue
        text = path.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(text)
        title = (re.search(r"^#\s+(.+)$", body, re.M) or [None, path.stem])[1]
        keywords = meta.get("keywords", [])
        topic = meta.get("topic", "")
        track = _track(keywords, topic)
        links = sorted(set(re.findall(r"\[\[([^\]]+)\]\]", body)))
        # 챕터 노드
        records.append({
            "id": path.stem,
            "path": f"docs/reference/{path.name}",
            "title": title,
            "topic": topic,
            "track": track,
            "doc_type": meta.get("doc_type", "knowledge"),
            "keywords": keywords,
            "canonical_questions": meta.get("canonical_questions", []),
            "links": links,
            "has_frontmatter": bool(meta),
        })
        for kw in keywords:
            concepts.setdefault(kw, []).append(path.stem)
        for tgt in links:
            edges.append({"from": path.stem, "to": tgt,
                          "resolved": tgt in stems})

    OUT.mkdir(exist_ok=True)
    (OUT / "rag_index.json").write_text(
        json.dumps({"chapters": records}, ensure_ascii=False, indent=2), encoding="utf-8")

    graph = {
        "nodes": [{"id": r["id"], "title": r["title"], "track": r["track"],
                   "doc_type": r["doc_type"]} for r in records],
        "edges": edges,
        "concepts": {k: sorted(set(v)) for k, v in sorted(concepts.items())},
    }
    (OUT / "graph.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")

    # 사람용 CONCEPTS.md
    lines = ["# 밸류에이션 북 — 개념·트랙 색인 (자동생성, build.py)", ""]
    lines.append(f"챕터 {len(records)} · 개념 {len(concepts)} · 링크 {len(edges)}\n")
    by_track: dict[str, list] = {}
    for r in records:
        by_track.setdefault(r["track"], []).append(r)
    lines.append("## 트랙별 챕터")
    for track in sorted(by_track):
        lines.append(f"\n### {track}")
        for r in by_track[track]:
            lines.append(f"- **{r['title']}** ([{r['id']}]({Path(r['path']).name})) "
                         f"— {r['topic']}")
    # 미해소 링크(문서 부재) 경고
    unresolved = sorted({e["to"] for e in edges if not e["resolved"]})
    if unresolved:
        lines.append("\n## ⚠️ 미해소 링크(대상 문서 없음 — 저술 후보)")
        for u in unresolved:
            lines.append(f"- [[{u}]]")
    lines.append("\n## 다중 챕터 개념(교차 주제)")
    multi = {k: v for k, v in concepts.items() if len(set(v)) > 1}
    for k, v in sorted(multi.items(), key=lambda x: -len(set(x[1]))):
        lines.append(f"- **{k}**: {', '.join(sorted(set(v)))}")
    (OUT / "CONCEPTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"컴파일 완료: {len(records)}챕터 · {len(concepts)}개념 · {len(edges)}링크 "
          f"({sum(1 for e in edges if not e['resolved'])} 미해소)")
    print(f"  → {OUT/'rag_index.json'}\n  → {OUT/'graph.json'}\n  → {OUT/'CONCEPTS.md'}")


if __name__ == "__main__":
    main()
