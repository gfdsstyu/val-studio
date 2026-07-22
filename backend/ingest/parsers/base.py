"""BaseParser — 모든 인제스트 파서의 공통 백본.

파이프라인(문서종류 불문 동일):
    raw 조각(text/cell) ─▶ parse_number(정규화 + ① 숫자형 검증)
                        ─▶ ProvenancedValue(값 + 출처 span)
                        ─▶ ParseResult(값 리스트 + ValidationReport)

구체 파서(footnote/xlsx/dart/ocr)는 `extract()` 만 구현하면 된다. extract 안에서
`self.emit(...)` 로 각 값을 방출하면 정규화·검증·출처부착이 자동으로 일어난다.

철학(감린이 clean-truth): 원문 불변 + 검증은 라운드트립 정합. OCR/regex 는 confidence<1
로 방출해 하위(감사인 트랙)에서 추가검증을 트리거한다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal

from ..provenance import (
    ExtractMethod, Locator, Provenance, ProvenancedValue, SourceKind,
)
from ..validators import ValidationReport, classify_cell, parse_number


@dataclass
class ParseResult:
    """파싱 산출: 값 리스트 + 검증 리포트. report.ok=False 면 인제스트 게이트가 막는다."""
    values: list[ProvenancedValue] = field(default_factory=list)
    report: ValidationReport = field(default_factory=ValidationReport)

    @property
    def ok(self) -> bool:
        return self.report.ok

    def by_name(self, field_name: str) -> ProvenancedValue | None:
        for v in self.values:
            if v.field_name == field_name:
                return v
        return None

    def value_of(self, field_name: str) -> Decimal | None:
        pv = self.by_name(field_name)
        return pv.value if pv else None


class BaseParser(ABC):
    """인제스트 파서 추상 백본. 서브클래스는 source_kind/method 지정 + extract() 구현."""

    #: 서브클래스에서 지정
    source_kind: SourceKind
    default_method: ExtractMethod = ExtractMethod.REGEX

    def __init__(self, source_id: str, *, default_confidence: float = 1.0) -> None:
        self.source_id = source_id
        self.default_confidence = default_confidence
        self.result = ParseResult()

    # ── 서브클래스 구현부 ────────────────────────────────────────────────────
    @abstractmethod
    def extract(self, raw: object) -> ParseResult:
        """raw(문서·텍스트·워크북 등)에서 값을 뽑아 self.emit(...) 으로 방출.

        반환은 self.result. 구현체는 extract 시작 시 self.result = ParseResult() 로
        초기화하지 않아도 되도록 여기서 이미 초기화되어 있다(생성자에서).
        """
        raise NotImplementedError

    # ── 공통 방출 파이프라인 ─────────────────────────────────────────────────
    def emit(
        self,
        field_name: str,
        raw_text: object,
        *,
        locator: Locator | None = None,
        unit: str | None = None,
        method: ExtractMethod | None = None,
        confidence: float | None = None,
        char_start: int | None = None,
        char_end: int | None = None,
        note: str | None = None,
    ) -> ProvenancedValue:
        """raw 조각 하나 → 정규화·검증·출처부착 → self.result 에 추가하고 반환.

        - 숫자형 검증(parse_number): 실패 시 report 에 fail 기록, value=None.
        - 공백/대시/결측: value=None(비숫자 fail 아님) — classify_cell 로 구분.
        - 출처: source_kind/method/locator/char span/confidence 부착.
        """
        prov = Provenance(
            source_kind=self.source_kind,
            method=method or self.default_method,
            source_id=self.source_id,
            locator=locator or Locator(),
            char_start=char_start,
            char_end=char_end,
            raw_text=None if raw_text is None else str(raw_text),
            confidence=self.default_confidence if confidence is None else confidence,
            note=note,
        )
        val = parse_number(
            raw_text, unit=unit, report=self.result.report, field_name=field_name
        )
        pv = ProvenancedValue(value=val, provenance=prov, field_name=field_name)
        self.result.values.append(pv)
        return pv

    def emit_blank_aware(self, field_name: str, raw_text: object, **kw) -> ProvenancedValue:
        """공백/대시/결측을 명시적으로 기록하고 싶을 때(주석의 빈칸 오제외 방지).

        진짜 공백이면 note 에 셀종류를 남겨 '못 읽은 게 아니라 원래 비었음'을 추적.
        """
        kind = classify_cell(raw_text)
        if kind.value in ("blank", "dash", "missing"):
            tag = f"cell_kind={kind.value}"
            existing = kw.get("note")
            kw["note"] = f"{existing}; {tag}" if existing else tag
        return self.emit(field_name, raw_text, **kw)
