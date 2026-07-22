"""Provenance — 인제스트된 모든 값의 출처 추적(감사 증거능력의 근본).

감사인 트랙의 핵심 요구: "이 숫자는 어느 문서·어느 위치·원문 어느 span 에서 왔는가"에
답한다. validators(라운드트립 정합)와 짝을 이뤄 "값이 맞고 + 출처를 안다"를 보장한다.

설계(감린이 structured_meta 파이프라인과 동일 철학):
  - 원문 불변: 추출은 원문을 바꾸지 않고 char_start/char_end span 으로 가리킨다.
  - 위치 좌표: 문서종류별 locator(page/cell/row·col/line)로 사람이 찾아갈 수 있게.
  - 방법·신뢰도: 어떤 방법(수식/OCR/정규식/수동)으로 뽑았는지 + 신뢰도.

ProvenancedValue = 값 + Provenance. 인제스트 파이프라인의 최소 원자 단위.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any


class SourceKind(str, Enum):
    """출처 문서 종류."""
    DART = "dart"                 # OpenDART 공시 API
    XLSX = "xlsx"                 # 엑셀 모델(셀 좌표)
    PDF = "pdf"                   # PDF 의견서·보고서(페이지)
    PDF_OCR = "pdf_ocr"           # 스캔 PDF → OCR(외부평가의견서 등)
    FOOTNOTE = "footnote"         # 재무제표 주석
    MANUAL = "manual"             # 수동 입력/복붙


class ExtractMethod(str, Enum):
    """추출 방법(신뢰도 순서와 대략 일치)."""
    FORMULA = "formula"           # 엑셀 라이브 수식값(최고 신뢰)
    STRUCTURED = "structured"     # 구조화 API(DART XBRL 등)
    REGEX = "regex"               # 정규식/규칙 파싱
    OCR = "ocr"                   # 광학문자인식(검증 필수)
    MANUAL = "manual"             # 사람 입력


@dataclass(frozen=True)
class Locator:
    """사람이 원문에서 값을 찾아갈 수 있는 좌표. 문서종류별 해당 필드만 채운다.

    - XLSX: sheet + cell (예: "클래시스DCF", "C44")
    - PDF : page (+ 선택적으로 line/bbox)
    - DART: rcept_no(접수번호) + account_id(계정)
    - FOOTNOTE: note_no(주석 번호) + line
    """
    sheet: str | None = None
    cell: str | None = None
    page: int | None = None
    line: int | None = None
    rcept_no: str | None = None
    account_id: str | None = None
    note_no: str | None = None

    def label(self) -> str:
        """감사 로그용 사람이 읽는 한 줄 좌표."""
        if self.sheet and self.cell:
            return f"{self.sheet}!{self.cell}"
        if self.rcept_no:
            return f"DART {self.rcept_no}" + (f"/{self.account_id}" if self.account_id else "")
        if self.note_no is not None:
            return f"주석{self.note_no}" + (f":L{self.line}" if self.line is not None else "")
        if self.page is not None:
            return f"p.{self.page}" + (f":L{self.line}" if self.line is not None else "")
        return "(no-locator)"


@dataclass(frozen=True)
class Provenance:
    """값 하나의 출처. 원문 span(char_start~char_end)으로 원문을 불변 참조한다."""
    source_kind: SourceKind
    method: ExtractMethod
    source_id: str                        # 파일명/URL/rcept_no 등 문서 식별자
    locator: Locator = field(default_factory=Locator)
    char_start: int | None = None         # 원문 내 span 시작(불변 참조)
    char_end: int | None = None
    raw_text: str | None = None           # 파싱 전 원문 조각(재검증용)
    confidence: float = 1.0               # 0~1, OCR/regex 는 <1
    note: str | None = None

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence 는 0~1 범위: {self.confidence}")
        if (self.char_start is None) != (self.char_end is None):
            raise ValueError("char_start/char_end 는 함께 지정해야 함")
        if self.char_start is not None and self.char_end < self.char_start:
            raise ValueError("char_end < char_start")

    def label(self) -> str:
        """감사 로그 한 줄: '[method@source loc] (conf)'."""
        span = f" @{self.char_start}-{self.char_end}" if self.char_start is not None else ""
        conf = "" if self.confidence >= 1.0 else f" conf={self.confidence:.2f}"
        return f"[{self.method.value}@{self.source_id} {self.locator.label()}{span}]{conf}"


@dataclass(frozen=True)
class ProvenancedValue:
    """값 + 출처. 인제스트 파이프라인의 최소 원자.

    value 는 파싱·검증을 통과한 정규화 값(보통 Decimal, 백만원 기준). 검증 실패로 값이
    없으면 value=None 이되 provenance 는 남아 '무엇을 못 읽었는지' 추적 가능.
    """
    value: Decimal | None
    provenance: Provenance
    field_name: str = "value"

    @property
    def ok(self) -> bool:
        return self.value is not None

    def __str__(self) -> str:
        v = "∅" if self.value is None else f"{self.value}"
        return f"{self.field_name}={v} {self.provenance.label()}"


def merge_confidence(*values: ProvenancedValue) -> float:
    """여러 값에서 파생된 계산의 신뢰도 = 구성값 신뢰도의 최소(약한 고리)."""
    confs = [v.provenance.confidence for v in values]
    return min(confs) if confs else 1.0


def as_dict(pv: ProvenancedValue) -> dict[str, Any]:
    """직렬화(감사 로그·JSON). Decimal 은 문자열로 보존(정밀도 유지)."""
    p = pv.provenance
    return {
        "field": pv.field_name,
        "value": None if pv.value is None else str(pv.value),
        "source_kind": p.source_kind.value,
        "method": p.method.value,
        "source_id": p.source_id,
        "locator": p.locator.label(),
        "char_span": None if p.char_start is None else [p.char_start, p.char_end],
        "confidence": p.confidence,
        "raw_text": p.raw_text,
        "note": p.note,
    }
