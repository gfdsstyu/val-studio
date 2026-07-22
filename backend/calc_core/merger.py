"""합병·주식교환 평가 — 자본시장법 기준주가·본질가치·교환비율.

방법론 근거: [[합병_주식교환_방법론]] (두산로보틱스↔밥캣 실측). DCF 와 **별개의
규제 산식** 트랙:
  상장   → 기준주가 = 산술평균(1개월 VWAP, 1주일 VWAP, 최근일 종가)
  비상장 → 본질가치 = (자산가치×1 + 수익가치×1.5) / 2.5
DCF(calc_core.dcf)는 수익가치 산정 또는 교차검토에 사용.

골든(두산, 기준일 2024-07-10): 로보틱스 mean(82,859·77,482·80,000)=80,114원,
밥캣 50,612원 → 교환비율 50,612/80,114 ≈ 0.6318.
"""
from __future__ import annotations

from dataclasses import dataclass

# 자본시장법 시행령 비상장 본질가치 가중치(자산 1 : 수익 1.5).
ASSET_WEIGHT = 1.0
EARNINGS_WEIGHT = 1.5


def vwap(prices: list[float], volumes: list[float]) -> float:
    """거래량가중산술평균종가(VWAP) = Σ(종가×거래량)/Σ거래량. 기간(1개월·1주일)별
    입력은 호출측이 자름. 거래량 합 0 이면 ValueError(정지 종목 등 — 단순평균으로
    조용히 대체하지 않음)."""
    if len(prices) != len(volumes):
        raise ValueError(f"종가 {len(prices)}·거래량 {len(volumes)} 길이 불일치")
    tv = sum(volumes)
    if tv <= 0:
        raise ValueError("거래량 합 0 — VWAP 산정 불가(거래정지 여부 확인)")
    return sum(p * v for p, v in zip(prices, volumes)) / tv


def base_share_price(vwap_1m: float, vwap_1w: float, latest_close: float) -> float:
    """상장법인 기준주가 = 산술평균(1개월 VWAP, 1주일 VWAP, 최근일 종가)."""
    return (vwap_1m + vwap_1w + latest_close) / 3.0


def intrinsic_value(asset_value_ps: float, earnings_value_ps: float) -> float:
    """비상장법인 본질가치/주 = (자산가치×1 + 수익가치×1.5) / 2.5.

    자산가치 = 순자산 공정가치/발행주식수, 수익가치 = 추정이익 기반(DCF/이익할인 —
    calc_core.dcf 의 주당가치를 여기에 투입)."""
    return ((ASSET_WEIGHT * asset_value_ps + EARNINGS_WEIGHT * earnings_value_ps)
            / (ASSET_WEIGHT + EARNINGS_WEIGHT))


@dataclass(frozen=True)
class ExchangeTerms:
    """주식교환 조건 — 대상 1주당 취득회사 주식 몇 주."""
    acquirer_value_ps: float        # 취득(모)회사 주당 평가액
    target_value_ps: float          # 대상(자)회사 주당 평가액

    @property
    def ratio(self) -> float:
        """교환비율 = 대상 주당가액 / 취득 주당가액 (두산: 0.6318)."""
        if self.acquirer_value_ps <= 0:
            raise ValueError("취득회사 주당가액 ≤ 0 — 교환비율 산정 불가")
        return self.target_value_ps / self.acquirer_value_ps
