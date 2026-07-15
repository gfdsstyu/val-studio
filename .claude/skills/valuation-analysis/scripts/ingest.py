#!/usr/bin/env python
"""문서 인제스트 (Skill 도구) — 파일 → 방식·유형 라우팅 → 구조화 + 프로파일.

사용: python ingest.py <파일경로>
지원: .xbrl(사업보고서)·.pdf(의견서/리서치)·.xlsx(모델). DART PDF 한글은 CID→OCR 필요.
출력: 방식·유형·추출방법 + 프로파일 요약(의견서=SOTP/영구성장, 사업보고서=핵심계정) JSON.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path


def _find_backend() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "backend" / "ingest").is_dir():
            return parent / "backend"
    raise SystemExit("backend/ 를 찾을 수 없음.")


sys.path.insert(0, str(_find_backend()))

from ingest.router import ingest  # noqa: E402


def _profile_summary(profile) -> object:
    if profile is None:
        return None
    if is_dataclass(profile):
        d = asdict(profile)
        # 값 dict 등 큰 필드는 요약
        return {k: v for k, v in d.items() if not isinstance(v, (list, dict)) or len(str(v)) < 400}
    return str(profile)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    if len(sys.argv) < 2:
        raise SystemExit("사용: python ingest.py <파일경로>")
    path = sys.argv[1]
    r = ingest(path)
    out = {
        "method": r.decision.method.value,
        "doc_type": r.decision.doc_type.value,
        "type_confidence": r.decision.type_confidence,
        "extract_method": r.extract_method,
        "structured_values": len(r.structured.values),
        "gate_ok": r.structured.ok,
        "profile": _profile_summary(r.profile),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
