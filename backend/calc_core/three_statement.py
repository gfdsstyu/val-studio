"""3표 완전연결 (IS·BS·CF) — **모델 정합성 검증기**.

우리 DCF 는 FCFF(무차입) 기준이라 3표가 *가치 산정*에는 불필요하다. 그럼에도 만드는 이유:
`model.build_spine` 이 `ebit`·`fa`·`wc`·`tax` 네 모듈의 산출을 **교차검증 없이** 이어붙이기
때문이다. FA 가 내놓은 D&A 와 WC 가 내놓은 NWC 잔액이 서로 모순돼도 DCF 는 조용히 숫자를 낸다.

3표를 조립하면 회계 항등식 두 개가 배관 오류를 잡는 독립 검증기가 된다:

    자산 = 부채 + 자본            (대차)
    Δ현금 = CFO + CFI + CFF       (현금연결)

**조립이 정합하면 저절로 맞는다** — 아래 롤포워드에서:
    ΔAssets = NI + 발행 − 상환 − 배당 = ΔLiabilities+Equity
∴ 잔차가 뜨면 산술이 아니라 **입력 배관이 틀린 것**이다(기초 BS 불균형, D&A↔FA 롤 불일치,
CFO 의 ΔNWC ↔ NWC 잔액 변화 불일치). 차액을 "대차조정" 항목으로 **절대 밀어넣지 않는다** —
플러그를 넣는 순간 검증기가 죽는다.

근거 문서:
  - 앤트로픽_금융스킬_벤치마크 §2 audit-xls — 모델 스코프 무결성 목록(BS balance·RE
    rollforward·cash tie-out·D&A·CapEx 대사)이 그대로 이 모듈의 사양.
    "**BS 안 맞으면 그것부터 — 나머지는 전부 의심**"(심각도 순서 원칙 → checks.py).
  - 모델러스_통합모델_5.4 §2.2 — Circuit Switch·부채/이자수익 스케줄 실측.
  - 모델링_워크플로우_기초 §순환참조 — 순환 고리와 실무 해법.

BS 계정체계는 **새로 만들지 않고** `ingest.fs_mapper.BS_BUCKETS`(WC·FA·NOA·IBD·OAL·EQU)를
따른다 — W3 Reclass·지분 브리지와 같은 어휘여야 교차 사용이 된다.

━━ 순환참조 해법 3층 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

3표는 필연적으로 순환을 만든다: `이자수익 → 순이익 → 현금 → 이자부자산 → 이자수익`.
엑셀의 답(반복계산 켜기 + 순환 스위치)은 **수렴 여부를 사용자가 볼 수 없고**, 스위치를
OFF 로 두고 잊으면 이자 0인 채 결과가 나온다. 우리는 3층으로 푼다.

  ⭐ **기본은 정확도**(`average`)다. 순환 회피는 구현 편의이지 정확성 논거가 아니며,
  우리는 그 편의를 위해 정확도를 포기하지 않으려고 솔버를 만들었다.

  Layer 1 `interest_basis="average"` (**기본**) — 이자를 **기초·기말 평균잔액** 기준으로.
      연중 부채가 상환되거나 현금이 쌓이면 기초잔액만으로는 그 변화가 무시된다.
      수학적으로 기초잔액 = **좌단점 직사각형 근사**, 평균잔액 = **사다리꼴 근사**이므로,
      흐름이 연중 고르게 발생한다는 표준 가정에서 평균이 명백히 더 나은 근사다
      (모델러스 정본도 `AVERAGE(N146,O146)`).
      이 선택이 순환을 만들지만 — "엑셀에서 반복계산 켜세요" 대신 **연도별 스칼라
      고정점 반복**을 직접 돌려 푼다.
      수렴 보증: 사상의 기울기 ≈ r/2·(1−τ). r=3%·τ=24% 면 ≈0.011 ≪ 1 → **압축사상**
      → 오차가 회차마다 ~1/100 로 줄어든다(실측: tol=1e-9 에서 5~6회, 이론과 정합).
      구간세율이 비선형이라 폐형해가 없어 반복이 정답이다.
      **수렴 실패는 조용히 넘기지 않고 converged=False 로 노출**한다.
      ⚠️ 평균잔액도 근사다 — 자금이 특정 시점에 몰리면(예: 기말 대량 차입) 과대·과소
      된다. 정확히 하려면 일자별 스케줄이 필요하나 그건 PF·LBO 트랙의 주제다.

  Layer 2 `interest_basis="opening"` — **기초잔액 단순화**. 순환이 원천적으로 발생하지
      않아(t 의 이자가 t 의 순이익에 미의존) 1패스 결정론이며, 반복의 **초기값**이자
      결과 대조용 기준선이다. 보수적 관행이지만 **정확도는 Layer 1 보다 낮다** —
      연중 잔액 변화를 못 담는다. 회계정책상 기초기준을 쓰는 경우에만 명시적으로 선택.

  Layer 3 `circularity_enabled=False` — Circuit Switch(R14). 이자수익을 0으로 강제해
      고리를 끊는다(디버깅·대조용). 모델러스 `IF($L$5="ON", 스케줄, 0)` 재현.
      **단 순이익이 과소**되므로 checks 가 반드시 WARN 한다 — 조용히 지나가면 안 된다.

⚠️ 순환은 **이자수익에만** 있다. 이자비용의 기저인 부채는 발행·상환이 외생이라
평균잔액을 써도 완전히 결정된다. 그래서 고정점은 스칼라 하나에 대해서만 돈다.

전부 표준 라이브러리(pip 불요) — calc_core 규약.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .tax import corporate_tax

# 이자 기준 — "average"(평균잔액, 기본·더 정확) | "opening"(기초잔액, 단순화·순환 없음)
INTEREST_BASIS = ("average", "opening")
DEFAULT_INTEREST_BASIS = "average"
DEFAULT_MAX_ITERATIONS = 50
DEFAULT_TOLERANCE = 1e-9


@dataclass(frozen=True)
class OpeningBalanceSheet:
    """기초 재무상태표 — 평가용 재분류 버킷(fs_mapper.BS_BUCKETS 어휘).

    **스스로 대차가 맞아야 한다.** 안 맞으면 그 불균형이 전 추정기간에 그대로 남아
    모든 연도의 대차 잔차로 나타난다(누적되지 않고 상수로 지속) — 진단이 쉽도록 의도한 것.
    """

    cash: float = 0.0
    short_term_investments: float = 0.0     # 이자부 비영업자산(NOA)
    net_working_capital: float = 0.0        # WC 순액(운전자산 − 운전부채)
    net_fixed_assets: float = 0.0           # FA 순장부가
    other_assets: float = 0.0               # 무이자 기타자산
    interest_bearing_debt: float = 0.0      # IBD
    other_liabilities: float = 0.0          # OAL(무이자)
    paid_in_capital: float = 0.0
    retained_earnings: float = 0.0
    other_equity: float = 0.0

    def total_assets(self) -> float:
        return (self.cash + self.short_term_investments + self.net_working_capital
                + self.net_fixed_assets + self.other_assets)

    def total_liabilities(self) -> float:
        return self.interest_bearing_debt + self.other_liabilities

    def total_equity(self) -> float:
        return self.paid_in_capital + self.retained_earnings + self.other_equity

    def balance_residual(self) -> float:
        """자산 − (부채 + 자본). 0 이 아니면 기초 BS 자체가 안 맞는 것."""
        return self.total_assets() - (self.total_liabilities() + self.total_equity())

    def interest_bearing_assets(self) -> float:
        return self.cash + self.short_term_investments


@dataclass(frozen=True)
class FinancingPlan:
    """재무활동 가정 — 부채 스케줄·이자율·배당정책.

    부채는 **외생 스케줄**(발행/상환 주입)이라 cash sweep 은 하지 않는다. sweep 은
    LBO 트랙의 주제이고, 여기 목적은 정합성 검증이라 단순·결정론을 택한다.
    """

    debt_issuance: list[float] = field(default_factory=list)
    debt_repayment: list[float] = field(default_factory=list)
    interest_rate_debt: float = 0.0
    interest_rate_cash: float = 0.0
    # 순이익 대비 배당성향. 스칼라 또는 연도별. 결손(NI≤0)이면 배당 없음.
    dividend_payout_ratio: float | list[float] = 0.0
    other_income_expense: list[float] | None = None      # 영업외 기타(+수익/−비용)

    def _at(self, seq: list[float] | None, t: int) -> float:
        return 0.0 if not seq else (seq[t] if t < len(seq) else 0.0)

    def issuance(self, t: int) -> float:
        return self._at(self.debt_issuance, t)

    def repayment(self, t: int) -> float:
        return self._at(self.debt_repayment, t)

    def other(self, t: int) -> float:
        return self._at(self.other_income_expense, t)

    def payout(self, t: int) -> float:
        r = self.dividend_payout_ratio
        if isinstance(r, (int, float)):
            return float(r)
        return r[t] if t < len(r) else 0.0


@dataclass(frozen=True)
class ThreeStatementInput:
    """3표 조립 입력 — 영업 산출(상류 모듈) + 기초 BS + 재무 가정.

    ebit/dep_amort/capex 는 `model.build_spine` 이 쓰는 것과 **같은 벡터**를 넣어야
    검증이 의미 있다(다른 값을 넣으면 다른 모델을 검증하는 셈).
    net_working_capital 은 `wc.WcResult.net_working_capital`(잔액) 그대로.
    """

    ebit: list[float]
    dep_amort: list[float]
    capex: list[float]
    net_working_capital: list[float]
    opening: OpeningBalanceSheet
    financing: FinancingPlan
    effective_tax_rate: float | None = None   # None → 구간세율 corporate_tax(EBT)
    interest_basis: str = DEFAULT_INTEREST_BASIS   # 기본=평균잔액(더 정확)
    circularity_enabled: bool = True          # R14 Circuit Switch
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    tolerance: float = DEFAULT_TOLERANCE

    def n_years(self) -> int:
        return len(self.ebit)


@dataclass
class ThreeStatementResult:
    """3표 산출 + 정합 잔차. 잔차는 **플러그 없이** 그대로 노출한다."""

    # ── 손익계산서 ──
    ebit: list[float] = field(default_factory=list)
    interest_income: list[float] = field(default_factory=list)
    interest_expense: list[float] = field(default_factory=list)
    other_income_expense: list[float] = field(default_factory=list)
    ebt: list[float] = field(default_factory=list)
    tax: list[float] = field(default_factory=list)
    net_income: list[float] = field(default_factory=list)
    # ── 재무상태표 ──
    cash: list[float] = field(default_factory=list)
    short_term_investments: list[float] = field(default_factory=list)
    net_working_capital: list[float] = field(default_factory=list)
    net_fixed_assets: list[float] = field(default_factory=list)
    other_assets: list[float] = field(default_factory=list)
    interest_bearing_debt: list[float] = field(default_factory=list)
    other_liabilities: list[float] = field(default_factory=list)
    paid_in_capital: list[float] = field(default_factory=list)
    retained_earnings: list[float] = field(default_factory=list)
    other_equity: list[float] = field(default_factory=list)
    total_assets: list[float] = field(default_factory=list)
    total_liabilities: list[float] = field(default_factory=list)
    total_equity: list[float] = field(default_factory=list)
    # ── 현금흐름표 ──
    cfo: list[float] = field(default_factory=list)
    cfi: list[float] = field(default_factory=list)
    cff: list[float] = field(default_factory=list)
    net_change_in_cash: list[float] = field(default_factory=list)
    dividends: list[float] = field(default_factory=list)
    delta_nwc: list[float] = field(default_factory=list)
    # ── 정합 잔차(0 이어야 정상) ──
    balance_residual: list[float] = field(default_factory=list)
    cash_tie_residual: list[float] = field(default_factory=list)
    re_rollforward_residual: list[float] = field(default_factory=list)
    # ── 순환 해결 메타 ──
    iterations: list[int] = field(default_factory=list)
    converged: bool = True
    interest_basis: str = DEFAULT_INTEREST_BASIS
    circularity_enabled: bool = True
    opening_balance_residual: float = 0.0
    # 투입된 영업 벡터 원본(스파인 대사용). CAPEX 는 CFI 에 음수로만 담기므로 되살릴 수
    # 있게 보관하고, D&A 는 FA 롤·CFO 양쪽에 쓰이므로 함께 남긴다.
    _capex: list[float] = field(default_factory=list)
    _dep_amort: list[float] = field(default_factory=list)

    def effective_tax_rates(self) -> list[float]:
        """연도별 유효세율 = 세금/세전이익. 세전이익 0 이면 0(정의 불가)."""
        return [(self.tax[t] / self.ebt[t]) if self.ebt[t] else 0.0
                for t in range(len(self.ebt))]

    def fcff_from_cashflow(self, tax_rate: float | list[float] | None = None
                           ) -> list[float]:
        """CF표에서 FCFF 역산 — 무차입화(금융효과 제거).

            FCFF = CFO − (이자수익 − 이자비용)×(1−τ) − CAPEX

        NI 에는 이자 손익이 세후로 섞여 있으므로 그만큼 걷어낸다. 이 값이 DCF 스파인의
        FCFF 와 어긋나면 **FCF 에 이자가 섞였다(unlevered 위반)** 는 신호다
        (audit-xls "DCF 특화 버그 5종" 중 하나).

        ⚠️ 구간세율(비선형)을 쓰면 스파인은 corporate_tax(EBIT), 3표는 corporate_tax(EBT)
        라 과세표준이 달라 완전일치하지 않는다 — 정확한 대사는 `effective_tax_rate`
        (정률)를 쓸 때 성립한다. checks 가 이 caveat 을 finding 에 남긴다.
        """
        n = len(self.cfo)
        if tax_rate is None:
            rates = self.effective_tax_rates()
        elif isinstance(tax_rate, (int, float)):
            rates = [float(tax_rate)] * n
        else:
            rates = list(tax_rate)
        return [self.cfo[t]
                - (self.interest_income[t] - self.interest_expense[t]) * (1.0 - rates[t])
                - self.capex_at(t)
                for t in range(n)]

    def capex_at(self, t: int) -> float:
        return self._capex[t] if t < len(self._capex) else 0.0


def _tax_on(inp: ThreeStatementInput, ebt: float) -> float:
    """세전이익 → 법인세. 정률이 주어지면 정률, 아니면 구간세율(tax.corporate_tax).

    결손(EBT ≤ 0)이면 0 — 이월결손금 공제는 모델링하지 않는다(정합성 검증 목적 밖).
    """
    if ebt <= 0:
        return 0.0
    if inp.effective_tax_rate is not None:
        return ebt * inp.effective_tax_rate
    return corporate_tax(ebt)


def project_three_statements(inp: ThreeStatementInput) -> ThreeStatementResult:
    """영업 산출 + 기초 BS + 재무 가정 → IS·BS·CF 3표 + 정합 잔차.

    연도 루프 안에서 `interest_basis` 에 따라 1패스(opening) 또는 고정점 반복(average).
    **잔차에 플러그를 넣지 않는다** — 검증기의 존재 이유가 사라진다.
    """
    if inp.interest_basis not in INTEREST_BASIS:
        raise ValueError(
            f"interest_basis 는 {INTEREST_BASIS} 중 하나여야 한다: {inp.interest_basis!r}")
    if inp.max_iterations < 1:
        raise ValueError(f"max_iterations 는 1 이상이어야 한다: {inp.max_iterations}")

    n = inp.n_years()
    for name, seq in (("dep_amort", inp.dep_amort), ("capex", inp.capex),
                      ("net_working_capital", inp.net_working_capital)):
        if len(seq) != n:
            raise ValueError(f"{name} 길이 {len(seq)} ≠ ebit 길이 {n}")

    op, fin = inp.opening, inp.financing
    res = ThreeStatementResult(
        interest_basis=inp.interest_basis,
        circularity_enabled=inp.circularity_enabled,
        opening_balance_residual=op.balance_residual(),
        _capex=list(inp.capex),
        _dep_amort=list(inp.dep_amort),
    )

    # 기초(t=−1) 상태
    cash_prev = op.cash
    sti = op.short_term_investments          # 단기금융자산은 드라이버가 없어 기초값 유지
    nwc_prev = op.net_working_capital
    fa_prev = op.net_fixed_assets
    debt_prev = op.interest_bearing_debt
    re_prev = op.retained_earnings
    iba_prev = op.interest_bearing_assets()

    converged_all = True

    for t in range(n):
        ebit_t = inp.ebit[t]
        dep_t = inp.dep_amort[t]
        capex_t = inp.capex[t]
        nwc_t = inp.net_working_capital[t]
        d_nwc = nwc_t - nwc_prev                 # 증가 = 현금유출

        issue_t, repay_t = fin.issuance(t), fin.repayment(t)
        debt_t = debt_prev + issue_t - repay_t
        other_t = fin.other(t)

        # 이자비용은 순환과 무관 — 부채가 외생 스케줄이라 완전히 결정된다.
        debt_base = debt_prev if inp.interest_basis == "opening" \
            else (debt_prev + debt_t) / 2.0
        ie_t = fin.interest_rate_debt * debt_base

        def _pass(ii: float) -> tuple:
            """이자수익 가정치 → 그 해의 IS·CF·기말현금. 고정점 사상의 본체."""
            ebt = ebit_t + ii - ie_t + other_t
            tax = _tax_on(inp, ebt)
            ni = ebt - tax
            div = ni * fin.payout(t) if ni > 0 else 0.0   # 결손이면 배당 없음
            cfo = ni + dep_t - d_nwc
            cfi = -capex_t
            cff = issue_t - repay_t - div
            cash = cash_prev + cfo + cfi + cff
            return ebt, tax, ni, div, cfo, cfi, cff, cash

        # ── 순환 해법 3층 ──
        if not inp.circularity_enabled:
            # Layer 3: Circuit Switch OFF — 고리 절단(이자수익 0). NI 과소 → checks WARN.
            ii_t = 0.0
            iters = 1
            out = _pass(ii_t)
        elif inp.interest_basis == "opening":
            # Layer 2: 기초잔액 단순화 — 순환 없음(1패스). 평균잔액보다 정확도는 낮다.
            ii_t = fin.interest_rate_cash * iba_prev
            iters = 1
            out = _pass(ii_t)
        else:
            # Layer 1(기본): 평균잔액 — 고정점 반복. 초기값은 기초잔액 기준값.
            ii_t = fin.interest_rate_cash * iba_prev
            iters = 0
            converged_year = False
            for _ in range(inp.max_iterations):
                iters += 1
                out = _pass(ii_t)
                iba_t = out[7] + sti                       # 기말 이자부자산
                ii_next = fin.interest_rate_cash * (iba_prev + iba_t) / 2.0
                if abs(ii_next - ii_t) < inp.tolerance:
                    ii_t = ii_next
                    out = _pass(ii_t)                      # 수렴값으로 최종 1패스
                    converged_year = True
                    break
                ii_t = ii_next
            if not converged_year:
                converged_all = False

        ebt_t, tax_t, ni_t, div_t, cfo_t, cfi_t, cff_t, cash_t = out

        # ── 잔액 롤포워드 ──
        fa_t = fa_prev + capex_t - dep_t
        re_t = re_prev + ni_t - div_t
        iba_t = cash_t + sti

        assets = cash_t + sti + nwc_t + fa_t + op.other_assets
        liabs = debt_t + op.other_liabilities
        equity = op.paid_in_capital + re_t + op.other_equity

        # ── 기록 ──
        res.ebit.append(ebit_t)
        res.interest_income.append(ii_t)
        res.interest_expense.append(ie_t)
        res.other_income_expense.append(other_t)
        res.ebt.append(ebt_t)
        res.tax.append(tax_t)
        res.net_income.append(ni_t)

        res.cash.append(cash_t)
        res.short_term_investments.append(sti)
        res.net_working_capital.append(nwc_t)
        res.net_fixed_assets.append(fa_t)
        res.other_assets.append(op.other_assets)
        res.interest_bearing_debt.append(debt_t)
        res.other_liabilities.append(op.other_liabilities)
        res.paid_in_capital.append(op.paid_in_capital)
        res.retained_earnings.append(re_t)
        res.other_equity.append(op.other_equity)
        res.total_assets.append(assets)
        res.total_liabilities.append(liabs)
        res.total_equity.append(equity)

        res.cfo.append(cfo_t)
        res.cfi.append(cfi_t)
        res.cff.append(cff_t)
        res.net_change_in_cash.append(cfo_t + cfi_t + cff_t)
        res.dividends.append(div_t)
        res.delta_nwc.append(d_nwc)

        # ── 정합 잔차(플러그 없음) ──
        res.balance_residual.append(assets - (liabs + equity))
        res.cash_tie_residual.append((cash_t - cash_prev) - (cfo_t + cfi_t + cff_t))
        res.re_rollforward_residual.append(re_t - (re_prev + ni_t - div_t))
        res.iterations.append(iters)

        # 다음 연도 기초로 이월
        cash_prev, nwc_prev, fa_prev, debt_prev, re_prev, iba_prev = (
            cash_t, nwc_t, fa_t, debt_t, re_t, iba_t)

    res.converged = converged_all
    return res
