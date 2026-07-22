"""시나리오 분석 — Upside/Base/Downside 다중 입력세트 실행 + 가중 종합.

방법론 근거: [[리포트예시_클래시스]] 리포트 시트 구조(7.DCF_Upside/_base/
_downside 3-시나리오)·[[모델링_실무_2강4강]] 시나리오 매출방식. 민감도(WACC×g
그리드, dcf.run 내장)가 '파라미터 2개의 국소 요동'이라면, 시나리오는 '가정 세트
전체(매출·마진·CAPEX…)의 대안 세계' — 서로 보완재.

원칙: 시나리오 구성(무엇을 낙관/비관으로 볼지)은 LLM·유저 판단, 계산·집계는
여기(결정론). 가중치는 유저 승인 값만(확률 추정을 자동화하지 않는다).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .dcf import run
from .models import DcfResult, DcfSpineInput


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    weight: float | None            # 미지정이면 None(가중 종합에서 제외)
    result: DcfResult

    @property
    def per_share(self) -> float:
        return self.result.per_share


@dataclass(frozen=True)
class ScenarioAnalysis:
    scenarios: list[ScenarioResult]

    @property
    def weighted_per_share(self) -> float | None:
        """가중평균 주당가치 — 전 시나리오에 가중치가 있고 합≈1 일 때만."""
        ws = [s.weight for s in self.scenarios]
        if any(w is None for w in ws) or not math.isclose(sum(ws), 1.0, rel_tol=1e-9):
            return None
        return sum(s.weight * s.per_share for s in self.scenarios)

    @property
    def spread(self) -> tuple[float, float]:
        """(최소, 최대) 주당가치 — 시나리오 범위(리포트의 밸류 레인지)."""
        vals = [s.per_share for s in self.scenarios]
        return (min(vals), max(vals))

    def to_rows(self) -> list[dict]:
        """리포트용 행: 시나리오별 주당가치·EV·TV비중·가중치."""
        return [{
            "name": s.name,
            "weight": s.weight,
            "per_share": s.per_share,
            "enterprise_value": s.result.enterprise_value,
            "tv_weight": (s.result.terminal_value_pv / s.result.enterprise_value
                          if s.result.enterprise_value else float("nan")),
        } for s in self.scenarios]


def run_scenarios(
    cases: dict[str, DcfSpineInput],
    weights: dict[str, float] | None = None,
) -> ScenarioAnalysis:
    """시나리오명→입력세트 를 각각 dcf.run 으로 계산해 종합.

    weights 가 주어지면 시나리오명 완전 일치 + 합=1 을 요구(부분 가중치·잔여 배분
    같은 암묵 규칙 금지 — 유저 승인 값 그대로만).
    """
    if not cases:
        raise ValueError("시나리오가 비어 있음")
    if weights is not None:
        if set(weights) != set(cases):
            raise ValueError(f"가중치 시나리오명 불일치: {sorted(set(weights) ^ set(cases))}")
        total = sum(weights.values())
        if not math.isclose(total, 1.0, rel_tol=1e-9):
            raise ValueError(f"가중치 합 {total} ≠ 1 — 명시적으로 재배분할 것")
    out = [ScenarioResult(name, (weights or {}).get(name), run(inp))
           for name, inp in cases.items()]
    return ScenarioAnalysis(out)
