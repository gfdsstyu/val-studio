"""풀모델 템플릿(valstudio-full-v1) 레이아웃 — 셀맵 선언 + 되읽기(import).

`ValStudio_DCF_Template.xlsx`(루트 정본, 실무 표준 파생 풀모델)의 DCF 시트 좌표 SSOT.
기존 `template_schema`(스파인 export 레이아웃)와 **별개 레이아웃**이며 서로 대체하지
않는다 — export 왕복은 template_schema, 풀모델 되읽기는 이 모듈이 담당한다.

좌표 구조(실측):
  가정   H37=WACC(=WACC!D43) · H38=g · H36=평가기준일
  스파인 행7 매출 / 9 매출원가 / 13 판관비 / 22 (+)D&A / 23 (-)CAPEX / 24 ΔNWC(현금조정)
        추정기간 = M..Q 5개년(H..L 은 실적, R 은 Terminal)
  할인   행30 Period(mid-year) / R26 = Terminal FCFF(전 라인 ×(1+g) 재계산)
  결과   H42 PV합 / H45 (+)비영업 / H46 (-)이자부부채(음수 기입 규약) / H48 유통주식수
        H49 주당가치(원)

부호 규약(엔진 DcfSpineInput 과의 번역):
  · capex: 엔진=양수 크기, 시트 M23=음수 표시(=-FA!M10) → **부호 반전**해 복원.
  · net_debt: 엔진=양수 크기 차감, 시트 H46=음수 기입(SUM 브리지) → **부호 반전**.
  · delta_nwc_cash_adj: DCF 현금조정 부호 그대로(원 스파인과 동일 규약) — 반전 없음.

수식 셀은 **캐시값**을 읽는다 → Excel 에서 열어 저장(재계산)된 파일만 되읽기 가능.
openpyxl 로 갓 생성된 템플릿(캐시 없음)은 명시 에러로 안내한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from calc_core.models import DcfSpineInput

from .xlsx_reader import RCell, read_workbook

LAYOUT_ID = "valstudio-full-v1"
SHEET = "DCF"
FCOLS = ["M", "N", "O", "P", "Q"]        # 추정기간 5개년(고정)

# 단일 셀 슬롯
CELLS = {
    "wacc": "H37",
    "terminal_growth": "H38",
    "shares_outstanding": "H48",
    "non_operating_assets": "H45",       # 양수 기입
    "net_debt_signed": "H46",            # 음수 기입 규약 → 부호 반전해 복원
    "terminal_fcff": "R26",              # 터미널 FCFF(캐시) → override 로 재현
    "terminal_period": "Q30",            # 터미널 할인기간 = 마지막 명시연도 factor
    "claimed_per_share": "H49",          # 워크북 주장값(tie-out 대조 대상)
}
# 시계열 행 (엔진 필드 → (행, 부호계수))
ROWS = {
    "revenue": (7, 1.0),
    "cogs": (9, 1.0),
    "sga": (13, 1.0),
    "dep_amort": (22, 1.0),
    "capex": (23, -1.0),                 # 시트 음수 표시 → 양수 크기로
    "delta_nwc_cash_adj": (24, 1.0),
    "_period": (30, 1.0),                # mid-year 할인기간
}
# 레이아웃 지문(라벨) — _VS_STATE 없는 파일의 구조 판별용
_FINGERPRINT = {"D37": "WACC", "D48": "유통주식수", "D49": "주당가치", "C26": "FCFF"}


class FullModelImportError(RuntimeError):
    pass


@dataclass
class FullModelMeta:
    """되읽기 부속 정보 — tie-out 대조·경고 표면화용."""

    layout: str = LAYOUT_ID
    claimed_per_share: float | None = None
    terminal_fcff_override: float | None = None
    warnings: list[str] = field(default_factory=list)


def detect_fullmodel(wb: dict[str, dict[str, RCell]]) -> bool:
    """풀모델 레이아웃 판별 — ① _VS_STATE layout 키 ② DCF 시트 라벨 지문.

    ①이 우선(명시 선언). ②는 상태 시트가 지워진 파일의 폴백 — 라벨 4개 중 3개
    이상 일치면 참(라벨 1개쯤은 사용자가 고칠 수 있다).
    """
    for name, sheet in wb.items():
        if name.strip().lstrip("_").replace(" ", "").upper() != "VS_STATE":
            continue
        for ref, cell in sheet.items():
            if ref.startswith("A") and cell.value == "layout":
                b = sheet.get("B" + ref[1:])
                if b is not None and b.value == LAYOUT_ID:
                    return True
    dcf = wb.get(SHEET)
    if not dcf:
        return False
    hits = sum(1 for ref, want in _FINGERPRINT.items()
               if (c := dcf.get(ref)) is not None
               and isinstance(c.value, str) and want in c.value)
    return hits >= 3


def _num(cells: dict[str, RCell], ref: str, what: str, *,
         required: bool = True) -> float | None:
    c = cells.get(ref)
    if c is None or c.number is None:
        if not required:
            return None
        hint = ""
        if c is not None and c.formula:
            hint = (" — 수식은 있으나 캐시값이 없습니다. Excel 에서 열어 저장"
                    "(재계산)한 파일이어야 되읽을 수 있습니다")
        raise FullModelImportError(f"셀 {SHEET}!{ref}({what}) 숫자 없음{hint}")
    return c.number


def import_fullmodel(path: str) -> tuple[DcfSpineInput, FullModelMeta]:
    """풀모델 템플릿 xlsx → (DcfSpineInput, meta). 캐시값 기반 결정론 복원."""
    wb = read_workbook(path)
    if SHEET not in wb:
        raise FullModelImportError(
            f"시트 '{SHEET}' 없음 — 있는 시트: {', '.join(list(wb)[:8])}")
    cells = wb[SHEET]
    meta = FullModelMeta()

    series: dict[str, list[float]] = {}
    for fld, (row, sign) in ROWS.items():
        series[fld] = [sign * _num(cells, f"{c}{row}", fld) for c in FCOLS]
    if any(v < 0 for v in series["capex"]):
        meta.warnings.append(
            "CAPEX 행(23)에 양수 기입 감지 — 시트 규약은 음수 표시((-)CAPEX). 부호 확인 필요")

    net_debt_signed = _num(cells, CELLS["net_debt_signed"], "이자부부채", required=False) or 0.0
    if net_debt_signed > 0:
        meta.warnings.append(
            "H46(이자부부채)에 양수 기입 — 시트 규약은 음수 기입(SUM 브리지). 부호 확인 필요")

    meta.terminal_fcff_override = _num(cells, CELLS["terminal_fcff"],
                                       "터미널 FCFF", required=False)
    meta.claimed_per_share = _num(cells, CELLS["claimed_per_share"],
                                  "주당가치", required=False)

    inp = DcfSpineInput(
        wacc=_num(cells, CELLS["wacc"], "WACC"),
        terminal_growth=_num(cells, CELLS["terminal_growth"], "영구성장률"),
        revenue=series["revenue"], cogs=series["cogs"], sga=series["sga"],
        dep_amort=series["dep_amort"], capex=series["capex"],
        delta_nwc_cash_adj=series["delta_nwc_cash_adj"],
        non_operating_assets=_num(cells, CELLS["non_operating_assets"],
                                  "비영업자산", required=False) or 0.0,
        net_debt=-net_debt_signed,
        shares_outstanding=int(_num(cells, CELLS["shares_outstanding"], "유통주식수")),
        mid_year_periods=series["_period"],
        terminal_discount_period=_num(cells, CELLS["terminal_period"],
                                      "터미널 할인기간", required=False),
        terminal_fcff_override=meta.terminal_fcff_override,
    )
    return inp, meta
