"""모델 레지스트리 — 프론트 드롭다운·비용 추정·프로바이더 디스패치가 읽는 단일 정본.

가격은 **정적 내장 + vintage** 다(`ingest/damodaran.py` CRP 와 같은 규약): 외부 가격
API 를 매번 치지 않는 대신 "언제 기준 값인가"를 함께 들고 다녀, 낡은 숫자가 조용히
살아있는 것을 막는다. 가격이 바뀌면 `PRICING_VINTAGE` 를 반드시 함께 올린다.

⚠️ **표에 올린다 = 고를 수 있다고 선언한다.** 어댑터가 없는 프로바이더의 모델을 올리면
UI 에는 뜨는데 호출은 실패한다(기능 정직 표기 위반). 어댑터를 먼저 만들고 올린다 —
현재 구현된 프로바이더는 `agent.providers.PROVIDERS` 가 정본이고, 노출 목록은
`agent.judge.available_models()` 가 그 교집합으로 만든다.

⚠️ **`supports_effort`**: `output_config.effort` 는 Opus 5 / Sonnet 5 계열만 받는다.
Haiku 4.5 에 넘기면 요청이 거부되므로 어댑터가 이 플래그를 보고 떨군다. 모델 선택
기능을 붙이는 순간 생기는 함정이라 모델 속성으로 박아둔다.
"""
from __future__ import annotations

from dataclasses import dataclass

# 아래 단가·컨텍스트의 기준일. 가격 수정 시 함께 갱신할 것.
PRICING_VINTAGE = "2026-08-04"


@dataclass(frozen=True)
class Model:
    """호출 가능한 모델 1종. 단가는 USD / 100만 토큰."""

    provider: str                    # "anthropic" | (향후) "openai" | "gemini"
    id: str                          # API 에 그대로 넘기는 문자열(날짜 접미사 금지)
    label: str                       # UI 표시명
    input_usd_per_mtok: float
    output_usd_per_mtok: float
    context: str                     # 사람이 읽는 컨텍스트 표기("1M")
    tier: str                        # "judge"=정확도 우선 / "bulk"=대량·저가
    supports_effort: bool = True     # output_config.effort 수용 여부
    intro_input_usd_per_mtok: float | None = None    # 도입가(있으면)
    intro_output_usd_per_mtok: float | None = None
    intro_until: str | None = None                   # 도입가 종료일 YYYY-MM-DD
    note: str = ""

    @property
    def key_header(self) -> str:
        """이 모델을 부르는 데 필요한 BYOK 헤더명(서버 저장·로깅 0 규약)."""
        return {"anthropic": "X-Anthropic-Key",
                "openai": "X-OpenAI-Key",
                "gemini": "X-Gemini-Key"}.get(self.provider, "X-Api-Key")

    def to_dict(self) -> dict:
        return {
            "provider": self.provider, "id": self.id, "label": self.label,
            "input_usd_per_mtok": self.input_usd_per_mtok,
            "output_usd_per_mtok": self.output_usd_per_mtok,
            "context": self.context, "tier": self.tier,
            "supports_effort": self.supports_effort,
            "intro": None if self.intro_input_usd_per_mtok is None else {
                "input_usd_per_mtok": self.intro_input_usd_per_mtok,
                "output_usd_per_mtok": self.intro_output_usd_per_mtok,
                "until": self.intro_until,
            },
            "key_header": self.key_header, "note": self.note,
        }


# 단가·컨텍스트 출처: Anthropic 공식 모델표(PRICING_VINTAGE 기준 실측).
MODELS: tuple[Model, ...] = (
    Model(
        provider="anthropic", id="claude-opus-5", label="Claude Opus 5",
        input_usd_per_mtok=5.00, output_usd_per_mtok=25.00, context="1M", tier="judge",
        note="판정·수정플랜 등 정확도 우선 작업의 기본값",
    ),
    Model(
        provider="anthropic", id="claude-sonnet-5", label="Claude Sonnet 5",
        input_usd_per_mtok=3.00, output_usd_per_mtok=15.00, context="1M", tier="bulk",
        intro_input_usd_per_mtok=2.00, intro_output_usd_per_mtok=10.00,
        intro_until="2026-08-31",
        note="대량 판정용. 도입가 $2/$10 은 2026-08-31 까지",
    ),
    Model(
        provider="anthropic", id="claude-haiku-4-5", label="Claude Haiku 4.5",
        input_usd_per_mtok=1.00, output_usd_per_mtok=5.00, context="200K", tier="bulk",
        supports_effort=False,
        note="최저가·최속. effort 미지원(넘기면 요청 거부) → 어댑터가 자동으로 떨군다",
    ),
)

# Anthropic 공식 권고 기본값. 사용자가 명시적으로 다른 모델을 고르지 않는 한 이것.
DEFAULT_MODEL_ID = "claude-opus-5"


def get_model(model_id: str | None) -> Model:
    """모델 id → Model. None 이면 기본값. 미등록 id 는 후보를 붙여 ValueError."""
    wanted = model_id or DEFAULT_MODEL_ID
    for m in MODELS:
        if m.id == wanted:
            return m
    known = ", ".join(m.id for m in MODELS)
    raise ValueError(f"미등록 모델 '{wanted}' — 등록된 모델: {known}")


def estimate_usd(model: Model, input_tokens: int, output_tokens: int) -> float:
    """토큰 수 → 예상 비용(USD).

    **정가 기준**으로만 계산한다 — 도입가는 종료일이 지나면 조용히 과소 추정이 되므로,
    보수적으로 정가를 쓰고 도입가는 `Model.intro_*` 로 UI 에 안내만 한다.
    캐시 읽기 할인(≈0.1배)·배치 할인(0.5배)은 반영하지 않는다(역시 과소 추정 방지).
    """
    return (input_tokens * model.input_usd_per_mtok
            + output_tokens * model.output_usd_per_mtok) / 1_000_000
