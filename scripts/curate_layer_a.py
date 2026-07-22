"""raw_dump.json → Layer A (DCF spine) 골든 픽스처 생성.

Layer A = 투영 라인아이템(매출/원가/판관비·D&A·CAPEX·ΔNWC)과 WACC/g를 *입력*으로
받아 법인세→NOPLAT→FCFF→PV→EV→주당가치를 재현하는 최소 스파인 테스트.

민감도표는 원본 캐시값이 stale(중심셀≠H49)하므로 expected 에서 제외 — calc_core 가
재계산하고 자기일관성(중심=base)으로 검증한다.
"""
import json
from pathlib import Path

FX = Path(__file__).resolve().parent.parent / "fixtures" / "viol"
dcf = json.loads((FX / "raw_dump.json").read_text(encoding="utf-8"))["sheets"]["DCF"]["cells"]

EXPLICIT_COLS = list("MNOPQ")  # 2024..2028


def v(ref: str) -> float:
    return dcf[ref]["v"]


def row(r: int) -> list[float]:
    return [v(f"{c}{r}") for c in EXPLICIT_COLS]


inputs = {
    "_note": "Layer A: DCF 스파인 입력. 비올 DCF Model 최종본 DCF 시트 M:Q(2024~2028) + 평가결과 입력.",
    "explicit_years": [2024, 2025, 2026, 2027, 2028],
    "wacc": v("H37"),
    "terminal_growth": v("H38"),
    "mid_year_periods": [0.5, 1.5, 2.5, 3.5, 4.5],
    "terminal_discount_period": 4.5,  # 원본은 마지막 명시연도 factor(Q31)로 터미널 할인
    "revenue": row(7),
    "cogs": row(9),
    "sga": row(13),
    "dep_amort": row(22),
    "capex": [-x for x in row(23)],   # row23 은 음수 저장 → 양수 크기로
    "delta_nwc_cash_adj": row(24),    # DCF row24 값(=-WC!15), FCFF 에 그대로 더함
    "non_operating_assets": v("H45"),
    "net_debt": -v("H46"),            # H46 은 음수(-654.71) → 차감액 양수로
    "shares_outstanding": int(v("H48")),
}

expected = {
    "_note": "Layer A 기대 출력(비올 원본 라이브 수식값). 민감도는 stale이라 제외.",
    "ebit": row(15),
    "tax": row(17),
    "noplat": row(19),
    "fcff": row(26),
    "pv_factor": row(31),
    "pv_fcff": row(28),
    "terminal_fcff": v("R26"),
    "terminal_value_pv": v("R28"),
    "pv_explicit_sum": v("H42"),
    "enterprise_value": v("H44"),
    "equity_value": v("H47"),
    "per_share": v("H49"),
}

(FX / "inputs.json").write_text(json.dumps(inputs, ensure_ascii=False, indent=2), encoding="utf-8")
(FX / "expected.json").write_text(json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8")
print("wrote inputs.json / expected.json")
print(f"  per_share(H49) = {expected['per_share']}")
print(f"  EV(H44)        = {expected['enterprise_value']}")
print(f"  equity(H47)    = {expected['equity_value']}")
