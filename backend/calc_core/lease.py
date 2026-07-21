"""K-IFRS 1116 리스 스케줄 — 리스료 → 이자·원금 분리 + 사용권자산 감가상각.

참고 모델/실무 DCF 템플릿의 리스 처리. 하나의 리스료가 셋으로 갈라진다:
  ① 사용권자산 감가상각(정액) → D&A 가산(FCFF add-back)  → fa.py dep_amort 에 합류
  ② 리스이자 = 기초리스부채 × 리스이자율          → 금융비용(EBIT 아래)
  ③ 원금상환 = 리스료 − 이자                       → financing(FCFF 밖)
  ④ 리스부채 잔액                                   → 순차입부채(EV→지분 브리지)

입력 2모드:
  - annual_payment(연 리스료) + term + rate → 리스부채 = PV(리스료)
  - initial_liability(리스부채) + term + rate → 연 리스료 = 균등상환 연금
사용권자산 = 리스부채(초기, 관용) 또는 rou_asset 지정. 정액 감가상각.
"""
from __future__ import annotations

from dataclasses import dataclass


def annuity_pv(payment: float, term: int, rate: float) -> float:
    """균등 연 리스료의 현재가치 = payment × [1−(1+r)^−n]/r (기말지급)."""
    if rate == 0:
        return payment * term
    return payment * (1.0 - (1.0 + rate) ** (-term)) / rate


def annuity_payment(liability: float, term: int, rate: float) -> float:
    """리스부채 → 균등 연 리스료(원리금균등)."""
    if rate == 0:
        return liability / term if term else 0.0
    return liability * rate / (1.0 - (1.0 + rate) ** (-term))


@dataclass(frozen=True)
class LeaseResult:
    liability_open: list[float]      # 기초 리스부채
    interest: list[float]            # 리스이자(금융비용)
    principal: list[float]           # 원금상환(financing)
    payment: list[float]             # 리스료
    liability_close: list[float]     # 기말 리스부채(→순차입부채)
    rou_depreciation: list[float]    # 사용권자산 감가상각(→D&A)


def lease_schedule(
    term: int,
    discount_rate: float,
    *,
    annual_payment: float | None = None,
    initial_liability: float | None = None,
    rou_asset: float | None = None,
) -> LeaseResult:
    """리스 상각표. annual_payment 또는 initial_liability 중 하나 필수.

    ROU 감가상각 = rou_asset(기본=초기 리스부채) / term (정액). 기말지급 가정.
    """
    if term <= 0:
        raise ValueError("리스기간(term) > 0")
    if initial_liability is None and annual_payment is None:
        raise ValueError("annual_payment 또는 initial_liability 필요")
    r = discount_rate
    if initial_liability is None:
        initial_liability = annuity_pv(annual_payment, term, r)
    if annual_payment is None:
        annual_payment = annuity_payment(initial_liability, term, r)
    rou = initial_liability if rou_asset is None else rou_asset
    rou_dep = rou / term

    opens, ints, prins, pays, closes, deps = [], [], [], [], [], []
    liab = initial_liability
    for _ in range(term):
        interest = liab * r
        principal = annual_payment - interest
        close = liab - principal
        opens.append(liab); ints.append(interest); prins.append(principal)
        pays.append(annual_payment); closes.append(close); deps.append(rou_dep)
        liab = close
    return LeaseResult(liability_open=opens, interest=ints, principal=prins,
                       payment=pays, liability_close=closes, rou_depreciation=deps)
