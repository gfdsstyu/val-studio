"""/api/demo/cases — 골든 케이스가 **실제로 재현되는가**.

이 엔드포인트는 DART·거시 키가 없는 방문자에게 엔진의 결정론을 보여주는 데모
진입점이다. 프론트(Home)가 여기서 받은 inputs 를 DCF 시트에 채우고 /api/dcf 를
호출하면 expected_per_share 와 일치해야 한다.

그래서 회귀 대상은 "엔드포인트가 200 을 주는가"가 아니라 **왕복이 재현되는가**다.
엔진이나 픽스처가 바뀌어 재현이 깨지면, 화면은 멀쩡한데 "원본 1:1 재현"이라는
주장만 조용히 거짓이 된다 — 데모에서 가장 나쁜 실패 모드다.

허용오차는 케이스마다 다르고 그 차이가 곧 주장의 강도다:
  viol    = 원본의 라이브 수식값 → 부동소수점 수준 일치
  classys = 원본 시트 표기값(4~5 유효숫자 반올림) → ±5원이 상한
서버가 tolerance 를 함께 내려주므로 여기서도 그 값을 그대로 쓴다(이중 정의 방지).

`py -3.12 tests/test_api_demo_cases.py` 또는 pytest.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

try:
    from fastapi.testclient import TestClient
except ImportError:                                   # 3.14 등 미설치 환경
    if "pytest" in sys.modules:                       # 수집 중 — 모듈 단위 skip
        import pytest
        pytest.skip("fastapi 미설치 — py -3.12 로 실행", allow_module_level=True)
    print("fastapi 미설치 — skip (py -3.12 로 실행)")
    sys.exit(0)

from backend.api.main import app                      # noqa: E402

C = TestClient(app)


def _cases() -> list[dict]:
    r = C.get("/api/demo/cases")
    assert r.status_code == 200, r.text
    return r.json()["cases"]


def test_cases_are_available():
    """픽스처가 읽히는가. 빠졌으면 available=false 로 드러나야 한다(조용한 누락 금지)."""
    cases = _cases()
    assert {c["id"] for c in cases} == {"viol", "classys"}
    for c in cases:
        assert c["available"], f"{c['id']}: 픽스처 없음 — {c.get('reason')}"
        assert c["inputs"], f"{c['id']}: inputs 비어있음"
        assert c["expected_per_share"] is not None


def test_inputs_reproduce_expected_per_share():
    """받은 inputs 를 그대로 /api/dcf 에 넣으면 기대 주당가치가 나온다."""
    for c in _cases():
        body = {k: v for k, v in c["inputs"].items() if k != "explicit_years"}
        r = C.post("/api/dcf", json=body)
        assert r.status_code == 200, f"{c['id']}: {r.text[:300]}"
        got = r.json()["per_share"]
        exp = c["expected_per_share"]
        tol = c["tolerance"]["abs"]
        assert abs(got - exp) <= tol, (
            f"{c['id']}: 재현 실패 — got {got:,.4f} vs expected {exp:,.4f} "
            f"(허용 ±{tol}) / {c['tolerance']['label']}")


def test_inputs_are_unmodified_fixture_values():
    """서버가 inputs 를 가공하면 '재현'이라는 주장이 성립하지 않는다.

    픽스처 파일과 직접 대조한다(_ 로 시작하는 주석 키만 제외).
    """
    import json
    for c in _cases():
        raw = json.loads(
            (ROOT / "fixtures" / c["id"] / "inputs.json").read_text(encoding="utf-8"))
        expected_payload = {k: v for k, v in raw.items() if not k.startswith("_")}
        assert c["inputs"] == expected_payload, f"{c['id']}: inputs 가 가공됨"


if __name__ == "__main__":
    test_cases_are_available()
    test_inputs_reproduce_expected_per_share()
    test_inputs_are_unmodified_fixture_values()
    print("3 tests passed.")
