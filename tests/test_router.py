"""라우터 테스트 — 방식·유형 감지 + 실파일 라우팅 스모크.

방식은 확장자(결정적), 유형은 파일명 힌트+내용 앵커. stdlib: `python tests/test_router.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ingest.router import (  # noqa: E402
    DocType, InputMethod, build_parser, detect_doc_type, detect_method, route,
)


# ── 방식 감지 ────────────────────────────────────────────────────────────────
def test_detect_method_by_ext():
    assert detect_method("a/entity_2026.xbrl") is InputMethod.XBRL
    assert detect_method("DCF_클래시스.xlsx") is InputMethod.XLSX
    assert detect_method("[다산]평가의견서.pdf") is InputMethod.PDF
    assert detect_method("noext") is InputMethod.UNKNOWN


# ── 유형 감지(파일명) ────────────────────────────────────────────────────────
def test_detect_doctype_by_name():
    assert detect_doc_type("[다산네트웍스]외부평가기관의평가의견서.pdf")[0] is DocType.OPINION
    assert detect_doc_type("[삼성전자]사업보고서(2026).pdf")[0] is DocType.BUSINESS_REPORT
    assert detect_doc_type("한투_반도체_리서치.pdf")[0] is DocType.RESEARCH
    assert detect_doc_type("무의미한파일.pdf")[0] is DocType.UNKNOWN


def test_doctype_content_boosts_confidence():
    dt, conf, _ = detect_doc_type(
        "[다산]평가의견서.pdf", sample_text="... WACC = Ke E/V + Kd ... 평가의견 ...")
    assert dt is DocType.OPINION and conf >= 0.9      # 파일명+내용 교차확인


def test_doctype_content_only():
    dt, conf, why = detect_doc_type("scan001.pdf", sample_text="투자의견 BUY 목표주가 100,000")
    assert dt is DocType.RESEARCH and 0 < conf < 0.7   # 내용만 → 중간 신뢰


# ── route 보정 ───────────────────────────────────────────────────────────────
def test_route_xlsx_defaults_dcf_model():
    d = route("어떤모델.xlsx")
    assert d.method is InputMethod.XLSX and d.doc_type is DocType.DCF_MODEL


def test_route_xbrl_defaults_business_report():
    d = route("entity00126380_2026-03-31.xbrl")
    assert d.method is InputMethod.XBRL and d.doc_type is DocType.BUSINESS_REPORT


def test_build_parser_matches_method():
    from ingest.parsers.xbrl import XbrlParser
    from ingest.parsers.pdf import PdfParser
    from ingest.parsers.xlsx import XlsxParser
    assert isinstance(build_parser(route("x.xbrl")), XbrlParser)
    assert isinstance(build_parser(route("x.pdf")), PdfParser)
    assert isinstance(build_parser(route("x.xlsx")), XlsxParser)


# ── 실파일 스모크 ────────────────────────────────────────────────────────────
def test_real_files_smoke():
    checks = [
        (r"D:/Valuation/외부평가의견서", "*다산*DCF.pdf", InputMethod.PDF, DocType.OPINION),
    ]
    ran = 0
    for folder, pat, meth, dt in checks:
        hits = list(Path(folder).glob(pat)) if Path(folder).exists() else []
        if not hits:
            continue
        d = route(str(hits[0]))
        assert d.method is meth, f"{hits[0].name}: {d.method}"
        assert d.doc_type is dt, f"{hits[0].name}: {d.doc_type}"
        ran += 1
        print(f"  {hits[0].name[:30]} → {d.method.value}/{d.doc_type.value} conf={d.type_confidence}")
    if ran == 0:
        print("  (skip: 실파일 없음)")


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
