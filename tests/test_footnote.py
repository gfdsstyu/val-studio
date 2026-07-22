"""주석 추출기 테스트 — classify_ju 위치규칙 + 값추출 + 정합 tie-out.

stdlib: `python tests/test_footnote.py`
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ingest.parsers.footnote_extractor import (  # noqa: E402
    FootnoteExtractor, JuKind, classify_ju, tie_footnote_to_statement,
)
from ingest.validators import Severity  # noqa: E402

SAMPLE = """주5. 유형자산
당기 중 유형자산의 변동내역은 다음과 같습니다.
유형자산 (주5) 1,234,567
감가상각비 (주5) 89,012
매출채권 (주 6, 7) 456,000
5. 100
현금및현금성자산 199,400
"""


# ── classify_ju 위치규칙 ─────────────────────────────────────────────────────
def test_definition_vs_pointer():
    refs = classify_ju(SAMPLE)
    defs = [r for r in refs if r.kind is JuKind.DEFINITION]
    ptrs = [r for r in refs if r.kind is JuKind.POINTER]
    # '주5. 유형자산' = 정의블록 1개
    assert len(defs) == 1 and defs[0].note_no == 5
    # (주5)×2 + (주6,7)→6,7 = 포인터 4개
    assert sorted(r.note_no for r in ptrs) == [5, 5, 6, 7]


def test_definition_requires_title_not_number():
    # '5. 100' 은 제목이 숫자 → 정의블록 아님(값 라인)
    refs = classify_ju(SAMPLE)
    assert not any(r.kind is JuKind.DEFINITION and r.note_no == 5 and "100" in r.line_text
                   for r in refs)


def test_char_span_points_to_source():
    refs = classify_ju(SAMPLE)
    ptr = next(r for r in refs if r.kind is JuKind.POINTER and r.note_no == 5)
    # span 이 원문의 '주5' 를 실제로 가리킴(불변 참조)
    assert "주" in SAMPLE[ptr.char_start:ptr.char_end]


def test_multi_note_pointer():
    refs = classify_ju("매출채권 (주 6, 7) 456,000\n")
    ptrs = sorted(r.note_no for r in refs if r.kind is JuKind.POINTER)
    assert ptrs == [6, 7]


# ── FootnoteExtractor 값추출 ─────────────────────────────────────────────────
def test_extract_pointer_line_values():
    ex = FootnoteExtractor("회계법인감사보고서.pdf")
    res = ex.extract(SAMPLE)
    # 유형자산·감가상각비·매출채권 3개 값 방출
    assert res.value_of("유형자산") == Decimal(1234567)
    assert res.value_of("감가상각비") == Decimal(89012)
    assert res.value_of("매출채권") == Decimal(456000)
    assert res.ok


def test_extract_attaches_note_provenance():
    ex = FootnoteExtractor("회계법인감사보고서.pdf")
    res = ex.extract(SAMPLE)
    dep = res.by_name("감가상각비")
    assert dep.provenance.locator.note_no == 5
    assert dep.provenance.source_kind.value == "footnote"
    # 값이 원문 span 을 가리킴
    p = dep.provenance
    assert SAMPLE[p.char_start:p.char_end].replace(",", "") == "89012"


def test_pointer_without_definition_flagged():
    # (주9) 는 정의블록 없음 → note 에 '정의없음' 표기
    ex = FootnoteExtractor("x.pdf")
    res = ex.extract("기타비용 (주9) 1,000\n")
    pv = res.by_name("기타비용")
    assert "정의없음" in (pv.provenance.note or "")


# ── 정합 tie-out ─────────────────────────────────────────────────────────────
def test_tie_footnote_to_cashflow():
    # 주석 감가상각 = CF D&A
    f = tie_footnote_to_statement("D&A", "89,012", "89012")
    assert f.severity is Severity.PASS
    f2 = tie_footnote_to_statement("D&A", "89,012", "90,000")
    assert f2.severity is Severity.FAIL


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
