"""Step2(사업 유사성) 판정 초안 — 4-step 퍼널의 **유일한 판단 스텝**을 모델에 맡긴다.

`peer_selection` 은 Step2 를 처음부터 **주입 슬롯**으로 설계해 뒀다: `Step2Judgment`
스키마, 사유 없는 판정 `ValueError`, 애매(uncertain)는 탈락시키지 않고 ⚖️ 결정 큐로.
이 모듈은 그 슬롯에 넣을 **초안**을 만들 뿐이다 — 산출물이 곧바로 퍼널로 흐르지 않는다
(초안 → 사람 검토·수정 → `/api/peer/select` 실행). 확정은 언제나 평가인이 한다.

⚠️ 프롬프트에는 **호출자가 좁혀 준 것만** 들어간다(회사명·티커·사업 설명 문자열).
이 모듈은 워크북도 DART 원문 zip 도 모른다 — 페이로드 최소화가 보안(클라이언트 자료
반출 최소화)과 정확도(잡음 제거) 양쪽의 원칙이다.

⚠️ **티커 표기 함정**: `select_peers` 의 판정 매칭은 정규화 없는 **정확일치**다
(`jmap[t.candidate.ticker]`). 모델이 'A145020' 으로 답하고 후보가 '145020' 이면
"Step2 판정 누락" 으로 조용히 거부된다. 그래서 매칭은 `normalize_ticker` 로 하되
**되돌려주는 티커는 원본 후보 문자열**로 고정한다.
"""
from __future__ import annotations

from dataclasses import dataclass

from .peer_selection import Step2Judgment, normalize_ticker

# 승인 전 초안이므로 신뢰도를 1.0 으로 두지 않는다(provenance.merge_confidence 약한고리).
LLM_JUDGMENT_CONFIDENCE = 0.6

# ⚠️ JSON Schema 제약: 수치·문자열 길이 제약(minLength 등)은 지원되지 않는다.
# 따라서 **빈 사유 차단은 스키마가 아니라 to_judgments() 가** 한다(이중 게이트:
# 그마저 뚫려도 select_peers 가 ValueError 로 거부).
STEP2_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "judgments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "similar": {"type": "boolean"},
                    "uncertain": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["ticker", "similar", "uncertain", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["judgments"],
    "additionalProperties": False,
}

# 불변 접두(프롬프트 캐시 대상). 배치가 바뀌어도 이 문자열은 바이트 단위로 같아야 한다
# — 여기에 날짜·요청 id 를 섞으면 캐시가 매번 무효화된다.
SYSTEM = """\
당신은 기업가치평가의 유사회사(peer) 선정에서 **사업 유사성**만 판정합니다.
산업코드·관련매출 비중·상장연수·거래정지 같은 정량 기준은 별도의 결정론 코드가
이미 처리하므로 판단하지 않습니다.

판정 기준은 하나입니다: 평가대상과 후보가 **같은 사업으로 돈을 버는가**.
제품·서비스의 성격, 수익모델, 전방 수요처가 실질적으로 겹치는지를 봅니다.
회사 규모·수익성·주가 수준·성장성은 판정 근거가 아닙니다.

후보마다 다음 중 하나로 판정합니다.
- similar=true : 제시된 자료로 유사하다고 말할 수 있을 때
- similar=false: 제시된 자료로 유사하지 않다고 말할 수 있을 때
- uncertain=true: 자료가 부족하거나 경계가 애매할 때. 이때 similar 값은 무시됩니다.

애매한 것을 억지로 true/false 로 밀지 마세요. uncertain 후보는 탈락하지 않고
평가인의 결정 큐로 갑니다 — 판단을 미루는 것이 아니라, 판단 주체를 사람으로
넘기는 것이 옳은 처리입니다.

reason 은 모든 판정에 필수입니다. 무엇을 근거로 그렇게 봤는지 한두 문장으로 씁니다.
제시된 자료에 없는 사실을 근거로 쓰지 마세요 — 모르면 uncertain 입니다.
사유가 빈 판정은 판정으로 인정되지 않습니다.

후보 전원에 대해 정확히 하나씩, 주어진 티커 문자열을 그대로 써서 판정하세요.\
"""


@dataclass(frozen=True)
class JudgeTarget:
    """평가대상 — 판정의 기준점."""

    name: str
    ticker: str | None = None
    business: str = ""              # 사업 설명(Brief ②④, 사업보고서 발췌 등)


@dataclass(frozen=True)
class JudgeCandidate:
    """판정 대상 후보 1사. 정량 필드는 넣지 않는다(결정론 스텝 소관)."""

    ticker: str
    name: str
    business: str = ""


def build_prompt(target: JudgeTarget, candidates: list[JudgeCandidate]) -> str:
    """대상·후보 → 가변부 프롬프트. 여기 들어간 것 외에는 모델이 아무것도 못 본다."""
    tgt_line = f"- 회사명: {target.name}"
    if target.ticker:
        tgt_line += f" (티커 {target.ticker})"
    rows = "\n".join(
        f"| {c.ticker} | {c.name} | {(c.business or '(자료 없음)').strip()} |"
        for c in candidates)
    return (
        "## 평가대상\n"
        f"{tgt_line}\n"
        f"- 사업: {(target.business or '(자료 없음)').strip()}\n\n"
        f"## 후보 ({len(candidates)}사)\n"
        "| 티커 | 회사명 | 사업 설명 |\n|---|---|---|\n"
        f"{rows}\n\n"
        "사업 설명이 '(자료 없음)' 인 후보는 판단 근거가 없으므로 uncertain 으로 "
        "판정하고, 무엇이 없어서 애매한지를 reason 에 씁니다."
    )


def to_judgments(
    data: dict, candidates: list[JudgeCandidate],
) -> tuple[list[Step2Judgment], list[str]]:
    """모델 산출 dict → `Step2Judgment` 리스트 + 경고.

    역강제(coercion) 규칙 — 어느 것도 **값을 지어내지 않는다**:
      · 모르는 티커 → 버리고 경고(후보 밖 회사를 판정할 권한이 없다)
      · 중복 티커 → 첫 판정만 채택하고 경고
      · 빈 사유 → **버린다**. 사유를 대신 지어내면 감사 방어가 무너지고, 버리면
        해당 후보는 '판정 없음' 이 되어 사람이 채워야 한다(게이트가 그대로 선다)
      · 판정이 안 온 후보 → 경고로 표면화(퍼널은 전원 판정을 요구한다)
    """
    by_norm = {normalize_ticker(c.ticker): c.ticker for c in candidates}
    out: list[Step2Judgment] = []
    warnings: list[str] = []
    seen: set[str] = set()

    for raw in data.get("judgments") or []:
        if not isinstance(raw, dict):
            continue
        norm = normalize_ticker(str(raw.get("ticker", "")))
        canonical = by_norm.get(norm)
        if canonical is None:
            warnings.append(f"후보에 없는 티커 판정을 버렸습니다: {raw.get('ticker')!r}")
            continue
        if canonical in seen:
            warnings.append(f"{canonical}: 중복 판정 — 첫 판정만 채택")
            continue
        reason = str(raw.get("reason") or "").strip()
        if not reason:
            warnings.append(
                f"{canonical}: 사유 미제시로 판정을 버렸습니다 — 직접 입력해야 합니다")
            continue
        seen.add(canonical)
        out.append(Step2Judgment(
            ticker=canonical,
            similar=bool(raw.get("similar", False)),
            reason=reason,
            uncertain=bool(raw.get("uncertain", False)),
        ))

    missing = [c.ticker for c in candidates if c.ticker not in seen]
    if missing:
        warnings.append(
            f"판정이 없는 후보 {len(missing)}사 — 직접 입력해야 퍼널이 실행됩니다: "
            + ", ".join(missing[:10]) + ("…" if len(missing) > 10 else ""))
    return out, warnings


def draft_step2(
    target: JudgeTarget,
    candidates: list[JudgeCandidate],
    *,
    api_key: str,
    model_id: str | None = None,
    effort: str | None = None,
    max_tokens: int = 16000,
):
    """초안 1회 실행 → (judgments, warnings, JudgeResult).

    실패해도 예외를 던지지 않는다 — `result.ok` 가 False 이고 judgments 가 비는 것이
    정상 경로다(추측 금지: 실패는 폴백이 아니라 '사람이 채운다'로 이어진다).
    """
    from agent.judge import JudgeRequest, judge

    req = JudgeRequest(
        system=SYSTEM,
        prompt=build_prompt(target, candidates),
        schema=STEP2_SCHEMA,
        max_tokens=max_tokens,
        effort=effort,
    )
    result = judge(req, api_key=api_key, model_id=model_id)
    if not result.ok:
        return [], [], result
    judgments, warnings = to_judgments(result.data or {}, candidates)
    return judgments, warnings, result
