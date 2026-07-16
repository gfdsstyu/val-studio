#!/usr/bin/env python
"""Company Brief 프리필 (Skill 도구, 0단계) — XBRL → 10섹션 Brief 골격 markdown.

사용: python brief.py <원문XBRL.xbrl> [출력.md] [--회사명 힌트]
②회사개요(주식수·유통비율) ④사업부문·지역 매출 ⑩Financials 를 기계로 채우고,
나머지 섹션은 `_(LLM: ...)_` 슬롯 — 0단계 LLM 이 이 파일을 이어서 완성한다.
"""
from __future__ import annotations

import sys
from pathlib import Path


def _find_backend() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "backend" / "ingest").is_dir():
            return parent / "backend"
    raise SystemExit("backend/ 를 찾을 수 없음.")


sys.path.insert(0, str(_find_backend()))

from ingest.parsers.xbrl import XbrlParser  # noqa: E402
from ingest.profiles.research_brief import (  # noqa: E402
    extract_research_brief, render_brief_md,
)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    hint = next((a.split("=", 1)[1] for a in sys.argv[1:]
                 if a.startswith("--회사명=") or a.startswith("--name=")), "")
    if not args:
        raise SystemExit("사용: python brief.py <원문XBRL.xbrl> [출력.md] [--name=회사명]")
    xbrl = Path(args[0])
    parser = XbrlParser(xbrl.name)
    parser.extract(xbrl)
    md = render_brief_md(extract_research_brief(parser), company_hint=hint)
    if len(args) >= 2:
        Path(args[1]).write_text(md, encoding="utf-8")
        print(f"저장: {args[1]} ({len(md)}자)")
    else:
        print(md)


if __name__ == "__main__":
    main()
