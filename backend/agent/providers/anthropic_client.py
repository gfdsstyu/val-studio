"""Anthropic 어댑터 — 공식 SDK(`anthropic`) 로 구조화 출력 1회 요청.

**lazy import**: SDK 임포트는 함수 안에서 한다(레포 규약 — requirements.txt 주석).
미설치 배포에서는 이 엔드포인트만 실패하고 프로세스는 정상 기동한다(pykrx 와 동일).

현행 모델(Opus 5 계열)에서 반드시 지켜야 하는 것 — 어기면 400:
  · `temperature` / `top_p` / `top_k` 는 **파라미터가 제거**됐다. 넘기지 않는다.
    (= 온도로 결정론을 살 수 없다. 재현성은 게이트 채점과 provenance 로 확보한다.)
  · `thinking={"type":"enabled","budget_tokens":N}` 도 제거됐다. 깊이는 `effort`.
  · `thinking` 을 **생략**하면 Opus 5 는 adaptive 로 돈다(끄지 않는다 — 끄면 응답에
    `<thinking>` 태그가 새는 실패 모드가 있어 JSON 파싱이 깨진다).
  · `max_tokens` 는 사고+응답을 **합쳐서** 캡한다 → 여유를 두고, 도달 시 잘린 JSON 을
    파싱하지 말고 명시적으로 실패시킨다.
  · `output_config.effort` 는 Opus/Sonnet 5 계열만 받는다 → 호출자가 미지원 모델에
    None 을 넘긴다(`registry.Model.supports_effort`).

캐싱: system 블록에 `cache_control` 을 건다. system(역할·규약)은 배치마다 불변이고
가변부(대상·후보 목록)는 user 메시지에 있으므로 "공유 접두 + 가변 접미" 패턴이 성립한다
— 접두가 최소 캐시 길이에 못 미치면 조용히 미적용될 뿐 오류가 아니다.

**server-side `fallbacks` 는 의도적으로 쓰지 않는다.** 거절 시 다른 모델로 자동
전환하는 기능인데, ①우리 설계에서 실패는 폴백이 아니라 `uncertain`(추측 금지)이고
②사용자가 고른 모델과 실제 판정 모델이 갈리면 조서의 "무엇이 판정했나"가 흐려진다.
대신 `stop_reason == "refusal"` 을 명시적으로 잡아 상위에 올린다.
"""
from __future__ import annotations

from .base import ProviderError, ProviderReply


def call(
    *,
    model_id: str,
    api_key: str,
    system: str,
    prompt: str,
    schema: dict,
    max_tokens: int = 16000,
    effort: str | None = None,
    timeout: float = 120.0,
) -> ProviderReply:
    """단발 판정 요청 → JSON 텍스트. 실패는 전부 ProviderError 로 정규화."""
    try:
        import anthropic
    except ImportError as e:                      # 선택 계층 미설치
        raise ProviderError(
            "not_installed",
            "anthropic SDK 미설치 — `pip install anthropic` (requirements.txt [선택] 블록)",
        ) from e

    client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=2)

    output_config: dict = {"format": {"type": "json_schema", "schema": schema}}
    if effort:
        output_config["effort"] = effort

    try:
        msg = client.messages.create(
            model=model_id,
            max_tokens=max_tokens,
            # 불변 접두 = 캐시 대상. 가변부는 user 메시지로 간다.
            system=[{"type": "text", "text": system,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
            output_config=output_config,
        )
    except anthropic.AuthenticationError as e:
        raise ProviderError("auth", "Anthropic 키가 거부됐습니다(권한·유효성 확인).") from e
    except anthropic.PermissionDeniedError as e:
        raise ProviderError("auth", f"권한 없음 — 모델 접근 권한을 확인하세요: {model_id}") from e
    except anthropic.RateLimitError as e:
        raise ProviderError("rate_limit", "속도 제한 — 잠시 후 재시도하세요.") from e
    except anthropic.NotFoundError as e:
        raise ProviderError("bad_request", f"모델을 찾을 수 없습니다: {model_id}") from e
    except anthropic.BadRequestError as e:
        # 스키마 제약 위반(재귀·수치제약·additionalProperties 누락)이 여기로 온다.
        raise ProviderError("bad_request", f"요청 거부: {e}") from e
    except anthropic.APIConnectionError as e:
        raise ProviderError("network", f"네트워크 오류: {e}") from e
    except anthropic.APIStatusError as e:
        raise ProviderError("server", f"API 오류({e.status_code}): {e}") from e

    stop = getattr(msg, "stop_reason", None)
    if stop == "refusal":
        raise ProviderError(
            "refusal",
            "모델이 안전 정책으로 응답을 거절했습니다 — 입력 자료를 확인하세요.")
    if stop == "max_tokens":
        raise ProviderError(
            "truncated",
            f"max_tokens({max_tokens}) 도달 — JSON 이 잘렸습니다. "
            "max_tokens 를 올리거나 후보를 나눠 보내세요.")

    text = next((b.text for b in msg.content if getattr(b, "type", None) == "text"), "")
    if not text.strip():
        raise ProviderError("server", f"빈 응답(stop_reason={stop}).")

    u = getattr(msg, "usage", None)
    usage = {
        "input_tokens": getattr(u, "input_tokens", 0) or 0,
        "output_tokens": getattr(u, "output_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
    }
    # 요청 id 가 아니라 **응답이 밝힌 모델**을 기록한다(조서의 "무엇이 판정했나").
    return ProviderReply(text=text, model_id=getattr(msg, "model", model_id) or model_id,
                         usage=usage, stop_reason=stop)
