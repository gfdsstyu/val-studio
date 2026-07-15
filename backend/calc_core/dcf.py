"""DCF 스파인 계산 (Layer A) — 비올 DCF Model 최종본 DCF 시트 1:1 재현.

계산 순서(원본 DCF 시트 열 M~Q + Terminal R + 평가결과 H열):

    매출총이익 = 매출 − 매출원가
    EBIT       = 매출총이익 − 판관비
    법인세     = 구간세율(EBIT)                      # tax.corporate_tax
    NOPLAT     = EBIT − 법인세
    FCFF       = NOPLAT + D&A − CAPEX + ΔNWC(현금조정)
    PVfactor   = 1/(1+WACC)^period                  # 중간연도: 0.5,1.5,...
    PV(FCFF)   = FCFF × PVfactor
    Terminal   : EBIT_T = EBIT_last×(1+g) → 세금 재계산 → NOPLAT_T = FCFF_T
                 TV = FCFF_T/(WACC−g),  PV(TV) = TV × PVfactor(마지막 명시연도)
    EV         = ΣPV(FCFF) + PV(TV)
    주식가치   = EV + 비영업자산 − 순차입부채
    주당가치   = 주식가치 / 주식수 × 1e6            # 백만원→원

민감도표는 (WACC±1%p × g±1%p) 로 재계산. 원본 캐시값은 stale 이므로 참조하지 않고,
중심 셀 == base 주당가치 자기일관성으로 검증한다.
"""
from __future__ import annotations

from .models import DcfResult, DcfSpineInput
from .tax import corporate_tax


def _per_share_only(inp: DcfSpineInput, wacc: float, g: float) -> float:
    """민감도용: (wacc, g) 로 주당가치만 재계산."""
    return _compute(inp, wacc, g).per_share


def _tax_on(inp: DcfSpineInput, ebit_val: float, i: int | None) -> float:
    """세금 결정(개선 A). i=연도 인덱스, i=None 이면 터미널.

    우선순위: tax_override(명시) > effective_tax_rate(비율) > 구간세율(EBIT).
    터미널은 override 가 없으므로 effective_tax_rate → (tax_override 있으면 마지막
    유효세율) → 구간세율 순으로 성장시킨 EBIT 에 적용.
    """
    if i is not None and inp.tax_override is not None:
        return inp.tax_override[i]
    if inp.effective_tax_rate is not None:
        return ebit_val * inp.effective_tax_rate
    if i is None and inp.tax_override is not None:
        # 터미널: 마지막 명시연도의 유효세율을 성장 EBIT 에 적용(절대액 고정은 비현실)
        last_ebit = inp.revenue[-1] - inp.cogs[-1] - inp.sga[-1]
        last_eff = inp.tax_override[-1] / last_ebit if last_ebit else 0.0
        return ebit_val * last_eff
    return corporate_tax(ebit_val)


def _compute(inp: DcfSpineInput, wacc: float, g: float) -> DcfResult:
    n = inp.n_years()
    periods = inp.mid_year_periods or [i - 0.5 for i in range(1, n + 1)]
    term_period = inp.terminal_discount_period if inp.terminal_discount_period is not None else periods[-1]

    ebit = [inp.revenue[i] - inp.cogs[i] - inp.sga[i] for i in range(n)]
    tax = [_tax_on(inp, ebit[i], i) for i in range(n)]
    noplat = [ebit[i] - tax[i] for i in range(n)]
    fcff = [
        noplat[i] + inp.dep_amort[i] - inp.capex[i] + inp.delta_nwc_cash_adj[i]
        for i in range(n)
    ]
    pv_factor = [1.0 / (1.0 + wacc) ** periods[i] for i in range(n)]
    pv_fcff = [fcff[i] * pv_factor[i] for i in range(n)]

    # Terminal(개선 B): fcff_override > reinvestment_rate(g/ROIC) > D&A=CAPEX 기본.
    if inp.terminal_fcff_override is not None:
        terminal_fcff = inp.terminal_fcff_override  # 정규화된 FCF_{n+1} 직접 주입
    else:
        terminal_ebit = ebit[-1] * (1.0 + g)
        terminal_tax = _tax_on(inp, terminal_ebit, None)
        terminal_noplat = terminal_ebit - terminal_tax
        if inp.terminal_reinvestment_rate is not None:
            # 성장에 필요한 재투자 차감: FCFF_T = NOPLAT_T×(1−g/ROIC)
            terminal_fcff = terminal_noplat * (1.0 - inp.terminal_reinvestment_rate)
        else:
            terminal_fcff = terminal_noplat  # 영구구간 D&A=CAPEX, ΔNWC=0
    terminal_value = terminal_fcff / (wacc - g)
    terminal_value_pv = terminal_value * (1.0 / (1.0 + wacc) ** term_period)

    pv_explicit_sum = sum(pv_fcff)
    enterprise_value = pv_explicit_sum + terminal_value_pv
    equity_value = enterprise_value + inp.non_operating_assets - inp.net_debt
    per_share = equity_value / inp.shares_outstanding * 1_000_000

    return DcfResult(
        ebit=ebit,
        tax=tax,
        noplat=noplat,
        fcff=fcff,
        pv_factor=pv_factor,
        pv_fcff=pv_fcff,
        terminal_fcff=terminal_fcff,
        terminal_value=terminal_value,
        terminal_value_pv=terminal_value_pv,
        pv_explicit_sum=pv_explicit_sum,
        enterprise_value=enterprise_value,
        non_operating_assets=inp.non_operating_assets,
        net_debt=inp.net_debt,
        equity_value=equity_value,
        shares_outstanding=inp.shares_outstanding,
        per_share=per_share,
    )


def run(inp: DcfSpineInput, sensitivity_step: float = 0.01) -> DcfResult:
    """DCF 스파인 실행 + 2-way 민감도표(WACC × g).

    sensitivity: {'wacc_axis':[...], 'g_axis':[...], 'per_share':[[...]]} 형태.
    행=WACC(낮음→높음), 열=g(낮음→높음), 중심[1][1]=base 주당가치.
    """
    base = _compute(inp, inp.wacc, inp.terminal_growth)

    wacc_axis = [inp.wacc - sensitivity_step, inp.wacc, inp.wacc + sensitivity_step]
    g_axis = [inp.terminal_growth - sensitivity_step, inp.terminal_growth, inp.terminal_growth + sensitivity_step]
    grid = [[_per_share_only(inp, w, g) for g in g_axis] for w in wacc_axis]

    base.sensitivity.update(
        {"wacc_axis": wacc_axis, "g_axis": g_axis, "per_share": grid}
    )
    return base
