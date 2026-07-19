"""거시 시계열 API — 복붙 경로 + vintage look-ahead 가드.

감사 2026-07-19 §3.2-4 죽은 참조의 후속: `macro_cpi` 를 쓰는 곳만 있고 쓰는 주체가
없어 cpi 드라이버가 조용히 물가상승 0%로 계산됐다. 커넥터(macro_client)는 이미
있었고 API 노출만 없던 상태 — 그 계약을 회귀로 고정한다.

실행: `py -3.12 -m pytest tests/test_api_macro.py`
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

C = TestClient(app)

PASTE = "2024 2.3%\n2025 2.1%\n2026 2.0%\n2027 2.0%"


def test_paste_normalizes_to_ratio():
    """% → 소수 정규화 + 연도별 대표값(cost_build 의 cpi 연율 리스트 재료)."""
    d = C.post("/api/macro/series",
               json={"indicator": "cpi_inflation", "text": PASTE}).json()
    assert d["indicator"] == "cpi_inflation"
    assert d["annual"] == {"2024": 0.023, "2025": 0.021, "2026": 0.02, "2027": 0.02}


def test_forecast_tagging():
    """예측 시작연도 이상은 is_forecast — 실적과 전망을 섞지 않는다."""
    d = C.post("/api/macro/series",
               json={"indicator": "cpi_inflation", "text": PASTE,
                     "vintage": "2026-01-15", "is_forecast_from": "2026"}).json()
    by_period = {o["period"]: o for o in d["observations"]}
    assert by_period["2025"]["is_forecast"] is False
    assert by_period["2026"]["is_forecast"] is True
    assert by_period["2026"]["vintage"] == "2026-01-15"


def test_lookahead_guard_excludes_future_vintage():
    """평가기준일 이후에 공표된 스냅샷은 usable 에서 제외(그때 알 수 없던 정보)."""
    d = C.post("/api/macro/series",
               json={"indicator": "cpi_inflation", "text": PASTE,
                     "vintage": "2026-09-30", "base_date": "2026-03-31"}).json()
    assert d["observations"] == [], "기준일 이후 vintage 가 통과하면 look-ahead"
    assert any(f["severity"] != "pass" for f in d["findings"])


def test_future_years_need_forecast_tag():
    """예측 태깅이 없으면 미래 연도는 '미래 실적' 이라 정당하게 탈락한다.

    2026-03-31 기준으로 2027 '실적' 은 존재할 수 없다 → look-ahead. 전망치를
    붙여넣을 때 `is_forecast_from` 을 채워야 하는 이유이고, UI 는 탈락 건수를
    표면화해야 한다(조용히 사라지면 CPI 죽은 참조와 같은 종류의 사고).
    """
    untagged = C.post("/api/macro/series",
                      json={"indicator": "cpi_inflation", "text": PASTE,
                            "vintage": "2026-01-15", "base_date": "2026-03-31"}).json()
    assert [o["period"] for o in untagged["observations"]] == ["2024", "2025"]

    tagged = C.post("/api/macro/series",
                    json={"indicator": "cpi_inflation", "text": PASTE,
                          "vintage": "2026-01-15", "is_forecast_from": "2026",
                          "base_date": "2026-03-31"}).json()
    assert len(tagged["observations"]) == 4, "예측으로 태깅하면 전망연도가 살아야"


def test_requires_text_or_key():
    r = C.post("/api/macro/series", json={"indicator": "cpi_inflation"})
    assert r.status_code == 422 and "X-Ecos-Key" in r.json()["detail"]


def test_cpi_driver_is_flat_without_cpi():
    """엔진 계약 확인 — CPI 부재 시 누적계수 1.0(=0% 상승). UI 가 이걸 경고해야 한다."""
    body = {"years": 3, "lines": [{"name": "외주비", "category": "cogs",
                                   "method": "cpi", "base": 3000}]}
    flat = C.post("/api/assumptions/costs-build", json=body).json()
    with_cpi = C.post("/api/assumptions/costs-build",
                      json={**body, "cpi": [0.02, 0.02, 0.02]}).json()
    assert flat["cogs"] == [3000, 3000, 3000], "CPI 없으면 평탄 — 조용한 오답의 실체"
    assert with_cpi["cogs"][2] > flat["cogs"][2], "CPI 있으면 물가만큼 상승해야"
