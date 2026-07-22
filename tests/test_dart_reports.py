"""DART 정기보고서 주요정보 5종 테스트 — 순수 파서 + 주입 http(네트워크·키 불요).

stdlib: `python tests/test_dart_reports.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ingest.dart_reports import (  # noqa: E402
    DartReportError,
    fetch_company,
    fetch_dividends,
    fetch_investments,
    fetch_major_shareholders,
    fetch_shares_total,
    parse_audit_opinion,
    parse_company,
    parse_shares_total,
)


def _http(payload):
    """단일 응답을 돌려주는 주입용 http. 호출 인자를 record 에 남긴다."""
    record = {}

    def http(url, params):
        record["url"] = url
        record["params"] = params
        return payload

    http.record = record
    return http


def test_company_corp_cls_mapping():
    out = parse_company({"corp_name": "테스트", "corp_cls": "K", "acc_mt": "12"})
    assert out["corp_cls_nm"] == "코스닥"
    assert out["acc_mt"] == "12"          # 결산월 보존(DCF 기간 정합)


def test_company_unknown_cls_is_none():
    assert parse_company({"corp_cls": "?"})["corp_cls_nm"] is None


def test_fetch_company_passes_params():
    http = _http({"status": "000", "corp_name": "삼성전자", "corp_cls": "Y"})
    out = fetch_company("KEY", "00126380", http_json=http)
    assert out["corp_name"] == "삼성전자"
    assert http.record["params"] == {"crtfc_key": "KEY", "corp_code": "00126380"}


def test_audit_opinion_maps_kam():
    rows = parse_audit_opinion({"status": "000", "list": [
        {"bsns_year": "2023", "adtor": "한영", "adt_opinion": "적정",
         "core_adt_matter": "수익인식", "emphs_matter": "계속기업"},
    ]})
    assert rows[0]["auditor"] == "한영"
    assert rows[0]["opinion"] == "적정"
    assert rows[0]["kam"] == "수익인식"
    assert rows[0]["emphasis"] == "계속기업"


def test_shares_total_preserves_issued_and_distributed():
    # D7 게이트: 발행총수 ≠ 유통주식수 를 둘 다 보존해야 대조 가능
    out = parse_shares_total({"list": [
        {"se": "보통주", "isu_stock_totqy": "12,385,000",
         "distb_stock_co": "11,214,000", "tesstk_co": "1,171,000"},
    ]})
    r = out["rows"][0]
    assert r["isu_stock_totqy"] == "12,385,000"
    assert r["distb_stock_co"] == "11,214,000"
    assert r["tesstk_co"] == "1,171,000"


def test_major_shareholders_rate():
    rows = fetch_major_shareholders(
        "K", "c", "2023",
        http_json=_http({"status": "000", "list": [
            {"nm": "홍길동", "relate": "본인",
             "trmend_posesn_stock_qota_rt": "25.3"}]}))
    assert rows[0]["name"] == "홍길동"
    assert rows[0]["trmend_rate"] == "25.3"


def test_investments_book_amount():
    rows = fetch_investments(
        "K", "c", "2023",
        http_json=_http({"status": "000", "list": [
            {"inv_prm": "자회사", "trmend_blce_acntbk_amount": "5,000",
             "recent_total_aset": "80,000"}]}))
    assert rows[0]["corp_name"] == "자회사"
    assert rows[0]["trmend_book_amount"] == "5,000"        # NOA 시드
    assert rows[0]["recent_total_asset"] == "80,000"


def test_dividends_indicator_rows():
    rows = fetch_dividends(
        "K", "c", "2023",
        http_json=_http({"status": "000", "list": [
            {"se": "주당 현금배당금(원)", "thstrm": "500", "frmtrm": "400"}]}))
    assert rows[0]["se"] == "주당 현금배당금(원)"
    assert rows[0]["thstrm"] == "500"
    assert rows[0]["frmtrm"] == "400"


def test_status_013_returns_empty():
    # 조회데이터없음(013)은 오류가 아니라 빈 목록(분·반기 간소화 대응)
    rows = fetch_investments("K", "c", "2023", http_json=_http({"status": "013"}))
    assert rows == []


def test_error_status_raises():
    http = _http({"status": "020", "message": "요청제한 초과"})
    try:
        fetch_company("K", "c", http_json=http)
    except DartReportError as e:
        assert e.status == "020"
    else:
        raise AssertionError("DartReportError 가 발생해야 함")


def test_reprt_code_passthrough():
    http = _http({"status": "000", "list": []})
    fetch_shares_total("K", "00126380", "2023", reprt_code="11013", http_json=http)
    assert http.record["params"]["reprt_code"] == "11013"
    assert http.record["params"]["bsns_year"] == "2023"


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok {_name}")
    print("all passed")
