"""PDF 파서 테스트 — 표 복원(우측정렬 클러스터링)·garble 감지·RAG 청크.

실 PDF 없이 extractor 주입으로 합성 페이지를 흘려 파싱 로직 검증.
stdlib: `python tests/test_pdf.py`
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ingest.parsers.pdf import (  # noqa: E402
    PdfPage, PdfParser, confidence_from_garble, garble_ratio,
    reconstruct_tables, text_chunks,
)

# 우측정렬 숫자 표(라벨 정상)
CLEAN = """평가 요약
항목              2023      2024      2025
매출액           1,000     1,100     1,210
매출원가           400       440       484
영업이익           600       660       726
"""

# 같은 표인데 한글 라벨이 CID로 소실(공백만) — 외부의견서 상황
GARBLED = """
                  2023      2024      2025
                 1,000     1,100     1,210
                   400       440       484
                   600       660       726
"""


def _pages(text: str):
    def extractor(_path):
        return [PdfPage(page_no=1, text=text, char_offset=0)]
    return extractor


# ── 표 복원 ──────────────────────────────────────────────────────────────────
def test_reconstruct_columns_rightaligned():
    tbls = reconstruct_tables(PdfPage(1, CLEAN, 0), min_cols=3)
    assert len(tbls) == 1
    t = tbls[0]
    assert len(t.columns) == 3          # 2023/2024/2025 세 컬럼
    assert t.rows() == 4                 # 헤더행 + 3 데이터행
    # 첫 데이터행 값
    row1 = sorted([c for c in t.cells if c.row == 1], key=lambda c: c.col)
    assert [c.text for c in row1] == ["1,000", "1,100", "1,210"]


def test_columns_survive_label_garble():
    # 라벨이 사라져도 숫자 컬럼 구조는 동일하게 복원(핵심)
    tbls = reconstruct_tables(PdfPage(1, GARBLED, 0), min_cols=3)
    assert len(tbls) == 1
    assert len(tbls[0].columns) == 3


def test_char_span_points_to_number():
    t = reconstruct_tables(PdfPage(1, CLEAN, 0), min_cols=3)[0]
    c = next(c for c in t.cells if c.text == "1,210")
    assert CLEAN[c.char_start:c.char_end] == "1,210"


# ── garble 감지 ──────────────────────────────────────────────────────────────
def test_garble_ratio():
    assert garble_ratio("이것은 정상적인 한글 문장입니다. 매출 1000") < 0.1
    assert garble_ratio("      1,000   400   600   %  ") >= 0.5   # 한글없는 숫자표
    assert garble_ratio("") == 1.0


def test_confidence_inverse():
    assert confidence_from_garble("정상 한글 텍스트 다수 포함 매출 원가 이익") == 1.0


# ── PdfParser 방출 ───────────────────────────────────────────────────────────
def test_parser_emits_cells_with_provenance():
    p = PdfParser("test.pdf", extractor=_pages(CLEAN), min_cols=3)
    res = p.extract("test.pdf")
    # 12개 숫자셀(헤더 2023/24/25 포함 4행 × 3열) 방출
    nums = [v for v in res.values if v.value is not None]
    assert len(nums) == 12
    v = res.by_name("p1.t0.r1c0")        # 첫 데이터행 첫 컬럼 = 1,000
    assert v.value == Decimal(1000)
    assert v.provenance.locator.page == 1
    assert v.provenance.source_kind.value == "pdf"


def test_garbled_doc_low_confidence_ocr_method():
    p = PdfParser("scan.pdf", extractor=_pages(GARBLED), min_cols=3)
    res = p.extract("scan.pdf")
    v = next(v for v in res.values if v.value is not None)
    assert v.provenance.confidence < 0.6
    assert v.provenance.method.value == "ocr"   # garble → OCR 재처리 라우팅


# ── RAG 텍스트 청크 ──────────────────────────────────────────────────────────
def test_text_chunks_for_rag():
    pages = [PdfPage(1, "사업보고서 본문 내용이 충분히 길게 들어있는 페이지입니다. " * 3, 0),
             PdfPage(2, "짧음", 500)]
    chunks = text_chunks(pages, min_chars=40)
    assert len(chunks) == 1                       # 짧은 페이지 제외
    assert chunks[0].page_no == 1
    assert chunks[0].confidence == 1.0            # 디지털 사업보고서=고신뢰


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
