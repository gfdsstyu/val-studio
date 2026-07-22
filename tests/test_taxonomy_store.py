"""DART 택사노미 스토어 테스트 — 라벨·부호·계층·버킷 앵커·판단 표면화.

stdlib: `python tests/test_taxonomy_store.py`. backend/data/dart_taxonomy.json 이
있어야 한다(빌드: scripts/build_taxonomy_store.py). 없으면 전 테스트 skip.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

_DATA = ROOT / "backend" / "data" / "dart_taxonomy.json"
_HAVE = _DATA.is_file()

if _HAVE:
    from ingest import taxonomy_store as T  # noqa: E402


def _skip_if_no_data():
    if not _HAVE:
        print("SKIP: dart_taxonomy.json 없음")
        return True
    return False


def test_label_lookup():
    if _skip_if_no_data():
        return
    assert T.label("ifrs-full_Revenue") == "수익"
    assert T.label("ifrs-full_Revenue", "en") == "Revenue"
    assert T.label("존재하지_않는_요소") is None


def test_entry_carries_balance_and_period():
    if _skip_if_no_data():
        return
    e = T.entry("ifrs-full_CostOfSales")
    assert e is not None
    assert e.balance == "debit"
    assert e.period == "duration"


def test_is_under_ancestry():
    if _skip_if_no_data():
        return
    # 제품매출액은 수익의 후손
    assert T.is_under("dart_RevenueFromSaleOfGoodsProduct", "ifrs-full_Revenue")
    # 자기 자신은 자신의 조상으로 취급(포함관계)
    assert T.is_under("ifrs-full_Revenue", "ifrs-full_Revenue")
    # 매출원가는 수익의 후손이 아니다
    assert not T.is_under("ifrs-full_CostOfSales", "ifrs-full_Revenue")


def test_calc_weight_sign():
    if _skip_if_no_data():
        return
    # 정부보조금(현금및현금성자산)은 차감 → weight -1
    assert T.calc_weight("dart_GovernmentGrantsCashAndCashEquivalentsGross") == -1.0
    # 유동자산은 자산 합계에 가산 → +1
    assert T.calc_weight("ifrs-full_CurrentAssets") == 1.0


def test_cash_flow_section():
    if _skip_if_no_data():
        return
    assert T.cash_flow_section("dart_PurchaseOfMachinery") == "investing"
    assert T.cash_flow_section("ifrs-full_CashAndCashEquivalents") is None


def test_bucket_hint_settled():
    """두 층(회계분류·평가재분류)이 일치하는 계정은 결정론 확정(judgment=False)."""
    if _skip_if_no_data():
        return
    assert T.bucket_hint("ifrs-full_Revenue", "PL").bucket == "Sales"
    assert T.bucket_hint("ifrs-full_CostOfSales", "PL").bucket == "COGS"
    h = T.bucket_hint("ifrs-full_ShorttermBorrowings", "BS")
    assert h.bucket == "IBD(이자부부채)"
    assert h.judgment is False
    assert T.bucket_hint("ifrs-full_Inventories", "BS").bucket == "WC(운전자본)"
    assert T.bucket_hint("ifrs-full_PropertyPlantAndEquipment", "BS").bucket == "FA(유형자산)"


def test_bucket_hint_judgment_surfaced():
    """평가목적 재분류가 판단 사항인 계정은 제안+judgment=True(자동확정 금지 신호)."""
    if _skip_if_no_data():
        return
    for elem in (
        "ifrs-full_CashAndCashEquivalents",      # 초과현금만 NOA
        "ifrs-full_CurrentLeaseLiabilities",     # 리스부채 순차입금 포함 여부
        "dart_ShortTermAccruedExpenses",         # 미지급비용 영업성/금융성
        "dart_ShortTermLoans",                   # 대여금 영업 관련성
    ):
        h = T.bucket_hint(elem, "BS")
        assert h.bucket is not None, elem
        assert h.judgment is True, elem
        assert h.note, elem


def test_presentation_bundle_not_anchored():
    """표시목적 묶음 노드(매입채무 및 기타 유동 채무)는 버킷을 반환하지 않는다.

    이 노드 밑에는 매입채무(WC)·차입금(IBD)·미지급비용(판단)이 섞여 있어, 후손 전체를
    한 버킷으로 빨아들이면 순차입금이 틀어진다. 그래서 앵커로 쓰지 않는다.
    """
    if _skip_if_no_data():
        return
    assert T.bucket_hint("ifrs-full_TradeAndOtherCurrentPayables", "BS").bucket is None


def test_borrowing_not_swept_into_wc():
    """묶음 밑의 차입금이 WC 로 새지 않고 IBD 로 잡히는지(회귀 방지)."""
    if _skip_if_no_data():
        return
    assert T.bucket_hint("dart_CurrentBondsIssued", "BS").bucket == "IBD(이자부부채)"
    assert T.bucket_hint("dart_CurrentPortionOfConvertibleBonds", "BS").bucket == "IBD(이자부부채)"


def test_unmapped_returns_none_for_fallback():
    if _skip_if_no_data():
        return
    # 이연법인세자산: 택사노미 앵커 무매칭 → None(호출자가 키워드 폴백)
    assert T.bucket_hint("ifrs-full_DeferredTaxAssets", "BS").bucket is None
    # 미수록 요소도 None
    assert T.bucket_hint("회사임의계정", "BS").bucket is None


def test_meta_provenance():
    if _skip_if_no_data():
        return
    m = T.meta()
    assert "source" in m
    assert m["counts"]["elements"] > 9000


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok {_name}")
    print("all passed" if _HAVE else "skipped (no data)")
