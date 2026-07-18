"""DCF 모델 xlsx → DcfSpineInput (export 의 역방향, 왕복).

dcf_export.build_dcf_sheet 이 쓰는 고정 레이아웃을 되읽는다:
  가정: C3=WACC C4=g C5=주식수 C6=비영업자산 C7=순차입부채
  연도(C..G, 명시적 n년): 10=Year 11=매출 12=매출원가 14=판관비
                          18=D&A 19=CAPEX 20=ΔNWC(현금조정) 22=할인기간
결과행(EBIT·세금·FCFF·PV·TV)은 수식이라 읽지 않고 import 후 재계산으로 검증.

참고: 현재 export 는 개선 A/B 오버라이드(tax_override·terminal_fcff_override)를 입력셀로
남기지 않으므로(세금=구간세율 수식, terminal_fcff=하드값), 오버라이드 모델의 완전 왕복은
export 확장 후 가능. 표준 모델(오버라이드 없음)은 완전 왕복된다.
"""
from __future__ import annotations

from calc_core.models import DcfSpineInput

from .template_schema import ASSUMP, META, YEAR_COLS
from .template_schema import ROW as _ROW
from .xlsx_reader import read_workbook


class DcfModelImportError(RuntimeError):
    pass


def import_dcf_model(path: str, *, sheet: str = "DCF") -> DcfSpineInput:
    """DCF 모델 xlsx → DcfSpineInput. 표준 레이아웃 가정."""
    wb = read_workbook(path)
    if sheet not in wb:
        raise DcfModelImportError(f"시트 '{sheet}' 없음: {list(wb)}")
    cells = wb[sheet]

    def num(ref: str) -> float:
        c = cells.get(ref)
        if c is None or c.number is None:
            raise DcfModelImportError(f"셀 {ref} 숫자 아님/부재")
        return c.number

    # 명시적 연도 수 = Year 행에 값이 있는 열 개수
    n = sum(1 for col in YEAR_COLS if cells.get(f"{col}{_ROW['year']}") and
            cells[f"{col}{_ROW['year']}"].number is not None)
    if n == 0:
        raise DcfModelImportError("Year 행에 연도 없음")
    cols = YEAR_COLS[:n]

    def row(key: str) -> list[float]:
        return [num(f"{c}{_ROW[key]}") for c in cols]

    periods = row("period")

    # ── 개선 A/B 오버라이드 복원(메타/세금행) ──
    def opt(ref: str) -> float | None:
        c = cells.get(ref)
        return c.number if c and c.number is not None else None

    # 세금 행이 수식(구간세율)이 아니라 하드값이면 tax_override.
    tax_cells = [cells.get(f"{c}{_ROW['tax']}") for c in cols]
    tax_override = None
    if tax_cells and all(t is not None and t.formula is None for t in tax_cells):
        tax_override = [t.number for t in tax_cells]

    return DcfSpineInput(
        wacc=num(ASSUMP["wacc"]),
        terminal_growth=num(ASSUMP["terminal_growth"]),
        revenue=row("rev"),
        cogs=row("cogs"),
        sga=row("sga"),
        dep_amort=row("da"),
        capex=row("capex"),
        delta_nwc_cash_adj=row("nwc"),
        non_operating_assets=num(ASSUMP["non_operating_assets"]),
        net_debt=num(ASSUMP["net_debt"]),
        # NCI 는 구 워크북(C8 없음) 호환 위해 optional — 없으면 0(브리지 무영향).
        non_controlling_interest=opt(ASSUMP["non_controlling_interest"]) or 0.0,
        shares_outstanding=int(round(num(ASSUMP["shares_outstanding"]))),
        mid_year_periods=periods,
        terminal_discount_period=periods[-1],  # export 는 마지막 명시연도 factor 로 할인
        tax_override=tax_override,
        effective_tax_rate=opt(META["effective_tax_rate"]),
        terminal_fcff_override=opt(META["terminal_fcff_override"]),
        terminal_reinvestment_rate=opt(META["terminal_reinvestment_rate"]),
    )
