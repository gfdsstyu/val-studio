"""DcfSpineInput/DcfResult → 살아있는 수식 DCF 시트 export.

계산 결과를 하드값이 아니라 **수식**으로 기록해 감사인이 셀을 추적할 수 있게 한다.
가정(WACC·g·주식수 등)은 전용 셀에 두고 절대참조($C$3)로 연결. 법인세는 원본과 동일한
계단식 IF 수식으로 기록. 캐시값(<v>)을 함께 넣어 Excel 없이 열어도 숫자가 보인다.
"""
from __future__ import annotations

from calc_core.dcf import expand_fade_input, resolve_fade_growth
from calc_core.models import DcfResult, DcfSpineInput

from .template_schema import (
    ASSUMP,
    BASE_YEAR,
    META,
    META_FLAG_TAX_OVERRIDE,
    RESULT,
    YEAR_COLS,
    abs_cell,
    label_cell,
)
from .template_schema import ROW as R
from .xlsx_writer import Sheet, Workbook


def _tax_formula(ebit_ref: str) -> str:
    """원본 DCF!M17 계단식 법인세(지방소득세 ×1.1) 수식을 ebit 셀 참조로."""
    e = ebit_ref
    return (
        f"IF({e}<0,0,"
        f"IF({e}<200,{e}*0.09*1.1,"
        f"IF({e}<20000,(200*0.09+({e}-200)*0.19)*1.1,"
        f"IF({e}<300000,(200*0.09+19800*0.19+({e}-20000)*0.21)*1.1,"
        f"(200*0.09+19800*0.19+280000*0.21+({e}-300000)*0.24)*1.1))))"
    )


def build_dcf_sheet(inp: DcfSpineInput, res: DcfResult) -> Workbook:
    """스파인 입력+결과 → 살아있는 수식 워크북.

    페이드 모델(R1)은 **확장 열 실체화**로 표현한다: res.* 캐시가 확장 시계(명시+페이드)
    기준이므로 명시 열만 쓰면 PV합·TV 수식이 캐시와 어긋나 recalc 순간 값이 바뀐다
    (갭 실측: C27 캐시 203,834 vs 수식 SUM 127,002). 엔진의 입력확장(expand_fade_input)
    을 그대로 재사용해 전 열을 쓰고, 파라미터(fade_years·해석된 fade_growth)는 META 에
    기록해 import 가 3단 파라메트릭 형태로 복원하게 한다. 모델러스 원본도 명시5+페이드5
    를 10개 열로 표현한다 — 실체화가 원본 관행과 정합.
    """
    fade_meta: tuple[int, float] | None = None
    if inp.fade_years:                       # 비정수·음수는 엔진 확장이 ValueError 로 차단
        fade_meta = (inp.fade_years, resolve_fade_growth(inp, inp.terminal_growth))
        inp = expand_fade_input(inp)         # 등가의 명시 입력(재확장 방지 fade_years=None)

    wb = Workbook()
    s: Sheet = wb.add_sheet("DCF")
    n = inp.n_years()
    if n > len(YEAR_COLS):                   # 조용한 절단 금지 — 명시 에러로 표면화
        raise ValueError(
            f"연도 {n}개가 열 한도 {len(YEAR_COLS)}(YEAR_COLS C..{YEAR_COLS[-1]})를 초과 — "
            "template_schema.YEAR_COLS 확장 필요(명시+페이드 실체화 포함 총 연수)"
        )
    cols = YEAR_COLS[:n]

    s.text("B1", "DCF Valuation (auto-generated, formula-live)")

    # ── 가정 블록 (전용 셀, 절대참조 대상) — 셀 주소는 template_schema.ASSUMP SSOT ──
    a = ASSUMP
    s.text(label_cell(a["wacc"]), "WACC");                       s.num(a["wacc"], inp.wacc)
    s.text(label_cell(a["terminal_growth"]), "영구성장률(g)");     s.num(a["terminal_growth"], inp.terminal_growth)
    s.text(label_cell(a["shares_outstanding"]), "발행주식수");     s.num(a["shares_outstanding"], inp.shares_outstanding)
    s.text(label_cell(a["non_operating_assets"]), "(+)비영업자산"); s.num(a["non_operating_assets"], inp.non_operating_assets)
    s.text(label_cell(a["net_debt"]), "(-)순차입부채");           s.num(a["net_debt"], inp.net_debt)
    s.text(label_cell(a["non_controlling_interest"]), "(-)비지배지분(NCI)"); s.num(a["non_controlling_interest"], inp.non_controlling_interest)

    # ── 연도 헤더 (행 맵은 template_schema.ROW SSOT) ──
    s.text(f"B{R['year']}", "Year")
    for j, c in enumerate(cols):
        s.num(f"{c}{R['year']}", BASE_YEAR + j)

    def put_row(key, label, values):
        s.text(f"B{R[key]}", label)
        for c, v in zip(cols, values):
            s.num(f"{c}{R[key]}", v)

    # 입력(하드값) 라인
    put_row("rev", "매출", inp.revenue)
    put_row("cogs", "매출원가", inp.cogs)
    put_row("sga", "판매관리비", inp.sga)
    put_row("da", "(+)감가상각(D&A)", inp.dep_amort)
    put_row("capex", "(-)CAPEX", inp.capex)
    put_row("nwc", "(-)ΔNWC(현금조정)", inp.delta_nwc_cash_adj)
    put_row("period", "할인기간(중간연도)", inp.mid_year_periods or [i - 0.5 for i in range(1, n + 1)])

    # 수식 라인 (감사 추적)
    s.text(f"B{R['gp']}", "매출총이익")
    s.text(f"B{R['ebit']}", "영업이익(EBIT)")
    s.text(f"B{R['tax']}", "법인세(구간세율)")
    s.text(f"B{R['noplat']}", "NOPLAT")
    s.text(f"B{R['fcff']}", "FCFF")
    s.text(f"B{R['pvf']}", "현가계수")
    s.text(f"B{R['pv']}", "PV of FCFF")
    for j, c in enumerate(cols):
        s.formula(f"{c}{R['gp']}", f"{c}{R['rev']}-{c}{R['cogs']}", res.ebit[j] + inp.sga[j])
        s.formula(f"{c}{R['ebit']}", f"{c}{R['gp']}-{c}{R['sga']}", res.ebit[j])
        # 세금(개선 A): override면 하드값, effective_tax_rate면 EBIT×율, 아니면 구간세율.
        if inp.tax_override is not None:
            s.num(f"{c}{R['tax']}", res.tax[j])
        elif inp.effective_tax_rate is not None:
            s.formula(f"{c}{R['tax']}", f"{c}{R['ebit']}*{abs_cell(META['effective_tax_rate'])}", res.tax[j])
        else:
            s.formula(f"{c}{R['tax']}", _tax_formula(f"{c}{R['ebit']}"), res.tax[j])
        s.formula(f"{c}{R['noplat']}", f"{c}{R['ebit']}-{c}{R['tax']}", res.noplat[j])
        s.formula(
            f"{c}{R['fcff']}",
            f"{c}{R['noplat']}+{c}{R['da']}-{c}{R['capex']}+{c}{R['nwc']}",
            res.fcff[j],
        )
        s.formula(f"{c}{R['pvf']}", f"1/(1+{abs_cell(ASSUMP['wacc'])})^{c}{R['period']}", res.pv_factor[j])
        s.formula(f"{c}{R['pv']}", f"{c}{R['fcff']}*{c}{R['pvf']}", res.pv_fcff[j])

    last = cols[-1]
    # ── 평가결과 블록 (셀 주소는 template_schema.RESULT SSOT) ──
    wacc_a = abs_cell(ASSUMP["wacc"])
    g_a = abs_cell(ASSUMP["terminal_growth"])
    tf, tv = RESULT["terminal_fcff"], RESULT["terminal_value"]
    pve, ev = RESULT["pv_explicit"], RESULT["enterprise_value"]
    s.text(label_cell(pve), "명시적기간 PV합")
    s.formula(pve, f"SUM(C{R['pv']}:{last}{R['pv']})", res.pv_explicit_sum)
    s.text(label_cell(tf), "Terminal FCFF")
    s.num(tf, res.terminal_fcff)
    s.text(label_cell(tv), "Terminal Value")
    s.formula(tv, f"{tf}/({wacc_a}-{g_a})", res.terminal_value)
    s.text(label_cell(RESULT["terminal_value_pv"]), "Terminal PV")
    s.formula(RESULT["terminal_value_pv"], f"{tv}/(1+{wacc_a})^{last}{R['period']}", res.terminal_value_pv)
    s.text(label_cell(ev), "기업가치(EV)")
    s.formula(ev, f"{pve}+{RESULT['terminal_value_pv']}", res.enterprise_value)
    s.text(label_cell(RESULT["equity_value"]), "주식가치")
    s.formula(RESULT["equity_value"],
              f"{ev}+{ASSUMP['non_operating_assets']}-{ASSUMP['net_debt']}-{ASSUMP['non_controlling_interest']}",
              res.equity_value)
    s.text(label_cell(RESULT["per_share"]), "주당가치(원)")
    s.formula(RESULT["per_share"],
              f"{RESULT['equity_value']}/{ASSUMP['shares_outstanding']}*1000000", res.per_share)

    # ── 모델 메타(개선 A/B 오버라이드) — import 완전 왕복용. 설정된 것만 기록 ──
    s.text("B35", "── 모델 메타(오버라이드) ──")
    if inp.effective_tax_rate is not None:
        s.text(label_cell(META["effective_tax_rate"]), "effective_tax_rate")
        s.num(META["effective_tax_rate"], inp.effective_tax_rate)
    if inp.terminal_fcff_override is not None:
        s.text(label_cell(META["terminal_fcff_override"]), "terminal_fcff_override")
        s.num(META["terminal_fcff_override"], inp.terminal_fcff_override)
    if inp.terminal_reinvestment_rate is not None:
        s.text(label_cell(META["terminal_reinvestment_rate"]), "terminal_reinvestment_rate")
        s.num(META["terminal_reinvestment_rate"], inp.terminal_reinvestment_rate)
    # tax_override 는 세금 행(하드값)에서 복원되므로 별도 셀 불요(플래그만).
    if inp.tax_override is not None:
        s.text(META_FLAG_TAX_OVERRIDE, "tax_override=행16하드값")
    # 페이드(R1): 실체화된 열의 파라메트릭 원형 — import 가 뒤쪽 k열을 잘라 복원.
    # fade_growth 는 **해석된 값**을 기록(자동산출 AVERAGE 규칙이 바뀌어도 왕복 불변).
    if fade_meta is not None:
        s.text(label_cell(META["fade_years"]), "fade_years(실체화된 뒤쪽 열 수)")
        s.num(META["fade_years"], fade_meta[0])
        s.text(label_cell(META["fade_growth"]), "fade_growth(해석값)")
        s.num(META["fade_growth"], fade_meta[1])

    return wb


def export_dcf(inp: DcfSpineInput, res: DcfResult, path: str) -> None:
    build_dcf_sheet(inp, res).save(path)
