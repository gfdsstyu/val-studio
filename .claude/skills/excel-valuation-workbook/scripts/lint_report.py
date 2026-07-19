#!/usr/bin/env python
"""W9 서사 표현 가드 — 조서·리포트 텍스트의 결정론 린터.

숫자는 dcf.py·audit 이 검증하는데 **서사는 검증이 없었다**. 회계 실무에서 근거 없는
단정("분식입니다")은 그 자체가 감사 위험이고, variance 규격의 안티패턴(순환설명·
무설명·뭉뚱그리기)도 조서 품질을 직접 깎는다. 전부 WARN — 표현이 나빠도 계산이
무효는 아니므로 차단하지 않고 표면화만 한다(판단은 평가인).

**LLM 산출물 전용이 아니다.** 사람이 쓴 Driver·Action 에도 같은 규범이 적용된다.

사용:
  echo '{"text": "...", "notes": {"gap": {"driver": "...", "action": "..."}}}' \
    | python lint_report.py
  python lint_report.py --text "본 건은 분식입니다."
"""
from __future__ import annotations

import json
import sys

import _bootstrap  # noqa: F401

from report import lint_report  # noqa: E402


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows cp949 방지
    except (AttributeError, ValueError):
        pass
    if "--text" in sys.argv:
        payload = {"text": sys.argv[sys.argv.index("--text") + 1]}
    else:
        payload = json.load(sys.stdin)

    rep = lint_report(payload.get("text") or "",
                      notes=payload.get("notes") or {},
                      where=payload.get("where") or "리포트")
    warns = [f for f in rep.findings if f.severity.value != "pass"]
    json.dump({
        "ok": not warns,
        "count": len(warns),
        "findings": [{"rule": f.rule, "severity": f.severity.value,
                      "message": f.message, "detail": f.detail} for f in warns],
    }, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
