"""감사인 트랙 API — 의견서 앵커 추출 + 괴리 진단 배선.

감사 2026-07-19 §3.2-1 "감사인 트랙 UI 전무(백엔드는 완비)" 의 후속:
UI 가 소비하는 계약을 회귀로 고정한다. 추출은 결정론(고정양식 앵커), 판정은
감사인 — 엔드포인트는 후보와 confidence 만 돌려주고 단정하지 않는다.

실행: `py -3.12 -m pytest tests/test_api_auditor.py`
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

# app 임포트는 try **밖**에 둔다. 안에 넣으면 ingest·excel·calc_core 로 이어지는
# 연쇄 임포트 중 어디서 난 ImportError 든 "fastapi 미설치"로 오진하고 모듈레벨
# sys.exit(0) 을 때린다 → pytest 에선 INTERNALERROR 로 죽고 진짜 예외는 가려진다.
from backend.api.main import app                      # noqa: E402

C = TestClient(app)

OPINION = """
주식가치 평가의견서
평가방법: 현금흐름할인법(DCF)
WACC = Ke x E/(D+E) + Kd x (1 - t) x D/(D+E)
Terminal Value = FCFF(n) x (1 + B) / (WACC - B)
영구성장률(B) 1.00%
Size Risk Premium 2.75%
(단위: KRW)
"""

BODY = {
    "wacc": 0.10, "terminal_growth": 0.01,
    "revenue": [100000, 115000, 132000, 149000, 165000],
    "cogs": [40000, 46000, 52800, 59600, 66000],
    "sga": [20000, 23000, 26400, 29800, 33000],
    "dep_amort": [5000] * 5, "capex": [5000] * 5, "delta_nwc_cash_adj": [0] * 5,
    "non_operating_assets": 20000, "net_debt": 10000,
    "shares_outstanding": 10_000_000,
}


def test_opinion_extract_anchors():
    d = C.post("/api/opinion/extract", json={"text": OPINION}).json()
    assert d["terminal_growths"] == [0.01]          # (1+B) 앵커
    assert d["size_premiums"] == [0.0275]           # Size Risk Premium 앵커
    assert d["currencies"] == ["KRW"]
    assert d["entity_count"] >= 1 and d["confidence"] == 1.0


def test_opinion_extract_requires_input():
    r = C.post("/api/opinion/extract", json={})
    assert r.status_code == 422 and "text" in r.json()["detail"]


def test_opinion_extract_surfaces_failed_anchor():
    """앵커가 없으면 값을 지어내지 않고 note 로 표면화한다."""
    d = C.post("/api/opinion/extract", json={"text": "본문에 수치가 없는 문서"}).json()
    assert d["terminal_growths"] == []
    assert "영구성장률" in d["note"]


def test_gap_diagnosis_flags_structural_bug():
    """주장값이 'TV 미할인' 재계산과 맞으면 그 구조 오류를 지목한다."""
    base = C.post("/api/dcf", json=BODY).json()
    hyp = C.post("/api/dcf", json={**BODY, "claimed_per_share": base["per_share"]}) \
        .json()["gap_diagnosis"]["hypotheses"]

    claimed = hyp["tv_undiscounted"]
    d = C.post("/api/dcf", json={**BODY, "claimed_per_share": claimed}).json()
    diag = d["gap_diagnosis"]
    assert diag["severity"] == "warn"
    assert "tv_undiscounted" in diag["message"]


def test_gap_diagnosis_passes_when_claim_matches():
    base = C.post("/api/dcf", json=BODY).json()
    d = C.post("/api/dcf", json={**BODY, "claimed_per_share": base["per_share"]}).json()
    assert d["gap_diagnosis"]["severity"] == "pass"


def test_auditor_project_data_is_isolated():
    """모드는 생성 시 1회 — 전환 불가(감사인 독립성 = 데이터 격리)."""
    pid = C.post("/api/projects", json={"name": "검증건", "mode": "auditor"}).json()["id"]
    try:
        assert C.patch(f"/api/projects/{pid}", json={"mode": "appraiser"}).status_code == 422
        r = C.patch(f"/api/projects/{pid}",
                    json={"data": {"audit_claimed": 40600, "opinion_extract": {"confidence": 0.4}}})
        assert r.status_code == 200 and r.json()["data"]["audit_claimed"] == 40600
    finally:
        C.delete(f"/api/projects/{pid}")
