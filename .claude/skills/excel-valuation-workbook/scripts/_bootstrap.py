"""vendor 경로 부트스트랩 — 자기완결 스킬용.

각 래퍼가 `import _bootstrap` 첫 줄로 호출하면 vendor/(calc_core·ingest·excel·rag)를
sys.path 최상단에 올린다. 기존 valuation-analysis 의 `_find_backend()`(레포 의존)를 대체.
"""
from __future__ import annotations

import sys
from pathlib import Path

VENDOR = Path(__file__).resolve().parent / "vendor"
REFERENCE = VENDOR / "reference"

if VENDOR.exists() and str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))
