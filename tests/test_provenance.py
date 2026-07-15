"""Provenance + 파서 백본 단위테스트.

출처추적(char span·locator·confidence) + BaseParser.emit 파이프라인(정규화·검증·출처부착).
stdlib: `python tests/test_provenance.py`
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ingest.parsers.base import BaseParser  # noqa: E402
from ingest.provenance import (  # noqa: E402
    ExtractMethod, Locator, Provenance, ProvenancedValue, SourceKind,
    as_dict, merge_confidence,
)


# ── Locator/Provenance 기본 ──────────────────────────────────────────────────
def test_locator_labels():
    assert Locator(sheet="클래시스DCF", cell="C44").label() == "클래시스DCF!C44"
    assert Locator(note_no=12, line=3).label() == "주석12:L3"
    assert Locator(page=32).label() == "p.32"
    assert Locator().label() == "(no-locator)"


def test_provenance_confidence_bounds():
    Provenance(SourceKind.PDF_OCR, ExtractMethod.OCR, "a.pdf", confidence=0.8)  # ok
    for bad in (-0.1, 1.1):
        try:
            Provenance(SourceKind.PDF, ExtractMethod.OCR, "a.pdf", confidence=bad)
            assert False, "confidence 범위검증 실패"
        except ValueError:
            pass


def test_provenance_char_span_paired():
    # start/end 는 함께여야
    try:
        Provenance(SourceKind.PDF, ExtractMethod.REGEX, "a.pdf", char_start=5)
        assert False
    except ValueError:
        pass
    # end < start 불가
    try:
        Provenance(SourceKind.PDF, ExtractMethod.REGEX, "a.pdf", char_start=10, char_end=5)
        assert False
    except ValueError:
        pass
    # 정상
    p = Provenance(SourceKind.PDF, ExtractMethod.REGEX, "a.pdf", char_start=5, char_end=10)
    assert "@5-10" in p.label()


def test_merge_confidence_weakest_link():
    def pv(c):
        return ProvenancedValue(Decimal(1),
                                Provenance(SourceKind.XLSX, ExtractMethod.FORMULA, "x", confidence=c))
    assert merge_confidence(pv(1.0), pv(0.7), pv(0.9)) == 0.7


def test_as_dict_preserves_decimal_as_str():
    pv = ProvenancedValue(Decimal("1234.5"),
                          Provenance(SourceKind.DART, ExtractMethod.STRUCTURED, "rc1",
                                     locator=Locator(rcept_no="rc1", account_id="Revenue")))
    d = as_dict(pv)
    assert d["value"] == "1234.5" and d["source_kind"] == "dart"
    assert "DART rc1/Revenue" in d["locator"]


# ── BaseParser.emit 파이프라인 ───────────────────────────────────────────────
class _DummyParser(BaseParser):
    source_kind = SourceKind.MANUAL
    default_method = ExtractMethod.MANUAL

    def extract(self, raw):
        for i, (name, txt) in enumerate(raw):
            self.emit(name, txt, char_start=i, char_end=i + 1,
                      locator=Locator(line=i))
        return self.result


def test_parser_emit_normalizes_and_traces():
    p = _DummyParser("manual-1")
    res = p.extract([("wacc", "6.24%"), ("ev", "(1,234)"), ("rev", "56억")])
    assert res.value_of("wacc") == Decimal("0.0624")
    assert res.value_of("ev") == Decimal(-1234)
    assert res.value_of("rev") == Decimal(5600)          # 56 × 100(억→백만)
    assert res.ok
    # 출처 추적: char span + line locator
    wacc = res.by_name("wacc")
    assert wacc.provenance.char_start == 0
    assert wacc.provenance.locator.line == 0


def test_parser_emit_bad_number_fails_gate():
    p = _DummyParser("manual-2")
    res = p.extract([("good", "100"), ("bad", "N/A_숫자아님")])
    assert res.value_of("good") == Decimal(100)
    assert res.value_of("bad") is None
    assert not res.ok                       # 숫자 파싱 실패 → 게이트 차단
    assert res.report.fails


def test_emit_blank_aware_records_kind():
    p = _DummyParser("manual-3")
    pv = p.emit_blank_aware("empty", "")
    assert pv.value is None
    assert "cell_kind=blank" in (pv.provenance.note or "")
    assert p.result.ok                      # 공백은 fail 아님(게이트 통과)


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
