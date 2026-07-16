#!/usr/bin/env python
"""밸류에이션 북 검색 (Skill 도구) — 질의 → 정확한 챕터·섹션.

references/index.md 를 통째로 읽는 대신, 이 검색기로 필요한 섹션만 정확히 찾는다.
사용: python book_search.py "영구성장률 몇 퍼센트?"  (인코딩 문제시 파일로: -f query.txt)
출력: 챕터·섹션·근거(질문매칭/키워드/인접)·스니펫 JSON. path 의 해당 섹션을 Read로 열어 답한다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _find_backend() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "backend" / "rag").is_dir():
            return parent / "backend"
    raise SystemExit("backend/ 못 찾음.")


sys.path.insert(0, str(_find_backend()))

from rag.searcher import BookSearcher  # noqa: E402


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = sys.argv[1:]
    if args and args[0] == "-f":                       # 한글 argv 인코딩 우회
        query = Path(args[1]).read_text(encoding="utf-8").strip()
    elif args:
        query = " ".join(args)
    else:
        query = sys.stdin.read().strip()
    if not query:
        raise SystemExit('사용: python book_search.py "질의"')
    hits = BookSearcher().search(query, top_k=5)
    print(json.dumps([h.__dict__ for h in hits], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
