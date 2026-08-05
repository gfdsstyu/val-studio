"""판정 실행기 — 이 계층의 유일한 진입점.

추상화 수준이 "채팅"이 아니라 **"판정"** 이라는 게 설계의 핵심이다: 단발 요청 ·
스키마 강제 · 비스트리밍 · 대화이력 없음. 후보 작업(사업유사성 판정, 계정분류,
findings→수정플랜, 셀맵 인식, 주석 카테고리…)이 전부 이 모양이라 공급자 차이가
어댑터 수십 줄로 접힌다.

계층 규율 — 이 패키지는 **자산 무의존**이다(calc_core 가 IO 를 모르는 것과 동형):
peer 도 계정도 워크북도 모르고, 도메인이 조립해 준 `system`/`prompt` 문자열과
JSON Schema 만 받는다. "에이전트 페이로드는 게이트가 좁힌 최소 조각"이라는 원칙이
타입 수준에서 강제된다.

실패 규약 3가지:
  1. **프로바이더 폴백 금지** — 실패는 다른 모델로 갈아타지 않고 실패로 남는다.
     추측 금지 원칙(도메인은 이걸 uncertain 으로 받는다).
  2. **스키마 불일치는 1회만 재시도** — 어긋난 지점을 알려주고 다시 묻는다.
  3. **프로바이더의 strict 를 신뢰하지 않는다** — 받은 JSON 을 우리가 다시 검사한다
     (`check_shape`). 형식이 맞아도 "값이 말이 되나"는 도메인 게이트 몫.

재현성: 온도 파라미터가 현행 모델에서 제거돼 동일 출력 보장이 원천적으로 불가능하다.
그래서 `JudgeResult.provenance()` 가 provider·실제 모델·프롬프트 해시·attempts 를
남기고, 도메인은 그 산출물을 `suggested`(미승인)로 취급한다.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from .providers import PROVIDERS, ErrorKind, ProviderError
from .registry import PRICING_VINTAGE, Model, estimate_usd, get_model

# check_shape 가 이해하는 타입(우리가 실제로 쓰는 부분집합).
_TYPES: dict[str, type | tuple[type, ...]] = {
    "object": dict, "array": list, "string": str, "boolean": bool,
    "number": (int, float), "integer": int, "null": type(None),
}


def check_shape(data: object, schema: dict, path: str = "$") -> list[str]:
    """JSON Schema **부분집합** 검사 → 위반 목록(빈 리스트면 통과).

    완전한 JSON Schema 구현이 아니다. 우리가 실제로 쓰는 것만 본다:
    `type` · `properties` · `required` · `additionalProperties:false` · `items` · `enum`.
    모르는 키워드는 조용히 통과시킨다(과잉 거부 방지).

    존재 이유: 공급자마다 강제 방식이 다르고(Anthropic output_config /
    OpenAI json_schema / Gemini responseSchema), 어느 쪽이든 "강제했다"를 믿고
    파싱하면 드리프트가 조용히 통과한다. 같은 스키마로 우리가 한 번 더 본다.
    """
    errs: list[str] = []
    t = schema.get("type")
    if t:
        py = _TYPES.get(t)
        if py is None:
            return errs                       # 모르는 타입 — 검사 생략
        # bool 은 int 의 서브클래스 → True 가 number/integer 를 통과하는 함정
        if t in ("number", "integer") and isinstance(data, bool):
            return [f"{path}: {t} 여야 하는데 boolean"]
        if not isinstance(data, py):
            return [f"{path}: {t} 여야 하는데 {type(data).__name__}"]

    if "enum" in schema and data not in schema["enum"]:
        errs.append(f"{path}: 허용값 {schema['enum']} 밖 — {data!r}")

    if isinstance(data, dict) and (
            "properties" in schema or "required" in schema
            or "additionalProperties" in schema):
        props: dict = schema.get("properties", {})
        for k in schema.get("required", []):
            if k not in data:
                errs.append(f"{path}.{k}: 필수 키 누락")
        if schema.get("additionalProperties") is False:
            for k in data:
                if k not in props:
                    errs.append(f"{path}.{k}: 스키마에 없는 키")
        for k, sub in props.items():
            if k in data:
                errs.extend(check_shape(data[k], sub, f"{path}.{k}"))

    if isinstance(data, list) and "items" in schema:
        for i, item in enumerate(data):
            errs.extend(check_shape(item, schema["items"], f"{path}[{i}]"))

    return errs


@dataclass(frozen=True)
class JudgeRequest:
    """판정 1건. `system` 은 배치마다 불변(캐시 접두), `prompt` 가 가변부."""

    system: str
    prompt: str
    schema: dict
    max_tokens: int = 16000
    effort: str | None = None        # low|medium|high|xhigh|max (미지원 모델은 자동 무시)


@dataclass(frozen=True)
class JudgeResult:
    """판정 결과 + 조서에 남길 증적."""

    data: dict | None                # 스키마를 통과한 산출물 (None = 실패)
    provider: str
    model_id: str                    # 실제 응답 모델
    requested_model_id: str
    prompt_sha256: str
    usage: dict = field(default_factory=dict)
    attempts: int = 0
    estimated_usd: float = 0.0
    error: str | None = None
    error_kind: str | None = None

    @property
    def ok(self) -> bool:
        return self.data is not None

    def provenance(self) -> dict:
        """조서용 증적 — `_VS_STATE` 가정 대장의 `source_type=suggested` 와 짝을 이룬다.

        approval="suggested" 가 핵심이다: 이미 있는 미승인 게이트가
        "승인 없이는 하류로 못 흐른다"를 자동으로 집행한다.
        """
        return {
            "method": "llm",
            "provider": self.provider,
            "model": self.model_id,
            "requested_model": self.requested_model_id,
            "prompt_sha256": self.prompt_sha256,
            "attempts": self.attempts,
            "pricing_vintage": PRICING_VINTAGE,
            "approval": "suggested",
        }


def available_models() -> list[Model]:
    """레지스트리 ∩ 구현된 어댑터 — UI 드롭다운의 정본.

    어댑터 없는 모델이 표에 올라가 있어도 여기서 걸러지므로, 사용자가 고를 수 있는데
    호출은 실패하는 상태(기능 정직 표기 위반)가 구조적으로 생기지 않는다.
    """
    from .registry import MODELS
    return [m for m in MODELS if m.provider in PROVIDERS]


def _retry_hint(errors: list[str]) -> str:
    lines = "\n".join(f"- {e}" for e in errors[:12])
    return ("\n\n---\n직전 응답이 요구 형식을 벗어났습니다:\n"
            f"{lines}\n\n같은 작업을 다시 수행하되, 스키마를 정확히 지킨 JSON 만 "
            "반환하세요. 설명 문장을 덧붙이지 마세요.")


def judge(
    req: JudgeRequest,
    *,
    api_key: str,
    model_id: str | None = None,
    timeout: float = 120.0,
    max_attempts: int = 2,
) -> JudgeResult:
    """단발 판정. 스키마 위반은 1회 재시도, 그래도 안 되면 실패로 남긴다."""
    model = get_model(model_id)
    call = PROVIDERS.get(model.provider)
    if call is None:
        raise ValueError(
            f"'{model.provider}' 어댑터 미구현 — 구현된 프로바이더: "
            f"{', '.join(sorted(PROVIDERS))}")
    if not api_key:
        raise ValueError(f"{model.key_header} 헤더 없음")

    # 캐노니컬 프롬프트(재시도 힌트 제외)의 해시 — 같은 질문인지 조서에서 대조 가능.
    canonical = f"{req.system}\n\n{req.prompt}"
    prompt_sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    # 미지원 모델에 effort 를 넘기면 요청 자체가 거부된다(Haiku 4.5).
    effort = req.effort if model.supports_effort else None

    prompt = req.prompt
    last_err: tuple[str, str] | None = None      # (kind, message)
    usage: dict = {}
    actual_model = model.id

    for attempt in range(1, max_attempts + 1):
        try:
            reply = call(
                model_id=model.id, api_key=api_key, system=req.system, prompt=prompt,
                schema=req.schema, max_tokens=req.max_tokens, effort=effort,
                timeout=timeout,
            )
        except ProviderError as e:
            # 프로바이더 레벨 실패는 재시도해도 같다(SDK 가 이미 429/5xx 를 재시도했다).
            # **다른 모델로 갈아타지 않는다** — 실패는 실패로 남긴다.
            return JudgeResult(
                data=None, provider=model.provider, model_id=model.id,
                requested_model_id=model.id, prompt_sha256=prompt_sha,
                attempts=attempt, error=str(e), error_kind=e.kind)

        actual_model = reply.model_id
        usage = reply.usage
        try:
            data = json.loads(reply.text)
        except json.JSONDecodeError as e:
            errors = [f"$: JSON 파싱 실패 — {e}"]
        else:
            errors = check_shape(data, req.schema)
            if not errors:
                return JudgeResult(
                    data=data, provider=model.provider, model_id=actual_model,
                    requested_model_id=model.id, prompt_sha256=prompt_sha,
                    usage=usage, attempts=attempt,
                    estimated_usd=estimate_usd(model, usage.get("input_tokens", 0),
                                               usage.get("output_tokens", 0)))
        last_err = (ErrorKind.SCHEMA.value, "스키마 불일치: " + "; ".join(errors[:6]))
        prompt = req.prompt + _retry_hint(errors)

    kind, message = last_err or (ErrorKind.SCHEMA.value, "스키마 불일치")
    return JudgeResult(
        data=None, provider=model.provider, model_id=actual_model,
        requested_model_id=model.id, prompt_sha256=prompt_sha, usage=usage,
        attempts=max_attempts, error=message, error_kind=kind)
