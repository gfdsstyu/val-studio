"""L3 분석적 절차 API(/api/review/analytical) + history 어셈블리 테스트.

픽스처는 비올 리뷰노트 실측(test_analytical.py 와 동일 계열).
실행: `py -3.12 -m pytest tests/test_api_review.py` (fastapi 는 3.12 환경).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

try:
    from fastapi.testclient import TestClient
except ImportError:
    if "pytest" in sys.modules:
        import pytest
        pytest.skip("fastapi 미설치 — py -3.12 로 실행", allow_module_level=True)
    print("fastapi 미설치 — skip (py -3.12 로 실행)")
    sys.exit(0)

import pytest  # noqa: E402

from assemble.history_inputs import history_from_dart  # noqa: E402
from backend.api.main import app  # noqa: E402

C = TestClient(app)

COGS_RATIO_ACT = [0.256, 0.294, 0.331, 0.267, 0.222]
COGS_RATIO_FC = [0.288, 0.245, 0.238, 0.235, 0.234]
SGA_RATIO_ACT = [0.402, 0.425, 0.375, 0.318, 0.253]
SGA_RATIO_FC = [0.241, 0.224, 0.234, 0.229, 0.228]
REV_ACT = [11087.0, 12151.0, 18372.0, 31104.0, 42520.0]
REV_FC = [56784.0, 70538.0, 85139.0, 97484.0, 109260.0]

HISTORY = {
    "years": [2019, 2020, 2021, 2022, 2023],
    "revenue": REV_ACT,
    "cogs": [r * x for r, x in zip(COGS_RATIO_ACT, REV_ACT)],
    "sga": [r * x for r, x in zip(SGA_RATIO_ACT, REV_ACT)],
}
SPINE = {
    "wacc": 0.113, "terminal_growth": 0.02,
    "revenue": REV_FC,
    "cogs": [r * x for r, x in zip(COGS_RATIO_FC, REV_FC)],
    "sga": [r * x for r, x in zip(SGA_RATIO_FC, REV_FC)],
    "dep_amort": [1500.0] * 5, "capex": [1600.0] * 5,
    "delta_nwc_cash_adj": [0.0, -3000.0, -3500.0, -3800.0, -4000.0],
    "non_operating_assets": 49463.0, "net_debt": 655.0,
    "shares_outstanding": 57_656_967,
}


def _warn_rules(body):
    return {f["rule"] for f in body["findings"] if f["severity"] == "warn"}


# ── 엔드포인트 ───────────────────────────────────────────────────────────────
def test_review_history_plus_spine():
    r = C.post("/api/review/analytical", json={"history": HISTORY, "spine": SPINE})
    assert r.status_code == 200, r.text
    body = r.json()
    # 비올 소급: 접합부(원가율 +6.6%p)·성장-운전자본(ΔNWC=0) 둘 다 WARN
    assert {"ratio_seam", "nwc_growth_consistency"} <= _warn_rules(body)
    seam_names = {f["detail"]["series_name"] for f in body["findings"]
                  if f["rule"] == "ratio_seam" and f["severity"] == "warn"}
    assert "매출원가율" in seam_names
    # detail 동봉(스파크라인 소재) + 브리지 표(실적 4개 스텝)
    assert body["bridges"]["opm_bridge"][2]["gpm_contrib"] == pytest.approx(
        0.064, abs=1e-9)                                   # §3.5(b) 2022 GPM 기여
    assert body["warn_count"] >= 2


def test_review_consensus_anchor():
    r = C.post("/api/review/analytical", json={
        "history": {"years": [2023], "revenue": [42520.0]},
        "consensus": [{"metric": "GPM(2024E)", "own": 0.712, "consensus": 0.78,
                       "source": "이베스트증권 2024E"}]})
    assert r.status_code == 200
    assert "consensus_anchor" in _warn_rules(r.json())


def test_review_segments_bridge():
    hist = dict(HISTORY)
    hist["years"], hist["revenue"] = [2021, 2023], [100.0, 99.2]
    hist["cogs"], hist["sga"] = [33.257, 22.307], [37.5, 25.1]
    hist["segments"] = [
        {"name": "제품", "revenue": [87.0, 96.7], "cogs": [23.403, 20.597]},
        {"name": "상품", "revenue": [13.0, 2.5], "cogs": [9.854, 1.710]},
    ]
    r = C.post("/api/review/analytical", json={
        "history": hist,
        "forecast_segments": [
            {"name": "상품", "revenue": [2.0, 2.0], "cogs": [0.822, 0.884]}]})
    assert r.status_code == 200
    body = r.json()
    # E-10: 상품 원가율 68.4→41.1 부문 접합부 WARN + 믹스 분해 표 동봉
    seam_names = {f["detail"]["series_name"] for f in body["findings"]
                  if f["rule"] == "ratio_seam" and f["severity"] == "warn"}
    assert "부문 원가율(상품)" in seam_names
    step = body["bridges"]["mix_decomposition"]["steps"][0]
    assert step["mix_effect"] + step["rate_effect"] == pytest.approx(
        step["total"], abs=1e-9)


def test_review_requires_history():
    assert C.post("/api/review/analytical", json={}).status_code == 422
    assert C.post("/api/review/analytical",
                  json={"history": {"years": [2022, 2023],
                                    "revenue": [1.0]}}).status_code == 422


# ── DART → history 어셈블리 ──────────────────────────────────────────────────
def _acct(name, value, sj="IS"):
    return {"name": name, "sj_div": sj, "value": value}


def _year(year, rev, cogs=None, sga=None, sj="IS"):
    accounts = [_acct("수익(매출액)", rev, sj)]
    if cogs is not None:
        accounts.append(_acct("매출원가", cogs, sj))
    if sga is not None:
        accounts.append(_acct("판매비와관리비", sga, sj))
    return {"year": year, "accounts": accounts}


def test_history_from_dart_assembles_sorted():
    hist, notes = history_from_dart(
        [_year(2023, 42520.0, 9439.4, 10757.6), _year(2022, 31104.0, 8304.8, 9891.1)])
    assert hist.years == [2022, 2023]                     # 연도 오름차순 정렬
    assert hist.revenue == [31104.0, 42520.0]
    assert hist.cogs and hist.sga and not notes


def test_history_from_dart_first_match_wins():
    # 총계(수익(매출액))가 세부(제품매출)보다 먼저 — 첫 매칭 채택(이중계상 방지)
    payload = {"year": 2023, "accounts": [
        _acct("수익(매출액)", 42520.0), _acct("제품매출", 40000.0),
        _acct("매출원가", 9439.4)]}
    hist, _ = history_from_dart([payload])
    assert hist.revenue == [42520.0]


def test_history_from_dart_cis_fallback_and_field_drop():
    # 2022: CIS(단일 포괄손익) 폴백 / 2023: SGA 무매칭 → sga 필드 통째 제외 + note
    hist, notes = history_from_dart(
        [_year(2022, 31104.0, 8304.8, 9891.1, sj="CIS"), _year(2023, 42520.0, 9439.4)])
    assert hist.years == [2022, 2023]
    assert hist.sga is None
    assert any("sga" in n for n in notes)


def test_history_from_dart_employee_join():
    emp = [{"year": 2022, "headcount": 100, "total_salary": 5820.0},
           {"year": 2023, "headcount": 100, "total_salary": 6450.0}]
    hist, _ = history_from_dart(
        [_year(2022, 31104.0), _year(2023, 42520.0)], employee_years=emp)
    assert hist.headcount == [100.0, 100.0]
    assert hist.labor_cost == [5820.0, 6450.0]
    # 연도 커버리지 불일치 → 제외 + note
    hist2, notes2 = history_from_dart(
        [_year(2022, 31104.0), _year(2023, 42520.0)], employee_years=emp[:1])
    assert hist2.headcount is None and any("직원현황" in n for n in notes2)


# ── /api/review/ledger (오류 영향 분리 원장) ─────────────────────────────────
def test_review_ledger():
    r = C.post("/api/review/ledger", json={
        "spine": SPINE,
        "patches": [
            {"label": "ΔNWC 복원", "fields": {
                "delta_nwc_cash_adj": [-3759.0, -3000.0, -3500.0, -3800.0, -4000.0]}},
        ]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ledger"][0]["label"] == "기준선"
    assert body["ledger"][1]["delta"] < 0            # 운전자본 유출 반영 → 하락
    assert body["net_delta"] == pytest.approx(body["ledger"][1]["cum_delta"])


def test_review_ledger_bad_field_422():
    r = C.post("/api/review/ledger", json={
        "spine": SPINE, "patches": [{"label": "x", "fields": {"nope": 1}}]})
    assert r.status_code == 422


# ── BadZipFile 하드닝 (xlsx 3종 공통) ────────────────────────────────────────
def test_xlsx_audit_not_a_zip_422():
    import base64
    r = C.post("/api/xlsx/audit",
               json={"xlsx_b64": base64.b64encode(b"not a zip at all").decode()})
    assert r.status_code == 422
    assert "zip" in r.json()["detail"]


# ── /api/xlsx/audit (정적 감사) ──────────────────────────────────────────────
def test_xlsx_audit_end_to_end(tmp_path):
    import base64

    from calc_core.models import DcfSpineInput
    from excel.sensitivity_grid import build_sensitivity

    path = tmp_path / "model.xlsx"
    build_sensitivity(DcfSpineInput(**SPINE)).save(str(path))
    r = C.post("/api/xlsx/audit",
               json={"xlsx_b64": base64.b64encode(path.read_bytes()).decode()})
    assert r.status_code == 200, r.text
    body = r.json()
    # 표준 레이아웃 → import·재계산 성공 → Sens 중심셀(F7) 검산까지 수행·정합
    assert body["center_checked"] is True
    center = [f for f in body["findings"] if f["rule"] == "sensitivity_center"]
    assert center and center[0]["severity"] == "pass"
    assert "Sens" in body["sheets"]


def test_review_dart_years_end_to_end():
    r = C.post("/api/review/analytical", json={
        "dart_years": [_year(2022, 31104.0, 8304.8, 9891.1),
                       _year(2023, 42520.0, 9439.4, 10757.6)],
        "employee_years": [
            {"year": 2022, "headcount": 100, "total_salary": 5820.0},
            {"year": 2023, "headcount": 100, "total_salary": 6450.0}],
        "spine": SPINE})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["years"] == [2022, 2023]
    # 원가율 실적 26.7→22.2% vs 추정 28.8% → 접합부 WARN + 인당 인건비(+10.8%) WARN
    assert {"ratio_seam", "derived_continuity"} <= _warn_rules(body)
