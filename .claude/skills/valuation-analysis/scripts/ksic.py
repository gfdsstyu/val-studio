#!/usr/bin/env python
"""KSIC 조회 (Skill 도구, peer Step1a) — 로컬 2,000코드 표에서 "쓱" 찾기.

사용: python ksic.py "의료용 기기"   ← 키워드 검색(공백 = AND)
      python ksic.py 2719           ← 코드 조회 + 상위/하위 계층
데이터: backend/data/ksic10.json (KSIC 10차 = DART induty_code 체계, 오프라인).
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

from ingest.ksic import main  # noqa: E402

if __name__ == "__main__":
    main()
