"""전환사채(CB·RCPS) 평가 — 이항트리 + TF(Tsiveriotis-Fernandes) 분리할인.

복합금융상품 트랙([[밸류에이션_스코프_로드맵]])의 첫 계산코어. DCF(calc_core.dcf)와
별개 수학(옵션평가). 방법론 근거: [[복합금융상품_평가]].

TF 핵심: 전환사채 가치를 두 성분으로 분리해 **다른 할인율**로 후진귀납:
  - 주식성분(전환으로 종결될 부분) → 무위험이자율 rf 할인
  - 채권성분(현금상환으로 종결될 부분) → rf + credit_spread 할인
CRR 격자: u=e^{σ√Δt}, d=1/u, p=(e^{(rf−q)Δt}−d)/(u−d).

의사결정(각 노드):
  ① 발행자 콜 캡: call_price < 계속가치 → 계속가치가 max(전환가치, 콜가격)으로 대체
     - 전환가치 ≥ 콜 → **강제전환**(주식성분) ← 강제전환 누락 시 콜 과대평가(북 규칙)
     - 아니면 콜 상환(채권성분)
  ② 홀더 선택: max(콜캡 반영 계속가치, 전환가치, 풋가격) — 최대값 채택.
     풋-우선 캐스케이드가 아님: 전환>풋>계속 구간에서 풋을 먼저 고르면
     과소평가된다(T-F 워크북 3종 골든 채록에서 발견·교정, tests/golden/test_tf_workbooks.py).

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


@dataclass(frozen=True)
class WithWithoutResult:
    """with-without 분해([[복합금융상품_평가]] §with-without, Issue Paper 407).

    with(전체 CB) − without(옵션 제거 host 일반사채) = 내재파생(전환권+상환권 as a whole).
    양변이 **동일 가정**(같은 위험할인율·쿠폰·만기상환 규약)이어야 분해가 정합 —
    이종 가정 차감(T-F 워크북 반면교사: 연속할인 트리 − 이산할인 채권)은 checks 의
    check_cb_decomposition 이 잡는다.
    """
    with_value: float               # 전체 CB 공정가치(T-F 격자)
    without_value: float            # host 일반사채(전환·조기상환 옵션 제거)
    embedded_value: float           # 내재파생 = with − without


def with_without(inp: ConvertibleInputs) -> WithWithoutResult:
    """내재파생 공정가치 = 전체 CB(T-F) − 동일가정 일반사채 (Issue Paper 407 승격).

    host 는 straight_bond_value — 쿠폰·만기상환(RCPS 보장수익률 포함)을 동일 risky
    rate 로 할인. 만기 보장상환은 주계약의 일부이므로 host 에 남고, 조기 풋·전환권
    패키지만 내재파생으로 분리된다(홀더 옵션이므로 embedded ≥ 0).
    """
    full = price_convertible(inp)
    host = straight_bond_value(inp)
    return WithWithoutResult(
        with_value=full.value,
        without_value=host,
        embedded_value=full.value - host,
    )


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

            # ① 발행자 콜 캡: 콜이 유리하면 계속가치가 max(전환, 콜상환)으로 대체
            if callable_now and call_now < cont:
                if conv >= call_now:                                # 강제전환
                    cand_eq, cand_db = conv, 0.0
                else:                                               # 콜 상환
                    cand_eq, cand_db = 0.0, call_now
            else:                                                   # 보유
                cand_eq, cand_db = cont_eq, cont_db

            # ② 홀더 선택: max(계속(콜캡), 전환, 풋) — 풋-우선 캐스케이드 금지
            #    (전환>풋>계속이면 전환이 정답: 풋 먼저 고르면 과소평가)
            best_eq, best_db = cand_eq, cand_db
            if conv > best_eq + best_db:                            # 자발적 전환
                best_eq, best_db = conv, 0.0
            if puttable_now and put_now > best_eq + best_db:        # 투자자 풋
                best_eq, best_db = 0.0, put_now
            eq[j], db[j] = best_eq, best_db

    return ConvertibleResult(
        value=eq[0] + db[0],
        equity_component=eq[0],
        debt_component=db[0],
        straight_bond=straight_bond_value(inp),
        conversion_value_now=inp.conversion_value(inp.stock_price),
    )
