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

기간 구조는 **2단(명시+Gordon)이 기본**이고, `fade_years` 를 주면 **3단**이 된다(R1):

    [1] 명시추정   드라이버 기반 N년 (사용자 입력 시계열)
    [2] 페이드     fade_years 년 — 전 비율 동결, 성장률만 gf 로 수렴  ← _expand_fade
    [3] Gordon     TV = FCFF_T/(WACC−g)

페이드는 *입력 확장*으로 구현되어(§_expand_fade) 아래 계산은 전부 무수정 재사용된다.
근거: docs/reference/모델러스_통합모델_5.4.md §2.3 — 명시말기 고성장에서 영구성장률로의
급단절이 TV 를 왜곡하고 TV 비중을 끌어올린다(실측: 페이드 적용 시 TV 비중 57.8%).
    EV         = ΣPV(FCFF) + PV(TV)
    주식가치   = EV + 비영업자산 − 순차입부채
    주당가치   = 주식가치 / 주식수 × 1e6            # 백만원→원

민감도표는 (WACC±1%p × g±1%p) 로 재계산. 원본 캐시값은 stale 이므로 참조하지 않고,
중심 셀 == base 주당가치 자기일관성으로 검증한다.
"""
from __future__ import annotations

from dataclasses import replace

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


def resolve_fade_growth(inp: DcfSpineInput, g: float) -> float:
    """페이드 구간 성장률 결정(R1). 명시 지정 > AVERAGE(마지막 명시 성장률, g).

    모델러스 정본 `F30 = AVERAGE(S15, F33)` — 명시말기 성장률과 영구성장률의 중간값을
    페이드 전 구간에 고정한다. **g 의 함수**이므로 민감도에서 g 축이 움직이면 페이드
    성장률도 따라 움직인다(터미널만 바꾸고 페이드를 고정하면 시나리오가 비정합).
    """
    if inp.fade_growth is not None:
        return inp.fade_growth
    if inp.n_years() < 2:
        raise ValueError(
            "fade_growth 자동산출에는 명시추정 2개년 이상이 필요하다"
            "(마지막 매출성장률 계산 불가) — fade_growth 를 명시하라"
        )
    prev, last = inp.revenue[-2], inp.revenue[-1]
    if prev <= 0:
        raise ValueError(
            f"직전 매출({prev}) ≤ 0 — 마지막 명시 성장률 정의 불가, fade_growth 를 명시하라"
        )
    return ((last / prev - 1.0) + g) / 2.0


def _expand_fade(inp: DcfSpineInput, g: float) -> DcfSpineInput:
    """명시추정 시계열 뒤에 페이드 구간을 이어붙여 확장된 입력을 만든다(R1).

    **설계**: 페이드를 별도 계산분기로 만들지 않고 *입력 확장*으로 구현한다 →
    할인·터미널·브리지·민감도 로직이 전부 무수정으로 재사용된다.
    (하류 게이트 중 `tv_weight` 만 `result` 를 읽으므로 페이드를 자동 반영한다.
    `projection_smoothness`·`working_capital_burn` 은 **미확장 스파인**을 받는다 —
    페이드 구간은 마지막 명시연도의 균일 스케일이라 급변·회전기일 악화 판정에
    정보가 없어 무해하지만, "전 게이트가 페이드를 본다"는 뜻은 아니다.)

    ⚠️ `terminal_discount_period` 는 여기서 **건드리지 않는다** — 그 필드는 확장된
    전체 시계 기준의 절대 기간이라는 계약이다. 명시 5년 기준으로 4.5 를 선언한 뒤
    페이드 5년을 켜면 시계가 10년인데 TV 를 t=4.5 로 할인하게 되므로,
    `checks.check_terminal_discount_convention` 이 시계와의 정합을 검사한다.

    **비율 동결의 구현**: 전 라인아이템을 동일 성장률 gf 로 성장시킨다. 매출도 gf 로
    자라므로 모든 비율(원가율·판관비율·CAPEX/매출·D&A/매출·ΔWC/매출)이 자동 동결되고,
    EBIT 도 `매출(1+gf)×동결OPM = EBIT(1+gf)` 로 동일 성장한다(모델러스 T16 = T14×T17 와 동치).

    fade_years 가 None/0 이면 **입력을 그대로 반환**(기존 동작 완전 보존 — 골든 불변).
    """
    k = inp.fade_years
    if k is None:
        return inp
    # 검증을 **조기 반환보다 먼저** 한다 — `k <= 0` 을 먼저 걸러내면 음수가 조용히
    # "페이드 없음"으로 흡수되어 사용자는 페이드를 켰다고 믿는데 안 켜진 상태가 된다.
    if isinstance(k, bool) or not isinstance(k, int):
        raise ValueError(f"fade_years 는 정수여야 한다: {k!r}")
    if k < 0:
        raise ValueError(f"fade_years 는 음수일 수 없다: {k}")
    if k == 0:
        return inp

    gf = resolve_fade_growth(inp, g)
    factors = [(1.0 + gf) ** (j + 1) for j in range(k)]

    def grow(series: list[float]) -> list[float]:
        return list(series) + [series[-1] * f for f in factors]

    # 세금: override 가 있으면 EBIT 과 같은 속도로 성장 = 세금/EBIT 비율 동결
    # (모델러스 T19 = $F$32 = S19). effective_tax_rate·구간세율은 _tax_on 이
    # 확장된 EBIT 에 그대로 적용하므로 확장 불요.
    tax_override = grow(inp.tax_override) if inp.tax_override is not None else None

    # 할인기간: 명시 지정된 경우만 이어붙인다(None 이면 _compute 가 확장 길이 기준
    # 0.5,1.5,… 를 자동 생성 → 페이드까지 자연 연장).
    periods = inp.mid_year_periods
    if periods is not None:
        periods = list(periods) + [periods[-1] + (j + 1) for j in range(k)]

    return replace(
        inp,
        revenue=grow(inp.revenue),
        cogs=grow(inp.cogs),
        sga=grow(inp.sga),
        dep_amort=grow(inp.dep_amort),
        capex=grow(inp.capex),
        delta_nwc_cash_adj=grow(inp.delta_nwc_cash_adj),
        tax_override=tax_override,
        mid_year_periods=periods,
        fade_years=None,          # 확장 완료 — 재확장 방지
    )


def _compute(inp: DcfSpineInput, wacc: float, g: float) -> DcfResult:
    inp = _expand_fade(inp, g)      # R1: 페이드 구간을 명시 시계열로 편입
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

    # Terminal(개선 B): fcff_override > reinvestment_rate(g/ROIC) >
    #                   (D&A=CAPEX − 정규화 WC 재조정).
    if inp.terminal_fcff_override is not None:
        terminal_fcff = inp.terminal_fcff_override  # 정규화된 FCF_{n+1} 직접 주입
    elif inp.terminal_from_last_fcff:
        # 마지막 연도 FCFF 를 그대로 성장 — 그 해의 재투자 강도(CAPEX·ΔWC)를 영구 승계.
        # 페이드 최종연도는 비율이 동결된 정상상태라 이 컨벤션과 특히 정합적이다.
        terminal_fcff = fcff[-1] * (1.0 + g)
    else:
        terminal_ebit = ebit[-1] * (1.0 + g)
        terminal_tax = _tax_on(inp, terminal_ebit, None)
        terminal_noplat = terminal_ebit - terminal_tax
        if inp.terminal_reinvestment_rate is not None:
            # 성장에 필요한 재투자 차감(WC 포함 번들): FCFF_T = NOPLAT_T×(1−g/ROIC)
            terminal_fcff = terminal_noplat * (1.0 - inp.terminal_reinvestment_rate)
        else:
            # 영구구간 D&A=CAPEX(상각비만큼 재투자). ΔWC 는 정규화 재조정(정본):
            # 터미널 WC 투자 = 추정말매출 × g × WC비율 (없으면 0 = 과대계상 위험).
            terminal_wc_investment = 0.0
            if inp.terminal_wc_ratio is not None:
                terminal_wc_investment = inp.revenue[-1] * g * inp.terminal_wc_ratio
            terminal_fcff = terminal_noplat - terminal_wc_investment
    terminal_value = terminal_fcff / (wacc - g)
    terminal_value_pv = terminal_value * (1.0 / (1.0 + wacc) ** term_period)

    pv_explicit_sum = sum(pv_fcff)
    enterprise_value = pv_explicit_sum + terminal_value_pv
    # 지배주주 귀속 지분가치 = EV +비영업자산 −순차입부채 −비지배지분(NCI).
    equity_value = (enterprise_value + inp.non_operating_assets - inp.net_debt
                    - inp.non_controlling_interest)
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
        non_controlling_interest=inp.non_controlling_interest,
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
