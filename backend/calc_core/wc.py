"""운전자본(Working Capital) — 회전율 기반 투영 → ΔNWC.

비올 WC 시트 로직:
  회전율   = driver / 잔액              (예: 매출채권 회전율 = 매출 / 매출채권)
  회전기간 = 365 / 회전율               (일수)
  투영 잔액 = driver_투영 / 회전율      (회전기간을 마지막 실적으로 고정)
  순운전자본 = Σ운전자산 − Σ운전부채
  ΔNWC(현금흐름) = −(순운전자본_t − 순운전자본_{t-1})   # 증가 시 현금유출(−)

각 WC 항목은 특정 driver(매출 또는 매출원가)에 연동된다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WcItem:
    """운전자본 항목 정의."""

    name: str
    base_balance: float   # 마지막 실적 잔액
    base_driver: float    # 마지막 실적 driver(매출 or 매출원가)
    is_asset: bool        # True=운전자산(채권·재고), False=운전부채(매입채무)

    def turnover_days(self) -> float:
        """회전기간(일) = 365 / (driver/balance)."""
        if self.base_driver == 0:
            return 0.0
        turnover = self.base_driver / self.base_balance
        return 365.0 / turnover


def project_balance(item: WcItem, projected_driver: float) -> float:
    """투영 driver → 투영 잔액 (회전기간 고정): 잔액 = driver / 회전율 = driver·days/365."""
    days = item.turnover_days()
    return projected_driver * days / 365.0


@dataclass(frozen=True)
class WcResult:
    net_working_capital: list[float]   # 각 투영연도 순운전자본
    delta_nwc_cash_adj: list[float]    # FCFF 현금조정(−ΔNWC), DCF row24 부호


def project_working_capital(
    items: list[WcItem],
    driver_by_item: dict[str, list[float]],
    base_net_working_capital: float,
) -> WcResult:
    """항목별 투영 driver 로 순운전자본·ΔNWC 계산.

    driver_by_item: {item.name: [투영연도별 driver]} (매출 or 매출원가 벡터).
    base_net_working_capital: 마지막 실적 순운전자본(ΔNWC 첫 해 기준).
    """
    n = len(next(iter(driver_by_item.values())))
    nwc: list[float] = []
    for t in range(n):
        assets = 0.0
        liabs = 0.0
        for it in items:
            bal = project_balance(it, driver_by_item[it.name][t])
            if it.is_asset:
                assets += bal
            else:
                liabs += bal
        nwc.append(assets - liabs)

    delta: list[float] = []
    prev = base_net_working_capital
    for t in range(n):
        delta.append(-(nwc[t] - prev))  # 증가 → 현금유출(−)
        prev = nwc[t]
    return WcResult(net_working_capital=nwc, delta_nwc_cash_adj=delta)


def normalized_wc_ratio(net_working_capital_last: float, sales_last: float) -> float | None:
    """정규화 운전자본비율 = 추정말 순운전자본 / 추정말 매출 (터미널 WC 재조정 시드).

    dcf.terminal_wc_ratio 에 주입 → 터미널 ΔWC = 추정말매출 × g × 이 비율(정본 공식).
    회전기간이 추정말에 안정화됐다는 가정. 매출≤0 이면 None(산출 불가).
    """
    if sales_last <= 0:
        return None
    return net_working_capital_last / sales_last
