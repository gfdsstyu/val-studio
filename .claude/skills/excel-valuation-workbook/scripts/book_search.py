#!/usr/bin/env python
"""밸류에이션 북 검색 (지식 폴백) — 질의 → 정확한 챕터·섹션.

단계별 사전 바인딩(SKILL.md 표)에 안 잡히는 비정형 질문일 때만 폴백. vendor/rag 의
BookSearcher 를 embedder 없이(순수 lexical) 호출 — 네트워크·임베딩 불요.

사용: python book_search.py "영구성장률 몇 퍼센트?"  (한글 argv 깨지면 -f query.txt)
출력: 챕터·섹션·근거·스니펫 JSON. path 의 해당 md(vendor/reference/)를 Read로 열어 답한다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401  (vendor 경로 + REFERENCE)

from rag.searcher import BookSearcher  # noqa: E402


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = sys.argv[1:]
    if args and args[0] == "-f":
        query = Path(args[1]).read_text(encoding="utf-8").strip()
    elif args:
        query = " ".join(args)
    else:
        query = sys.stdin.read().strip()
    if not query:
        raise SystemExit('사용: python book_search.py "질의"')
    # ref_dir = vendor/reference (자기완결 — 레포 docs/reference 미의존)
    hits = BookSearcher(ref_dir=_bootstrap.REFERENCE).search(query, top_k=5)
    print(json.dumps([h.__dict__ for h in hits], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
