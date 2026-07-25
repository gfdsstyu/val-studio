"""/api/method/recommend — 엔드포인트가 recommend_by_business_nature 계약을 보존하는가.

회귀 대상: 일괄 bool(data.get(k)) 는 생략된 has_stable_earnings_and_peers(기본 True)를
None→False 로 덮어써, 같은 입력이 직접 호출과 엔드포인트에서 다른 기법을 추천했다.
이제 생략·null 키는 전달하지 않아 함수 기본값이 그대로 적용된다.

`py -3.12 tests/test_api_method.py` 또는 pytest.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

try:
    from fastapi.testclient import TestClient

    from backend.api.main import app
except ImportError:                                   # 3.14 등 미설치 환경
    print("fastapi 미설치 — skip (py -3.12 로 실행)")
    sys.exit(0)

from calc_core.method_selector import recommend_by_business_nature  # noqa: E402

C = TestClient(app)


def test_empty_body_matches_function_default():
    """빈 body → 함수 기본값(stable_earnings=True) 경로. comps 로 귀결."""
    endpoint = C.post("/api/method/recommend", json={}).json()
    direct = recommend_by_business_nature()
    assert endpoint == direct
    assert endpoint["method"] == "comps"   # stable_earnings=True 기본 규칙


def test_omitted_stable_flag_stays_true():
    """다른 플래그만 주고 stable 은 생략 — True 기본이 유지되어야 한다."""
    endpoint = C.post("/api/method/recommend",
                      json={"is_pipeline_bio": False}).json()
    direct = recommend_by_business_nature(is_pipeline_bio=False)
    assert endpoint == direct


def test_explicit_false_is_preserved():
    """명시적 false 는 기본값으로 되돌리지 않고 그대로 전달한다."""
    endpoint = C.post("/api/method/recommend",
                      json={"has_stable_earnings_and_peers": False}).json()
    direct = recommend_by_business_nature(has_stable_earnings_and_peers=False)
    assert endpoint == direct


def test_pipeline_bio_routes_to_rnpv():
    """양성 플래그는 정상 라우팅(회귀로 기본 경로만 타지 않는지 확인)."""
    r = C.post("/api/method/recommend", json={"is_pipeline_bio": True}).json()
    assert r["method"] == "rnpv"


if __name__ == "__main__":
    test_empty_body_matches_function_default()
    test_omitted_stable_flag_stays_true()
    test_explicit_false_is_preserved()
    test_pipeline_bio_routes_to_rnpv()
    print("4 tests passed.")
