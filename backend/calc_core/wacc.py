"""WACC — CAPM 빌드업 + 자본구조 (표준 방법론, 회계법인 교육자료 근거).

비올 원본 WACC 시트는 채권수익률 매트릭스·베타 회귀가 뒤섞인 연구시트라 비트복제 대신
표준 빌드업을 깨끗한 함수로 구현한다. 최종 WACC 가 DCF 스파인의 자본비용으로 들어간다.

빌드업(감사인 검토 방법론 / 한공회 가이던스)::

    Unlever(Hamada):  βu = βL / (1 + (1−t)·D/E)          # 유사기업 관측 βL → 무부채 βu
    Relever:          βL' = βu · (1 + (1−t')·D/E')        # 대상회사 자본구조로 재부채
    Cost of Equity:   Ke = Rf + βL'·MRP + Size + CRP + CSRP
    Cost of Debt:     Kd(after-tax) = Kd(pre-tax)·(1−t')
    WACC:             WACC = We·Ke + Wd·Kd(after-tax)     # We=E/(D+E), Wd=D/(D+E)

용어:
  Rf  무위험이자율(국고채)          MRP 시장위험프리미엄(한공회 가이던스 7~9%)
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


# Kroll(구 Duff & Phelps) 2019 CRSP Deciles Size Premium — 근거: 감사인 검토 방법론 자료
# (감사인검토_WACC방법론.md). (시가총액 하한 $M, decile 라벨, size premium).
# ⚠️ 실제 평가 시 반드시 당해연도 Valuation Handbook 값으로 갱신할 것(예시 고정치).
_KROLL_2019_DECILES: list[tuple[float, str, float]] = [
    (13456.0, "1 (Largest)", 0.0052),
    (7254.0,  "2",           0.0081),
    (4504.0,  "3 (Mid 3-5)", 0.0085),
    (2992.0,  "4",           0.0128),
    (1960.0,  "5",           0.0150),
    (1292.0,  "6 (Low 6-8)", 0.0158),
    (728.0,   "7",           0.0180),
    (325.0,   "8",           0.0246),
    (0.0,     "9-10 (Micro)", 0.0522),
]


def kroll_size_decile(market_cap_musd: float) -> tuple[str, float]:
    """시가총액($백만) → (decile 라벨, size premium). 큰 회사일수록 낮은 프리미엄.

    자유입력 size_premium 대신 근거 있는 decile 룩업으로 provenance 를 강제한다.
    """
    if market_cap_musd < 0:
        raise ValueError("시가총액은 음수일 수 없음")
    for floor, label, premium in _KROLL_2019_DECILES:
        if market_cap_musd >= floor:
            return label, premium
    return _KROLL_2019_DECILES[-1][1], _KROLL_2019_DECILES[-1][2]


def kroll_size_premium(market_cap_musd: float) -> float:
    """시가총액($백만) → size premium (Kroll decile). kroll_size_decile 의 편의 래퍼."""
    return kroll_size_decile(market_cap_musd)[1]


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
    market_risk_premium: float     # MRP (MRP)
    unlevered_beta: float          # 유사기업 무부채 베타
    target_debt_to_equity: float   # 대상회사 목표 D/E
    tax_rate: float                # 유효세율 t
    pre_tax_cost_of_debt: float    # Kd(pre-tax), 신용등급 회사채 수익률
    size_premium: float = 0.0      # CSRP size (Kroll)
    country_risk_premium: float = 0.0
    company_specific_risk: float = 0.0
    # β provenance (감사 추적) — 근거: docs/reference/베타_Bloomberg_vs_KICPA.md.
    # β 는 숫자가 아니라 "어느 시장의 체계적위험인가"의 선택이므로 출처·기준시장을 남긴다.
    beta_source: str | None = None   # 'bloomberg' | 'kicpa'
    beta_market: str | None = None   # 'SP500' | 'KOSPI' | 'KOSDAQ'
    beta_adjusted: bool | None = None  # Bloomberg Adjusted(0.67·raw+0.33) 여부
    # ↑ 조정베타 계산 헬퍼·주가 회귀는 ingest/price_client.py(β 회귀가 있는 곳이 canonical).
    # MRP provenance — β 와 MRP 는 같은 시장에서 와야 한다(KICPA β ↔ KICPA MRP).
    mrp_source: str | None = None    # 'kicpa' | 'damodaran' | 'dfas' ...
    mrp_market: str | None = None    # 'SP500' | 'KOSPI' — beta_market 와 일치해야 함


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
        + beta_l * inp.market_risk_premium
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
