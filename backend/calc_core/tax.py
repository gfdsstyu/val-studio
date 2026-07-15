"""한국 법인세 구간세율(2023 기준) — 비올 DCF 모델 재현.

원본 엑셀 수식(DCF!M17)을 그대로 이식::

    IF(EBIT<0, 0,
     IF(EBIT<200,        EBIT*9%*1.1,
      IF(EBIT<20000,     (200*9% + (EBIT-200)*19%)*1.1,
       IF(EBIT<300000,   (200*9% + 19800*19% + (EBIT-20000)*21%)*1.1,
                         (200*9% + 19800*19% + 280000*21% + (EBIT-300000)*24%)*1.1))))

단위: 백만원(KRW mn). 구간(과세표준 EBIT 기준):
  - ≤ 200      (2억원)      : 9%
  - 200~20000  (2억~200억)   : 19%
  - 20000~300000 (200억~3000억): 21%
  - > 300000   (3000억 초과)  : 24%
×1.1 = 지방소득세(법인세의 10%) 포함.

* 누적상수: 19800 = 20000−200 (19% 구간 폭), 280000 = 300000−20000 (21% 구간 폭).
* 원본은 과세표준을 **영업이익(EBIT)** 으로 근사(별도 세무조정 없음). 실무 확장 시
  세무조정·이월결손금은 상위 레이어에서 처리하고 여기엔 과세표준을 넘긴다.
"""
from __future__ import annotations

LOCAL_TAX_GROSS_UP = 1.1  # 지방소득세 10% 포함

# (상한, 한계세율) — 상한 미만 구간에 한계세율 적용. 마지막은 상한 None(무한).
_BRACKETS = [
    (200.0, 0.09),
    (20000.0, 0.19),
    (300000.0, 0.21),
    (None, 0.24),
]


def corporate_tax(taxable_income: float) -> float:
    """구간세율 법인세(지방소득세 포함). 과세표준 ≤ 0 이면 0.

    엑셀의 계단식 IF 를 누진공제 방식으로 동등하게 계산한다.
    """
    if taxable_income <= 0:
        return 0.0
    tax = 0.0
    lower = 0.0
    for upper, rate in _BRACKETS:
        if upper is None or taxable_income < upper:
            tax += (taxable_income - lower) * rate
            break
        tax += (upper - lower) * rate
        lower = upper
    return tax * LOCAL_TAX_GROSS_UP


def effective_rate(taxable_income: float) -> float:
    """유효세율 = 법인세 / 과세표준 (과세표준 0 이하면 0)."""
    if taxable_income <= 0:
        return 0.0
    return corporate_tax(taxable_income) / taxable_income
