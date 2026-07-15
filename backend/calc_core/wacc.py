"""WACC — CAPM 빌드업 + 자본구조 (표준 방법론, 삼일/Deloitte 교육자료 근거).

비올 원본 WACC 시트는 채권수익률 매트릭스·베타 회귀가 뒤섞인 연구시트라 비트복제 대신
표준 빌드업을 깨끗한 함수로 구현한다. 최종 WACC 가 DCF 스파인의 자본비용으로 들어간다.

빌드업(Deloitte VKG / 한공회 가이던스 방법론)::

    Unlever(Hamada):  βu = βL / (1 + (1−t)·D/E)          # 유사기업 관측 βL → 무부채 βu
    Relever:          βL' = βu · (1 + (1−t')·D/E')        # 대상회사 자본구조로 재부채
    Cost of Equity:   Ke = Rf + βL'·ERP + Size + CRP + CSRP
    Cost of Debt:     Kd(after-tax) = Kd(pre-tax)·(1−t')
    WACC:             WACC = We·Ke + Wd·Kd(after-tax)     # We=E/(D+E), Wd=D/(D+E)

용어:
  Rf  무위험이자율(국고채)          ERP 시장위험프리미엄(한공회 가이던스 7~9%)
  Size 규모프리미엄(Kroll deciles)   CRP 국가위험프리미엄(Damodaran)
  CSRP 기업특유위험                  t   법인세 유효세율
"""
from __future__ import annotations

from dataclasses import dataclass


def unlever_beta(levered_beta: float, debt_to_equity: float, tax_rate: float) -> float:
    """Hamada 무부채화: βu = βL / (1 + (1−t)·D/E)."""
    return levered_beta / (1.0 + (1.0 - tax_rate) * debt_to_equity)


def relever_beta(unlevered_beta: float, debt_to_equity: float, tax_rate: float) -> float:
    """Hamada 재부채화: βL = βu · (1 + (1−t)·D/E)."""
    return unlevered_beta * (1.0 + (1.0 - tax_rate) * debt_to_equity)


def peer_unlevered_beta(
    peers: list[tuple[float, float, float]]
) -> float:
    """유사기업 리스트 [(levered_beta, D/E, tax_rate), ...] → 평균 무부채 베타(median 권장).

    비올 방법론: 각 peer 를 무부채화 후 중앙값/평균. 여기선 평균(단순), 상위에서 median 선택 가능.
    """
    if not peers:
        raise ValueError("peers 가 비어 있음")
    us = [unlever_beta(b, de, t) for (b, de, t) in peers]
    return sum(us) / len(us)


@dataclass(frozen=True)
class WaccInputs:
    risk_free: float               # Rf
    equity_risk_premium: float     # ERP (MRP)
    unlevered_beta: float          # 유사기업 무부채 베타
    target_debt_to_equity: float   # 대상회사 목표 D/E
    tax_rate: float                # 유효세율 t
    pre_tax_cost_of_debt: float    # Kd(pre-tax), 신용등급 회사채 수익률
    size_premium: float = 0.0      # CSRP size (Kroll)
    country_risk_premium: float = 0.0
    company_specific_risk: float = 0.0


@dataclass(frozen=True)
class WaccResult:
    relevered_beta: float
    cost_of_equity: float
    after_tax_cost_of_debt: float
    equity_weight: float
    debt_weight: float
    wacc: float


def build_wacc(inp: WaccInputs) -> WaccResult:
    """CAPM 빌드업 → WACC."""
    de = inp.target_debt_to_equity
    beta_l = relever_beta(inp.unlevered_beta, de, inp.tax_rate)
    ke = (
        inp.risk_free
        + beta_l * inp.equity_risk_premium
        + inp.size_premium
        + inp.country_risk_premium
        + inp.company_specific_risk
    )
    kd_at = inp.pre_tax_cost_of_debt * (1.0 - inp.tax_rate)
    # D/E → 비중: E/(D+E) = 1/(1+D/E), D/(D+E) = D/E/(1+D/E)
    we = 1.0 / (1.0 + de)
    wd = de / (1.0 + de)
    wacc = we * ke + wd * kd_at
    return WaccResult(
        relevered_beta=beta_l,
        cost_of_equity=ke,
        after_tax_cost_of_debt=kd_at,
        equity_weight=we,
        debt_weight=wd,
        wacc=wacc,
    )
