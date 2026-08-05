"""agent — 판정(judgment) 전용 LLM 계층. 자산 무의존(도메인을 모른다).

경계: **에이전트 산출물을 결정론이 채점할 수 있는 자리에만** 쓴다. 채점 장치가 없는
작업(임의 워크북 자유 조작, 사용자 의도 해석)은 이 계층의 일이 아니다.
설계 근거: docs/plan/agent_transplant_walkthrough.md
"""
from __future__ import annotations

from .judge import JudgeRequest, JudgeResult, available_models, check_shape, judge
from .registry import DEFAULT_MODEL_ID, MODELS, PRICING_VINTAGE, Model, get_model

__all__ = [
    "DEFAULT_MODEL_ID", "MODELS", "PRICING_VINTAGE", "JudgeRequest", "JudgeResult",
    "Model", "available_models", "check_shape", "get_model", "judge",
]
