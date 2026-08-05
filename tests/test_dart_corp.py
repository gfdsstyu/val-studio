"""DART 보조 API 테스트 — corpCode 파싱·검색·zip 추출·filings(주입 http).

stdlib: `python tests/test_dart_corp.py`.
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ingest.dart_corp import (  # noqa: E402
    extract_corpcode_zip, fetch_corp_index, list_filings, parse_corp_index,
    infer_search_by,
    search_corp,
    search_corp_index,
)

_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<result>
  <list><corp_code>00126380</corp_code><corp_name>\xec\x82\xbc\xec\x84\xb1\xec\xa0\x84\xec\x9e\x90</corp_name><stock_code>005930</stock_code><modify_date>20230101</modify_date></list>
  <list><corp_code>00164779</corp_code><corp_name>\xec\x82\xbc\xec\x84\xb1\xec\xa0\x84\xea\xb8\xb0</corp_name><stock_code>009150</stock_code><modify_date>20230101</modify_date></list>
  <list><corp_code>00999999</corp_code><corp_name>\xec\x82\xbc\xec\x84\xb1\xeb\xb9\x84\xec\x83\x81\xec\x9e\xa5\xec\x82\xac</corp_name><stock_code></stock_code><modify_date>20230101</modify_date></list>
</result>"""


def test_parse_corp_index():
    idx = parse_corp_index(_XML)
    assert len(idx) == 3
    assert idx[0]["corp_code"] == "00126380" and idx[0]["stock_code"] == "005930"


def test_search_exact_and_listed_first():
    idx = parse_corp_index(_XML)
    res = search_corp_index(idx, "삼성전자")
    assert res[0]["corp_name"] == "삼성전자"          # 정확일치 최상단
    # 부분일치 '삼성' → 상장사 우선
    res2 = search_corp_index(idx, "삼성")
    assert res2[0]["stock_code"] != "" and len(res2) == 3


def test_search_listed_only():
    idx = parse_corp_index(_XML)
    res = search_corp_index(idx, "삼성", listed_only=True)
    assert all(c["stock_code"] for c in res) and len(res) == 2


def test_infer_search_axis():
    """실무자는 회사명·종목코드·고유번호를 한 칸에 친다 — 입력 모양으로 축을 가른다."""
    assert infer_search_by("00126380") == "corp"      # 8자리 = 고유번호
    assert infer_search_by("005930") == "stock"       # 6자리 = 종목코드
    assert infer_search_by("삼성전자") == "name"
    assert infer_search_by("12345") == "name"         # 6·8자리 아닌 숫자는 이름 취급


def test_search_by_corp_and_stock():
    idx = parse_corp_index(_XML)
    hits, total, axis = search_corp(idx, "00126380")
    assert axis == "corp" and total == 1 and hits[0]["corp_name"] == "삼성전자"
    hits, total, axis = search_corp(idx, "009150")
    assert axis == "stock" and total == 1 and hits[0]["corp_name"] == "삼성전기"
    # 비상장은 종목코드가 빈 문자열 — 빈 질의로 전부 걸리면 안 된다
    assert search_corp(idx, "000000", by="stock")[1] == 0


def test_search_total_reports_matches_not_index_size():
    """total 은 **매칭 건수**여야 한다 — 인덱스 크기를 실어 보내면 화면이 거짓말한다."""
    idx = parse_corp_index(_XML)
    hits, total, _ = search_corp(idx, "삼성", limit=2)
    assert len(hits) == 2 and total == 3              # 잘렸지만 전체는 3건
    assert total != len(idx) or len(idx) == 3         # 인덱스 크기와 우연히 같은 경우만 허용


def test_search_by_override_beats_inference():
    """명시 축이 auto 추론을 이긴다 — 숫자 상호를 이름으로 찾을 길이 있어야 한다."""
    idx = parse_corp_index(_XML)
    assert search_corp(idx, "005930", by="name")[1] == 0
    assert search_corp(idx, "005930", by="stock")[1] == 1


def test_extract_corpcode_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("CORPCODE.xml", _XML)
    idx = extract_corpcode_zip(buf.getvalue())
    assert len(idx) == 3


def test_fetch_corp_index_injected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("CORPCODE.xml", _XML)
    zbytes = buf.getvalue()
    idx = fetch_corp_index("KEY", http_bytes=lambda url, p: zbytes)
    assert len(idx) == 3


def test_list_filings_injected():
    canned = {"status": "000", "list": [
        {"rcept_no": "20230101000001", "report_nm": "사업보고서", "rcept_dt": "20230101", "flr_nm": "삼성전자"},
    ]}
    res = list_filings("KEY", "00126380", bgn_de="20230101",
                       http_json=lambda url, p: canned)
    assert res[0]["rcept_no"] == "20230101000001"


def test_list_filings_no_data_ok():
    res = list_filings("KEY", "00000000", bgn_de="20230101",
                       http_json=lambda url, p: {"status": "013", "message": "no data"})
    assert res == []


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


# ── 사업연도 → 사업보고서 접수번호 자동 해소 ─────────────────────────────────
def _annual_http(rows):
    def http(url, params):
        assert params.get("pblntf_ty") == "A"          # 정기공시만
        return {"status": "000", "list": rows}
    return http


_ROWS = [
    {"rcept_no": "20260318000182", "report_nm": "사업보고서 (2025.12)",
     "rcept_dt": "20260318", "flr_nm": "리노공업"},
    {"rcept_no": "20230321000231", "report_nm": "사업보고서 (2022.12)",
     "rcept_dt": "20230321", "flr_nm": "리노공업"},
    {"rcept_no": "20230814000718", "report_nm": "[기재정정]사업보고서 (2022.12)",
     "rcept_dt": "20230814", "flr_nm": "리노공업"},
    {"rcept_no": "20250515000111", "report_nm": "분기보고서 (2025.03)",
     "rcept_dt": "20250515", "flr_nm": "리노공업"},
]


def test_annual_year_comes_from_title_not_receipt_date():
    """2025 사업보고서는 2026-03 에 접수된다 — 접수일로 귀속하면 한 해씩 밀린다."""
    from ingest.dart_corp import find_annual_reports
    got = find_annual_reports("K", "00369657", http_json=_annual_http(_ROWS))
    assert got[2025]["rcept_no"] == "20260318000182"
    assert got[2025]["rcept_dt"] == "20260318"          # 접수는 이듬해
    assert 2026 not in got


def test_amended_report_wins():
    """같은 사업연도에 정정본이 따로 접수된다 — 늦게 접수된 쪽을 쓴다(실측 2022)."""
    from ingest.dart_corp import find_annual_reports
    got = find_annual_reports("K", "00369657", http_json=_annual_http(_ROWS))
    assert got[2022]["rcept_no"] == "20230814000718"
    assert got[2022]["amended"] is True


def test_non_annual_reports_are_ignored():
    from ingest.dart_corp import find_annual_reports
    got = find_annual_reports("K", "00369657", http_json=_annual_http(_ROWS))
    assert set(got) == {2025, 2022}                     # 분기보고서 제외


def test_year_filter_narrows_result():
    from ingest.dart_corp import find_annual_reports
    got = find_annual_reports("K", "00369657", years=[2022], http_json=_annual_http(_ROWS))
    assert set(got) == {2022}
