"""DcfSpineInput/DcfResult → 살아있는 수식 DCF 시트 export.

계산 결과를 하드값이 아니라 **수식**으로 기록해 감사인이 셀을 추적할 수 있게 한다.
가정(WACC·g·주식수 등)은 전용 셀에 두고 절대참조($C$3)로 연결. 법인세는 원본과 동일한
계단식 IF 수식으로 기록. 캐시값(<v>)을 함께 넣어 Excel 없이 열어도 숫자가 보인다.
"""
from __future__ import annotations

from calc_core.models import DcfResult, DcfSpineInput

from .xlsx_writer import Sheet, Workbook

# 명시적 추정기간 5년 → C..G
YEAR_COLS = ["C", "D", "E", "F", "G"]


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
    """스파인 입력+결과 → 살아있는 수식 워크북."""
    wb = Workbook()
    s: Sheet = wb.add_sheet("DCF")
    n = inp.n_years()
    cols = YEAR_COLS[:n]

    s.text("B1", "DCF Valuation (auto-generated, formula-live)")

    # ── 가정 블록 (전용 셀, 절대참조 대상) ──
    s.text("B3", "WACC");            s.num("C3", inp.wacc)
    s.text("B4", "영구성장률(g)");     s.num("C4", inp.terminal_growth)
    s.text("B5", "발행주식수");        s.num("C5", inp.shares_outstanding)
    s.text("B6", "(+)비영업자산");     s.num("C6", inp.non_operating_assets)
    s.text("B7", "(-)순차입부채");     s.num("C7", inp.net_debt)

    # ── 연도 헤더 ──
    R = {"year": 10, "rev": 11, "cogs": 12, "gp": 13, "sga": 14, "ebit": 15,
         "tax": 16, "noplat": 17, "da": 18, "capex": 19, "nwc": 20, "fcff": 21,
         "period": 22, "pvf": 23, "pv": 24}
    s.text("B10", "Year")
    for j, c in enumerate(cols):
        s.num(f"{c}{R['year']}", 2024 + j)

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
        s.formula(f"{c}{R['tax']}", _tax_formula(f"{c}{R['ebit']}"), res.tax[j])
        s.formula(f"{c}{R['noplat']}", f"{c}{R['ebit']}-{c}{R['tax']}", res.noplat[j])
        s.formula(
            f"{c}{R['fcff']}",
            f"{c}{R['noplat']}+{c}{R['da']}-{c}{R['capex']}+{c}{R['nwc']}",
            res.fcff[j],
        )
        s.formula(f"{c}{R['pvf']}", f"1/(1+$C$3)^{c}{R['period']}", res.pv_factor[j])
        s.formula(f"{c}{R['pv']}", f"{c}{R['fcff']}*{c}{R['pvf']}", res.pv_fcff[j])

    last = cols[-1]
    # ── 평가결과 블록 ──
    s.text("B27", "명시적기간 PV합")
    s.formula("C27", f"SUM(C{R['pv']}:{last}{R['pv']})", res.pv_explicit_sum)
    s.text("B28", "Terminal FCFF")
    s.num("C28", res.terminal_fcff)
    s.text("B29", "Terminal Value")
    s.formula("C29", "C28/($C$3-$C$4)", res.terminal_value)
    s.text("B30", "Terminal PV")
    s.formula("C30", f"C29/(1+$C$3)^{last}{R['period']}", res.terminal_value_pv)
    s.text("B31", "기업가치(EV)")
    s.formula("C31", "C27+C30", res.enterprise_value)
    s.text("B32", "주식가치")
    s.formula("C32", "C31+C6-C7", res.equity_value)
    s.text("B33", "주당가치(원)")
    s.formula("C33", "C32/C5*1000000", res.per_share)

    return wb


def export_dcf(inp: DcfSpineInput, res: DcfResult, path: str) -> None:
    build_dcf_sheet(inp, res).save(path)
