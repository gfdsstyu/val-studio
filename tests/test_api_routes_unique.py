"""라우트 경로 중복 금지 — 도달 불가능한 핸들러가 생기지 않는가.

회귀 대상(2026-07-29 라이브 결함): /api/method/recommend 에 핸들러가 **두 번**
등록돼 있었다. line 118 = 사업성격 추천(recommend_by_business_nature),
line 1701 = 법제 매핑(recommend_method). Starlette 은 먼저 등록된 라우트를
매칭하므로 후자는 도달 불가능한 죽은 코드였다.

증상이 고약했던 이유: 중복 등록은 **에러가 아니다**. 서버는 정상 기동하고
200 을 반환한다. 다만 형태가 다른 응답이 돌아와서, 이를 소비하는 Home.jsx 가
렌더 중 rec.notes.length 에서 TypeError 를 내고 트리 전체가 언마운트됐다
(= 흰 화면). 백엔드 테스트는 먼저 등록된 쪽 계약만 검증하고 있어 전부 통과했다.

그래서 "엔드포인트별 계약" 테스트로는 이 결함을 못 잡는다. 라우트 테이블
자체를 불변식으로 검사해야 한다.

`py -3.12 tests/test_api_routes_unique.py` 또는 pytest.
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

try:
    from backend.api.main import app
except ImportError:                                   # 3.14 등 미설치 환경
    print("fastapi 미설치 — skip (py -3.12 로 실행)")
    sys.exit(0)


def _route_table() -> dict[tuple[str, str], list[str]]:
    """(HTTP 메서드, 경로) → 등록된 핸들러 이름 목록(등록 순)."""
    table: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
    for r in app.routes:
        for method in getattr(r, "methods", ()) or ():
            table[(method, r.path)].append(r.endpoint.__name__)
    return table


def test_no_duplicate_route_registration():
    """같은 (메서드, 경로)에 핸들러가 둘 이상이면 뒤엣것은 영원히 도달 불가."""
    dups = {k: v for k, v in _route_table().items() if len(v) > 1}
    assert not dups, (
        "중복 라우트 — 먼저 등록된 것만 매칭되고 나머지는 죽은 코드가 된다:\n"
        + "\n".join(f"  {m} {p}: {names}" for (m, p), names in dups.items())
    )


def test_both_method_recommenders_reachable():
    """추천 2종은 입력축이 달라 경로가 분리돼 있어야 한다(위 결함의 직접 회귀)."""
    paths = {p for (_m, p) in _route_table()}
    assert "/api/method/recommend" in paths          # 사업성격 축
    assert "/api/method/recommend-legal" in paths    # 법제 목적 축


def test_legal_recommender_returns_home_contract():
    """법제 추천은 Home.jsx 가 소비하는 5개 키를 모두 반환해야 한다.

    primary/notes 가 배열이 아니면 Home 이 렌더에서 터진다(흰 화면).
    """
    from fastapi.testclient import TestClient
    c = TestClient(app)
    # purpose 와 deal_type 은 서로 다른 축이다(purpose=transaction, deal_type=merger).
    # 상장법인 간 합병 = 자본시장법 시행령 규정이 걸리는 대표 조합.
    r = c.post("/api/method/recommend-legal",
               json={"purpose": "transaction", "deal_type": "merger",
                     "target_listed": True, "counterparty_listed": False})
    assert r.status_code == 200, r.text
    d = r.json()
    for key in ("primary", "secondary", "legal_basis", "notes", "uncertain"):
        assert key in d, f"Home.jsx 가 기대하는 키 누락: {key}"
    assert isinstance(d["primary"], list)
    assert isinstance(d["notes"], list)


if __name__ == "__main__":
    test_no_duplicate_route_registration()
    test_both_method_recommenders_reachable()
    test_legal_recommender_returns_home_contract()
    print("3 tests passed.")
