"""의견서 시맨틱 프로파일 테스트 — 고정양식 앵커 추출(SOTP·영구성장률·통화).

합성 의견서 텍스트(한글 라벨 소실 모사) + 실 다산 PDF 스모크.
stdlib: `python tests/test_opinion_template.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ingest.profiles.opinion_template import extract_opinion  # noqa: E402

# 한글 라벨이 CID로 소실된 의견서 모사(영문·수식·숫자만 생존). 2개 엔티티(SOTP), JPY.
GARBLED_OPINION = """
4.4.1.6
WACC = Ke E / V + Kd (1 - Tc) D / V
(Rm - Rf)(B)(2)   4.01%
Size Risk Premium(D)(4)   3.35%
(F)(5)   15.34%
   12.80%
4.4.1.7
   2028         1.00%
4.4.2. DZS Japan, Inc.
   (: JPY)
WACC = Ke E / V + Kd (1 - Tc) D / V
Size Risk Premium(D)(4)   4.10%
   11.50%
2029 (C=A x (1+B))   1.00%
"""


def test_entity_count_sotp():
    e = extract_opinion(GARBLED_OPINION)
    assert e.entity_count == 2               # WACC = Ke 두 번
    assert e.is_sotp is True


def test_terminal_growth_anchor():
    e = extract_opinion(GARBLED_OPINION)
    assert 0.01 in e.terminal_growths        # 1.00% 영구성장률 포착
    # 큰 %(WACC 12.80% 등)는 영구성장률 후보서 제외
    assert all(g < 0.03 for g in e.terminal_growths)


def test_size_premium_anchor():
    e = extract_opinion(GARBLED_OPINION)
    assert 0.0335 in e.size_premiums
    assert 0.041 in e.size_premiums


def test_currency_detection():
    e = extract_opinion(GARBLED_OPINION)
    assert "JPY" in e.currencies


def test_single_entity_not_sotp():
    txt = "WACC = Ke E / V + Kd\nSize Risk Premium 3.00%\n2028 (1+B) 1.00%\n"
    e = extract_opinion(txt)
    assert e.entity_count == 1 and e.is_sotp is False


def test_garble_confidence_note():
    e = extract_opinion(GARBLED_OPINION, garble_confidence=0.3)
    assert e.confidence == 0.3
    assert "CID" in e.note


def test_real_dasan_smoke():
    """실 다산 의견서(있으면): SOTP·엔티티 다수·통화 다수 검출."""
    pdf = Path(r"D:/Valuation/외부평가의견서")
    hits = list(pdf.glob("*다산*DCF.pdf")) if pdf.exists() else []
    if not hits:
        print("  (skip: 다산 PDF 없음)"); return
    sys.path.insert(0, str(ROOT / "backend"))
    from ingest.parsers.pdf import pdftotext_layout
    pages = pdftotext_layout(str(hits[0]))
    text = "\n".join(p.text for p in pages)
    e = extract_opinion(text, garble_confidence=0.3)
    assert e.entity_count >= 2               # 5개 종속회사(WACC 반복)
    assert e.is_sotp is True
    assert 0.01 in e.terminal_growths        # 영구성장률 1.00%
    print(f"  다산: entity={e.entity_count} terminal={e.terminal_growths} "
          f"currencies={e.currencies}")


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
