"""어댑터 공용 타입 — 패키지 `__init__` 과 각 어댑터가 함께 읽는다(순환 임포트 회피).

어댑터의 계약은 좁다: **한 번의 요청, 스키마를 강제한 JSON 텍스트 한 덩어리**.
스트리밍·멀티턴·툴콜·대화이력이 없다(패널 UI 가 채팅이 아니라 제안 카드이기 때문).
인터페이스가 좁으므로 공급자 하나당 어댑터가 수십 줄에서 끝난다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class ErrorKind(str, Enum):
    """판정 실패의 분류 — HTTP 상태 매핑의 정본.

    문자열로 두면 `_AGENT_STATUS.get(kind, 502)` 같은 fail-open 이 생겨, 새 kind 를
    추가하고 매핑을 빠뜨리면 **인증 오류가 서버 장애로 둔갑**한다(사용자에겐 "내가
    고칠 것"이 "기다릴 것"으로 보인다). 열거로 두고 전수 매핑을 테스트가 강제한다.
    """

    NOT_INSTALLED = "not_installed"   # SDK 미설치(선택 계층)
    AUTH = "auth"                     # 키 거부·권한 없음
    RATE_LIMIT = "rate_limit"
    BAD_REQUEST = "bad_request"       # 스키마 제약 위반 등
    REFUSAL = "refusal"               # 안전 정책 거절
    TRUNCATED = "truncated"           # max_tokens 도달 → JSON 잘림
    SERVER = "server"
    NETWORK = "network"
    SCHEMA = "schema"                 # 재시도 후에도 스키마 불일치(judge 가 낸다)


@dataclass(frozen=True)
class ProviderReply:
    """어댑터의 정규화된 응답. 파싱·스키마 검증은 상위(judge)가 한다."""

    text: str                        # 모델이 낸 JSON 문자열(파싱 전)
    model_id: str                    # **실제로 응답한** 모델(요청 id 와 다를 수 있음)
    usage: dict = field(default_factory=dict)   # input/output/cache 토큰
    stop_reason: str | None = None


class ProviderError(RuntimeError):
    """공급자 호출 실패의 정규화 — `kind` 로 상위가 HTTP 상태를 정한다.

    kind: not_installed | auth | rate_limit | bad_request | refusal | truncated
          | server | network

    ⚠️ 메시지에 **API 키를 절대 담지 않는다**(BYOK: 서버 저장·로깅 0 규약).
    """

    def __init__(self, kind: "ErrorKind | str", message: str) -> None:
        super().__init__(message)
        # 등록되지 않은 kind 는 여기서 ValueError 로 죽는다 — 조용히 502 로 흘려보내는
        # 것보다 개발 중에 터지는 편이 낫다. 소비자에겐 계속 문자열로 보인다.
        self.kind: str = ErrorKind(kind).value


# 어댑터 시그니처(키워드 전용):
#   call(*, model_id, api_key, system, prompt, schema, max_tokens, effort, timeout)
#       -> ProviderReply
ProviderCall = Callable[..., ProviderReply]
