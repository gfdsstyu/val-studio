"""리포트 산출물 계층 — 텍스트 결과물의 결정론 게이트.

숫자에는 게이트가 여럿인데(ingest.validators 4종 tie-out, calc_core.checks 가정
타당성) **텍스트 산출물에는 검증이 없었다**. 평가의견서·감사조서의 서사는 회계
실무에서 숫자만큼 규범이 강하므로(근거 없는 단정은 감사 위험) 같은 층위로 승격한다.
"""
from .language_guard import (
    SLOT_LABELS,
    check_finding_note,
    check_language,
    lint_report,
)

__all__ = ["SLOT_LABELS", "check_finding_note", "check_language", "lint_report"]
