"""사업 설명 프리필 — 상장사 인덱스 → Step2 판정 근거. 네트워크 0(인덱스 직접 구성).

회귀 핵심 3가지:
  · 티커 정규화로 **찾되**, 되돌려주는 값은 **원본 문자열**(퍼널 매칭이 정확일치)
  · 못 찾거나 내용이 없으면 **채우지 않고 경고**(빈 값을 사실로 기록하지 않는다)
  · 산출물이 `_VS_FACTS` 한 행 모양(`approval="suggested"` 격리)

stdlib: `py -3.12 tests/test_peer_prefill.py` 또는 pytest.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from ingest.peer_prefill import (  # noqa: E402
    BUSINESS_CONFIDENCE, compose_business, prefill_business,
)
from ingest.screener import ScreenerIndex, ScreenerRow, rows_by_code  # noqa: E402

_INDEX = ScreenerIndex(as_of="2026-08-04", rows=[
    ScreenerRow(stock_code="145020", name="휴젤", market="KOSDAQ",
                industry="기초 의약물질 및 생물학적 제제 제조업",
                products="보툴리눔 톡신, 히알루론산 필러"),
    ScreenerRow(stock_code="214150", name="클래시스", market="KOSDAQ GLOBAL",
                industry="의료용 기기 제조업", products="미용 의료기기"),
    ScreenerRow(stock_code="000001", name="업종만사", market="KOSPI",
                industry="특수 목적용 기계 제조업", products=""),
    ScreenerRow(stock_code="000002", name="정보없음사", market="KOSPI",
                industry="", products=""),
])


def test_rows_by_code_indexes_all():
    m = rows_by_code(_INDEX)
    assert set(m) == {"145020", "214150", "000001", "000002"}
    assert m["145020"].name == "휴젤"


def test_compose_prefers_products_and_keeps_industry_context():
    assert compose_business("보툴리눔 톡신", "제약") == "보툴리눔 톡신 (업종: 제약)"
    assert compose_business("보툴리눔 톡신", "") == "보툴리눔 톡신"


def test_compose_marks_missing_products_instead_of_hiding_it():
    """업종만 있으면 '무엇을 파는지 모른다'를 문장에 드러낸다 — 판정에 영향을 준다."""
    out = compose_business("", "의료용 기기 제조업")
    assert "주요제품 미상" in out and "의료용 기기 제조업" in out


def test_compose_returns_empty_when_nothing_known():
    """없는 것을 있는 것처럼 만들지 않는다."""
    assert compose_business("", "") == ""
    assert compose_business(None, None) == ""


def test_prefill_normalizes_ticker_but_returns_original():
    """'A145020' 으로 조회해도 표·퍼널이 쓰는 원본 문자열 그대로 돌려준다."""
    facts, warnings = prefill_business(_INDEX, [{"ticker": "A145020"}])
    assert list(facts) == ["A145020"]
    f = facts["A145020"]
    assert f.ticker == "A145020" and f.name == "휴젤"
    assert "보툴리눔 톡신" in f.business
    assert not warnings


def test_prefill_record_is_a_vs_facts_row():
    """산출물은 문자열이 아니라 출처를 진 레코드 — 공유 원장 한 행과 같은 모양."""
    facts, _ = prefill_business(_INDEX, [{"ticker": "214150"}])
    d = facts["214150"].to_dict()
    assert d["key"] == "peer.214150.business"
    assert d["approval"] == "suggested"          # 승인 전 초안으로 격리
    assert d["method"] == "structured" and d["source_id"] == "screener"
    assert d["as_of"] == "2026-08-04"            # vintage 동반
    assert d["confidence"] == BUSINESS_CONFIDENCE


def test_prefill_warns_on_unknown_ticker_without_filling():
    facts, warnings = prefill_business(_INDEX, [{"ticker": "999999", "name": "비상장사"}])
    assert facts == {}
    assert any("인덱스에 없음" in w for w in warnings)


def test_prefill_skips_when_nothing_known_but_says_so():
    facts, warnings = prefill_business(_INDEX, [{"ticker": "000002"}])
    assert facts == {}                           # 빈 값을 사실로 기록하지 않는다
    assert any("모두 미상" in w for w in warnings)


def test_prefill_fills_industry_only_company():
    facts, warnings = prefill_business(_INDEX, [{"ticker": "000001"}])
    assert "주요제품 미상" in facts["000001"].business
    assert not warnings                          # 채웠으므로 경고 아님


def test_prefill_warns_on_name_mismatch():
    """티커 오기 조기 검출 — 이름이 다르면 엉뚱한 회사를 채우고 있는 것."""
    facts, warnings = prefill_business(_INDEX, [{"ticker": "145020", "name": "클래시스"}])
    assert facts["145020"].name == "휴젤"        # 인덱스 값을 그대로 알려준다
    assert any("확인하세요" in w for w in warnings)


def test_prefill_dedupes_and_ignores_blank_tickers():
    facts, _ = prefill_business(_INDEX, [
        {"ticker": "145020"}, {"ticker": " "}, {"ticker": "145020"}, {"ticker": ""}])
    assert list(facts) == ["145020"]


def test_api_peer_prefill(monkeypatch):
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip fastapi 미설치")
        return
    from api import main as api_main

    monkeypatch.setattr(api_main, "_load_screener", lambda force=False: _INDEX)
    client = TestClient(api_main.app)
    r = client.post("/api/peer/prefill", json={
        "target": {"ticker": "214150"},
        "candidates": [{"ticker": "A145020"}, {"ticker": "999999"}]})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["target"]["name"] == "클래시스"
    assert [c["ticker"] for c in d["candidates"]] == ["A145020"]   # 못 찾은 건 빠진다
    assert any("999999" in w for w in d["warnings"])               # 사유는 경고로
    assert d["as_of"] == "2026-08-04"

    assert client.post("/api/peer/prefill", json={"candidates": []}).status_code == 422


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    import traceback
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    ok = skipped = 0
    for name, fn in fns:
        if "monkeypatch" in fn.__code__.co_varnames[:fn.__code__.co_argcount]:
            print(f"  skip {name} (pytest 픽스처 필요)"); skipped += 1; continue
        try:
            fn(); ok += 1; print(f"  ok  {name}")
        except Exception:
            print(f"  FAIL {name}"); traceback.print_exc()
    print(f"\n{ok}/{len(fns) - skipped} passed ({skipped} skipped)")
