"""parsers — 문서종류별 인제스트 파서(공통 백본 base.py + 구체 파서들).

모든 파서는 BaseParser 를 상속해 동일 파이프라인을 따른다:
  raw 추출 → parse_number(정규화·숫자형 검증) → ProvenancedValue(출처 부착) → ParseResult.

구체 파서: footnote_extractor(주석), (예정) xlsx_parser, dart_parser, pdf_ocr_parser.
"""
from .base import BaseParser, ParseResult

__all__ = ["BaseParser", "ParseResult"]
