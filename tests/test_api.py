"""로컬 모드 API 스모크 — FastAPI TestClient(서버 기동 불요).

실행: `py -3.12 tests/test_api.py` (fastapi/httpx 는 3.12 환경에 설치됨 —
3.14 는 pydantic-core 휠 부재로 미지원, 미설치 환경이면 전체 skip)
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

BODY = {
    "wacc": 0.10, "terminal_growth": 0.01,
    "revenue": [100000, 115000, 132000, 149000, 165000],
    "cogs": [40000, 46000, 52800, 59600, 66000],
    "sga": [20000, 23000, 26400, 29800, 33000],
    "dep_amort": [5000] * 5, "capex": [5000] * 5, "delta_nwc_cash_adj": [0] * 5,
    "non_operating_assets": 20000, "net_debt": 10000,
    "shares_outstanding": 10_000_000,
}


def test_health():
    r = C.get("/api/health")
    assert r.status_code == 200 and r.json()["mode"] == "local-byok"


def test_dcf_endpoint_matches_engine():
    from calc_core import DcfSpineInput, run
    import dataclasses
    r = C.post("/api/dcf", json=BODY)
    assert r.status_code == 200, r.text
    d = r.json()
    fields = {f.name for f in dataclasses.fields(DcfSpineInput)}
    direct = run(DcfSpineInput(**{k: v for k, v in BODY.items() if k in fields}))
    assert abs(d["per_share"] - direct.per_share) < 1e-9      # API=엔진 무가공
    # 민감도 중심셀 = base (벤치마크 채택 검증)
    assert abs(d["sensitivity"]["per_share"][1][1] - d["per_share"]) < 1e-9
    assert any(f["rule"] == "tv_weight" for f in d["findings"])


def test_dcf_claimed_triggers_diagnosis():
    r = C.post("/api/dcf", json={**BODY, "claimed_per_share": 1000.0})
    d = r.json()
    assert "gap_diagnosis" in d and d["gap_diagnosis"]["severity"] in ("warn", "pass")


def test_dcf_bad_input_422():
    r = C.post("/api/dcf", json={"wacc": 0.1})            # 필수 필드 누락
    assert r.status_code == 422


def test_scenario_endpoint():
    up = {**BODY, "revenue": [x * 1.1 for x in BODY["revenue"]]}
    r = C.post("/api/scenario", json={
        "cases": {"base": BODY, "up": up},
        "weights": {"base": 0.6, "up": 0.4},
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["rows"]) == 2 and d["weighted_per_share"] is not None
    assert d["spread"][0] <= d["weighted_per_share"] <= d["spread"][1]


def test_scenario_bad_weights_422():
    r = C.post("/api/scenario", json={"cases": {"base": BODY}, "weights": {"base": 0.5}})
    assert r.status_code == 422


def test_keys_validate_requires_header():
    r = C.post("/api/keys/validate")
    assert r.status_code == 400


# ── /api/projects — 로컬 JSON CRUD + 모드 불변 원칙 ─────────────────────────
def test_projects_crud_roundtrip():
    p = C.post("/api/projects",
               json={"name": "테스트 평가", "mode": "appraiser", "company": "OO사"}).json()
    pid = p["id"]
    try:
        assert p["mode"] == "appraiser" and p["data"] == {}
        assert any(x["id"] == pid for x in C.get("/api/projects").json())
        # data 부분 갱신 + 메타 수정
        p2 = C.patch(f"/api/projects/{pid}",
                     json={"company": "XX사", "data": {"dcf_input": {"wacc": "0.1"}}}).json()
        assert p2["company"] == "XX사" and p2["data"]["dcf_input"]["wacc"] == "0.1"
        # 모드 변경은 거부(역할 바뀌면 새 프로젝트 원칙)
        r = C.patch(f"/api/projects/{pid}", json={"mode": "auditor"})
        assert r.status_code == 422
    finally:
        assert C.delete(f"/api/projects/{pid}").status_code == 204
    assert C.get(f"/api/projects/{pid}").status_code == 404


def test_projects_validation():
    assert C.post("/api/projects", json={"name": "", "mode": "appraiser"}).status_code == 422
    assert C.post("/api/projects", json={"name": "x", "mode": "??"}).status_code == 422
    assert C.get("/api/projects/../../etc").status_code in (400, 404)   # 경로 탈출 방어


# ── 어셈블리 엔드포인트 스모크 (커넥터 원천 → 검증엔진입력 → 결과) ──────────
_WACC_BODY = {
    "risk_free": "3.45%",                    # 문자열 → 서버가 복붙 커넥터로 range 게이트
    "mrp": "8",
    "peers": [
        {"ticker": "A", "levered_beta": 1.20, "debt_to_equity": 0.5, "tax_rate": 0.22},
        {"ticker": "B", "levered_beta": 1.05, "debt_to_equity": 0.3, "tax_rate": 0.22},
    ],
    "target_debt_to_equity": 0.4, "tax_rate": 0.22,
    "kd_matrix_text": "등급 3Y 5Y\nAAA 3.21 3.48\nBBB 5.40 5.80\n",
    "kd_grade": "BBB", "kd_tenor": "5Y", "market_cap_musd": 1500.0,
    "beta_source": "bloomberg", "beta_market": "KOSPI",
    "mrp_source": "kicpa", "mrp_market": "KOSPI",
    "pasted_at": "2023-06-30", "user": "jjb",
}
_OPS_BODY = {
    "revenue": [1000, 1100, 1210], "cogs_pct": [0.6, 0.6, 0.6], "sga_pct": [0.2, 0.2, 0.2],
    "asset_classes": [{"name": "설비", "opening_net_book": 300,
                       "remaining_life": 3, "useful_life": 10}],
    "new_capex_by_class": {"설비": [50, 50, 50]},
    "wc_items": [{"name": "AR", "base_balance": 100, "base_driver": 1000, "is_asset": True}],
    "wc_driver_by_item": {"AR": [1000, 1100, 1210]},
    "base_net_working_capital": 100.0, "terminal_growth": 0.02,
    "non_operating_assets": 100.0, "net_debt": 50.0, "shares_outstanding": 1_000_000,
}


def test_wacc_assemble_from_paste():
    r = C.post("/api/wacc/assemble", json=_WACC_BODY)
    assert r.status_code == 200, r.text
    d = r.json()
    assert not d["blocked"]
    assert 0.08 < d["wacc"] < 0.16               # 커넥터 조립 WACC ≈11%대(골든 대역)
    assert "risk_free" in d["provenance"]
    assert "BBB×5Y" in d["provenance"]["pre_tax_cost_of_debt"]
    assert d["inputs"]["pre_tax_cost_of_debt"] == 0.058


def test_wacc_assemble_bad_paste_blocks():
    bad = {**_WACC_BODY, "risk_free": "350"}      # 350% → range FAIL, 서버 게이트 차단
    d = C.post("/api/wacc/assemble", json=bad).json()
    assert d["blocked"] and d["wacc"] is None
    assert any(f["rule"] == "range" and f["severity"] == "fail" for f in d["findings"])


def test_dcf_assemble_end_to_end():
    r = C.post("/api/dcf/assemble", json={"wacc": _WACC_BODY, "ops": _OPS_BODY})
    assert r.status_code == 200, r.text
    d = r.json()
    assert not d["blocked"]
    assert d["per_share"] > 0 and d["enterprise_value"] > 0
    assert any(f["rule"] == "tv_weight" for f in d["findings"])


def test_dcf_assemble_pgr_ge_wacc_blocks():
    body = {"wacc": _WACC_BODY, "ops": {**_OPS_BODY, "terminal_growth": 0.20}}
    d = C.post("/api/dcf/assemble", json=body).json()
    assert d["blocked"] and d["per_share"] is None
    assert any(f["rule"] == "pgr_vs_wacc" and f["severity"] == "fail" for f in d["findings"])


def test_peer_select_seed_peers_ksic_reverse():
    """③ 웹 패리티: seed_peers(rough 유사회사) → KSIC 역산(codes_used)으로 모집단 필터."""
    body = {
        "candidates": [
            {"ticker": "A", "name": "동종A", "industry_code": "2710", "revenue_share_related": 0.9, "listed_years": 5},
            {"ticker": "B", "name": "무관B", "industry_code": "5811", "revenue_share_related": 0.9, "listed_years": 5},
        ],
        "seed_peers": [{"ticker": "S1", "industry_code": "2710"}, {"ticker": "S2", "industry_code": "2711"}],
    }
    d = C.post("/api/peer/select", json=body).json()
    assert set(d["codes_used"]) == {"2710", "2711"}          # 역산 코드
    assert [c["ticker"] for c in d["selected"]] == ["A"]     # B는 코드 불일치 탈락


def test_peer_select_no_reason_422():
    """Step2 무근거 판정 → 422(검증 게이트)."""
    body = {"candidates": [{"ticker": "A", "name": "A", "industry_code": "2710",
                            "revenue_share_related": 0.9, "listed_years": 5}],
            "target_industry_codes": ["2710"],
            "judgments": [{"ticker": "A", "similar": True, "reason": " "}]}
    assert C.post("/api/peer/select", json=body).status_code == 422


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
