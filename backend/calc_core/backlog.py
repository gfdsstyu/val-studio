"""수주산업 매출 모델 — 수주잔고(backlog) → 매출 전환 → 정상화 마진.

수주산업(조선·건설·플랜트·방산)은 현재 손익이 아니라 **수주잔고의 매출 전환**이 DCF
출발점([[실전평가_상장사_사례집]] 한화오션). 계약 이행에 따라 backlog 가 매출로 인식되고,
신규 수주가 backlog 를 보충한다. 정상화 마진(steady-state)으로 EBIT 를 산출해 dcf 스파인
(revenue=매출, cogs=매출−EBIT, sga=0)에 주입한다.

핵심 규율(한화오션 칼럼):
  · 매출 전환은 backlog 소진율(conversion rate)로 — 잔고가 여러 해에 걸쳐 인식.
  · 신규 수주(new orders)가 backlog 를 보충 — 없으면 잔고 고갈로 매출 감소.
  · 미실현 대형수주(군함·잠수함)는 base 에 과도 선반영 금지 — 별도 시나리오/역DCF 점검.
  · 선수금·중도금 구조라 ΔNWC ≈ 0(일반 제조업보다 운전자본 부담 완만).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BacklogInputs:
    """수주산업 매출 모델 입력."""
    opening_backlog: float              # 기초 수주잔고(백만원)
    conversion_rate: float              # 연 backlog → 매출 전환율(0~1, 예 0.35 = 잔고의 35%)
    new_orders: list[float]             # 연도별 신규 수주(backlog 보충)
    normalized_margin: float            # 정상화 EBIT 마진(매출 대비, 예 0.12)
    years: int

    def __post_init__(self) -> None:
        if not (0.0 < self.conversion_rate <= 1.0):
            raise ValueError("conversion_rate 는 (0, 1]")
        if len(self.new_orders) != self.years:
            raise ValueError(f"new_orders 길이({len(self.new_orders)}) ≠ years({self.years})")


@dataclass
class BacklogResult:
    revenue: list[float]                # 연도별 매출(backlog 전환)
    ebit: list[float]                   # 연도별 EBIT(정상화 마진)
    closing_backlog: list[float]        # 연말 수주잔고
    warnings: list[str] = field(default_factory=list)


def project_backlog(inp: BacklogInputs) -> BacklogResult:
    """수주잔고 롤포워드 → 매출·EBIT 투영.

    각 연도: 매출 = 기초잔고 × 전환율. 연말잔고 = 기초잔고 − 매출 + 신규수주.
    (신규수주는 기말 보충이라 당해 매출 전환에 미포함 — 보수적.)
    """
    rev: list[float] = []
    ebit: list[float] = []
    closing: list[float] = []
    warnings: list[str] = []
    backlog = inp.opening_backlog
    for i in range(inp.years):
        sales = backlog * inp.conversion_rate
        rev.append(sales)
        ebit.append(sales * inp.normalized_margin)
        backlog = backlog - sales + inp.new_orders[i]
        closing.append(backlog)
        if backlog < 0:
            warnings.append(f"{i + 1}년차 수주잔고 소진(음수 {backlog:,.0f}) — "
                            f"신규수주 가정 재검토")
    # 잔고 고갈 추세 경고: 마지막 잔고가 기초의 절반 미만이면 매출 지속성 의심
    if inp.opening_backlog > 0 and closing[-1] < inp.opening_backlog * 0.5:
        warnings.append(
            f"수주잔고가 기초 대비 {closing[-1] / inp.opening_backlog:.0%}로 감소 — "
            f"매출 지속성 위해 신규수주 회복 필요(터미널 정상상태 점검)")
    return BacklogResult(revenue=rev, ebit=ebit, closing_backlog=closing,
                         warnings=warnings)


def to_spine_lines(result: BacklogResult) -> dict[str, list[float]]:
    """backlog 산출 → dcf 스파인 라인(revenue=매출, cogs=매출−EBIT, sga=0).

    EBIT = 매출 − cogs − sga 이므로 cogs = 매출 − EBIT, sga = 0 으로 두면 스파인 EBIT
    가 정상화 마진과 일치. 선수금 구조이므로 ΔNWC ≈ 0(호출자가 delta_nwc_cash_adj=0).
    """
    return {
        "revenue": list(result.revenue),
        "cogs": [result.revenue[i] - result.ebit[i] for i in range(len(result.revenue))],
        "sga": [0.0] * len(result.revenue),
    }
