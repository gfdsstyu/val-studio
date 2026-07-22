"""DART 클라이언트 mock 테스트 — API 키·네트워크 없이 파싱·출처·게이트 검증.

http 주입으로 canned OpenDART 응답을 흘려 넣는다.
stdlib: `python tests/test_dart_client.py`
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ingest.dart_client import DartClient, DartError, pick  # noqa: E402

# canned fnlttSinglAcntAll.json (원 단위). 실제 응답 형태 축약.
_OK_RESPONSE = {
    "status": "000",
    "message": "정상",
    "list": [
        {"rcept_no": "20240401000123", "sj_div": "IS", "account_id": "ifrs-full_Revenue",
         "account_nm": "수익(매출액)", "thstrm_amount": "180,122,798,016"},
        {"rcept_no": "20240401000123", "sj_div": "IS", "account_id": "dart_OperatingIncomeLoss",
         "account_nm": "영업이익", "thstrm_amount": "89,622,382,063"},
        {"rcept_no": "20240401000123", "sj_div": "BS", "account_id": "ifrs-full_CashAndCashEquivalents",
         "account_nm": "현금및현금성자산", "thstrm_amount": "199,400,000,000"},
        {"rcept_no": "20240401000123", "sj_div": "BS", "account_id": "dart_ShortTermBorrowings",
         "account_nm": "단기차입금", "thstrm_amount": "-"},  # 공백 관행 표기
    ],
}


def _mock_http(response):
    calls = []

    def http(url, params):
        calls.append((url, params))
        return response

    http.calls = calls
    return http


# ── 정상 조회 ────────────────────────────────────────────────────────────────
def test_financial_statements_parses_and_scales():
    http = _mock_http(_OK_RESPONSE)
    client = DartClient(api_key="KEY", http=http)
    res = client.financial_statements("00126380", 2023)
    # 원 → 백만원 자동환산: 180,122,798,016원 = 180,122.798016 백만원
    assert res.value_of("IS:수익(매출액)") == Decimal("180122.798016")
    assert res.value_of("IS:영업이익") == Decimal("89622.382063")
    assert res.value_of("BS:현금및현금성자산") == Decimal("199400")
    assert res.ok


def test_api_key_and_params_sent():
    http = _mock_http(_OK_RESPONSE)
    DartClient(api_key="SECRET", http=http).financial_statements(
        "00126380", 2023, reprt_code="11011", fs_div="CFS")
    url, params = http.calls[0]
    assert params["crtfc_key"] == "SECRET"
    assert params["corp_code"] == "00126380" and params["bsns_year"] == "2023"
    assert "fnlttSinglAcntAll.json" in url


def test_blank_amount_recorded_not_dropped():
    # '-' 단기차입금은 blank 로 기록(value None) but 게이트 통과, 오제외 방지
    res = DartClient("K", http=_mock_http(_OK_RESPONSE)).financial_statements("c", 2023)
    borrow = res.by_name("BS:단기차입금")
    assert borrow is not None and borrow.value is None
    assert "cell_kind=" in (borrow.provenance.note or "")
    assert res.ok


def test_provenance_has_rcept_and_account():
    res = DartClient("K", http=_mock_http(_OK_RESPONSE)).financial_statements("c", 2023)
    rev = res.by_name("IS:수익(매출액)")
    assert rev.provenance.locator.rcept_no == "20240401000123"
    assert rev.provenance.locator.account_id == "ifrs-full_Revenue"
    assert rev.provenance.source_kind.value == "dart"
    assert rev.provenance.method.value == "structured"


def test_error_status_raises():
    http = _mock_http({"status": "020", "message": "요청 제한 초과", "list": []})
    try:
        DartClient("K", http=http).financial_statements("c", 2023)
        assert False, "DartError 미발생"
    except DartError as e:
        assert e.status == "020"


def test_pick_helper():
    res = DartClient("K", http=_mock_http(_OK_RESPONSE)).financial_statements("c", 2023)
    got = pick(res, "수익", "영업이익", "현금")
    assert got["수익"] == Decimal("180122.798016")
    assert got["영업이익"] == Decimal("89622.382063")
    assert got["현금"] == Decimal("199400")


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
