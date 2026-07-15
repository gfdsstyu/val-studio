"""calc_core 도메인 모델 (Layer A: DCF 스파인).

순수 계산 코어라 외부 의존 없이 표준 dataclass 사용(pip 불필요). API 레이어에서
Pydantic 로 감싸 검증한다. 단위는 전부 백만원(KRW mn), 주식수만 주(shares).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DcfSpineInput:
    """DCF 스파인 입력 — 투영된 라인아이템 + 자본비용 + 브리지 항목.

    revenue/cogs/sga/dep_amort/capex/delta_nwc_cash_adj 는 명시적 추정기간(N년)
    길이의 동일 리스트. capex 는 양수 크기, delta_nwc_cash_adj 는 DCF 시트 현금조정
    부호(원본 row24 = -ΔWC) 그대로.
    """

    wacc: float
    terminal_growth: float
    revenue: list[float]
    cogs: list[float]
    sga: list[float]
    dep_amort: list[float]
    capex: list[float]
    delta_nwc_cash_adj: list[float]
    non_operating_assets: float
    net_debt: float
    shares_outstanding: int
    # 중간연도 할인 컨벤션. 기본 0.5,1.5,... ; terminal 은 마지막 명시연도 factor 로 할인.
    mid_year_periods: list[float] | None = None
    terminal_discount_period: float | None = None

    def n_years(self) -> int:
        return len(self.revenue)


@dataclass(frozen=True)
class DcfResult:
    """DCF 스파인 산출."""

    ebit: list[float]
    tax: list[float]
    noplat: list[float]
    fcff: list[float]
    pv_factor: list[float]
    pv_fcff: list[float]
    terminal_fcff: float
    terminal_value: float          # 할인 전 TV = FCFF_T/(WACC-g)
    terminal_value_pv: float       # 할인 후 TV
    pv_explicit_sum: float
    enterprise_value: float
    non_operating_assets: float
    net_debt: float
    equity_value: float
    shares_outstanding: int
    per_share: float
    sensitivity: dict = field(default_factory=dict)
