"""ingest — DART·주석·수동 데이터 인제스트 + 4종 검증 게이트.

모든 인제스트 값은 validators 의 게이트를 통과해야 calc_core/DB 에 들어간다.
"""
from .validators import (
    CellKind, Finding, Severity, ValidationReport,
    classify_cell, parse_number, reconcile_sum, tie_out,
)

__all__ = [
    "CellKind", "Finding", "Severity", "ValidationReport",
    "classify_cell", "parse_number", "reconcile_sum", "tie_out",
]
