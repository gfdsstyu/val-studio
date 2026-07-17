"""로컬 모드 API — FastAPI 1프로세스 (docs/plan.md §현 단계 운영 형태).

실행: `py -3.12 -m uvicorn backend.api.main:app --reload` (레포 루트에서)
- 계산·검증은 calc_core 그대로 호출(결정론) — API 는 얇은 어댑터.
- **BYOK**: LLM 키는 클라이언트가 요청 헤더(X-Gemini-Key 등)로 전달, 서버는
  통과만 하고 어디에도 저장·로깅하지 않는다.
- 프론트: frontend/dist 빌드가 있으면 정적 서빙(/), 없으면 API 만(dev 는 Vite 프록시).
"""
from __future__ import annotations

import dataclasses
import sys
import urllib.error
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "backend"))

from fastapi import FastAPI, Header, HTTPException, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from calc_core import DcfSpineInput, run  # noqa: E402
from calc_core.checks import audit_dcf, diagnose_dcf_gap  # noqa: E402
from calc_core.method_selector import DEAL_TYPES, PURPOSES, recommend_method  # noqa: E402
from calc_core.scenario import run_scenarios  # noqa: E402

app = FastAPI(title="val-studio local", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],  # Vite dev
    allow_methods=["*"], allow_headers=["*"],
)

_FIELDS = {f.name for f in dataclasses.fields(DcfSpineInput)}


def _parse_input(data: dict) -> DcfSpineInput:
    try:
        return DcfSpineInput(**{k: v for k, v in data.items() if k in _FIELDS})
    except (TypeError, ValueError) as e:
        raise HTTPException(422, f"입력 오류: {e}") from e


def _result_payload(inp: DcfSpineInput, claimed: float | None = None) -> dict:
    res = run(inp)
    rep = audit_dcf(inp, res)
    out = {
        "per_share": res.per_share,
        "enterprise_value": res.enterprise_value,
        "equity_value": res.equity_value,
        "pv_explicit_sum": res.pv_explicit_sum,
        "terminal_value_pv": res.terminal_value_pv,
        "tv_weight": (res.terminal_value_pv / res.enterprise_value
                      if res.enterprise_value else None),
        "findings": [{"rule": f.rule, "severity": f.severity.value, "message": f.message}
                     for f in rep.findings],
        "sensitivity": {
            "per_share": res.sensitivity.get("per_share"),
            "wacc_axis": res.sensitivity.get("wacc_axis"),
            "g_axis": res.sensitivity.get("g_axis"),
        },
    }
    if claimed is not None:
        diag = diagnose_dcf_gap(inp, res, claimed)
        out["gap_diagnosis"] = {"severity": diag.severity.value, "message": diag.message,
                                "hypotheses": diag.detail.get("hypotheses")}
    return out


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "engine": "calc_core", "mode": "local-byok"}


@app.post("/api/dcf")
async def dcf_endpoint(request: Request) -> dict:
    """DcfSpineInput JSON → 주당가치·EV·TV비중·audit findings·민감도.

    선택 필드 `claimed_per_share` 를 주면 괴리 구조버그 진단(gap_diagnosis) 동봉.
    """
    data = await request.json()
    claimed = data.pop("claimed_per_share", None)
    inp = _parse_input(data)
    try:
        return _result_payload(inp, float(claimed) if claimed not in (None, "") else None)
    except ZeroDivisionError as e:
        raise HTTPException(422, f"계산 불능(0 나눗셈 — WACC≈g 확인): {e}") from e


@app.post("/api/scenario")
async def scenario_endpoint(request: Request) -> dict:
    """{"cases": {이름: DcfSpineInput}, "weights": {이름: w}?} → 시나리오 결과."""
    data = await request.json()
    cases = {name: _parse_input(c) for name, c in (data.get("cases") or {}).items()}
    try:
        a = run_scenarios(cases, weights=data.get("weights"))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"rows": a.to_rows(), "spread": a.spread,
            "weighted_per_share": a.weighted_per_share}


@app.get("/api/method/options")
def method_options() -> dict:
    """위저드 선택지 — 목적·거래유형 카탈로그(프론트 하드코딩 방지, SSOT=백엔드)."""
    return {"purposes": PURPOSES, "deal_types": DEAL_TYPES}


@app.post("/api/method/recommend")
async def method_recommend(request: Request) -> dict:
    """{purpose, deal_type?, target_listed?, counterparty_listed?} → 방법론 추천.

    결정론 법제 매핑(북 정본) — 추천이지 강제 아님. 규칙 없는 조합은 uncertain.
    """
    d = await request.json()
    if d.get("purpose") not in PURPOSES:
        raise HTTPException(422, f"purpose 는 {sorted(PURPOSES)} 중 하나")
    r = recommend_method(
        d["purpose"], d.get("deal_type"),
        target_listed=d.get("target_listed"),
        counterparty_listed=d.get("counterparty_listed"),
    )
    return r.to_dict()


@app.post("/api/keys/validate")
def validate_key(x_gemini_key: str | None = Header(default=None)) -> dict:
    """BYOK 배관 검증 — 헤더의 Gemini 키로 모델 목록 1회 조회(통과만, 저장 안 함)."""
    if not x_gemini_key:
        raise HTTPException(400, "X-Gemini-Key 헤더 없음")
    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1",
        headers={"x-goog-api-key": x_gemini_key})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310
            ok = r.status == 200
        return {"valid": ok}
    except urllib.error.HTTPError as e:
        return {"valid": False, "status": e.code}
    except urllib.error.URLError as e:
        raise HTTPException(502, f"네트워크 오류: {e.reason}") from e


# ── 프로젝트 저장 (로컬 JSON 폴더 — ia_ux_architecture.md 권고안) ────────────
# 프로젝트 = 밸류에이션 용역 1건(워크북 메타포). 모드는 생성 시 1회 속성 —
# 전환 API 는 의도적으로 없다(감사인 독립성 = 데이터 격리).
import json as _json  # noqa: E402
import re as _re  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

_PROJECTS_DIR = _ROOT / "var" / "projects"
_MODES = {"appraiser", "auditor"}
_ID_RE = _re.compile(r"^[0-9a-f]{12}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _proj_path(pid: str) -> Path:
    if not _ID_RE.fullmatch(pid):                       # 경로 탈출 방지
        raise HTTPException(400, f"잘못된 프로젝트 id: {pid}")
    return _PROJECTS_DIR / f"{pid}.json"


def _load_project(pid: str) -> dict:
    p = _proj_path(pid)
    if not p.exists():
        raise HTTPException(404, f"프로젝트 없음: {pid}")
    return _json.loads(p.read_text(encoding="utf-8"))


def _save_project(proj: dict) -> None:
    _PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    _proj_path(proj["id"]).write_text(
        _json.dumps(proj, ensure_ascii=False, indent=1), encoding="utf-8")


@app.get("/api/projects")
def list_projects() -> list[dict]:
    """목록(메타만) — 홈 화면. 수정시각 내림차순."""
    out = []
    if _PROJECTS_DIR.is_dir():
        for f in _PROJECTS_DIR.glob("*.json"):
            try:
                p = _json.loads(f.read_text(encoding="utf-8"))
                out.append({k: p.get(k) for k in
                            ("id", "name", "mode", "company", "created_at", "updated_at")})
            except (_json.JSONDecodeError, OSError):
                continue
    return sorted(out, key=lambda p: p.get("updated_at") or "", reverse=True)


@app.post("/api/projects", status_code=201)
async def create_project(request: Request) -> dict:
    """{name, mode: appraiser|auditor, company?} → 새 프로젝트."""
    d = await request.json()
    name = (d.get("name") or "").strip()
    mode = d.get("mode")
    if not name:
        raise HTTPException(422, "name 필수")
    if mode not in _MODES:
        raise HTTPException(422, f"mode 는 {sorted(_MODES)} 중 하나")
    proj = {
        "id": uuid.uuid4().hex[:12], "name": name, "mode": mode,
        "company": (d.get("company") or "").strip(),
        # 평가 설계(셋업 위저드 확정값): 목적·거래유형·상장여부·기준일·추정기간·확정 방법론
        "setup": d.get("setup") if isinstance(d.get("setup"), dict) else {},
        "created_at": _now(), "updated_at": _now(),
        "data": {},                                     # 단계별 입력·산출물 저장소
    }
    _save_project(proj)
    return proj


@app.get("/api/projects/{pid}")
def get_project(pid: str) -> dict:
    return _load_project(pid)


@app.patch("/api/projects/{pid}")
async def update_project(pid: str, request: Request) -> dict:
    """메타(name·company)·data 부분 갱신. mode 는 불변(전환 금지 원칙)."""
    proj = _load_project(pid)
    d = await request.json()
    if "mode" in d and d["mode"] != proj["mode"]:
        raise HTTPException(422, "mode 는 변경 불가 — 역할이 바뀌면 새 프로젝트를 생성")
    for k in ("name", "company"):
        if k in d:
            proj[k] = str(d[k]).strip()
    if isinstance(d.get("data"), dict):
        proj["data"].update(d["data"])
    proj["updated_at"] = _now()
    _save_project(proj)
    return proj


@app.delete("/api/projects/{pid}", status_code=204)
def delete_project(pid: str) -> None:
    p = _proj_path(pid)
    if not p.exists():
        raise HTTPException(404, f"프로젝트 없음: {pid}")
    p.unlink()


# 프론트 빌드가 있으면 정적 서빙 (없으면 API 전용 — dev 는 Vite 5173 + 프록시)
_DIST = _ROOT / "frontend" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="frontend")
