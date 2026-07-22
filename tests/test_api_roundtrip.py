"""xlsx 왕복 루프 API — 저장본 기준선·부분 반영·스킬 증적 이관.

감사 2026-07-19 §4 "루프가 안 닫힘" 4단절의 회귀:
  ② before 를 손수 보관·업로드해야 함  → `project_id` 기준선 재생성
  ④ 수식 변경 섞이면 입력분도 반영 불가 → auto_apply 있으면 new_input 동봉
  + 스킬 `_VS_STATE` 증적이 import 시 유실됨 → skill_state 이관

실행: `py -3.12 -m pytest tests/test_api_roundtrip.py`
"""
from __future__ import annotations

import base64
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

from excel.xlsx_reader import read_workbook            # noqa: E402
from excel.xlsx_writer import Workbook                 # noqa: E402

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


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _export(body=None) -> bytes:
    r = C.post("/api/xlsx/export", json=body or BODY)
    assert r.status_code == 200
    return r.content


def _project(with_input: bool = True) -> str:
    """임시 프로젝트 생성(+DCF 입력 저장) → id. 테스트 종료 시 삭제 책임은 호출부."""
    r = C.post("/api/projects", json={"name": "왕복테스트", "mode": "appraiser"})
    assert r.status_code == 201
    pid = r.json()["id"]
    if with_input:
        assert C.patch(f"/api/projects/{pid}", json={"data": {"dcf_input": BODY}}).status_code == 200
    return pid


def _edited(path_bytes: bytes, tmp_path, *, wacc: float) -> bytes:
    """export 산출물의 WACC 입력셀만 바꾼 '엑셀 편집본' 재현."""
    p = tmp_path / "src.xlsx"
    p.write_bytes(path_bytes)
    wb_in = read_workbook(str(p))
    out = Workbook()
    for name, cells in wb_in.items():
        s = out.add_sheet(name)
        for ref, c in cells.items():
            if c.formula:
                s.formula(ref, c.formula, c.value if isinstance(c.value, (int, float)) else None)
            elif ref == "C3" and name == "DCF":
                s.num(ref, wacc)                        # ← 평가인 편집
            elif isinstance(c.value, (int, float)):
                s.num(ref, c.value)
            elif c.value is not None:
                s.text(ref, str(c.value))
    q = tmp_path / "edited.xlsx"
    out.save(str(q))
    return q.read_bytes()


def test_diff_baseline_from_project(tmp_path):
    """단일 업로드 왕복 — before 없이 프로젝트 저장본과 비교."""
    pid = _project()
    try:
        after = _edited(_export(), tmp_path, wacc=0.12)
        r = C.post("/api/xlsx/diff", json={"project_id": pid, "after_b64": _b64(after)})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["baseline"] == "project"
        assert d["safe"] and d["counts"]["auto_apply"] >= 1
        assert d["new_input"]["wacc"] == 0.12
        assert d["new_result"]["per_share"] > 0
    finally:
        C.delete(f"/api/projects/{pid}")


def test_diff_without_saved_input_is_422():
    """저장된 DCF 입력이 없으면 기준선을 만들 수 없다 — 안내 메시지로 차단."""
    pid = _project(with_input=False)
    try:
        r = C.post("/api/xlsx/diff", json={"project_id": pid, "after_b64": _b64(_export())})
        assert r.status_code == 422 and "저장된 DCF 입력" in r.json()["detail"]
    finally:
        C.delete(f"/api/projects/{pid}")


def test_diff_requires_a_baseline():
    r = C.post("/api/xlsx/diff", json={"after_b64": _b64(_export())})
    assert r.status_code == 422 and "project_id" in r.json()["detail"]


def test_partial_apply_when_formula_changed(tmp_path):
    """수식 변경이 섞여도 입력분 반영용 new_input 은 제공된다(부분 반영)."""
    pid = _project()
    try:
        base = _export()
        p = tmp_path / "b.xlsx"
        p.write_bytes(base)
        wb_in = read_workbook(str(p))
        out = Workbook()
        for name, cells in wb_in.items():
            s = out.add_sheet(name)
            for ref, c in cells.items():
                if name == "DCF" and ref == "C3":
                    s.num(ref, 0.12)                      # ① 입력 변경
                elif c.formula:
                    expr = c.formula + "+0" if ref == "C13" else c.formula   # ② 수식 변경
                    s.formula(ref, expr, c.value if isinstance(c.value, (int, float)) else None)
                elif isinstance(c.value, (int, float)):
                    s.num(ref, c.value)
                elif c.value is not None:
                    s.text(ref, str(c.value))
        q = tmp_path / "a.xlsx"
        out.save(str(q))

        d = C.post("/api/xlsx/diff",
                   json={"project_id": pid, "after_b64": _b64(q.read_bytes())}).json()
        assert not d["safe"], "수식 변경이 있으면 전체 자동반영은 막힌다"
        assert d["counts"]["review_queue"] >= 1
        assert d["counts"]["auto_apply"] >= 1
        assert d["new_input"] is not None, "입력분 부분 반영 경로가 살아있어야 한다"
        assert d["new_input"]["wacc"] == 0.12
    finally:
        C.delete(f"/api/projects/{pid}")


def test_import_carries_skill_state(tmp_path):
    """스킬 `_VS_STATE` 가 붙은 워크북 → import 시 증적 이관."""
    base = _export()
    p = tmp_path / "b.xlsx"
    p.write_bytes(base)
    wb_in = read_workbook(str(p))
    out = Workbook()
    for name, cells in wb_in.items():
        s = out.add_sheet(name)
        for ref, c in cells.items():
            if c.formula:
                s.formula(ref, c.formula, c.value if isinstance(c.value, (int, float)) else None)
            elif isinstance(c.value, (int, float)):
                s.num(ref, c.value)
            elif c.value is not None:
                s.text(ref, str(c.value))
    st = out.add_sheet("_VS_STATE")
    st.text("A1", "skill_version"); st.text("B1", "1.0")
    st.text("A2", "stage"); st.text("B2", "W6")
    st.text("A4", "── 가정 대장(provenance) ──")
    for col, label in zip("ABCDE", ["가정명", "값", "출처유형", "근거", "승인상태"]):
        st.text(f"{col}5", label)
    st.text("A6", "WACC"); st.num("B6", 0.10)
    st.text("C6", "suggested"); st.text("D6", "peer 빌드업"); st.text("E6", "")
    q = tmp_path / "skill.xlsx"
    out.save(str(q))

    r = C.post("/api/xlsx/import", json={"xlsx_b64": _b64(q.read_bytes())})
    assert r.status_code == 200, r.text
    state = r.json()["skill_state"]
    assert state and state["stage"] == "W6"
    assert state["assumptions"][0]["name"] == "WACC"
    assert any("미승인" in w for w in state["warnings"])


def test_import_plain_workbook_has_no_state():
    r = C.post("/api/xlsx/import", json={"xlsx_b64": _b64(_export())})
    assert r.status_code == 200 and r.json()["skill_state"] is None


def test_legacy_erp_keys_migrate_to_mrp():
    """ERP→MRP 개명 이전 저장본이 provenance 를 잃지 않는가.

    정규화가 없으면 프론트가 `mrp_source` 를 못 찾아 빈 값으로 조립하고,
    F3(β/MRP 시장 정합) 게이트가 판정 근거를 잃는다.
    """
    pid = C.post("/api/projects", json={"name": "구용어", "mode": "appraiser"}).json()["id"]
    try:
        C.patch(f"/api/projects/{pid}", json={"data": {"wacc_input": {"form": {
            "erp_source": "kicpa", "erp_market": "KOSPI", "beta_market": "KOSPI"}}}})
        form = C.get(f"/api/projects/{pid}").json()["data"]["wacc_input"]["form"]
        assert form["mrp_source"] == "kicpa" and form["mrp_market"] == "KOSPI"
        assert not [k for k in form if k.startswith("erp_")]
        assert form["beta_market"] == "KOSPI", "무관한 키는 보존"
    finally:
        C.delete(f"/api/projects/{pid}")


def test_current_keys_win_over_legacy():
    """구·현행 키가 공존하면 현행 값을 채택(구키가 덮어쓰지 않는다)."""
    pid = C.post("/api/projects", json={"name": "혼재", "mode": "appraiser"}).json()["id"]
    try:
        C.patch(f"/api/projects/{pid}", json={"data": {"wacc_input": {"form": {
            "erp_market": "SP500", "mrp_market": "KOSPI"}}}})
        form = C.get(f"/api/projects/{pid}").json()["data"]["wacc_input"]["form"]
        assert form["mrp_market"] == "KOSPI"
    finally:
        C.delete(f"/api/projects/{pid}")
