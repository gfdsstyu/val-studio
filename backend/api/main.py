"""로컬 모드 API — FastAPI 1프로세스 (docs/plan.md §현 단계 운영 형태).

실행: `py -3.12 -m uvicorn backend.api.main:app --reload` (레포 루트에서)
- 계산·검증은 calc_core 그대로 호출(결정론) — API 는 얇은 어댑터.
- **BYOK**: LLM 키는 클라이언트가 요청 헤더(X-Gemini-Key 등)로 전달, 서버는
  통과만 하고 어디에도 저장·로깅하지 않는다.
- 프론트: frontend/dist 빌드가 있으면 정적 서빙(/), 없으면 API 만(dev 는 Vite 프록시).
"""
from __future__ import annotations

import base64
import binascii
import dataclasses
import os
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "backend"))

from fastapi import FastAPI, Header, HTTPException, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from assemble.dcf_inputs import assemble_dcf_inputs  # noqa: E402
from assemble.wacc_inputs import PeerBeta, WaccAssembly, assemble_wacc_inputs  # noqa: E402
from calc_core import DcfSpineInput, run  # noqa: E402
from excel import build_dcf_sheet, import_dcf_model, read_workbook  # noqa: E402
from excel.apply_policy import build_apply_plan  # noqa: E402
from excel.dcf_import import DcfModelImportError  # noqa: E402
from excel.workbook_diff import diff_workbooks  # noqa: E402
from calc_core import fa as _fa, wc as _wc  # noqa: E402
from calc_core.checks import audit_dcf, diagnose_dcf_gap  # noqa: E402
from calc_core.method_selector import DEAL_TYPES, PURPOSES, recommend_method  # noqa: E402
from calc_core.scenario import run_scenarios  # noqa: E402
from ingest.manual_paste import (  # noqa: E402
    PasteParser, paste_mrp, paste_risk_free,
)

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


# ── xlsx 왕복 (export → 편집 → import/diff → 로컬 모델 반영) ──────────────────
# 업로드는 base64-in-JSON(멀티파트 의존성 python-multipart 불요, 로컬 단일프로세스에 적합).
def _decode_xlsx(b64: str) -> bytes:
    try:
        return base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise HTTPException(422, f"xlsx base64 디코드 실패: {e}") from e


def _write_temp_xlsx(data: bytes) -> str:
    fd, path = tempfile.mkstemp(suffix=".xlsx")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


@app.post("/api/xlsx/export")
async def xlsx_export(request: Request) -> Response:
    """DcfSpineInput JSON → 수식 live .xlsx 다운로드(감사 추적·재편집 가능)."""
    inp = _parse_input(await request.json())
    res = run(inp)
    path = _write_temp_xlsx(b"")
    try:
        build_dcf_sheet(inp, res).save(path)
        data = Path(path).read_bytes()
    finally:
        os.unlink(path)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="valstudio_dcf.xlsx"'},
    )


@app.post("/api/xlsx/import")
async def xlsx_import(request: Request) -> dict:
    """{"xlsx_b64": "..."} → import_dcf_model → 복원 입력 + 재계산 결과.

    표준 Val-Studio DCF 레이아웃 가정(scaffold/export 산출). 타 템플릿은 422.
    """
    data = await request.json()
    if "xlsx_b64" not in data:
        raise HTTPException(422, "xlsx_b64 필요")
    path = _write_temp_xlsx(_decode_xlsx(data["xlsx_b64"]))
    try:
        inp = import_dcf_model(path)
    except DcfModelImportError as e:
        raise HTTPException(422, f"DCF 모델 import 실패(표준 레이아웃 아님?): {e}") from e
    finally:
        os.unlink(path)
    return {"input": {f: getattr(inp, f) for f in _FIELDS}, "result": _result_payload(inp)}


@app.post("/api/xlsx/diff")
async def xlsx_diff(request: Request) -> dict:
    """{"before_b64", "after_b64"} → 3버킷 diff + apply-정책 계획.

    safe(입력 변경만)면 after 를 import·재계산해 new_result 동봉(자동 반영 가능).
    수식/구조 변경은 review_queue/blocked 로 표면화(평가인 승인·차단).
    """
    data = await request.json()
    if "before_b64" not in data or "after_b64" not in data:
        raise HTTPException(422, "before_b64, after_b64 필요")
    p_before = _write_temp_xlsx(_decode_xlsx(data["before_b64"]))
    p_after = _write_temp_xlsx(_decode_xlsx(data["after_b64"]))
    try:
        diff = diff_workbooks(read_workbook(p_before), read_workbook(p_after))
        plan = build_apply_plan(diff)
        out = plan.to_dict()
        if plan.safe:
            try:
                inp = import_dcf_model(p_after)
                out["new_result"] = _result_payload(inp)
                out["new_input"] = {f: getattr(inp, f) for f in _FIELDS}
            except DcfModelImportError:
                out["new_result"] = None  # 표준 레이아웃 아니면 재계산 생략(diff 만)
    finally:
        os.unlink(p_before)
        os.unlink(p_after)
    return out


# ── 어셈블리 (커넥터 원천값 → 검증된 엔진입력 → 결과) ────────────────────────
# 복붙 값(문자열)은 서버가 커넥터로 통과시켜 range/게이트를 서버사이드에서 건다.
# _pull 이 ParseResult(복붙)·float(직접) 둘 다 받으므로 API 는 얇은 어댑터로 남는다.
def _findings(rep) -> list[dict]:
    return [{"rule": f.rule, "severity": f.severity.value, "message": f.message}
            for f in rep.findings]


def _rf_or_mrp(val, kind: str, pasted_at: str, user: str | None):
    """숫자면 그대로(검증 완료 값), 문자열이면 복붙 커넥터로 통과(range 게이트)."""
    if isinstance(val, str):
        src = "paste"
        return (paste_risk_free if kind == "rate" else paste_mrp)(
            val, source_id=src, pasted_at=pasted_at, user=user)
    return val


def _wacc_from_json(d: dict) -> WaccAssembly:
    pasted_at = d.get("pasted_at") or _now()[:10]
    user = d.get("user")
    try:
        peers = [PeerBeta(ticker=p.get("ticker", "?"),
                          levered_beta=float(p["levered_beta"]),
                          debt_to_equity=float(p["debt_to_equity"]),
                          tax_rate=float(p["tax_rate"]))
                 for p in (d.get("peers") or [])]
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(422, f"peers 형식 오류: {e}") from e

    kd_matrix = None
    if d.get("kd_matrix_text"):
        kd_matrix = PasteParser("paste", pasted_at=pasted_at, user=user).parse_bond_matrix(
            str(d["kd_matrix_text"]))
    try:
        return assemble_wacc_inputs(
            risk_free=_rf_or_mrp(d.get("risk_free"), "rate", pasted_at, user),
            mrp=_rf_or_mrp(d.get("mrp"), "mrp", pasted_at, user),
            peers=peers,
            target_debt_to_equity=float(d.get("target_debt_to_equity", 0.0)),
            tax_rate=float(d.get("tax_rate", 0.0)),
            kd_matrix=kd_matrix, kd_grade=d.get("kd_grade"), kd_tenor=d.get("kd_tenor"),
            pre_tax_cost_of_debt=d.get("pre_tax_cost_of_debt"),
            market_cap_musd=d.get("market_cap_musd"),
            size_premium=d.get("size_premium"),
            country_risk_premium=float(d.get("country_risk_premium", 0.0)),
            company_specific_risk=float(d.get("company_specific_risk", 0.0)),
            beta_source=d.get("beta_source"), beta_market=d.get("beta_market"),
            beta_adjusted=d.get("beta_adjusted"),
            erp_source=d.get("erp_source"), erp_market=d.get("erp_market"),
        )
    except (TypeError, ValueError) as e:
        raise HTTPException(422, f"WACC 입력 오류: {e}") from e


def _serialize_wacc(a: WaccAssembly) -> dict:
    r = a.result
    return {
        "blocked": a.blocked,
        "wacc": r.wacc if r else None,
        "cost_of_equity": r.cost_of_equity if r else None,
        "after_tax_cost_of_debt": r.after_tax_cost_of_debt if r else None,
        "relevered_beta": r.relevered_beta if r else None,
        "equity_weight": r.equity_weight if r else None,
        "debt_weight": r.debt_weight if r else None,
        "inputs": (dataclasses.asdict(a.inputs) if a.inputs else None),
        "provenance": a.provenance,
        "findings": _findings(a.report),
    }


@app.post("/api/wacc/assemble")
async def wacc_assemble_endpoint(request: Request) -> dict:
    """커넥터 원천값(복붙 문자열 or 숫자) → 검증된 WACC. blocked 면 게이트 FAIL 사유 동봉."""
    d = await request.json()
    return _serialize_wacc(_wacc_from_json(d))


def _asset_classes(items: list) -> list:
    try:
        return [_fa.AssetClass(name=a["name"], opening_net_book=float(a["opening_net_book"]),
                               remaining_life=int(a["remaining_life"]),
                               useful_life=int(a["useful_life"])) for a in items]
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(422, f"asset_classes 형식 오류: {e}") from e


def _wc_items(items: list) -> list:
    try:
        return [_wc.WcItem(name=w["name"], base_balance=float(w["base_balance"]),
                           base_driver=float(w["base_driver"]),
                           is_asset=bool(w.get("is_asset", True))) for w in items]
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(422, f"wc_items 형식 오류: {e}") from e


@app.post("/api/dcf/assemble")
async def dcf_assemble_endpoint(request: Request) -> dict:
    """WACC(커넥터) + 운영가정 → 검증된 주당가치. 실행 순서 게이트(PGR≥WACC 등) 반영.

    body: {"wacc": {...WACC 원천...}, "ops": {revenue·cogs_pct·sga_pct·asset_classes·
    new_capex_by_class·wc_items·wc_driver_by_item·base_net_working_capital·terminal_growth·
    non_operating_assets·net_debt·shares_outstanding·...}}
    """
    d = await request.json()
    wacc = _wacc_from_json(d.get("wacc") or {})
    ops = d.get("ops") or {}
    try:
        a = assemble_dcf_inputs(
            wacc=wacc,
            revenue=[float(x) for x in ops.get("revenue", [])],
            cogs_pct=[float(x) for x in ops.get("cogs_pct", [])],
            sga_pct=[float(x) for x in ops.get("sga_pct", [])],
            asset_classes=_asset_classes(ops.get("asset_classes") or []),
            new_capex_by_class={k: [float(x) for x in v]
                                for k, v in (ops.get("new_capex_by_class") or {}).items()},
            wc_items=_wc_items(ops.get("wc_items") or []),
            wc_driver_by_item={k: [float(x) for x in v]
                               for k, v in (ops.get("wc_driver_by_item") or {}).items()},
            base_net_working_capital=float(ops.get("base_net_working_capital", 0.0)),
            terminal_growth=float(ops.get("terminal_growth", 0.02)),
            non_operating_assets=float(ops.get("non_operating_assets", 0.0)),
            net_debt=float(ops.get("net_debt", 0.0)),
            shares_outstanding=int(ops.get("shares_outstanding", 1)),
            mid_year_periods=ops.get("mid_year_periods"),
            terminal_discount_period=ops.get("terminal_discount_period"),
        )
    except (TypeError, ValueError) as e:
        raise HTTPException(422, f"운영가정 오류: {e}") from e
    r, s = a.result, a.spine
    return {
        "blocked": a.blocked,
        "per_share": r.per_share if r else None,
        "enterprise_value": r.enterprise_value if r else None,
        "equity_value": r.equity_value if r else None,
        "pv_explicit_sum": r.pv_explicit_sum if r else None,
        "terminal_value_pv": r.terminal_value_pv if r else None,
        "tv_weight": (r.terminal_value_pv / r.enterprise_value
                      if r and r.enterprise_value else None),
        "wacc": s.wacc if s else None,
        "provenance": a.provenance,
        "findings": _findings(a.report),
    }


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
