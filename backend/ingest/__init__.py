"""ingest — DART·주석·수동 데이터 인제스트 + 4종 검증 게이트 + 출처추적.

모든 인제스트 값은 validators 의 게이트를 통과해야 calc_core/DB 에 들어가고,
Provenance 로 출처(문서·위치·원문 span)를 추적한다.
"""
from .provenance import (
    ExtractMethod, Locator, Provenance, ProvenancedValue, SourceKind,
    as_dict, merge_confidence,
)
from .validators import (
    CellKind, Finding, Severity, ValidationReport,
    classify_cell, parse_number, reconcile_sum, tie_out,
)

__all__ = [
    # validators
    "CellKind", "Finding", "Severity", "ValidationReport",
    "classify_cell", "parse_number", "reconcile_sum", "tie_out",
    # provenance
    "ExtractMethod", "Locator", "Provenance", "ProvenancedValue", "SourceKind",
    "as_dict", "merge_confidence",
]
