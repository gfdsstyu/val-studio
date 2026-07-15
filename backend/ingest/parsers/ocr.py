"""OCR — DART PDF 한글(CID) · 스캔 의견서의 텍스트 잠금해제.

DART PDF 는 한글이 CID폰트라 텍스트추출기가 못 읽는다(ToUnicode 부재). 유일 해법=OCR.
PdfParser 가 이미 `TextExtractor`(경로→PdfPage) 콜러블을 주입받으므로, **OCR = 대체
TextExtractor**. PdfParser 를 한 줄도 안 고치고 끼운다.

백엔드 pluggable(OcrBackend): TesseractBackend(로컬)·CloudBackend(Document AI/Upstage,
API키)·MockOcrBackend(테스트). 미설치 시 명확한 오류. lang 기본 'kor+eng'.

smart_extract: pdftotext 로 뽑고 → garble 감지되면 → OCR 로 재추출(자동 폴백).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from .pdf import (
    PdfPage, TextExtractor, confidence_from_garble, garble_ratio, pdftotext_layout,
)


class OcrBackend(Protocol):
    """페이지 이미지를 텍스트로. 구현체가 렌더링·인식 담당."""
    def ocr_pdf(self, path: str, *, lang: str = "kor+eng") -> list[str]:
        """PDF 각 페이지 → 인식 텍스트 리스트(페이지 순서)."""
        ...

    @property
    def confidence(self) -> float:
        """이 백엔드 산출의 기본 신뢰도(OCR 은 <1)."""
        ...


@dataclass
class TesseractBackend:
    """로컬 tesseract(pytesseract + pdf2image). 미설치 시 설치 안내 오류."""
    dpi: int = 300
    confidence: float = 0.75

    def ocr_pdf(self, path: str, *, lang: str = "kor+eng") -> list[str]:
        try:
            import pytesseract
            from pdf2image import convert_from_path
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "OCR 백엔드 미설치: pip install pytesseract pdf2image + tesseract(한국어 "
                "traineddata: kor) + poppler 필요"
            ) from e
        images = convert_from_path(path, dpi=self.dpi)
        return [pytesseract.image_to_string(img, lang=lang) for img in images]


@dataclass
class MockOcrBackend:
    """테스트용: 페이지별 canned 텍스트."""
    pages_text: list[str]
    confidence: float = 0.75

    def ocr_pdf(self, path: str, *, lang: str = "kor+eng") -> list[str]:
        return list(self.pages_text)


def make_ocr_extractor(backend: OcrBackend, *, lang: str = "kor+eng") -> TextExtractor:
    """OcrBackend → PdfParser 에 주입 가능한 TextExtractor. 페이지 offset 채운다."""
    def extractor(path: str) -> list[PdfPage]:
        texts = backend.ocr_pdf(path, lang=lang)
        pages: list[PdfPage] = []
        offset = 0
        for i, t in enumerate(texts, 1):
            pages.append(PdfPage(page_no=i, text=t, char_offset=offset))
            offset += len(t) + 1
        return pages
    return extractor


def smart_extract(
    path: str,
    *,
    ocr_backend: OcrBackend | None = None,
    garble_threshold: float = 0.5,
    lang: str = "kor+eng",
) -> tuple[list[PdfPage], str]:
    """pdftotext 우선, garble 심하면 OCR 폴백. (pages, 사용방법) 반환.

    방법 = 'pdftotext' | 'ocr' | 'pdftotext(ocr없음)'. OCR 백엔드 없으면 pdftotext 유지.
    """
    pages = pdftotext_layout(path)
    doc_text = "\n".join(p.text for p in pages)
    if garble_ratio(doc_text) < garble_threshold:
        return pages, "pdftotext"
    if ocr_backend is None:
        return pages, "pdftotext(ocr없음)"
    ocr_pages = make_ocr_extractor(ocr_backend, lang=lang)(path)
    return ocr_pages, "ocr"


def ocr_confidence(backend: OcrBackend, text: str) -> float:
    """OCR 결과 신뢰도 = 백엔드 기본 × garble 보정."""
    return round(backend.confidence * confidence_from_garble(text), 2)
