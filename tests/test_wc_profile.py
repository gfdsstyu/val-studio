"""WC 산업 프로파일 대조 — 회전기간 노출 + DSO/DIO 라벨 라우팅.

`out['wc']` 이 DSO(매출채권 회전일)·DIO(재고 회전일)를 산출해야 CostsSheet 의
산업 프로파일 카드가 동종 분포와 대조할 수 있다. 이전엔 net_working_capital·
delta_nwc_cash_adj 만 반환해 두 지표가 항상 null 이었다(silent dead metric).

`py -3.12 tests/test_wc_profile.py` 또는 pytest.
"""
from __future__ import annotations

from calc_core.wc import WcItem, dso_dio, project_working_capital


def _build():
    items = [
        WcItem("매출채권", 100, 1000, True),   # 100/1000*365 = 36.5 → DSO
        WcItem("재고자산", 200, 800, True),    # 200/800*365  = 91.25 → DIO
        WcItem("매입채무", 60, 600, False),    # 라우팅 대상 아님(채무≠채권)
    ]
    drv = {"매출채권": [1100.0], "재고자산": [880.0], "매입채무": [660.0]}
    return project_working_capital(items, drv, 240.0)


def test_turnover_days_surfaced():
    """엔진 내부 turnover_days() 가 결과에 노출된다(대조용 원천)."""
    r = _build()
    assert r.turnover_days_by_item["매출채권"] == 36.5
    assert r.turnover_days_by_item["재고자산"] == 91.25


def test_dso_dio_routes_by_label():
    """매출채권→DSO, 재고→DIO. 매입채무의 회전일에 오염되지 않는다."""
    dso, dio = dso_dio(_build().turnover_days_by_item)
    assert dso == 36.5   # 매입채무 turnover 도 우연히 36.5 지만 채권만 매칭
    assert dio == 91.25


def test_dso_dio_none_when_unmatched():
    """관용 라벨이 없으면 None(대조 불가를 정직하게 노출, 오탐 금지)."""
    dso, dio = dso_dio({"선급비용": 12.0, "미지급금": 5.0})
    assert dso is None and dio is None


def test_payable_alone_yields_no_dso():
    """부채만 있는 항목집합은 DSO/DIO 모두 None(채무≠채권 substring 오탐 방어)."""
    items = [WcItem("매입채무", 60, 600, False)]
    r = project_working_capital(items, {"매입채무": [660.0]}, 0.0)
    dso, dio = dso_dio(r.turnover_days_by_item)
    assert dso is None and dio is None


if __name__ == "__main__":
    test_turnover_days_surfaced()
    test_dso_dio_routes_by_label()
    test_dso_dio_none_when_unmatched()
    test_payable_alone_yields_no_dso()
    print("4 tests passed.")
