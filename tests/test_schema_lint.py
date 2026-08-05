"""드리프트 가드 — 선언된 JSON Schema 와 오류 매핑이 계약 안에 머무는가.

두 fail-open 을 정적으로 막는다(docs/plan/workbook_shared_memory.md §3 P3-G):
  · `agent.judge.check_shape` 는 **모르는 키워드를 조용히 통과**시킨다(런타임 관대함).
    그러면 지원되지 않는 키워드를 쓴 스키마가 "검증됐다"는 착각 속에 흐른다 →
    검증 시점을 **여기(정적)** 로 옮긴다. 런타임은 관대하게 두고 CI 가 드리프트를 잡는다.
  · `_AGENT_STATUS.get(kind, 502)` 는 매핑을 빠뜨린 kind 를 502 로 둔갑시킨다
    (사용자에겐 "내 키 문제"가 "서버 장애"로 보인다) → 전수 매핑을 단언한다.

stdlib: `py -3.12 tests/test_schema_lint.py` 또는 pytest.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from agent.judge import check_shape  # noqa: E402
from agent.providers import ErrorKind  # noqa: E402
from ingest.peer_judge import STEP2_SCHEMA  # noqa: E402

#: `check_shape` 가 실제로 해석하는 키워드 — 이 밖은 런타임에서 무시된다.
SUPPORTED = {"type", "properties", "required", "additionalProperties", "items", "enum"}

#: 레포가 선언한 스키마 전량. 새 스키마를 만들면 여기 등록한다
#: (등록 누락은 아래 test_no_unregistered_schema 가 잡는다).
DECLARED = {"ingest.peer_judge.STEP2_SCHEMA": STEP2_SCHEMA}


def _walk(node: dict, path: str = "$"):
    yield path, node
    for k, sub in (node.get("properties") or {}).items():
        if isinstance(sub, dict):
            yield from _walk(sub, f"{path}.{k}")
    item = node.get("items")
    if isinstance(item, dict):
        yield from _walk(item, f"{path}[]")


def test_declared_schemas_use_only_supported_keywords():
    """지원 밖 키워드는 런타임에서 조용히 무시된다 — 여기서 미리 막는다."""
    for name, schema in DECLARED.items():
        for path, node in _walk(schema):
            unknown = set(node) - SUPPORTED
            assert not unknown, (
                f"{name} {path}: 미지원 키워드 {sorted(unknown)} — check_shape 가 무시한다. "
                "수치·길이 제약은 스키마가 아니라 도메인 게이트에서 검사할 것")


def test_declared_object_schemas_close_additional_properties():
    """`additionalProperties:false` 가 빠지면 모델이 덧붙인 키가 그대로 통과한다."""
    for name, schema in DECLARED.items():
        for path, node in _walk(schema):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False, (
                    f"{name} {path}: object 에 additionalProperties:false 필요")


def test_declared_object_schemas_require_every_property():
    """선택 필드는 '왔는지 안 왔는지' 분기를 낳는다 — 판정 스키마는 전 필드 필수."""
    for name, schema in DECLARED.items():
        for path, node in _walk(schema):
            if node.get("type") == "object" and node.get("properties"):
                missing = set(node["properties"]) - set(node.get("required") or [])
                assert not missing, f"{name} {path}: required 누락 {sorted(missing)}"


def test_declared_schemas_pass_their_own_checker():
    """스키마가 자기 검사기와 어긋나지 않는가 — 최소 유효 인스턴스로 왕복."""
    ok = {"judgments": [{"ticker": "A", "similar": True, "uncertain": False,
                         "reason": "r"}]}
    assert check_shape(ok, STEP2_SCHEMA) == []


def test_no_unregistered_schema():
    """`*_SCHEMA` 상수를 새로 만들고 DECLARED 등재를 잊는 드리프트를 잡는다."""
    pat = re.compile(r"^([A-Z][A-Z0-9_]*_SCHEMA)\s*[:=]", re.MULTILINE)
    found: set[str] = set()
    for py in (ROOT / "backend").rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        mod = ".".join(py.relative_to(ROOT / "backend").with_suffix("").parts)
        for m in pat.finditer(py.read_text(encoding="utf-8")):
            found.add(f"{mod}.{m.group(1)}")
    assert found == set(DECLARED), (
        f"등록 안 된 스키마: {sorted(found - set(DECLARED))} / "
        f"사라진 스키마: {sorted(set(DECLARED) - found)}")


def test_agent_status_maps_every_error_kind():
    """kind 를 추가하고 매핑을 빠뜨리면 인증 오류가 502(서버 장애)로 둔갑한다."""
    from api.main import _AGENT_STATUS
    assert set(_AGENT_STATUS) == {k.value for k in ErrorKind}
    # 4xx/5xx 구분이 뒤집히면 프론트가 "내가 고칠 것/기다릴 것"을 잘못 안내한다.
    assert _AGENT_STATUS[ErrorKind.AUTH.value] < 500
    assert _AGENT_STATUS[ErrorKind.NETWORK.value] >= 500


def test_provider_error_rejects_unknown_kind():
    from agent.providers import ProviderError
    try:
        ProviderError("made_up", "x")
    except ValueError:
        pass
    else:
        raise AssertionError("등록되지 않은 kind 는 생성 시점에 거부돼야 한다")


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
