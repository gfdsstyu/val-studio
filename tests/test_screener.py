"""기업 스크리너 — 네트워크 없이 canned 목록으로 전량 검증.

픽스처는 `fdr.StockListing("KRX-DESC")`·`("KRX")` 의 **실측 열 구성**을 축약해 재현한다.
stdlib: `python tests/test_screener.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ingest.screener import (  # noqa: E402
    ScreenerIndex, build_index, industries, search, staleness_days,
)

# ── 픽스처: 실측 열 이름 그대로 ──────────────────────────────────────────────
_DESC = [
    {"Code": "214150", "Name": "클래시스", "Market": "KOSDAQ GLOBAL",
     "Sector": "우량기업부", "Industry": "의료용 기기 제조업", "Products": "미용의료기기",
     "ListingDate": "2017-12-28", "SettleMonth": "12월", "HomePage": "http://classys.com",
     "Region": "서울특별시"},
    {"Code": "450950", "Name": "아스테라시스", "Market": "KOSDAQ",
     "Sector": "벤처기업부", "Industry": "의료용 기기 제조업",
     "Products": "피부 미용의료기기 제조, 판매",
     "ListingDate": "2024-02-23", "SettleMonth": "12월", "HomePage": "", "Region": "경기도"},
    {"Code": "005930", "Name": "삼성전자", "Market": "KOSPI",
     "Sector": float("nan"), "Industry": "통신 및 방송 장비 제조업",
     "Products": "통신 및 방송 장비, 반도체",
     "ListingDate": "1975-06-11", "SettleMonth": "12월", "HomePage": "www.samsung.com",
     "Region": "경기도"},
]
_CAP = [
    # ⚠️ 실측에서 클래시스의 시장 표기는 양쪽 다 'KOSDAQ GLOBAL' 이다. 픽스처에서만
    # 'KOSDAQ' 으로 두면 조인이 덮어써 **정확일치 필터의 결함이 가려진다**(실제로 그랬다).
    {"Code": "214150", "Name": "클래시스", "Market": "KOSDAQ GLOBAL",
     "Marcap": 2_961_700_000_000, "Stocks": 64_000_000},
    {"Code": "450950", "Name": "아스테라시스", "Market": "KOSDAQ",
     "Marcap": 219_400_000_000, "Stocks": 30_000_000},
    {"Code": "005930", "Name": "삼성전자", "Market": "KOSPI",
     "Marcap": 1_403_106_865_920_000, "Stocks": 5_846_278_608},
    # 시총 목록에만 있는 종목(우선주 등) — 버리지 않고 정보만으로 수록되어야 한다.
    {"Code": "005935", "Name": "삼성전자우", "Market": "KOSPI",
     "Marcap": 141_538_280_209_200, "Stocks": 802_371_203},
]
_CORP = [
    {"corp_code": "01061327", "corp_name": "클래시스", "stock_code": "214150"},
    {"corp_code": "00126380", "corp_name": "삼성전자", "stock_code": "005930"},
    {"corp_code": "00999999", "corp_name": "비상장사", "stock_code": ""},
]


def _idx():
    return build_index(_DESC, _CAP, as_of="2026-08-04", corp_index=_CORP)


# ── 빌드 ─────────────────────────────────────────────────────────────────────
def test_join_and_corp_code_link():
    idx = _idx()
    by = {r.stock_code: r for r in idx.rows}
    assert len(idx.rows) == 4                      # 시총 전용 종목도 남는다
    assert by["214150"].corp_code == "01061327"    # 종목코드로 고유번호 연결
    assert by["450950"].corp_code == ""            # corp 인덱스에 없으면 빈 값
    assert by["214150"].marcap == 2_961_700_000_000
    assert by["005935"].industry == ""             # 설명 없이 수록
    assert any("시총 목록에만" in n for n in idx.notes)
    assert any("고유번호 연결" in n for n in idx.notes)


def test_nan_becomes_empty_string():
    """FDR 은 결측을 float('nan') 으로 준다 — 문자열 'nan' 이 화면에 새면 안 된다."""
    idx = _idx()
    samsung = next(r for r in idx.rows if r.stock_code == "005930")
    assert samsung.sector == ""
    assert samsung.homepage == "www.samsung.com"


def test_sorted_by_marcap_desc_by_default():
    assert [r.stock_code for r in _idx().rows][:2] == ["005930", "005935"]


# ── 검색 ─────────────────────────────────────────────────────────────────────
def test_search_hits_products_not_just_name():
    """제품 문자열이 판별력의 핵심 — 이름·업종에 '미용'이 없어도 잡혀야 한다."""
    hits, total = search(_idx(), q="미용")
    assert total == 2
    assert {r.stock_code for r in hits} == {"214150", "450950"}


def test_search_by_industry_and_market_and_mcap():
    idx = _idx()
    assert search(idx, industry="의료용 기기")[1] == 2
    assert search(idx, markets=("KOSPI",))[1] == 2
    # 1천억~1조 구간 → 아스테라시스(2,194억)만
    hits, total = search(idx, mcap_min=1e11, mcap_max=1e12)
    assert total == 1 and hits[0].stock_code == "450950"


def test_market_filter_matches_kosdaq_global():
    """FDR 은 'KOSDAQ GLOBAL' 처럼 세분 표기를 준다 — 정확일치로 거르면 사라진다."""
    idx = _idx()
    codes = {r.stock_code for r in search(idx, markets=("KOSDAQ",))[0]}
    assert "214150" in codes, "KOSDAQ GLOBAL 종목이 KOSDAQ 필터에서 누락"


def test_inverted_mcap_range_is_swapped_not_silently_empty():
    """상·하한이 뒤집히면 조용히 0건이 된다 — 화면은 '조건에 맞는 회사 없음'만 보여
    원인을 알 수 없다. 연도 구간과 같은 규약으로 뒤바꿔 받는다."""
    idx = _idx()
    ok = search(idx, mcap_min=1e11, mcap_max=1e12)[1]
    flipped = search(idx, mcap_min=1e12, mcap_max=1e11)[1]
    assert flipped == ok == 1


def test_search_reports_total_when_truncated():
    hits, total = search(_idx(), limit=1)
    assert len(hits) == 1 and total == 4


def test_sort_options():
    idx = _idx()
    assert search(idx, sort="marcap_asc")[0][0].stock_code == "450950"
    assert search(idx, sort="name")[0][0].name == "삼성전자"          # 가나다 정렬
    assert search(idx, sort="bogus")[0][0].stock_code == "005930"    # 미지 값은 기본 정렬


# ── 업종 목록 ────────────────────────────────────────────────────────────────
def test_industries_counts_industry_not_sector():
    """⚠️ FDR `Sector` 는 업종이 아니라 코스닥 **소속부**다(중견기업부·벤처기업부…).

    이름이 그럴듯해 그대로 쓰면 업종 드롭다운이 통째로 엉뚱해진다(실측 오류).
    """
    names = [n for n, _ in industries(_idx())]
    assert "의료용 기기 제조업" in names
    assert not any("기업부" in n for n in names), f"소속부가 업종으로 샜다: {names}"
    assert dict(industries(_idx()))["의료용 기기 제조업"] == 2


# ── vintage ──────────────────────────────────────────────────────────────────
def test_staleness_days():
    assert staleness_days("2026-08-01", "2026-08-04") == 3
    assert staleness_days("", "2026-08-04") is None       # 판단 불가를 0으로 위장하지 않는다
    assert staleness_days("2026-08-01", "bogus") is None


def test_index_roundtrip():
    idx = _idx()
    back = ScreenerIndex.from_json(idx.to_json())
    assert back.as_of == idx.as_of and len(back.rows) == len(idx.rows)
    assert back.rows[0] == idx.rows[0]


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
