"""FS 계정 분류기 테스트 — 순서 규칙(매출원가<매출)·NOA/IBD·uncertain.

stdlib: `python tests/test_fs_mapper.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ingest.fs_mapper import classify, classify_all  # noqa: E402


def test_cogs_before_sales():
    # 부분문자열 함정: '매출원가'가 '매출'(Sales)보다 먼저 매칭돼야 함
    assert classify("매출원가", "PL").bucket == "COGS"
    assert classify("매출액", "PL").bucket == "Sales"
    assert classify("상품매출", "PL").bucket == "Sales"


def test_pl_buckets():
    assert classify("판매비와관리비", "PL").bucket == "SGA"
    assert classify("종업원급여", "PL").bucket == "SGA"
    assert classify("이자비용", "PL").bucket == "NonOp(영업외)"
    assert classify("법인세비용", "PL").bucket == "NonOp(영업외)"


def test_bs_noa_ibd_bridge():
    # EV→지분 브리지 핵심: 차입금=IBD, 투자자산=NOA
    assert classify("단기차입금", "BS").bucket == "IBD(이자부부채)"
    assert classify("사채", "BS").bucket == "IBD(이자부부채)"
    assert classify("투자부동산", "BS").bucket == "NOA(비영업자산)"
    assert classify("매출채권", "BS").bucket == "WC(운전자본)"
    assert classify("유형자산", "BS").bucket == "FA(유형자산)"
    assert classify("이익잉여금", "BS").bucket == "EQU(자본)"


def test_cash_low_confidence_with_note():
    # 현금 = NOA 이나 영업현금 분리 필요 → 낮은 confidence + 검토 노트
    c = classify("현금및현금성자산", "BS")
    assert c.bucket == "NOA(비영업자산)"
    assert c.confidence < 0.7 and c.note and "영업현금" in c.note


def test_uncertain_on_no_match():
    # 무매칭 = 임의 추측 금지 → uncertain(유저 분류 필요)
    c = classify("듣도보도못한계정", "BS")
    assert c.bucket is None and c.uncertain and c.confidence == 0.0


def test_whitespace_tolerance():
    assert classify("판매비와 관리비", "PL").bucket == "SGA"   # 공백 흔들림 흡수


def test_classify_all():
    res = classify_all(["매출액", "매출원가", "판매비와관리비"], "PL")
    assert [r.bucket for r in res] == ["Sales", "COGS", "SGA"]


def test_bad_statement_raises():
    try:
        classify("매출", "CF")
        raise AssertionError("잘못된 statement 인데 통과")
    except ValueError:
        pass


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
