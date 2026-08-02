"""DCF 모델 xlsx → DcfSpineInput (export 의 역방향, 왕복).

dcf_export.build_dcf_sheet 이 쓰는 고정 레이아웃을 되읽는다:
  가정: C3=WACC C4=g C5=주식수 C6=비영업자산 C7=순차입부채
  연도(C..G, 명시적 n년): 10=Year 11=매출 12=매출원가 14=판관비
                          18=D&A 19=CAPEX 20=ΔNWC(현금조정) 22=할인기간
결과행(EBIT·세금·FCFF·PV·TV)은 수식이라 읽지 않고 import 후 재계산으로 검증.

오버라이드(개선 A/B)는 META C37~C39·세금행 하드값에서, **페이드(R1)는 META C40~C41**
에서 복원한다 — export 가 페이드 열을 실체화하므로 뒤쪽 fade_years 개 열을 잘라
파라메트릭(3단) 형태로 되돌린다. 재계산 등가성은 test_dcf_roundtrip 이 보증.
"""
from __future__ import annotations

from calc_core.models import DcfSpineInput

from .template_schema import ASSUMP, META, YEAR_COLS
from .template_schema import ROW as _ROW
from .xlsx_reader import read_workbook


class DcfModelImportError(RuntimeError):
    pass


_NOT_STANDARD = (
    "이 워크북은 Val-Studio 표준 레이아웃이 아닙니다({why}).\n"
    "되읽기·왕복 diff 는 **Val-Studio 가 내보낸 xlsx** 에만 동작합니다"
    "(셀 좌표가 template_schema 로 고정돼 있어야 역파싱이 가능).\n"
    "임의 모델(자체 템플릿·타사 모델)은 → **모델 정적 감사**를 쓰세요. "
    "재계산 없이 수식만 분석하므로 레이아웃과 무관하게 동작합니다."
)


def _assert_standard_layout(cells: dict) -> None:
    """되읽기 가능한 표준 레이아웃인지 **먼저** 판정한다.

    없으면 개별 셀에서 "셀 C22 숫자 아님/부재" 같은 좌표 오류가 튀어나오는데, 그 메시지는
    사용자에게 **다음 행동을 알려주지 않는다**(실측 피드백: 임의 워크북으로 되읽기 시도).
    무엇이 왜 안 되는지 + 대신 무엇을 쓰면 되는지를 한 번에 준다.
    """
    def _num(ref: str) -> bool:
        c = cells.get(ref)
        return c is not None and c.number is not None

    missing = []
    if not _num(ASSUMP["wacc"]):
        missing.append(f"가정셀 {ASSUMP['wacc']}(WACC)")
    if not _num(ASSUMP["shares_outstanding"]):
        missing.append(f"가정셀 {ASSUMP['shares_outstanding']}(주식수)")
    if not any(_num(f"{c}{_ROW['year']}") for c in YEAR_COLS):
        missing.append(f"연도 행 {_ROW['year']}")
    if missing:
        raise DcfModelImportError(_NOT_STANDARD.format(why="비어 있음: " + ", ".join(missing)))


def import_dcf_model(path: str, *, sheet: str = "DCF") -> DcfSpineInput:
    """DCF 모델 xlsx → DcfSpineInput. 표준 레이아웃 가정."""
    wb = read_workbook(path)
    if sheet not in wb:
        raise DcfModelImportError(
            _NOT_STANDARD.format(why=f"시트 '{sheet}' 가 없음 — 있는 시트: {', '.join(list(wb)[:8])}"))
    cells = wb[sheet]
    _assert_standard_layout(cells)

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

    # ── 페이드(R1) 파라메트릭 복원 — 실체화된 뒤쪽 k열을 잘라낸다 ──
    # terminal_discount_period 는 자르기 **전** 마지막 열 기준(확장 시계 계약 유지 —
    # export 의 TV 할인 수식과 동일 시점). 엔진이 재확장하면 동일 시계가 복원된다.
    fade_raw = opt(META["fade_years"])
    fade_years = int(round(fade_raw)) if fade_raw else None
    fade_growth = opt(META["fade_growth"])
    term_period = periods[-1]
    n_explicit = n
    if fade_years:
        n_explicit = n - fade_years
        if n_explicit < 1:
            raise DcfModelImportError(
                f"fade_years({fade_years}) ≥ 전체 연도({n}) — META C40 손상 의심"
            )

    def explicit(series):
        return series[:n_explicit] if series is not None else None

    return DcfSpineInput(
        wacc=num(ASSUMP["wacc"]),
        terminal_growth=num(ASSUMP["terminal_growth"]),
        revenue=explicit(row("rev")),
        cogs=explicit(row("cogs")),
        sga=explicit(row("sga")),
        dep_amort=explicit(row("da")),
        capex=explicit(row("capex")),
        delta_nwc_cash_adj=explicit(row("nwc")),
        non_operating_assets=num(ASSUMP["non_operating_assets"]),
        net_debt=num(ASSUMP["net_debt"]),
        # NCI 는 구 워크북(C8 없음) 호환 위해 optional — 없으면 0(브리지 무영향).
        non_controlling_interest=opt(ASSUMP["non_controlling_interest"]) or 0.0,
        shares_outstanding=int(round(num(ASSUMP["shares_outstanding"]))),
        mid_year_periods=explicit(periods),
        terminal_discount_period=term_period,  # 확장 시계 기준(위 주석)
        tax_override=explicit(tax_override),
        effective_tax_rate=opt(META["effective_tax_rate"]),
        terminal_fcff_override=opt(META["terminal_fcff_override"]),
        terminal_reinvestment_rate=opt(META["terminal_reinvestment_rate"]),
        fade_years=fade_years,
        fade_growth=fade_growth,
    )
