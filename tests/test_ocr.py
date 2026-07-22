"""OCR 추상화 테스트 — Mock 백엔드로 아키텍처 검증(실 tesseract 불요).

OCR = 대체 TextExtractor → PdfParser 무수정 통합. smart_extract 자동 폴백.
stdlib: `python tests/test_ocr.py`
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ingest.parsers.ocr import (  # noqa: E402
    MockOcrBackend, make_ocr_extractor, ocr_confidence, smart_extract,
)
from ingest.parsers.pdf import PdfParser  # noqa: E402

# OCR 이 복원한 한글 표(pdftotext 가 CID로 놓친 것)
OCR_PAGES = [
    "삼성전자 재무제표\n항목        2025      2026\n매출액    1,000     1,100\n영업이익    600       660\n",
]


def test_ocr_extractor_produces_pages():
    ext = make_ocr_extractor(MockOcrBackend(OCR_PAGES))
    pages = ext("dummy.pdf")
    assert len(pages) == 1
    assert "매출액" in pages[0].text          # 한글 복원됨(pdftotext 는 못하던)


def test_pdfparser_with_ocr_extractor():
    # PdfParser 무수정 — OCR extractor 주입만으로 표 추출
    p = PdfParser("scan_opinion", extractor=make_ocr_extractor(MockOcrBackend(OCR_PAGES)),
                  min_cols=2)
    res = p.extract("dummy.pdf")
    nums = [v for v in res.values if v.value is not None]
    assert any(v.value == Decimal(1000) for v in nums)
    assert any(v.value == Decimal(1100) for v in nums)


def test_smart_extract_no_backend_keeps_pdftotext():
    # 실 다산(garble)이 있으면 OCR 백엔드 없을 때 pdftotext 유지
    hits = list(Path(r"D:/Valuation/외부평가의견서").glob("*다산*DCF.pdf"))
    if not hits:
        print("  (skip: 실파일 없음)"); return
    pages, method = smart_extract(str(hits[0]))
    assert method == "pdftotext(ocr없음)"       # garble 감지되나 백엔드 없음


def test_smart_extract_falls_back_to_ocr():
    hits = list(Path(r"D:/Valuation/외부평가의견서").glob("*다산*DCF.pdf"))
    if not hits:
        print("  (skip)"); return
    backend = MockOcrBackend(["OCR로 복원한 한글 텍스트 매출 영업이익 " * 5])
    pages, method = smart_extract(str(hits[0]), ocr_backend=backend)
    assert method == "ocr"                       # garble → OCR 폴백
    assert "OCR로 복원" in pages[0].text


def test_ocr_confidence_combines():
    b = MockOcrBackend([], confidence=0.75)
    c = ocr_confidence(b, "정상 한글 텍스트 매출 영업이익 자산")
    assert c == 0.75                             # 0.75 × 1.0(정상)


def test_ocr_environment_diagnostic():
    from ingest.parsers.ocr import ocr_environment
    env = ocr_environment()
    # 진단 필드 존재 + 일관성
    assert set(env) >= {"tesseract", "renderer", "langs", "has_korean", "ready", "missing"}
    assert env["ready"] == (not env["missing"])
    assert env["has_korean"] == ("kor" in env["langs"])
    print(f"  OCR 환경: tesseract={'O' if env['tesseract'] else 'X'} "
          f"renderer={'O' if env['renderer'] else 'X'} kor={'O' if env['has_korean'] else 'X'}")


def test_tesseract_backend_reports_missing():
    from ingest.parsers.ocr import TesseractBackend, ocr_environment
    env = ocr_environment()
    if env["ready"]:
        print("  (OCR 환경 완비 — skip)"); return
    try:
        TesseractBackend().ocr_pdf("x.pdf")
        assert False, "미비 환경인데 오류 안 남"
    except RuntimeError as e:
        assert "OCR 실행 불가" in str(e)
        # 실제 미비 항목이 메시지에 반영
        assert any(m.split("(")[0][:4] in str(e) or m[:4] in str(e) for m in env["missing"])


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    ok = 0
    for fn in fns:
        try:
            fn(); ok += 1; print(f"  ok  {fn.__name__}")
        except Exception:
            print(f"  FAIL {fn.__name__}"); traceback.print_exc()
    print(f"\n{ok}/{len(fns)} passed")
