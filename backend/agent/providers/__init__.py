"""프로바이더 어댑터 — 공급자별 차이를 여기서만 흡수한다.

`PROVIDERS` 가 **구현된 프로바이더의 정본**이다: 레지스트리에 모델을 올리기 전에
여기 어댑터가 먼저 있어야 하고, 노출 목록은 `agent.judge.available_models()` 가
레지스트리 ∩ 이 표로 만든다(어댑터 없는 모델이 UI 에 뜨는 것을 구조적으로 차단).

공용 타입은 `base.py` — 어댑터가 이 패키지를 다시 임포트하지 않도록 분리했다.
"""
from __future__ import annotations

from .anthropic_client import call as _anthropic_call
from .base import ErrorKind, ProviderCall, ProviderError, ProviderReply

PROVIDERS: dict[str, ProviderCall] = {
    "anthropic": _anthropic_call,
    # "openai":  구현 시 여기 등록 → 그때 registry.MODELS 에 모델 추가
    # "gemini":  동
}

__all__ = ["PROVIDERS", "ErrorKind", "ProviderCall", "ProviderError", "ProviderReply"]
