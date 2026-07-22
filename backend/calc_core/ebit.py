"""EBIT 빌드 — 매출벡터 + 원가/판관비 드라이버 → EBIT 라인아이템.

매출은 revenue.py(top_down|bottom_up)에서 산출. 원가·판관비는 매출연동 비율(%) 또는
성격별 구성(원재료/노무비/경비/감가상각 등)으로 빌드. 여기선 비율 방식(일반)을 제공하고,
성격별 상세 빌드는 상위(assist/parsers)에서 매출원가·판관비 벡터로 합산해 넘길 수 있다.

산출: 매출, 매출원가, 매출총이익, 판관비, EBIT (모두 연도별 벡터).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EbitResult:
    revenue: list[float]
    cogs: list[float]
    gross_profit: list[float]
    sga: list[float]
    ebit: list[float]


def build_ebit_from_ratios(
    revenue: list[float],
    cogs_pct: list[float],
    sga_pct: list[float],
) -> EbitResult:
    """매출 × COGS% / SGA% 방식(일반). 각 리스트 동일 길이."""
    n = len(revenue)
    cogs = [revenue[t] * cogs_pct[t] for t in range(n)]
    gross = [revenue[t] - cogs[t] for t in range(n)]
    sga = [revenue[t] * sga_pct[t] for t in range(n)]
    ebit = [gross[t] - sga[t] for t in range(n)]
    return EbitResult(revenue=revenue, cogs=cogs, gross_profit=gross, sga=sga, ebit=ebit)


def build_ebit_from_lines(
    revenue: list[float],
    cogs: list[float],
    sga: list[float],
) -> EbitResult:
    """이미 산출된 매출원가·판관비 벡터(성격별 합산 등)로 EBIT 조립."""
    n = len(revenue)
    gross = [revenue[t] - cogs[t] for t in range(n)]
    ebit = [gross[t] - sga[t] for t in range(n)]
    return EbitResult(revenue=revenue, cogs=cogs, gross_profit=gross, sga=sga, ebit=ebit)
