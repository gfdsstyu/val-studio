"""상대가치(CCA) 트랙 첫 계산코어 — LTM 실적·계절성 지표.

방법론 근거: [[상대가치_계절성_LTM]] — 분·반기 평가에서 `1분기×4` 연환산은 계절성
기업에서 왜곡(과소/과대)되므로, ①계절성이 평가대상과 다른 유사회사는 제외가 원칙
②불가피하면 LTM(최근 4개 분기 누적)으로 보정. 멀티플 엔진 자체는 ⏳향후 —
여기는 그 전제가 되는 실적 정규화 유틸.
"""
from __future__ import annotations


def ltm(quarters: list[float]) -> float:
    """LTM(Last Twelve Months) = 최근 4개 분기 합.

    quarters 는 오래된→최신 순. 4개 미만이면 ValueError(연환산 유혹을 차단 —
    부족하면 명시적으로 다른 방법을 선택해야지 조용히 근사하지 않는다).

    북 골든: [100,120,130,350,120](X1Q1~X2Q1) → 120+130+350+120 = 720.
    """
    if len(quarters) < 4:
        raise ValueError(f"LTM 은 최소 4개 분기 필요(현재 {len(quarters)}개) — "
                         "연환산(×4) 근사는 계절성 왜곡 위험이라 자동 대체하지 않음")
    return float(sum(quarters[-4:]))


def annualize_naive(quarter_value: float) -> float:
    """분기×4 연환산 — 계절성 없는 기업 전제. checks.check_peer_seasonality 로
    사용 가능 여부를 먼저 검사할 것(북: 과소/과대 왜곡 실측 예시)."""
    return quarter_value * 4.0


def max_quarter_share(quarters: list[float]) -> float:
    """최근 4개 분기 중 최대 분기의 연간 비중(계절성 지표).

    북 예시: [100,120,130,350] → 350/700 = 0.50. 균등이면 0.25.
    합이 0 이하(적자·결측)면 판정 불가 — nan 반환(호출측이 uncertain 처리).
    """
    if len(quarters) < 4:
        raise ValueError(f"계절성 판정은 최소 4개 분기 필요(현재 {len(quarters)}개)")
    last4 = quarters[-4:]
    total = sum(last4)
    if total <= 0:
        return float("nan")
    return max(last4) / total
