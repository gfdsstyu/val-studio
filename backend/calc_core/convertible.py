"""전환사채(CB·RCPS) 평가 — 이항트리 + TF(Tsiveriotis-Fernandes) 분리할인.

복합금융상품 트랙([[밸류에이션_스코프_로드맵]])의 첫 계산코어. DCF(calc_core.dcf)와
별개 수학(옵션평가). 방법론 근거: [[복합금융상품_평가]].

TF 핵심: 전환사채 가치를 두 성분으로 분리해 **다른 할인율**로 후진귀납:
  - 주식성분(전환으로 종결될 부분) → 무위험이자율 rf 할인
  - 채권성분(현금상환으로 종결될 부분) → rf + credit_spread 할인
CRR 격자: u=e^{σ√Δt}, d=1/u, p=(e^{(rf−q)Δt}−d)/(u−d).

의사결정(각 노드, 우선순위):
  ① 투자자 풋: put_price > 계속가치 → 풋(전액 채권성분)
  ② 발행자 콜: call_price < 계속가치 → 보유자는 max(전환가치, 콜가격)
     - 전환가치 ≥ 콜 → **강제전환**(주식성분) ← 강제전환 누락 시 콜 과대평가(북 규칙)
     - 아니면 콜 상환(채권성분)
  ③ 자발적 전환: 전환가치 > 계속가치 → 전환(주식성분)

쿠폰: 연 coupon_rate × face 를 스텝별 안분해 채권성분에 가산(연속 근사).
만기: max(전환가치, 만기상환액+잔여쿠폰) — 전환이면 주식성분, 아니면 채권성분.

RCPS 상환권(보장수익률) 확장: 실무 RCPS 의 상환가는 고정이 아니라
**상환가(t) = 액면 × (1+보장수익률)^t** 연복리 스케줄로 증가한다(put_accrual_rate).
만기 잔존분도 보장수익률 반영액으로 상환(만기상환액 = face×(1+r)^T). 발행자
콜(매도청구)도 동일 스케줄 가능(call_accrual_rate). ⚠️ 계약의 보장수익률이 쿠폰(배당)
포함 IRR 기준이면 이중계상 방지 위해 coupon_rate=0 으로 두고 accrual 만 쓸 것.
리픽싱(전환가 조정)은 미구현 — 경로의존이라 몬테카를로 트랙([[복합금융상품_평가]]).
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ConvertibleInputs:
    """전환사채 입력. 금액 단위는 자유(face 와 동일 단위로 산출)."""
    face: float                     # 액면(상환금액)
    stock_price: float              # 현재 주가
    conversion_ratio: float         # 사채 1단위당 전환 주식수
    maturity_years: float
    volatility: float               # 주가 변동성(연, 예 0.4)
    risk_free: float                # rf(연속복리 근사)
    credit_spread: float            # 발행자 신용스프레드(채권성분 가산)
    coupon_rate: float = 0.0        # 연 쿠폰(액면 대비)
    dividend_yield: float = 0.0     # 배당수익률 q
    call_price: float | None = None     # 발행자 콜(수의상환) 가격 — 고정형
    call_start_year: float = 0.0        # 콜 행사 가능 시점
    put_price: float | None = None      # 투자자 풋 가격 — 고정형
    put_start_year: float = 0.0
    # RCPS 보장수익률 스케줄(연복리). 설정 시 고정 price 대신 face×(1+r)^t 사용.
    put_accrual_rate: float | None = None
    call_accrual_rate: float | None = None
    steps: int = 200                    # 격자 스텝

    def conversion_value(self, s: float) -> float:
        return self.conversion_ratio * s

    def put_value_at(self, t: float) -> float | None:
        """t 시점 투자자 상환가. accrual 스케줄 > 고정 put_price 우선."""
        if self.put_accrual_rate is not None:
            return self.face * (1.0 + self.put_accrual_rate) ** t
        return self.put_price

    def call_value_at(self, t: float) -> float | None:
        """t 시점 발행자 콜가격. accrual 스케줄 > 고정 call_price 우선."""
        if self.call_accrual_rate is not None:
            return self.face * (1.0 + self.call_accrual_rate) ** t
        return self.call_price

    def maturity_redemption(self) -> float:
        """만기 상환액 — 보장수익률 있으면 face×(1+r)^T (RCPS 만기 보장상환)."""
        if self.put_accrual_rate is not None:
            return self.face * (1.0 + self.put_accrual_rate) ** self.maturity_years
        return self.face


@dataclass(frozen=True)
class ConvertibleResult:
    value: float                    # 전환사채 공정가치
    equity_component: float         # 주식성분(t=0)
    debt_component: float           # 채권성분(t=0)
    straight_bond: float            # 옵션 없는 채권가치(참고)
    conversion_value_now: float     # 현재 전환가치(참고)


def straight_bond_value(inp: ConvertibleInputs) -> float:
    """옵션 없는 채권가치 = 쿠폰·만기상환액을 risky rate 로 할인(연속복리 근사)."""
    r = inp.risk_free + inp.credit_spread
    T = inp.maturity_years
    n = max(int(inp.steps), 1)
    dt = T / n
    pv = inp.maturity_redemption() * math.exp(-r * T)
    coupon_per_step = inp.coupon_rate * inp.face * dt
    for i in range(1, n + 1):
        pv += coupon_per_step * math.exp(-r * i * dt)
    return pv


def price_convertible(inp: ConvertibleInputs) -> ConvertibleResult:
    """CRR 격자 + TF 분리할인으로 전환사채 평가."""
    n = max(int(inp.steps), 1)
    T = inp.maturity_years
    dt = T / n
    sigma = max(inp.volatility, 1e-9)
    u = math.exp(sigma * math.sqrt(dt))
    d = 1.0 / u
    growth = math.exp((inp.risk_free - inp.dividend_yield) * dt)
    p = (growth - d) / (u - d)
    p = min(max(p, 0.0), 1.0)               # 수치 안정(σ 극소 시)

    disc_rf = math.exp(-inp.risk_free * dt)
    disc_risky = math.exp(-(inp.risk_free + inp.credit_spread) * dt)
    coupon_step = inp.coupon_rate * inp.face * dt

    # 만기 노드
    eq = [0.0] * (n + 1)
    db = [0.0] * (n + 1)
    maturity_pay = inp.maturity_redemption()
    for j in range(n + 1):
        s = inp.stock_price * (u ** j) * (d ** (n - j))
        conv = inp.conversion_value(s)
        redeem = maturity_pay + coupon_step  # 마지막 스텝 쿠폰 포함
        if conv > redeem:
            eq[j], db[j] = conv, 0.0
        else:
            eq[j], db[j] = 0.0, redeem

    # 후진귀납
    for i in range(n - 1, -1, -1):
        t = i * dt
        put_now = inp.put_value_at(t)
        call_now = inp.call_value_at(t)
        callable_now = call_now is not None and t >= inp.call_start_year
        puttable_now = put_now is not None and t >= inp.put_start_year
        for j in range(i + 1):
            s = inp.stock_price * (u ** j) * (d ** (i - j))
            cont_eq = disc_rf * (p * eq[j + 1] + (1 - p) * eq[j])
            cont_db = disc_risky * (p * db[j + 1] + (1 - p) * db[j]) + coupon_step
            cont = cont_eq + cont_db
            conv = inp.conversion_value(s)

            if puttable_now and put_now > cont:                     # ① 투자자 풋
                eq[j], db[j] = 0.0, put_now
            elif callable_now and call_now < cont:                  # ② 발행자 콜
                if conv >= call_now:                                # 강제전환
                    eq[j], db[j] = conv, 0.0
                else:                                               # 콜 상환
                    eq[j], db[j] = 0.0, call_now
            elif conv > cont:                                       # ③ 자발적 전환
                eq[j], db[j] = conv, 0.0
            else:                                                   # 보유
                eq[j], db[j] = cont_eq, cont_db

    return ConvertibleResult(
        value=eq[0] + db[0],
        equity_component=eq[0],
        debt_component=db[0],
        straight_bond=straight_bond_value(inp),
        conversion_value_now=inp.conversion_value(inp.stock_price),
    )
