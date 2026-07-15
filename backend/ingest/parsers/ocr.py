"""OCR — DART PDF 한글(CID) · 스캔 의견서의 텍스트 잠금해제.

DART PDF 는 한글이 CID폰트라 텍스트추출기가 못 읽는다(ToUnicode 부재). 유일 해법=OCR.
PdfParser 가 이미 `TextExtractor`(경로→PdfPage) 콜러블을 주입받으므로, **OCR = 대체
TextExtractor**. PdfParser 를 한 줄도 안 고치고 끼운다.

백엔드 pluggable(OcrBackend): TesseractBackend(로컬)·CloudBackend(Document AI/Upstage,
API키)·MockOcrBackend(테스트). 미설치 시 명확한 오류. lang 기본 'kor+eng'.

smart_extract: pdftotext 로 뽑고 → garble 감지되면 → OCR 로 재추출(자동 폴백).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .pdf import (
    PdfPage, TextExtractor, confidence_from_garble, garble_ratio, pdftotext_layout,
)

# ── 환경 탐지 (tesseract·렌더러·언어) ─────────────────────────────────────────
_TESSERACT_CANDIDATES = [
    "tesseract",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]
# PDF→이미지 렌더러 후보(우선순위). 인자 규약은 _render_page 에서 분기.
_RENDERER_CANDIDATES = ["pdftoppm", "pdftocairo", "magick", "gswin64c", "gs"]


def find_tesseract() -> str | None:
    for c in _TESSERACT_CANDIDATES:
        if shutil.which(c) or (os.path.sep in c and Path(c).exists()):
            return c if Path(c).exists() or shutil.which(c) else None
    return None


def find_renderer() -> str | None:
    for c in _RENDERER_CANDIDATES:
        if shutil.which(c):
            return c
    return None


def tesseract_langs(tesseract: str) -> list[str]:
    try:
        out = subprocess.run([tesseract, "--list-langs"], capture_output=True, timeout=30)
        lines = out.stdout.decode("utf8", "ignore").splitlines() + \
            out.stderr.decode("utf8", "ignore").splitlines()
        return [ln.strip() for ln in lines if ln.strip() and " " not in ln.strip()
                and not ln.startswith("List")]
    except (OSError, subprocess.SubprocessError):
        return []


def ocr_environment() -> dict:
    """OCR 실행 가능성 진단: tesseract·렌더러·언어(kor 포함 여부)."""
    tess = find_tesseract()
    langs = tesseract_langs(tess) if tess else []
    renderer = find_renderer()
    missing = []
    if not tess:
        missing.append("tesseract 바이너리")
    if not renderer:
        missing.append("PDF 렌더러(pdftoppm/pdftocairo/ImageMagick/ghostscript)")
    if tess and "kor" not in langs:
        missing.append("한국어 데이터 kor.traineddata")
    return {
        "tesseract": tess, "renderer": renderer, "langs": langs,
        "has_korean": "kor" in langs, "ready": not missing, "missing": missing,
    }


class OcrBackend(Protocol):
    """페이지 이미지를 텍스트로. 구현체가 렌더링·인식 담당."""
    def ocr_pdf(self, path: str, *, lang: str = "kor+eng") -> list[str]:
        """PDF 각 페이지 → 인식 텍스트 리스트(페이지 순서)."""
        ...

    @property
    def confidence(self) -> float:
        """이 백엔드 산출의 기본 신뢰도(OCR 은 <1)."""
        ...


def _render_page(renderer: str, pdf: str, page: int, out_prefix: str, dpi: int) -> str | None:
    """PDF 한 페이지 → PNG. 렌더러별 인자 분기. 생성된 png 경로 반환(실패 None)."""
    png = f"{out_prefix}-{page}.png"
    try:
        if renderer in ("pdftoppm", "pdftocairo"):
            subprocess.run([renderer, "-png", "-r", str(dpi), "-f", str(page),
                            "-l", str(page), pdf, out_prefix], check=True,
                           capture_output=True, timeout=120)
            # pdftoppm 은 -{page} 접미(자리수 가변) → glob 로 탐색
            import glob
            hits = sorted(glob.glob(f"{out_prefix}-*.png"))
            return hits[0] if hits else None
        if renderer == "magick":
            subprocess.run([renderer, "-density", str(dpi), f"{pdf}[{page-1}]", png],
                           check=True, capture_output=True, timeout=120)
            return png if Path(png).exists() else None
        if renderer in ("gswin64c", "gs"):
            subprocess.run([renderer, "-dNOPAUSE", "-dBATCH", "-sDEVICE=png16m",
                            f"-r{dpi}", f"-dFirstPage={page}", f"-dLastPage={page}",
                            f"-sOutputFile={png}", pdf], check=True,
                           capture_output=True, timeout=120)
            return png if Path(png).exists() else None
    except (OSError, subprocess.SubprocessError):
        return None
    return None


@dataclass
class TesseractBackend:
    """로컬 tesseract + PDF 렌더러(subprocess). pip 불요. 미비 시 설치안내 오류.

    tesseract·렌더러 경로 자동탐지. 렌더러로 페이지 렌더 → tesseract 인식. 렌더러 또는
    tesseract 부재 시 ocr_environment() 진단 메시지로 명확히 안내.
    """
    dpi: int = 300
    confidence: float = 0.72
    tesseract: str | None = None
    renderer: str | None = None

    def __post_init__(self) -> None:
        self.tesseract = self.tesseract or find_tesseract()
        self.renderer = self.renderer or find_renderer()

    def ocr_pdf(self, path: str, *, lang: str = "kor+eng") -> list[str]:
        env = ocr_environment()
        if not self.tesseract or not self.renderer:
            raise RuntimeError(
                "OCR 실행 불가 — 미비: " + ", ".join(env["missing"]) +
                ". 설치: ①렌더러=poppler(pdftoppm)/ImageMagick/ghostscript "
                "②tesseract 한국어 kor.traineddata → tessdata 폴더."
            )
        # 요청 언어 중 설치된 것만(kor 없으면 eng)
        want = [x for x in lang.split("+") if x in env["langs"]] or ["eng"]
        lang_arg = "+".join(want)
        n = _page_count(path)
        texts: list[str] = []
        with tempfile.TemporaryDirectory() as td:
            for pg in range(1, n + 1):
                png = _render_page(self.renderer, path, pg, str(Path(td) / "pg"), self.dpi)
                if png is None:
                    texts.append(""); continue
                out = subprocess.run(
                    [self.tesseract, png, "stdout", "-l", lang_arg],
                    capture_output=True, timeout=180)
                texts.append(out.stdout.decode("utf8", "ignore"))
                try:
                    os.remove(png)
                except OSError:
                    pass
        return texts


def _page_count(path: str) -> int:
    """pdftotext 로 페이지 수 추정(\\f 분리)."""
    try:
        out = subprocess.run(["pdftotext", "-layout", path, "-"],
                             capture_output=True, timeout=60)
        return max(1, out.stdout.decode("utf8", "ignore").count("\f") + 1)
    except (OSError, subprocess.SubprocessError):
        return 1


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
