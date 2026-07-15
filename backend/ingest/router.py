"""라우터 — 파일 → (불러오기 방식 × 자료유형) 감지 → 적정 파서·프로파일 선택.

파서 매트릭스([[파서_아키텍처_매트릭스]])의 진입점. 두 신호로 좌표를 정한다:
  - 방식(InputMethod): 확장자/매직바이트 — 결정적.
  - 유형(DocType): 파일명 힌트 + 내용 앵커 — 확률적(confidence).

route(path) → RouteDecision(방식·유형·파서 팩토리·프로파일). ingest(path) → 실행까지.
DART API 는 파일이 아니라 프로그램 호출이므로 라우터 밖(dart_client 직접).
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .parsers.base import BaseParser, ParseResult


class InputMethod(str, Enum):
    XBRL = "xbrl"
    XLSX = "xlsx"
    PDF = "pdf"
    UNKNOWN = "unknown"


class DocType(str, Enum):
    BUSINESS_REPORT = "business_report"    # 사업/분기보고서
    OPINION = "opinion"                    # 외부평가의견서
    RESEARCH = "research"                  # 증권사 리서치
    IR = "ir"                              # IR 자료
    DCF_MODEL = "dcf_model"                # DCF 평가모델(엑셀)
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RouteDecision:
    method: InputMethod
    doc_type: DocType
    type_confidence: float
    path: str
    reason: str = ""


# ── 방식 감지 (확장자 + 매직) ─────────────────────────────────────────────────
def detect_method(path: str) -> InputMethod:
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".xbrl":
        return InputMethod.XBRL
    if ext in (".xlsx", ".xlsb", ".xls"):
        return InputMethod.XLSX
    if ext == ".pdf":
        return InputMethod.PDF
    if ext == ".zip":
        # XBRL 패키지 zip(내부 .xbrl) 판별
        try:
            with zipfile.ZipFile(path) as z:
                if any(n.endswith(".xbrl") for n in z.namelist()):
                    return InputMethod.XBRL
        except zipfile.BadZipFile:
            pass
    return InputMethod.UNKNOWN


# ── 유형 감지 (파일명 힌트 + 내용 앵커) ───────────────────────────────────────
_NAME_HINTS: list[tuple[DocType, tuple[str, ...]]] = [
    (DocType.OPINION, ("평가의견서", "외부평가")),
    (DocType.BUSINESS_REPORT, ("사업보고서", "분기보고서", "반기보고서")),
    (DocType.RESEARCH, ("리서치", "research", "증권", "투자의견")),
    (DocType.IR, ("ir", "실적발표", "earnings")),
    (DocType.DCF_MODEL, ("dcf", "valuation", "밸류", "모델")),
]
_CONTENT_ANCHORS: list[tuple[DocType, tuple[str, ...]]] = [
    (DocType.OPINION, ("WACC = Ke", "외부평가기관", "평가의견")),
    (DocType.BUSINESS_REPORT, ("사업의 개요", "재무제표에 관한 사항", "이사의 경영진단")),
    (DocType.RESEARCH, ("목표주가", "투자의견", "BUY", "Overweight")),
]


def detect_doc_type(path: str, *, sample_text: str | None = None) -> tuple[DocType, float, str]:
    """파일명 힌트(강) + 내용 앵커(보강). (유형, confidence, 근거)."""
    name = Path(path).name.lower()
    for dt, keys in _NAME_HINTS:
        for k in keys:
            if k.lower() in name:
                # 내용으로 교차확인되면 confidence↑
                conf = 0.7
                if sample_text:
                    for adt, anchors in _CONTENT_ANCHORS:
                        if adt is dt and any(a.lower() in sample_text.lower() for a in anchors):
                            conf = 0.95
                            break
                return dt, conf, f"파일명 '{k}'"
    # 파일명 실패 → 내용 앵커만
    if sample_text:
        for dt, anchors in _CONTENT_ANCHORS:
            hits = [a for a in anchors if a.lower() in sample_text.lower()]
            if hits:
                return dt, 0.6, f"내용 앵커 {hits[:2]}"
    return DocType.UNKNOWN, 0.0, "감지 실패"


# ── 라우팅 ────────────────────────────────────────────────────────────────────
def _peek_pdf_text(path: str, max_chars: int = 4000) -> str | None:
    try:
        from .parsers.pdf import pdftotext_layout
        pages = pdftotext_layout(path)
        return "\n".join(p.text for p in pages[:3])[:max_chars]
    except Exception:
        return None


def route(path: str) -> RouteDecision:
    """파일 → RouteDecision. PDF·XLSX 는 내용 샘플로 유형 confidence 보강."""
    method = detect_method(path)
    sample = _peek_pdf_text(path) if method is InputMethod.PDF else None
    dt, conf, why = detect_doc_type(path, sample_text=sample)
    # 방식 기반 기본 유형 보정: xlsx 이고 유형 미상이면 DCF 모델로 추정
    if dt is DocType.UNKNOWN and method is InputMethod.XLSX:
        dt, conf, why = DocType.DCF_MODEL, 0.4, "xlsx 기본 추정"
    if dt is DocType.UNKNOWN and method is InputMethod.XBRL:
        dt, conf, why = DocType.BUSINESS_REPORT, 0.8, "XBRL=정형공시"
    return RouteDecision(method, dt, round(conf, 2), path, why)


def build_parser(decision: RouteDecision, source_id: str | None = None,
                 *, extractor=None) -> BaseParser:
    """RouteDecision → 파서 인스턴스(방식별). extractor 주입 시 PDF 는 그걸로 추출."""
    sid = source_id or Path(decision.path).stem
    if decision.method is InputMethod.XBRL:
        from .parsers.xbrl import XbrlParser
        return XbrlParser(sid)
    if decision.method is InputMethod.PDF:
        from .parsers.pdf import PdfParser, pdftotext_layout
        return PdfParser(sid, extractor=extractor or pdftotext_layout)
    if decision.method is InputMethod.XLSX:
        from .parsers.xlsx import XlsxParser
        return XlsxParser(sid)
    raise ValueError(f"라우팅 불가 방식: {decision.method}")


@dataclass
class IngestResult:
    """end-to-end 인제스트 산출: 라우팅 + 구조화 + (유형별) 시맨틱 프로파일."""
    decision: RouteDecision
    structured: ParseResult
    profile: object | None = None        # OpinionExtract 등 유형별 시맨틱 추출
    extract_method: str | None = None    # 'pdftotext' | 'ocr' 등

    @property
    def ok(self) -> bool:
        return self.structured.ok


def _profile_from_text(decision: RouteDecision, text: str, garble_conf: float):
    """텍스트 기반 프로파일(PDF). 미지원 유형 None."""
    if decision.doc_type is DocType.OPINION:
        from .profiles.opinion_template import extract_opinion
        return extract_opinion(text, garble_confidence=garble_conf)
    return None


def _profile_from_parser(decision: RouteDecision, parser: BaseParser):
    """구조화 기반 프로파일(XBRL). 사업보고서 → 핵심 재무계정."""
    if decision.doc_type is DocType.BUSINESS_REPORT and hasattr(parser, "primary_facts"):
        from .profiles.business_report import extract_business_report
        return extract_business_report(parser.primary_facts(), getattr(parser, "labels", {}))
    return None


def ingest(path: str, *, source_id: str | None = None, ocr_backend=None) -> IngestResult:
    """end-to-end: 라우팅 → (PDF는 OCR 폴백) 추출 → 구조화 + 시맨틱 프로파일 자동적용."""
    decision = route(path)
    method_used = None
    profile = None

    if decision.method is InputMethod.PDF:
        from .parsers.ocr import smart_extract
        from .parsers.pdf import confidence_from_garble
        pages, method_used = smart_extract(path, ocr_backend=ocr_backend)
        # 이미 추출한 pages 재사용(재추출 방지)로 PdfParser 구동
        parser = build_parser(decision, source_id, extractor=lambda _p: pages)
        result = parser.extract(path)
        text = "\n".join(p.text for p in pages)
        profile = _profile_from_text(decision, text, confidence_from_garble(text))
    else:
        parser = build_parser(decision, source_id)
        result = parser.extract(path)
        profile = _profile_from_parser(decision, parser)

    return IngestResult(decision=decision, structured=result,
                        profile=profile, extract_method=method_used)
