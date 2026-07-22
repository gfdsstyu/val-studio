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
