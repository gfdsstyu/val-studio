"""Backsolve/OPM — 비상장주식 공정가치: breakpoint 워터폴 배분 + 앵커 역산.

공정가치 트랙([[공정가치_측정_FV]])의 첫 계산코어. 방법론 근거: IFRS Issue Paper
201/411/412 — DCF가 유효하지 않은(매출 미실현) Stage 1 기업의 보통주 가치를
최근 우선주 라운드 거래가액(앵커)에서 역산한다.

핵심 사상:
  - 청산·매각 시 배분권리가 달라지는 지점 = **breakpoint**. 각 breakpoint 를
    행사가격으로 하는 Black-Scholes Call 로 총 지분가치를 구간 분해한다.
  - 구간 [K_lo, K_hi) 에서 지분율 s 를 받는 클래스의 가치
    = s × (Call(K_lo) − Call(K_hi))   (마지막 구간은 Call(K_hi)=0)
  - **Backsolve**: 앵커 클래스(최근 라운드)의 배분가치 == 발행가액이 되는
    총 지분 FV 를 이분탐색으로 역산(시행착오법의 결정론 구현). 각 클래스
    배분가치는 총 지분 FV 에 단조증가하므로 이분탐색이 유효하다.

전제(411): 앵커 거래가액 = 공정가액. Arm's Length 가 아니거나 평가일과 시점이
다르면 조정 필요 — checks.check_backsolve_anchor 게이트가 잡는다. 노드별 행사가격이
변동하는 RCPS/CPS(청산 vs 전환 선택)는 이항/몬테카를로 필요 — 미구현, 명시적 보류.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class OpmParams:
    """OPM 공통 입력(412 Schedule 1). 기간=예상 유동성 이벤트(IPO 등)까지."""
    term_years: float
    volatility: float               # 유사 상장 peer 변동성 참고(412)
    risk_free: float
    dividend_yield: float = 0.0


def bs_call(s: float, k: float, p: OpmParams) -> float:
    """Black-Scholes-Merton 유럽형 콜. K≤0 이면 전체 지분(=S·e^{-qT})."""
    if s <= 0:
        return 0.0
    if k <= 0:
        return s * math.exp(-p.dividend_yield * p.term_years)
    v = max(p.volatility, 1e-12)
    sq = v * math.sqrt(p.term_years)
    d1 = (math.log(s / k) + (p.risk_free - p.dividend_yield + v * v / 2.0)
          * p.term_years) / sq
    d2 = d1 - sq
    ncdf = lambda x: 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))  # noqa: E731
    return (s * math.exp(-p.dividend_yield * p.term_years) * ncdf(d1)
            - k * math.exp(-p.risk_free * p.term_years) * ncdf(d2))


@dataclass(frozen=True)
class WaterfallTranche:
    """배분 구간 [lower, upper). upper=None 이면 최상단(무한) 구간.

    shares: 클래스명 → 이 구간 배분율(합=1). 412 예제:
      (0, 1.2M, {"preferred": 1.0}) / (1.2M, 2.4M, {"common": 1.0}) /
      (2.4M, None, {"preferred": 0.1, "common": 0.9})
    """
    lower: float
    upper: float | None
    shares: dict[str, float] = field(default_factory=dict)


def _validate_tranches(tranches: list[WaterfallTranche]) -> None:
    if not tranches:
        raise ValueError("워터폴 트랜치가 비어 있음")
    if tranches[0].lower != 0.0:
        raise ValueError("첫 트랜치는 lower=0 이어야 함(전체 배분 포괄)")
    for i, t in enumerate(tranches):
        total = sum(t.shares.values())
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"트랜치 {i} 배분율 합 {total} ≠ 1 — 임의 정규화 금지")
        if t.upper is not None and t.upper <= t.lower:
            raise ValueError(f"트랜치 {i} 구간 역전 lower={t.lower} upper={t.upper}")
        if i + 1 < len(tranches):
            nxt = tranches[i + 1]
            if t.upper is None or abs(nxt.lower - t.upper) > 1e-9:
                raise ValueError(f"트랜치 {i}→{i+1} 구간 불연속(빈틈/중첩 금지)")
    if tranches[-1].upper is not None:
        raise ValueError("마지막 트랜치는 upper=None(무한 구간)이어야 함")


def allocate_equity(equity_value: float, tranches: list[WaterfallTranche],
                    params: OpmParams) -> dict[str, float]:
    """총 지분 FV 를 breakpoint 워터폴로 클래스별 배분(옵션가치 기준).

    항등식: Σ클래스 배분 = bs_call(E, 0) (= q=0 이면 E). 구간 분해가 전체를
    남김없이 덮으므로 구성상 성립 — 외부 분해 검증은 checks.check_cb_decomposition 계열.
    """
    _validate_tranches(tranches)
    out: dict[str, float] = {}
    for t in tranches:
        lo_call = bs_call(equity_value, t.lower, params)
        hi_call = bs_call(equity_value, t.upper, params) if t.upper is not None else 0.0
        slice_value = lo_call - hi_call
        for cls, share in t.shares.items():
            out[cls] = out.get(cls, 0.0) + share * slice_value
    return out


@dataclass(frozen=True)
class BacksolveResult:
    equity_value: float                 # 역산된 총 지분 FV
    allocations: dict[str, float]       # 클래스별 배분가치
    anchor_class: str
    anchor_value: float                 # 앵커(최근 라운드 발행가액)
    anchor_error: float                 # 수렴 잔차(배분 − 앵커)


def backsolve_equity(tranches: list[WaterfallTranche], params: OpmParams,
                     anchor_class: str, anchor_value: float,
                     *, hi: float | None = None, tol: float = 1e-6,
                     max_iter: int = 200) -> BacksolveResult:
    """앵커 클래스 배분가치 == 발행가액이 되는 총 지분 FV 이분탐색(412 Step 5).

    시행착오법(trial and error)의 결정론 구현. 배분가치는 E 에 단조증가
    (∂slice/∂E = N(d1(K_lo)) − N(d1(K_hi)) > 0)이므로 이분탐색이 항상 수렴.
    """
    _validate_tranches(tranches)
    if anchor_value <= 0:
        raise ValueError("앵커 발행가액은 양수여야 함")
    if not any(anchor_class in t.shares for t in tranches):
        raise ValueError(f"앵커 클래스 '{anchor_class}' 가 워터폴에 없음")

    lo = 1e-9
    # 상한 자동 확장: 앵커 배분이 anchor_value 를 넘는 E 를 찾을 때까지 배증
    high = hi if hi is not None else max(anchor_value * 4.0, 1.0)
    for _ in range(200):
        if allocate_equity(high, tranches, params).get(anchor_class, 0.0) >= anchor_value:
            break
        high *= 2.0
    else:
        raise ValueError("앵커 배분이 발행가액에 도달하지 못함 — 워터폴/앵커 확인")

    for _ in range(max_iter):
        mid = (lo + high) / 2.0
        got = allocate_equity(mid, tranches, params).get(anchor_class, 0.0)
        if abs(got - anchor_value) <= tol * max(anchor_value, 1.0):
            break
        if got < anchor_value:
            lo = mid
        else:
            high = mid
    mid = (lo + high) / 2.0
    alloc = allocate_equity(mid, tranches, params)
    return BacksolveResult(
        equity_value=mid,
        allocations=alloc,
        anchor_class=anchor_class,
        anchor_value=anchor_value,
        anchor_error=alloc.get(anchor_class, 0.0) - anchor_value,
    )


def common_per_share(result: BacksolveResult, common_class: str,
                     shares_outstanding: float) -> float:
    """보통주 주당가치 = 배분가치 ÷ 발행주식수(411 사례의 최종 산출물)."""
    if shares_outstanding <= 0:
        raise ValueError("발행주식수는 양수여야 함")
    return result.allocations.get(common_class, 0.0) / shares_outstanding


# ═══════════════ RCPS/CPS 노드변동 행사가격 이항 격자 (Issue Paper 411) ═══════════════
@dataclass(frozen=True)
class PreferredClass:
    """전환상환우선주(RCPS)/전환우선주(CPS) 1클래스.

    각 노드에서 우선주는 **청산 vs 전환**을 선택 — 행사가격(전환 임계 기업가치)이
    노드별로 동적 변동하므로 BSM 폐형 부적합, 이항 격자로 backward induction(411).
      · liquidation_preference: 유동성 이벤트 시 우선 수령액(투자금 × 청산배수).
        RCPS 상환권도 하방보장이라 이 값에 통합(상환보장액 = max 로 반영).
      · conversion_fraction: 전환 시 받는 **전체 기업가치 대비 지분율**(0~1).
    """
    name: str
    liquidation_preference: float
    conversion_fraction: float

    def payoff(self, enterprise_value: float) -> float:
        """유동성 노드 페이오프 = max(청산우선권, 전환 지분가치). 411 노드변동의 핵심."""
        return max(self.liquidation_preference,
                   enterprise_value * self.conversion_fraction)


@dataclass(frozen=True)
class RcpsResult:
    preferred_value: float          # 우선주 현재가치(격자 backward induction)
    common_value: float             # 보통주 잔여가치 = V0 − 우선주
    conversion_boundary: float | None  # 전환이 청산보다 유리해지는 임계 기업가치(만기)


def price_rcps(enterprise_value: float, pref: PreferredClass, params: OpmParams,
               *, steps: int = 300, american: bool = False) -> RcpsResult:
    """CRR 격자로 RCPS/CPS 우선주 현재가치 + 보통주 잔여 (411 노드변동 모델).

    기업가치 V 가 위험중립 GBM 격자로 진화. 만기(예상 exit) 노드에서 우선주 페이오프
    = max(청산, 전환). american=True 면 각 노드에서 조기 청산/전환도 허용(상환권 성격).
    보통주 = V0 − 우선주(단일 클래스 잔여). 다클래스는 순차 차감으로 확장.
    """
    if enterprise_value <= 0:
        raise ValueError("기업가치는 양수여야 함")
    n = max(int(steps), 1)
    dt = params.term_years / n
    import math
    v = max(params.volatility, 1e-12)
    u = math.exp(v * math.sqrt(dt))
    d = 1.0 / u
    growth = math.exp((params.risk_free - params.dividend_yield) * dt)
    p = min(max((growth - d) / (u - d), 0.0), 1.0)
    disc = math.exp(-params.risk_free * dt)

    # 만기 노드 페이오프
    vals = [pref.payoff(enterprise_value * u ** j * d ** (n - j)) for j in range(n + 1)]
    for i in range(n - 1, -1, -1):
        vals = [disc * (p * vals[j + 1] + (1 - p) * vals[j]) for j in range(i + 1)]
        if american:
            vals = [max(vals[j], pref.payoff(enterprise_value * u ** j * d ** (i - j)))
                    for j in range(i + 1)]
    pref_pv = vals[0]

    # 전환 경계(만기): LP == V×frac → V = LP/frac
    boundary = (pref.liquidation_preference / pref.conversion_fraction
                if pref.conversion_fraction > 0 else None)
    return RcpsResult(
        preferred_value=pref_pv,
        common_value=enterprise_value - pref_pv,
        conversion_boundary=boundary,
    )
