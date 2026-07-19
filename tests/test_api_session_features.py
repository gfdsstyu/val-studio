"""API 노출 스모크 — 이번 세션 엔진기능 5종(footnote/employee/capex/razor/wc).

기존 test_api.py 와 분리(동시 작업 충돌 회피). FastAPI TestClient, 네트워크 불요
(DART 는 http 주입 대신 헤더검증만 스모크). `py -3.12 tests/test_api_session_features.py`.
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
except ImportError:
    print("fastapi 미설치 — skip (py -3.12 로 실행)")
    sys.exit(0)

C = TestClient(app)

_TABLE = (
    "구분        2024      2023\n"
    "급여        12,340    11,200\n"
    "퇴직급여     1,500     1,300\n"
    "감가상각비   3,200     3,000\n"
    "지급수수료   2,000     1,900\n"
)


# ── ① 성격별 원가 주석 추출 + tie-out ────────────────────────────────────────
def test_footnote_costs_extract_and_suggest():
    r = C.post("/api/footnote/costs", json={"text": _TABLE, "note_no": 24})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] and d["years"] == ["2024", "2023"]
    by = {n["name"]: n for n in d["natures"]}
    assert by["급여"]["method"] == "headcount" and by["급여"]["category"] == "sga"
    assert by["급여"]["amounts"]["2024"] == 12340.0
    assert by["감가상각비"]["uncertain"] is True          # cogs/sga 애매
    assert any(x["name"] == "급여" and x["method"] == "headcount" for x in d["drafts"])


def test_footnote_costs_tieout_fail():
    # 표기 판관비 조작(20,000) → Σ성격별(sga) ≠ 표기 → tieout FAIL
    r = C.post("/api/footnote/costs",
               json={"text": _TABLE, "year": "2024", "stated_sga": 20000})
    d = r.json()
    assert any(f["rule"] == "sum" and f["severity"] == "fail" for f in d["tieout"])


def test_footnote_costs_requires_text():
    assert C.post("/api/footnote/costs", json={"text": "  "}).status_code == 422


# ── ② DART 직원현황 (BYOK 헤더 검증만) ───────────────────────────────────────
def test_dart_employee_requires_key():
    r = C.post("/api/dart/employee", json={"corp_code": "00126380", "bsns_year": 2024})
    assert r.status_code == 400                          # X-Dart-Key 없음


def test_dart_employee_requires_fields():
    r = C.post("/api/dart/employee", json={"corp_code": ""},
               headers={"X-Dart-Key": "dummy"})
    assert r.status_code == 422


# ── ④ razor-and-blades 매출 트리 ─────────────────────────────────────────────
def test_revenue_razor_tree():
    tree = {"name": "총매출", "children": [
        {"name": "장비", "price": [50, 50, 50], "qty": [10, 20, 30]},
        {"name": "소모품", "equipment_new": [10, 20, 30],
         "consumable_per_unit": [3, 3, 3]},
    ]}
    r = C.post("/api/revenue/build",
               json={"method": "bottom_up", "years": 3, "tree": tree})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["errors"] == []
    assert d["revenue"][0] == 500 + 30                   # 장비 500 + 소모품(base10×3)
    assert d["revenue"][2] == 1500 + 180                 # 누적base 60 × 3
    assert d["breakdown"]["소모품"] == [30, 90, 180]


# ── ③⑤ CAPEX 유지보수 + 터미널 WC 정규화 (assemble 관통) ─────────────────────
_WACC = {
    "risk_free": "3.45%", "mrp": "8",
    "peers": [{"ticker": "A", "levered_beta": 1.2, "debt_to_equity": 0.5, "tax_rate": 0.22},
              {"ticker": "B", "levered_beta": 1.05, "debt_to_equity": 0.3, "tax_rate": 0.22}],
    "target_debt_to_equity": 0.4, "tax_rate": 0.22,
    "kd_matrix_text": "등급 3Y 5Y\nAAA 3.21 3.48\nBBB 5.40 5.80\n",
    "kd_grade": "BBB", "kd_tenor": "5Y", "market_cap_musd": 1500.0,
    "beta_source": "bloomberg", "beta_market": "KOSPI",
    "mrp_source": "kicpa", "mrp_market": "KOSPI", "pasted_at": "2023-06-30",
}
_OPS = {
    "revenue": [1000, 1100, 1210], "cogs_pct": [0.6, 0.6, 0.6], "sga_pct": [0.2, 0.2, 0.2],
    "asset_classes": [{"name": "설비", "opening_net_book": 300,
                       "remaining_life": 3, "useful_life": 10}],
    "new_capex_by_class": {"설비": [50, 50, 50]},
    "wc_items": [{"name": "AR", "base_balance": 100, "base_driver": 1000, "is_asset": True}],
    "wc_driver_by_item": {"AR": [1000, 1100, 1210]},
    "base_net_working_capital": 100.0, "terminal_growth": 0.02,
    "non_operating_assets": 100.0, "net_debt": 50.0, "shares_outstanding": 1_000_000,
}


def test_dcf_assemble_maintenance_and_wc_ratio():
    # 유지보수 CAPEX + 터미널 WC 정규화가 assemble 관통해 결과 낸다.
    # g=3%(>2%)라야 F1 terminal_reinvestment 가 발화 → WC 정규화로 PASS 승격 확인.
    ops = {**_OPS, "terminal_growth": 0.03,
           "maintenance_capex_by_class": {"설비": [20, 20, 20]},
           "terminal_wc_ratio": 0.30}
    r = C.post("/api/dcf/assemble", json={"wacc": _WACC, "ops": ops})
    assert r.status_code == 200, r.text
    d = r.json()
    assert not d["blocked"] and d["per_share"] is not None
    # 터미널 WC 정규화 반영 → F1 과대계상 WARN 이 PASS 로(terminal_reinvestment)
    tr = [f for f in d["findings"] if f["rule"] == "terminal_reinvestment"]
    assert tr and tr[0]["severity"] == "pass"


def test_dcf_maintenance_lowers_fcff_vs_none():
    # 유지보수 CAPEX 추가 → CAPEX↑ → per_share 하락(현금유출 반영 확인)
    base = C.post("/api/dcf/assemble", json={"wacc": _WACC, "ops": _OPS}).json()
    withm = C.post("/api/dcf/assemble", json={
        "wacc": _WACC,
        "ops": {**_OPS, "maintenance_capex_by_class": {"설비": [30, 30, 30]}}}).json()
    assert withm["per_share"] < base["per_share"]


def test_assumptions_build_maintenance_split():
    # /api/assumptions/build fa 분기가 유지보수 CAPEX 분리 + detail 반환(FaSheet 소비)
    r = C.post("/api/assumptions/build", json={
        "asset_classes": [{"name": "설비", "opening_net_book": 300,
                           "remaining_life": 3, "useful_life": 10}],
        "new_capex_by_class": {"설비": [50, 50, 50]},
        "maintenance_capex_by_class": {"설비": [20, 20, 20]}})
    assert r.status_code == 200, r.text
    fa = r.json()["fa"]
    assert fa["capex"][0] == 70.0                        # 신규50 + 유지20
    assert fa["detail"]["maintenance_capex"][0] == 20.0
    assert fa["detail"]["new_capex"][0] == 50.0


def test_dcf_endpoint_terminal_wc_ratio_passthrough():
    # /api/dcf 는 _parse_input 필드 필터로 terminal_wc_ratio 자동 통과
    body = {
        "wacc": 0.10, "terminal_growth": 0.03,
        "revenue": [1000, 1100], "cogs": [600, 660], "sga": [200, 220],
        "dep_amort": [50, 50], "capex": [50, 50], "delta_nwc_cash_adj": [0, 0],
        "non_operating_assets": 0, "net_debt": 0, "shares_outstanding": 1_000_000,
        "terminal_wc_ratio": 0.30,
    }
    r = C.post("/api/dcf", json=body)
    assert r.status_code == 200, r.text
    tr = [f for f in r.json()["findings"] if f["rule"] == "terminal_reinvestment"]
    assert tr and tr[0]["severity"] == "pass"           # WC 정규화 → 과대계상 방어


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
