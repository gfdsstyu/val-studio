"""판정 계층(agent/) + Step2 초안(ingest/peer_judge) — 네트워크·API 키 0 전량 mock.

프로바이더 어댑터를 가짜로 갈아끼워 판정 배관 전 경로를 검증한다(`PROVIDERS` 딕셔너리
교체). 실제 LLM 을 호출하면 스위트가 비결정적이 되므로 **테스트는 절대 모델을 부르지
않는다** — canned 응답으로 계약만 본다(test_dart_fs 와 같은 방식).

stdlib: `py -3.12 tests/test_agent_judge.py` 또는 pytest.
"""
from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from agent.judge import (  # noqa: E402
    JudgeRequest, available_models, check_shape, judge,
)
from agent.providers import PROVIDERS  # noqa: E402
from agent.providers.base import ProviderError, ProviderReply  # noqa: E402
from agent.registry import (  # noqa: E402
    DEFAULT_MODEL_ID, MODELS, PRICING_VINTAGE, estimate_usd, get_model,
)
from ingest.peer_judge import (  # noqa: E402
    STEP2_SCHEMA, JudgeCandidate, JudgeTarget, build_prompt, draft_step2, to_judgments,
)
from ingest.peer_selection import PeerCandidate, select_peers  # noqa: E402
from ingest.provenance import ExtractMethod  # noqa: E402


# ── 가짜 프로바이더 ──────────────────────────────────────────────────────────
@contextmanager
def fake_provider(fn):
    """PROVIDERS['anthropic'] 를 임시 교체. 호출 인자는 calls 리스트에 쌓인다."""
    calls: list[dict] = []

    def wrapped(**kw):
        calls.append(kw)
        return fn(len(calls), kw)

    original = PROVIDERS["anthropic"]
    PROVIDERS["anthropic"] = wrapped
    try:
        yield calls
    finally:
        PROVIDERS["anthropic"] = original


def _reply(payload, model="claude-opus-5"):
    return ProviderReply(text=json.dumps(payload, ensure_ascii=False), model_id=model,
                         usage={"input_tokens": 1000, "output_tokens": 200})


# ── check_shape (부분집합 검사기) ────────────────────────────────────────────
def test_check_shape_accepts_valid():
    ok = {"judgments": [{"ticker": "A", "similar": True, "uncertain": False,
                         "reason": "동일 사업"}]}
    assert check_shape(ok, STEP2_SCHEMA) == []


def test_check_shape_catches_missing_type_and_extra():
    bad = {"judgments": [{"ticker": "A", "similar": "yes", "reason": "r"}]}
    errs = check_shape(bad, STEP2_SCHEMA)
    assert any("uncertain" in e and "누락" in e for e in errs)
    assert any("similar" in e and "boolean" in e for e in errs)

    extra = {"judgments": [], "note": "x"}
    assert any("스키마에 없는 키" in e for e in check_shape(extra, STEP2_SCHEMA))


def test_check_shape_bool_is_not_number():
    """bool 은 int 의 서브클래스라 순진한 isinstance 로는 number 를 통과한다."""
    assert check_shape(True, {"type": "integer"}) != []
    assert check_shape(True, {"type": "boolean"}) == []


def test_check_shape_ignores_unknown_keywords():
    # minLength 는 JSON Schema 제약상 쓸 수 없다 → 모르는 키워드는 조용히 통과
    assert check_shape("", {"type": "string", "minLength": 3}) == []


# ── 레지스트리 ───────────────────────────────────────────────────────────────
def test_registry_default_and_unknown():
    assert get_model(None).id == DEFAULT_MODEL_ID
    try:
        get_model("gpt-nope")
    except ValueError as e:
        assert "미등록" in str(e) and DEFAULT_MODEL_ID in str(e)
    else:
        raise AssertionError("미등록 모델은 ValueError 여야 한다")


def test_registry_haiku_rejects_effort_flag():
    """Haiku 4.5 는 effort 를 받으면 요청이 거부된다 — 표에 사실로 박혀 있어야 한다."""
    assert get_model("claude-haiku-4-5").supports_effort is False
    assert get_model("claude-opus-5").supports_effort is True


def test_registry_pricing_has_vintage():
    assert len(PRICING_VINTAGE) == 10 and PRICING_VINTAGE[4] == "-"
    assert all(m.input_usd_per_mtok > 0 and m.output_usd_per_mtok > 0 for m in MODELS)


def test_estimate_uses_list_price_not_intro():
    """도입가로 추정하면 종료일 이후 조용히 과소 추정이 된다 → 정가 기준 고정."""
    sonnet = get_model("claude-sonnet-5")
    assert sonnet.intro_input_usd_per_mtok == 2.00        # 표에는 있고
    assert estimate_usd(sonnet, 1_000_000, 0) == 3.00     # 계산엔 안 쓴다


def test_available_models_only_implemented():
    provs = {m.provider for m in available_models()}
    assert provs <= set(PROVIDERS)
    assert "anthropic" in provs


# ── judge 실행기 ─────────────────────────────────────────────────────────────
_REQ = JudgeRequest(system="S", prompt="P",
                    schema={"type": "object", "properties": {"a": {"type": "integer"}},
                            "required": ["a"], "additionalProperties": False})


def test_judge_happy_path_records_actual_model():
    with fake_provider(lambda n, kw: _reply({"a": 1}, model="claude-opus-5-actual")):
        res = judge(_REQ, api_key="k")
    assert res.ok and res.data == {"a": 1}
    assert res.model_id == "claude-opus-5-actual"      # 응답이 밝힌 모델
    assert res.requested_model_id == DEFAULT_MODEL_ID  # 요청한 모델도 함께 남는다
    assert res.attempts == 1
    assert res.provenance()["approval"] == "suggested"
    assert res.provenance()["method"] == ExtractMethod.LLM.value


def test_judge_retries_once_on_schema_violation():
    def flaky(n, kw):
        return _reply({"a": 1}) if n == 2 else _reply({"wrong": 1})

    with fake_provider(flaky) as calls:
        res = judge(_REQ, api_key="k")
    assert res.ok and res.attempts == 2
    assert "요구 형식을 벗어났습니다" in calls[1]["prompt"]   # 어긋난 지점을 알려주고 재질의
    assert calls[0]["prompt"] == "P"                          # 1회차는 원문 그대로


def test_judge_gives_up_after_max_attempts():
    with fake_provider(lambda n, kw: _reply({"wrong": 1})) as calls:
        res = judge(_REQ, api_key="k")
    assert not res.ok and res.data is None
    assert res.error_kind == "schema" and len(calls) == 2


def test_judge_does_not_fall_back_to_another_provider():
    """실패는 다른 모델로 갈아타지 않는다 — 추측 금지 원칙의 배관 측 표현."""
    def boom(n, kw):
        raise ProviderError("rate_limit", "속도 제한")

    with fake_provider(boom) as calls:
        res = judge(_REQ, api_key="k")
    assert not res.ok and res.error_kind == "rate_limit"
    assert len(calls) == 1                     # 재시도조차 하지 않는다(SDK 가 이미 함)
    assert res.model_id == DEFAULT_MODEL_ID


def test_judge_drops_effort_for_unsupported_model():
    with fake_provider(lambda n, kw: _reply({"a": 1})) as calls:
        judge(JudgeRequest(system="S", prompt="P", schema=_REQ.schema, effort="high"),
              api_key="k", model_id="claude-haiku-4-5")
        judge(JudgeRequest(system="S", prompt="P", schema=_REQ.schema, effort="high"),
              api_key="k", model_id="claude-opus-5")
    assert calls[0]["effort"] is None          # Haiku 4.5 → 떨군다(넘기면 400)
    assert calls[1]["effort"] == "high"


def test_judge_prompt_hash_is_canonical_across_retries():
    def flaky(n, kw):
        return _reply({"a": 1}) if n == 2 else _reply({"wrong": 1})

    with fake_provider(lambda n, kw: _reply({"a": 1})):
        clean = judge(_REQ, api_key="k").prompt_sha256
    with fake_provider(flaky):
        retried = judge(_REQ, api_key="k").prompt_sha256
    assert clean == retried                    # 재시도 힌트는 해시에 섞이지 않는다


def test_judge_requires_key():
    try:
        judge(_REQ, api_key="")
    except ValueError as e:
        assert "X-Anthropic-Key" in str(e)
    else:
        raise AssertionError("키 없이 호출하면 ValueError")


# ── Step2 도메인 ─────────────────────────────────────────────────────────────
_TGT = JudgeTarget(name="비올", ticker="335890", business="미용 의료기기 제조")
_CANDS = [
    JudgeCandidate("145020", "휴젤", "보툴리눔 톡신"),
    JudgeCandidate("214150", "클래시스", "미용 의료기기"),
    JudgeCandidate("999999", "무자료사", ""),
]


def test_prompt_contains_only_given_fields():
    p = build_prompt(_TGT, _CANDS)
    assert "비올" in p and "휴젤" in p and "보툴리눔 톡신" in p
    assert "(자료 없음)" in p                   # 사업 설명 빈 후보는 그렇게 표시
    assert "335890" in p


def test_to_judgments_normalizes_ticker_but_returns_original():
    """모델이 'A145020' 으로 답해도 퍼널이 찾는 원본 '145020' 으로 되돌린다.

    회귀 대상: select_peers 의 판정 매칭은 정규화 없는 정확일치라, 표기가 어긋나면
    "Step2 판정 누락" 으로 조용히 거부된다.
    """
    data = {"judgments": [{"ticker": "A145020", "similar": True, "uncertain": False,
                           "reason": "동일 미용 의료 시장"}]}
    js, warns = to_judgments(data, _CANDS)
    assert [j.ticker for j in js] == ["145020"]
    assert any("판정이 없는 후보" in w for w in warns)


def test_to_judgments_drops_blank_reason_and_unknown_ticker():
    data = {"judgments": [
        {"ticker": "145020", "similar": True, "uncertain": False, "reason": "  "},
        {"ticker": "000000", "similar": True, "uncertain": False, "reason": "무관"},
        {"ticker": "214150", "similar": True, "uncertain": False, "reason": "동일 사업"},
        {"ticker": "214150", "similar": False, "uncertain": False, "reason": "중복"},
    ]}
    js, warns = to_judgments(data, _CANDS)
    assert [j.ticker for j in js] == ["214150"]                  # 사유 O 인 것만
    assert any("사유 미제시" in w for w in warns)                 # 지어내지 않고 버린다
    assert any("후보에 없는 티커" in w for w in warns)
    assert any("중복" in w for w in warns)


def test_to_judgments_keeps_uncertain_without_forcing_similar():
    data = {"judgments": [{"ticker": "999999", "similar": False, "uncertain": True,
                           "reason": "사업 설명 미확보"}]}
    js, _ = to_judgments(data, _CANDS)
    assert js[0].uncertain is True


# ── end-to-end: 초안 → 결정론 퍼널 ───────────────────────────────────────────
def test_draft_feeds_select_peers_end_to_end():
    """초안이 그대로 4-step 퍼널에 먹히는가 — 두 계층의 계약이 맞물리는 지점."""
    payload = {"judgments": [
        {"ticker": "A145020", "similar": True, "uncertain": False, "reason": "톡신·미용"},
        {"ticker": "214150", "similar": True, "uncertain": False, "reason": "동일 기기"},
        {"ticker": "999999", "similar": False, "uncertain": True, "reason": "자료 없음"},
    ]}
    with fake_provider(lambda n, kw: _reply(payload)):
        js, warns, res = draft_step2(_TGT, _CANDS, api_key="k")
    assert res.ok and warns == [] and len(js) == 3

    cands = [PeerCandidate(ticker=c.ticker, name=c.name, industry_code="C271",
                           revenue_share_related=0.9, listed_years=5) for c in _CANDS]
    out = select_peers(cands, target_industry_codes={"C271"}, judgments=js)
    assert {c.ticker for c in out.selected} == {"145020", "214150"}
    assert [t.candidate.ticker for t in out.needs_review] == ["999999"]  # ⚖️ 큐로


def test_draft_returns_empty_on_provider_failure():
    """실패는 예외가 아니라 '판정 없음' — 사람이 채우는 경로로 이어진다."""
    def boom(n, kw):
        raise ProviderError("network", "끊김")

    with fake_provider(boom):
        js, warns, res = draft_step2(_TGT, _CANDS, api_key="k")
    assert js == [] and not res.ok and res.error_kind == "network"


# ── API ──────────────────────────────────────────────────────────────────────
def _client():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        return None
    from api.main import app
    return TestClient(app)


def test_api_models_and_judge():
    client = _client()
    if client is None:
        print("  skip fastapi 미설치 — py -3.12 로 실행")
        return
    r = client.get("/api/agent/models")
    assert r.status_code == 200
    body = r.json()
    assert body["default"] == DEFAULT_MODEL_ID and body["pricing_vintage"]
    assert all(m["provider"] in PROVIDERS for m in body["models"])

    payload = {"target": {"name": "비올"},
               "candidates": [{"ticker": "145020", "name": "휴젤"}]}
    assert client.post("/api/peer/judge", json=payload).status_code == 400  # 키 없음

    reply = {"judgments": [{"ticker": "145020", "similar": True, "uncertain": False,
                            "reason": "동일 미용 의료"}]}
    with fake_provider(lambda n, kw: _reply(reply)):
        r = client.post("/api/peer/judge", json=payload,
                        headers={"X-Anthropic-Key": "sk-test"})
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["judgments"][0]["ticker"] == "145020"
    assert got["provenance"]["approval"] == "suggested"
    assert got["estimated_usd"] > 0


def test_api_judge_maps_provider_error_status():
    client = _client()
    if client is None:
        return

    def boom(n, kw):
        raise ProviderError("rate_limit", "속도 제한")

    with fake_provider(boom):
        r = client.post("/api/peer/judge",
                        json={"target": {"name": "비올"},
                              "candidates": [{"ticker": "145020", "name": "휴젤"}]},
                        headers={"X-Anthropic-Key": "sk-test"})
    assert r.status_code == 429


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    ok = 0
    for fn in fns:
        try:
            fn(); ok += 1; print(f"  ok  {fn.__name__}")
        except Exception:
            print(f"  FAIL {fn.__name__}"); traceback.print_exc()
    print(f"\n{ok}/{len(fns)} passed")
