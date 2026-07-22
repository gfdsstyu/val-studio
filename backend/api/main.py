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
from excel.vs_state import parse_vs_state  # noqa: E402
from ingest.macro_client import (  # noqa: E402
    CPI_INFLATION, EcosProvider, check_macro_vintage, parse_paste_table, usable_as_of,
)
from ingest.parsers.pdf import confidence_from_garble, pdftotext_layout  # noqa: E402
from ingest.profiles.opinion_template import extract_opinion  # noqa: E402
from ingest.validators import ValidationReport  # noqa: E402
from report import lint_report  # noqa: E402
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


# 프론트는 폼 문자열을 그대로 저장·전송하므로 선택 숫자필드에 "" 가 실려 온다.
# 그대로 두면 `(1+w)**""` 같은 TypeError → 500. 입구에서 None 으로 접는다.
_OPTIONAL_NUMERIC = (
    "terminal_discount_period", "terminal_wc_ratio", "terminal_fcff_override",
    "terminal_reinvestment_rate", "effective_tax_rate", "fade_years", "fade_growth",
)


def _parse_input(data: dict) -> DcfSpineInput:
    for k in _OPTIONAL_NUMERIC:
        if isinstance(data.get(k), str) and not data[k].strip():
            data[k] = None
    try:
        return DcfSpineInput(**{k: v for k, v in data.items() if k in _FIELDS})
    except (TypeError, ValueError) as e:
        raise HTTPException(422, f"입력 오류: {e}") from e


def _result_payload(inp: DcfSpineInput, claimed: float | None = None,
                    pgr_source: str | None = None,
                    pgr_basis: str | None = None) -> dict:
    res = run(inp)
    rep = audit_dcf(inp, res, pgr_source=pgr_source, pgr_basis=pgr_basis)
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
    # PGR 출처(R2) — 스파인 필드가 아니라 audit 메타라 별도로 뽑는다.
    pgr_source = data.pop("pgr_source", None) or None
    pgr_basis = data.pop("pgr_basis", None) or None
    inp = _parse_input(data)
    try:
        return _result_payload(inp, float(claimed) if claimed not in (None, "") else None,
                               pgr_source=pgr_source, pgr_basis=pgr_basis)
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


def _baseline_from_project(pid: str) -> str:
    """저장된 프로젝트의 dcf_input → export 재생성(before 기준선) 임시파일 경로.

    왕복 루프를 닫는 핵심: 평가인이 before 원본 파일을 손수 보관·업로드하지 않아도
    되도록, 서버가 로컬 모델에서 기준선을 **결정론적으로 재생성**한다(export 는
    입력의 순수 함수라 같은 입력이면 같은 워크북).
    """
    proj = _load_project(pid)
    saved = (proj.get("data") or {}).get("dcf_input")
    if not saved:
        raise HTTPException(422,
                            "프로젝트에 저장된 DCF 입력이 없습니다 — 먼저 4.밸류에이션 › DCF 에서 계산·저장하세요.")
    inp = _parse_input(saved)
    path = _write_temp_xlsx(b"")
    build_dcf_sheet(inp, run(inp)).save(path)
    return path


def _skill_state_payload(path: str) -> dict | None:
    """워크북의 `_VS_STATE`·`Claude Log` → 이관용 dict(없으면 None).

    Claude for Excel 스킬 세션의 증적(단계·게이트·가정 대장·작업 로그)을 웹
    프로젝트로 넘긴다. 없으면 조용히 None — 웹 단독 워크북도 정상 경로.
    """
    st = parse_vs_state(read_workbook(path))
    return st.to_dict() if st.present else None


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
        state = _skill_state_payload(path)          # 스킬 증적은 import 실패해도 살린다
        try:
            inp = import_dcf_model(path)
        except DcfModelImportError as e:
            raise HTTPException(422, f"DCF 모델 import 실패(표준 레이아웃 아님?): {e}") from e
    finally:
        os.unlink(path)
    return {"input": {f: getattr(inp, f) for f in _FIELDS},
            "result": _result_payload(inp), "skill_state": state}


@app.post("/api/xlsx/diff")
async def xlsx_diff(request: Request) -> dict:
    """편집본 → 4버킷 diff + apply-정책 계획.

    before 지정 2방식(택1):
      - `project_id`: **저장된 로컬 모델에서 기준선 재생성**(권장 — 왕복 루프가 닫힘,
        평가인이 원본 파일을 보관·업로드할 필요 없음)
      - `before_b64`: 원본 파일 직접 업로드(외부 워크북끼리 비교할 때)

    입력 변경이 있으면 safe 여부와 무관하게 after 를 import·재계산해 new_input/
    new_result 를 동봉한다 — 수식 변경이 섞여도 **입력분만 부분 반영**할 수 있어야
    하기 때문(수식 변경은 review_queue 에 남아 승인 대기).
    """
    data = await request.json()
    if "after_b64" not in data:
        raise HTTPException(422, "after_b64 필요")
    if "before_b64" in data:
        p_before = _write_temp_xlsx(_decode_xlsx(data["before_b64"]))
    elif data.get("project_id"):
        p_before = _baseline_from_project(str(data["project_id"]))
    else:
        raise HTTPException(422, "before_b64 또는 project_id 필요")
    p_after = _write_temp_xlsx(_decode_xlsx(data["after_b64"]))
    try:
        diff = diff_workbooks(read_workbook(p_before), read_workbook(p_after))
        plan = build_apply_plan(diff)
        out = plan.to_dict()
        out["baseline"] = "project" if "before_b64" not in data else "upload"
        out["skill_state"] = _skill_state_payload(p_after)
        out["new_result"] = out["new_input"] = None
        if plan.auto_apply or plan.safe:
            try:
                inp = import_dcf_model(p_after)
                out["new_result"] = _result_payload(inp)
                out["new_input"] = {f: getattr(inp, f) for f in _FIELDS}
            except DcfModelImportError:
                pass                        # 표준 레이아웃 아니면 재계산 생략(diff 만)
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
            mrp_source=d.get("mrp_source"), mrp_market=d.get("mrp_market"),
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


def _opening_bs(d: dict):
    """dict → OpeningBalanceSheet. 빈 문자열은 0 으로 접는다(폼 문자열 유입 방어)."""
    from calc_core.three_statement import OpeningBalanceSheet
    def f(k):
        v = d.get(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            return 0.0
        return float(v)
    try:
        return OpeningBalanceSheet(
            cash=f("cash"), short_term_investments=f("short_term_investments"),
            net_working_capital=f("net_working_capital"),
            net_fixed_assets=f("net_fixed_assets"), other_assets=f("other_assets"),
            interest_bearing_debt=f("interest_bearing_debt"),
            other_liabilities=f("other_liabilities"),
            paid_in_capital=f("paid_in_capital"),
            retained_earnings=f("retained_earnings"), other_equity=f("other_equity"))
    except (TypeError, ValueError) as e:
        raise HTTPException(422, f"opening(기초 BS) 형식 오류: {e}") from e


def _financing(d: dict, n: int):
    """dict → FinancingPlan. 리스트는 n 개년으로 패딩(짧으면 0)."""
    from calc_core.three_statement import FinancingPlan
    def vec(k):
        raw = d.get(k) or []
        out = []
        for i in range(n):
            v = raw[i] if i < len(raw) else 0.0
            out.append(0.0 if (v is None or (isinstance(v, str) and not v.strip()))
                       else float(v))
        return out
    def num(k, default=0.0):
        v = d.get(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            return default
        return float(v)
    try:
        payout = d.get("dividend_payout_ratio", 0.0)
        if isinstance(payout, list):
            payout = [float(x or 0.0) for x in payout]
        else:
            payout = num("dividend_payout_ratio")
        return FinancingPlan(
            debt_issuance=vec("debt_issuance"), debt_repayment=vec("debt_repayment"),
            interest_rate_debt=num("interest_rate_debt"),
            interest_rate_cash=num("interest_rate_cash"),
            dividend_payout_ratio=payout,
            other_income_expense=vec("other_income_expense")
            if d.get("other_income_expense") else None)
    except (TypeError, ValueError) as e:
        raise HTTPException(422, f"financing 형식 오류: {e}") from e


@app.post("/api/three-statement")
async def three_statement_endpoint(request: Request) -> dict:
    """3표(IS·BS·CF) 조립 + **모델 정합성 게이트**.

    우리 DCF 는 무차입 FCFF 라 3표가 가치산정엔 불필요하다 — 이 엔드포인트의 목적은
    `자산=부채+자본`·`Δ현금=CFO+CFI+CFF` 항등식으로 **상류 모듈 조립 배관을 검증**하는 것.

    입력 `{ebit[], dep_amort[], capex[], net_working_capital[], opening{}, financing{},
    effective_tax_rate?, interest_basis?, circularity_enabled?, spine?}`.
    `spine`(DcfSpineInput)을 함께 주면 **3표 ↔ 스파인 영업벡터 대사** + FCFF 대사까지 돈다.

    ⚠️ 잔차는 플러그 없이 그대로 반환한다 — 차액을 메우면 검증기가 죽는다.
    """
    from calc_core.checks import (
        check_fcff_vs_cashflow, check_three_statement_integrity,
        check_three_statement_vs_spine,
    )
    from calc_core.three_statement import (
        DEFAULT_INTEREST_BASIS, ThreeStatementInput, project_three_statements,
    )

    d = await request.json()

    def vec(key: str) -> list[float]:
        raw = d.get(key) or []
        try:
            return [float(x) for x in raw]
        except (TypeError, ValueError) as e:
            raise HTTPException(422, f"{key} 형식 오류: {e}") from e

    ebit = vec("ebit")
    if not ebit:
        raise HTTPException(422, "ebit 계열 필요")
    n = len(ebit)
    tax_rate = d.get("effective_tax_rate")
    if isinstance(tax_rate, str) and not tax_rate.strip():
        tax_rate = None

    try:
        inp = ThreeStatementInput(
            ebit=ebit, dep_amort=vec("dep_amort"), capex=vec("capex"),
            net_working_capital=vec("net_working_capital"),
            opening=_opening_bs(d.get("opening") or {}),
            financing=_financing(d.get("financing") or {}, n),
            effective_tax_rate=None if tax_rate is None else float(tax_rate),
            interest_basis=str(d.get("interest_basis") or DEFAULT_INTEREST_BASIS),
            circularity_enabled=bool(d.get("circularity_enabled", True)),
        )
        res = project_three_statements(inp)
    except (TypeError, ValueError) as e:
        raise HTTPException(422, f"3표 입력 오류: {e}") from e

    findings = check_three_statement_integrity(res)
    if d.get("spine"):
        spine = _parse_input(dict(d["spine"]))
        findings.append(check_three_statement_vs_spine(spine, res))
        spine_fcff = run(spine).fcff
        findings.append(check_fcff_vs_cashflow(
            spine_fcff, res, tax_rate=inp.effective_tax_rate))

    return {
        "income_statement": {
            "ebit": res.ebit, "interest_income": res.interest_income,
            "interest_expense": res.interest_expense,
            "other_income_expense": res.other_income_expense,
            "ebt": res.ebt, "tax": res.tax, "net_income": res.net_income,
        },
        "balance_sheet": {
            "cash": res.cash, "short_term_investments": res.short_term_investments,
            "net_working_capital": res.net_working_capital,
            "net_fixed_assets": res.net_fixed_assets, "other_assets": res.other_assets,
            "interest_bearing_debt": res.interest_bearing_debt,
            "other_liabilities": res.other_liabilities,
            "paid_in_capital": res.paid_in_capital,
            "retained_earnings": res.retained_earnings, "other_equity": res.other_equity,
            "total_assets": res.total_assets, "total_liabilities": res.total_liabilities,
            "total_equity": res.total_equity,
        },
        "cash_flow": {
            "cfo": res.cfo, "cfi": res.cfi, "cff": res.cff,
            "net_change_in_cash": res.net_change_in_cash,
            "dividends": res.dividends, "delta_nwc": res.delta_nwc,
        },
        "residuals": {
            "opening_balance": res.opening_balance_residual,
            "balance": res.balance_residual,
            "cash_tie": res.cash_tie_residual,
            "re_rollforward": res.re_rollforward_residual,
        },
        "circularity": {
            "interest_basis": res.interest_basis,
            "enabled": res.circularity_enabled,
            "iterations": res.iterations, "converged": res.converged,
        },
        "ok": all(f.severity.value != "fail" for f in findings),
        "findings": [{"rule": f.rule, "severity": f.severity.value,
                      "message": f.message, "detail": f.detail} for f in findings],
    }


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
            maintenance_capex_by_class={k: [float(x) for x in v]
                                        for k, v in (ops.get("maintenance_capex_by_class")
                                                     or {}).items()} or None,
            maintenance_depreciates=bool(ops.get("maintenance_depreciates", True)),
            terminal_wc_ratio=(float(ops["terminal_wc_ratio"])
                               if ops.get("terminal_wc_ratio") is not None else None),
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
            fade_years=(int(ops["fade_years"])
                        if ops.get("fade_years") is not None else None),
            fade_growth=(float(ops["fade_growth"])
                         if ops.get("fade_growth") is not None else None),
            terminal_from_last_fcff=bool(ops.get("terminal_from_last_fcff", False)),
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


# ── 매출 트리 (bottom_up P×Q / top_down CAGR) ────────────────────────────────
def _revenue_node(d: dict):
    """dict → RevenueNode 재귀 조립(프론트 트리 UI → 서버 검증)."""
    from calc_core.revenue import RevenueNode
    return RevenueNode(
        name=d.get("name", "?"),
        children=[_revenue_node(c) for c in (d.get("children") or [])],
        price=d.get("price"), qty=d.get("qty"),
        base=d.get("base"), growth=d.get("growth"),
        # razor-and-blades: 소모품 = 장비 누적 설치base × 대당매출
        equipment_new=d.get("equipment_new"),
        consumable_per_unit=d.get("consumable_per_unit"),
        installed_base0=d.get("installed_base0", 0.0),
        retirement_rate=d.get("retirement_rate", 0.0),
        provenance=d.get("provenance"),
    )


@app.post("/api/revenue/build")
async def revenue_build(request: Request) -> dict:
    """매출 추정 → 연도별 벡터 + 합계검증. bottom_up(트리) | top_down(CAGR).

    bottom_up: {method:"bottom_up", years, tree:{name,children[],price[],qty[],base,growth}}
      → 총매출 + 최상위 자식별 분해 + validate_tree_sums(내부노드=자식합) 위반 목록.
    top_down: {method:"top_down", years, params:{market_size,share,cagr,share_path?}}.
    """
    from calc_core.revenue import bottom_up, top_down, validate_tree_sums
    d = await request.json()
    years = int(d.get("years", 5))
    if d.get("method") == "top_down":
        p = d.get("params") or {}
        try:
            vec = top_down(float(p["market_size"]), float(p["share"]), float(p["cagr"]),
                           years, p.get("share_path"))
        except (KeyError, TypeError, ValueError) as e:
            raise HTTPException(422, f"top_down 파라미터 오류: {e}") from e
        return {"revenue": vec, "errors": [], "breakdown": {}}
    root = _revenue_node(d.get("tree") or {})
    try:
        vec = bottom_up(root, years)
    except ValueError as e:
        raise HTTPException(422, f"트리 리프 오류: {e}") from e
    return {
        "revenue": vec,
        "errors": validate_tree_sums(root, years),
        "breakdown": {c.name: c.revenue(years) for c in root.children},
    }


# ── 유사회사 4-step 선정 퍼널 ────────────────────────────────────────────────
@app.post("/api/peer/select")
async def peer_select(request: Request) -> dict:
    """4-step 퍼널 실행 → 확정 peer + ⚖️ 애매 큐(needs_review) + 탈락 사유 전량.

    body: {candidates:[{ticker,name,industry_code?,revenue_share_related?,listed_years?,
    suspended?}], target_industry_codes?:[...], judgments?:[{ticker,similar,reason,uncertain?}],
    revenue_share_threshold?, min_listed_years?}. Step2 무근거 판정은 422(검증 게이트).
    """
    from ingest.peer_selection import (
        PeerCandidate, Step2Judgment, codes_from_seed_peers, select_peers,
    )
    d = await request.json()
    try:
        cands = [PeerCandidate(
            ticker=c["ticker"], name=c.get("name", c["ticker"]),
            industry_code=c.get("industry_code"),
            revenue_share_related=c.get("revenue_share_related"),
            listed_years=c.get("listed_years"), suspended=bool(c.get("suspended", False)),
        ) for c in (d.get("candidates") or [])]
        judgments = [Step2Judgment(
            ticker=j["ticker"], similar=bool(j["similar"]), reason=j.get("reason", ""),
            uncertain=bool(j.get("uncertain", False)),
        ) for j in (d.get("judgments") or [])] or None
    except (KeyError, TypeError) as e:
        raise HTTPException(422, f"candidates/judgments 형식 오류: {e}") from e
    # Step1 코드: 직접 지정 우선, 없으면 seed_peers(rough 유사회사)로 KSIC 역산(Step1a)
    codes = set(d.get("target_industry_codes") or [])
    if not codes and d.get("seed_peers"):
        codes = codes_from_seed_peers([PeerCandidate(
            ticker=s.get("ticker", "?"), name=s.get("name", ""),
            industry_code=s.get("industry_code")) for s in d["seed_peers"]])
    codes = codes or None
    kw = {}
    if "revenue_share_threshold" in d:
        kw["revenue_share_threshold"] = float(d["revenue_share_threshold"])
    if "min_listed_years" in d:
        kw["min_listed_years"] = float(d["min_listed_years"])
    try:
        res = select_peers(cands, target_ticker=d.get("target_ticker"),
                           target_industry_codes=codes, judgments=judgments, **kw)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {
        "funnel": res.funnel,
        "selected": [{"ticker": c.ticker, "name": c.name} for c in res.selected],
        "needs_review": [{"ticker": t.candidate.ticker, "name": t.candidate.name,
                          "reason": t.review_reason} for t in res.needs_review],
        "dropped": [{"ticker": t.candidate.ticker, "name": t.candidate.name,
                     "dropped_at": t.dropped_at, "reason": t.reason}
                    for t in res.traces if t.dropped_at],
        "warnings": [f"{t.candidate.name}: {w}" for t in res.traces for w in t.warnings],
        "size_note": res.size_note(),
        "markdown": res.to_markdown(),
        "codes_used": sorted(codes or []),      # Step1a 역산 결과(감사 추적)
    }


@app.get("/api/ksic/search")
def ksic_search(q: str) -> dict:
    """KSIC 산업코드 검색(모집단 코드 조회 보조). q=키워드(공백=AND)."""
    from ingest import ksic
    return {"results": [{"code": c, "name": n} for c, n in ksic.search(q)]}


# ── 가정 상류 계산 (원가·판관비 / FA / WC → DCF 시리즈) ───────────────────────
@app.post("/api/assumptions/build")
async def assumptions_build(request: Request) -> dict:
    """운영가정 → DCF 시리즈. 파트별로 입력 있는 것만 계산(3시트 공유 엔드포인트).

    - ebit: {revenue, cogs_pct, sga_pct} → {cogs, sga, gross_profit, ebit}
    - fa:   {asset_classes:[{name,opening_net_book,remaining_life,useful_life}],
             new_capex_by_class:{name:[...]}}  → {dep_amort, capex}
    - wc:   {wc_items:[{name,base_balance,base_driver,is_asset}], wc_driver_by_item,
             base_net_working_capital} → {net_working_capital, delta_nwc_cash_adj}
    """
    from calc_core.ebit import build_ebit_from_ratios
    from calc_core.fa import project_fixed_assets
    from calc_core.wc import project_working_capital
    d = await request.json()
    out: dict = {}
    try:
        if d.get("revenue") and d.get("cogs_pct") and d.get("sga_pct"):
            eb = build_ebit_from_ratios(
                [float(x) for x in d["revenue"]],
                [float(x) for x in d["cogs_pct"]], [float(x) for x in d["sga_pct"]])
            out["ebit"] = {"cogs": eb.cogs, "sga": eb.sga,
                           "gross_profit": eb.gross_profit, "ebit": eb.ebit}
        if d.get("asset_classes"):
            maint = {k: [float(x) for x in v]
                     for k, v in (d.get("maintenance_capex_by_class") or {}).items()} or None
            fa_res = project_fixed_assets(
                _asset_classes(d["asset_classes"]),
                {k: [float(x) for x in v]
                 for k, v in (d.get("new_capex_by_class") or {}).items()},
                maint,
                maintenance_depreciates=bool(d.get("maintenance_depreciates", True)))
            out["fa"] = {"dep_amort": fa_res.dep_amort, "capex": fa_res.capex,
                         "detail": fa_res.detail}
        if d.get("wc_items"):
            wc_res = project_working_capital(
                _wc_items(d["wc_items"]),
                {k: [float(x) for x in v]
                 for k, v in (d.get("wc_driver_by_item") or {}).items()},
                float(d.get("base_net_working_capital", 0.0)))
            out["wc"] = {"net_working_capital": wc_res.net_working_capital,
                         "delta_nwc_cash_adj": wc_res.delta_nwc_cash_adj}
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as e:
        raise HTTPException(422, f"가정 계산 오류: {e}") from e
    return out


# ── FS 계정 자동 분류 (NOA/IBD 등 버킷 제안) ─────────────────────────────────
@app.post("/api/assumptions/costs-build")
async def costs_build(request: Request) -> dict:
    """성격별 원가 라인 → 매출원가·판관비 벡터(비올/참고 모델 다중 드라이버).

    body: {years, cpi?:[연율], fa_dep?:[감가상각], lines:[{name, category:'cogs'|'sga',
    method:'growth'|'ratio'|'headcount'|'cpi'|'fa_dep'|'fixed', ...params}]}.
    → {cogs, sga, detail}. 각 라인은 자기 경제동인으로 투영 후 카테고리 합산.
    """
    from calc_core.cost_build import CostLine, project_costs
    d = await request.json()
    years = int(d.get("years", 0))
    if years <= 0:
        raise HTTPException(422, "years 필요")
    _F = {"base", "growth", "driver", "pct", "headcount", "wage_per_head",
          "bonus_rate", "severance_rate", "fa_share"}
    try:
        lines = [CostLine(name=ln.get("name", "?"), category=ln.get("category", "cogs"),
                          method=ln["method"], **{k: ln[k] for k in _F if k in ln})
                 for ln in (d.get("lines") or [])]
        res = project_costs(lines, years, cpi=d.get("cpi"), fa_dep=d.get("fa_dep"))
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(422, f"원가 라인 오류: {e}") from e
    return {"cogs": res.cogs, "sga": res.sga, "detail": res.detail}


@app.post("/api/assumptions/lease")
async def assumptions_lease(request: Request) -> dict:
    """K-IFRS 1116 리스 스케줄 → 이자·원금·ROU 감가상각·리스부채잔액.

    body: {term, discount_rate, annual_payment? | initial_liability?, rou_asset?}.
    → ROU 감가상각(D&A 가산), 리스부채잔액(순차입부채), 이자(금융비용).
    """
    from calc_core.lease import lease_schedule
    d = await request.json()
    try:
        r = lease_schedule(
            int(d["term"]), float(d["discount_rate"]),
            annual_payment=d.get("annual_payment"),
            initial_liability=d.get("initial_liability"),
            rou_asset=d.get("rou_asset"))
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(422, f"리스 입력 오류: {e}") from e
    return {"liability_open": r.liability_open, "interest": r.interest,
            "principal": r.principal, "payment": r.payment,
            "liability_close": r.liability_close, "rou_depreciation": r.rou_depreciation}


@app.post("/api/footnote/costs")
async def footnote_costs_endpoint(request: Request) -> dict:
    """성격별 원가/판관비 주석표 → 성격별 금액 추출 + 드라이버 제안 + tie-out(계정세분화 ①단).

    body: {text(복붙 표), note_no?, unit?('백만원'등), source_id?, year?(tie-out 기준연도),
    stated_sga?, stated_cogs?(IS 표기 판관비/매출원가 → Σ성격별 tie-out)}.
    → {natures:[{name,category,method,confidence,uncertain,amounts,note}], drafts(CostLine 초안),
    years, extraction(추출 findings), tieout(Σ 검증 findings), ok}. 추출=결정론, 드라이버=제안.
    """
    from decimal import Decimal

    from ingest.footnote_costs import (
        FootnoteCostParser, costs_tieout, to_cost_line_drafts,
    )
    d = await request.json()
    text = d.get("text") or ""
    if not str(text).strip():
        raise HTTPException(422, "text 필요")
    p = FootnoteCostParser(d.get("source_id", "주석"),
                           note_no=d.get("note_no"), unit=d.get("unit"))
    p.extract(text)
    natures, years = p.natures, p.years

    tieout: list[dict] = []
    s_sga, s_cogs = d.get("stated_sga"), d.get("stated_cogs")
    if (s_sga is not None or s_cogs is not None) and years:
        rpt = costs_tieout(
            natures, year=str(d.get("year") or years[0]),
            stated_sga=Decimal(str(s_sga)) if s_sga is not None else None,
            stated_cogs=Decimal(str(s_cogs)) if s_cogs is not None else None)
        tieout = _findings(rpt)

    def _nd(n) -> dict:
        return {"name": n.name, "category": n.category, "method": n.method,
                "confidence": n.method_confidence, "uncertain": n.uncertain,
                "amounts": {k: float(v) for k, v in n.amounts.items()}, "note": n.note}

    return {
        "natures": [_nd(n) for n in natures],
        "drafts": to_cost_line_drafts(natures, years),
        "years": years,
        "extraction": _findings(p.result.report),
        "tieout": tieout,
        "ok": p.result.report.ok,
    }


@app.post("/api/dart/employee")
async def dart_employee_endpoint(request: Request,
                                 x_dart_key: str | None = Header(default=None)) -> dict:
    """{corp_code, bsns_year, reprt_code?} + X-Dart-Key → 직원현황 집계 + headcount CostLine.

    노무비 headcount 드라이버 실측 시드(인원×인당급여). 성장률 주면 CostLine 벡터까지 전개.
    cross-source tie-out(주석 급여 vs DART 급여총액)은 /api/footnote/costs 결과와 조합.
    """
    if not x_dart_key:
        raise HTTPException(400, "X-Dart-Key 헤더 없음")
    from ingest.dart_client import DartClient, DartError
    from ingest.dart_employee import to_headcount_costline
    d = await request.json()
    corp = str(d.get("corp_code", "")).strip()
    year = str(d.get("bsns_year", "")).strip()
    if not (corp and year):
        raise HTTPException(422, "corp_code, bsns_year 필요")
    client = DartClient(api_key=x_dart_key)
    try:
        snap = client.employee_status(corp, year, reprt_code=d.get("reprt_code", "11011"))
    except DartError as e:
        raise HTTPException(422, f"DART 오류: {e.status} {e.message}") from e
    except urllib.error.URLError as e:
        raise HTTPException(502, f"네트워크 오류: {e.reason}") from e
    costline = to_headcount_costline(
        snap, name=d.get("name", "노무비"), category=d.get("category", "sga"),
        years=int(d.get("years", 5)),
        headcount_growth=float(d.get("headcount_growth", 0.0)),
        wage_growth=float(d.get("wage_growth", 0.0)),
        bonus_rate=float(d.get("bonus_rate", 0.0)),
        severance_rate=float(d.get("severance_rate", 0.0)))
    return {
        "headcount": float(snap.headcount),
        "total_salary": float(snap.total_salary),
        "avg_wage": float(snap.avg_wage) if snap.avg_wage is not None else None,
        "by_division": {k: {kk: float(vv) for kk, vv in v.items()}
                        for k, v in snap.by_division.items()},
        "costline": costline,
        "findings": _findings(snap.report),
        "ok": snap.report.ok,
        "corp_code": corp, "year": year,
    }


@app.post("/api/fs/classify")
async def fs_classify(request: Request) -> dict:
    """계정명(+표준 요소명) 리스트 → 버킷 제안. 무매칭 = uncertain(유저 분류 필요).

    body: {statement: "PL"|"BS", accounts: [...]}. accounts 원소는 문자열이거나
        {name, account_id} 객체. account_id(예 `ifrs-full_Revenue`)가 있으면 택사노미로
        먼저 판정(표기 흔들림 면역), 없으면 계정명 키워드 폴백. 반환은 **제안**일 뿐 —
        judgment=True(평가목적 재분류 판단 사항)는 자동 확정 금지, 유저 승인 대상.
    """
    from ingest.fs_mapper import classify_all
    d = await request.json()
    stmt = str(d.get("statement", "")).upper()
    if stmt not in ("PL", "BS"):
        raise HTTPException(422, "statement 는 'PL'|'BS'")
    names: list[str] = []
    ids: list[str | None] = []
    for a in (d.get("accounts") or []):
        if isinstance(a, dict):
            names.append(str(a.get("name", "")))
            aid = a.get("account_id")
            ids.append(str(aid) if aid else None)
        else:
            names.append(str(a))
            ids.append(None)
    try:
        cls = classify_all(names, stmt, account_ids=ids)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"classifications": [
        {"account": c.account, "bucket": c.bucket, "confidence": c.confidence,
         "rule": c.rule, "uncertain": c.uncertain, "note": c.note,
         "judgment": c.judgment} for c in cls]}


# ── Company Brief — DART 원문 XBRL → 프리필 + 마크다운 골격 ───────────────────
@app.post("/api/brief/from_xbrl")
async def brief_from_xbrl(request: Request) -> dict:
    """{xbrl_b64, company_hint?} → 재무·세그먼트·주식수 프리필 + Brief 마크다운(10섹션).

    DART 원문 XBRL instance(.xbrl)를 업로드하면 결정론 추출. label 링크베이스가 함께
    있으면(형제 *_lab-ko.xml) 세그먼트 한글명까지, 없으면 축코드로 degrade.
    """
    from ingest.parsers.xbrl import XbrlParser
    from ingest.profiles.research_brief import extract_research_brief, render_brief_md
    d = await request.json()
    if "xbrl_b64" not in d:
        raise HTTPException(422, "xbrl_b64 필요")
    raw = _decode_xlsx(d["xbrl_b64"])                 # base64 디코드 재사용
    fd, path = tempfile.mkstemp(suffix=".xbrl")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        p = XbrlParser("brief-upload")
        try:
            p.extract(path)
        except Exception as e:                        # noqa: BLE001 — 파싱 실패 안내
            raise HTTPException(422, f"XBRL 파싱 실패(원문 instance 아님?): {e}") from e
        pre = extract_research_brief(p)
        md = render_brief_md(pre, company_hint=d.get("company_hint", ""))
    finally:
        os.unlink(path)
    def _seg(s):
        return {"label": s.label, "period": s.period, "revenue": s.revenue}
    return {
        "company": pre.company, "homepage": pre.homepage, "doc_period": pre.doc_period,
        "financials": pre.financials,
        "segments": [_seg(s) for s in pre.segments],
        "regions": [_seg(s) for s in pre.regions],
        "issued_shares": pre.issued_shares, "treasury_shares": pre.treasury_shares,
        "floating_ratio": pre.floating_ratio(),
        "periods": sorted(pre.financials), "markdown": md,
    }


# ── DART API 재무제표 (BYOK: X-Dart-Key 헤더 통과, 서버 미저장) ───────────────
@app.post("/api/dart/validate")
def dart_validate(x_dart_key: str | None = Header(default=None)) -> dict:
    """BYOK DART 키 검증 — company.json 1회 조회(status '000'=유효, '020'=키오류)."""
    if not x_dart_key:
        raise HTTPException(400, "X-Dart-Key 헤더 없음")
    import json as _j
    import urllib.parse
    qs = urllib.parse.urlencode({"crtfc_key": x_dart_key, "corp_code": "00126380"})
    try:
        with urllib.request.urlopen(  # noqa: S310
                f"https://opendart.fss.or.kr/api/company.json?{qs}", timeout=15) as r:
            d = _j.loads(r.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise HTTPException(502, f"네트워크 오류: {e.reason}") from e
    return {"valid": d.get("status") == "000", "status": d.get("status"),
            "message": d.get("message")}


@app.post("/api/dart/financials")
async def dart_financials(request: Request,
                          x_dart_key: str | None = Header(default=None)) -> dict:
    """{corp_code, year, reprt_code?, fs_div?} + X-Dart-Key → 계정별 값(백만원·출처).

    fnlttSinglAcntAll(단일회사 전체 재무제표). sj_div(BS/IS/CF/CIS)로 손익·BS 분리 가능
    → 매핑 시트로 보내 fs_mapper 자동 분류 → NOA/IBD 브리지. reprt_code 기본=사업보고서.
    """
    if not x_dart_key:
        raise HTTPException(400, "X-Dart-Key 헤더 없음")
    from ingest.dart_client import DartClient, DartError
    d = await request.json()
    corp, year = str(d.get("corp_code", "")).strip(), str(d.get("year", "")).strip()
    if not (corp and year):
        raise HTTPException(422, "corp_code, year 필요")
    client = DartClient(api_key=x_dart_key)
    try:
        res = client.financial_statements(
            corp, year, reprt_code=d.get("reprt_code", "11011"),
            fs_div=d.get("fs_div", "CFS"))
    except DartError as e:
        raise HTTPException(422, f"DART 오류: {e.status} {e.message}") from e
    except urllib.error.URLError as e:
        raise HTTPException(502, f"네트워크 오류: {e.reason}") from e
    accounts = []
    for pv in res.values:
        sj, _, nm = pv.field_name.partition(":")
        accounts.append({"field": pv.field_name, "sj_div": sj, "name": nm or pv.field_name,
                         "value": float(pv.value) if pv.value is not None else None,
                         "account_id": pv.provenance.locator.account_id})
    return {"accounts": accounts, "count": len(accounts), "ok": res.report.ok,
            "corp_code": corp, "year": year}


# ── DART 기업코드 검색(캐시) · 공시목록 · 원본 zip ───────────────────────────
# corpCode.xml(~10만사)은 최초 1회 다운로드해 서버 캐시(var/), 이후 인메모리 검색.
_CORP_CACHE = _ROOT / "var" / "dart_corpcode.json"
_corp_index: list[dict] | None = None


def _load_corp_index(api_key: str) -> list[dict]:
    """캐시 있으면 로드, 없으면 DART 에서 1회 다운로드 후 캐시."""
    global _corp_index
    if _corp_index is not None:
        return _corp_index
    if _CORP_CACHE.exists():
        _corp_index = _json.loads(_CORP_CACHE.read_text(encoding="utf-8"))
        return _corp_index
    from ingest.dart_corp import fetch_corp_index
    idx = fetch_corp_index(api_key)
    _CORP_CACHE.parent.mkdir(parents=True, exist_ok=True)
    _CORP_CACHE.write_text(_json.dumps(idx, ensure_ascii=False), encoding="utf-8")
    _corp_index = idx
    return idx


@app.post("/api/dart/corp-search")
async def dart_corp_search(request: Request,
                           x_dart_key: str | None = Header(default=None)) -> dict:
    """{q, listed_only?} + X-Dart-Key → 회사명 → corp_code 후보. 최초 1회만 키로 다운로드."""
    from ingest.dart_corp import search_corp_index
    d = await request.json()
    q = str(d.get("q", "")).strip()
    if not q:
        raise HTTPException(422, "q(회사명) 필요")
    if _corp_index is None and not _CORP_CACHE.exists() and not x_dart_key:
        raise HTTPException(400, "최초 기업코드 다운로드에 X-Dart-Key 필요(이후 캐시)")
    try:
        idx = _load_corp_index(x_dart_key or "")
    except urllib.error.URLError as e:
        raise HTTPException(502, f"corpCode 다운로드 실패: {e.reason}") from e
    hits = search_corp_index(idx, q, listed_only=bool(d.get("listed_only")))
    return {"results": hits, "cached": _CORP_CACHE.exists(), "total": len(idx)}


@app.post("/api/dart/filings")
async def dart_filings(request: Request,
                       x_dart_key: str | None = Header(default=None)) -> dict:
    """{corp_code, bgn_de, end_de?, pblntf_ty?} + X-Dart-Key → 공시목록(rcept_no 등)."""
    if not x_dart_key:
        raise HTTPException(400, "X-Dart-Key 헤더 없음")
    from ingest.dart_corp import list_filings
    d = await request.json()
    corp = str(d.get("corp_code", "")).strip()
    bgn = str(d.get("bgn_de", "")).strip()
    if not (corp and bgn):
        raise HTTPException(422, "corp_code, bgn_de(YYYYMMDD) 필요")
    try:
        rows = list_filings(x_dart_key, corp, bgn_de=bgn, end_de=d.get("end_de"),
                            pblntf_ty=d.get("pblntf_ty"))
    except RuntimeError as e:
        raise HTTPException(422, str(e)) from e
    except urllib.error.URLError as e:
        raise HTTPException(502, f"네트워크 오류: {e.reason}") from e
    return {"filings": rows, "count": len(rows)}


@app.post("/api/dart/document")
async def dart_document(request: Request,
                        x_dart_key: str | None = Header(default=None)) -> Response:
    """{rcept_no} + X-Dart-Key → 원본 공시 zip(document.xml) 다운로드."""
    if not x_dart_key:
        raise HTTPException(400, "X-Dart-Key 헤더 없음")
    from ingest.dart_corp import download_document
    d = await request.json()
    rcept = str(d.get("rcept_no", "")).strip()
    if not rcept:
        raise HTTPException(422, "rcept_no 필요")
    try:
        blob = download_document(x_dart_key, rcept)
    except urllib.error.URLError as e:
        raise HTTPException(502, f"네트워크 오류: {e.reason}") from e
    return Response(
        content=blob, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="dart_{rcept}.zip"'})


# ── DART 정기보고서 주요정보 5종 (BYOK, 서버 미저장) ─────────────────────────────
# 재무 숫자(fnlttSinglAcntAll) 밖의 구조·귀속 정보: 개황·감사의견·주식총수·최대주주·
# 타법인출자·배당. 전부 {corp_code, bsns_year, reprt_code?} 공통(개황만 corp_code).
def _dart_report_args(d: dict) -> tuple[str, str, str]:
    corp = str(d.get("corp_code", "")).strip()
    year = str(d.get("bsns_year") or d.get("year") or "").strip()
    if not (corp and year):
        raise HTTPException(422, "corp_code, bsns_year 필요")
    return corp, year, str(d.get("reprt_code", "11011"))


@app.post("/api/dart/company")
async def dart_company(request: Request,
                       x_dart_key: str | None = Header(default=None)) -> dict:
    """{corp_code} + X-Dart-Key → 기업개황. acc_mt(결산월)는 DCF 기간 정합 게이트."""
    if not x_dart_key:
        raise HTTPException(400, "X-Dart-Key 헤더 없음")
    from ingest.dart_reports import DartReportError, fetch_company
    d = await request.json()
    corp = str(d.get("corp_code", "")).strip()
    if not corp:
        raise HTTPException(422, "corp_code 필요")
    try:
        info = fetch_company(x_dart_key, corp)
    except DartReportError as e:
        raise HTTPException(422, f"DART 오류: {e.status} {e.message}") from e
    except urllib.error.URLError as e:
        raise HTTPException(502, f"네트워크 오류: {e.reason}") from e
    return {"company": info, "corp_code": corp}


@app.post("/api/dart/audit-opinion")
async def dart_audit_opinion(request: Request,
                             x_dart_key: str | None = Header(default=None)) -> dict:
    """{corp_code, bsns_year, reprt_code?} → 감사인·감사의견·강조사항·KAM(3개년)."""
    if not x_dart_key:
        raise HTTPException(400, "X-Dart-Key 헤더 없음")
    from ingest.dart_reports import DartReportError, fetch_audit_opinion
    corp, year, reprt = _dart_report_args(await request.json())
    try:
        rows = fetch_audit_opinion(x_dart_key, corp, year, reprt_code=reprt)
    except DartReportError as e:
        raise HTTPException(422, f"DART 오류: {e.status} {e.message}") from e
    except urllib.error.URLError as e:
        raise HTTPException(502, f"네트워크 오류: {e.reason}") from e
    return {"opinions": rows, "count": len(rows), "corp_code": corp, "year": year}


@app.post("/api/dart/shares")
async def dart_shares(request: Request,
                      x_dart_key: str | None = Header(default=None)) -> dict:
    """{corp_code, bsns_year, reprt_code?} → 주식총수(발행/유통) + 최대주주.

    발행주식수와 유통주식수를 함께 반환한다 — 주당가치 분모가 어느 쪽이냐로 갈리는
    D7 게이트(발행 vs 유통 괴리)의 원천. 최대주주 현황도 같이 실어 지분율을 붙인다.
    """
    if not x_dart_key:
        raise HTTPException(400, "X-Dart-Key 헤더 없음")
    from ingest.dart_reports import (DartReportError, fetch_major_shareholders,
                                     fetch_shares_total)
    corp, year, reprt = _dart_report_args(await request.json())
    try:
        shares = fetch_shares_total(x_dart_key, corp, year, reprt_code=reprt)
        holders = fetch_major_shareholders(x_dart_key, corp, year, reprt_code=reprt)
    except DartReportError as e:
        raise HTTPException(422, f"DART 오류: {e.status} {e.message}") from e
    except urllib.error.URLError as e:
        raise HTTPException(502, f"네트워크 오류: {e.reason}") from e
    return {"shares": shares, "major_shareholders": holders,
            "corp_code": corp, "year": year}


@app.post("/api/dart/investments")
async def dart_investments(request: Request,
                           x_dart_key: str | None = Header(default=None)) -> dict:
    """{corp_code, bsns_year, reprt_code?} → 타법인 출자현황(장부가액 = NOA 시드)."""
    if not x_dart_key:
        raise HTTPException(400, "X-Dart-Key 헤더 없음")
    from ingest.dart_reports import DartReportError, fetch_investments
    corp, year, reprt = _dart_report_args(await request.json())
    try:
        rows = fetch_investments(x_dart_key, corp, year, reprt_code=reprt)
    except DartReportError as e:
        raise HTTPException(422, f"DART 오류: {e.status} {e.message}") from e
    except urllib.error.URLError as e:
        raise HTTPException(502, f"네트워크 오류: {e.reason}") from e
    return {"investments": rows, "count": len(rows), "corp_code": corp, "year": year}


@app.post("/api/dart/dividends")
async def dart_dividends(request: Request,
                         x_dart_key: str | None = Header(default=None)) -> dict:
    """{corp_code, bsns_year, reprt_code?} → 배당지표(당기/전기/전전기)."""
    if not x_dart_key:
        raise HTTPException(400, "X-Dart-Key 헤더 없음")
    from ingest.dart_reports import DartReportError, fetch_dividends
    corp, year, reprt = _dart_report_args(await request.json())
    try:
        rows = fetch_dividends(x_dart_key, corp, year, reprt_code=reprt)
    except DartReportError as e:
        raise HTTPException(422, f"DART 오류: {e.status} {e.message}") from e
    except urllib.error.URLError as e:
        raise HTTPException(502, f"네트워크 오류: {e.reason}") from e
    return {"dividends": rows, "count": len(rows), "corp_code": corp, "year": year}


# ── 주가·β·시총·환율 (KRX FinanceDataReader — 무료, 키 불요) ──────────────────
def _fdr_provider():
    from ingest.price_client import FinanceDataReaderProvider
    return FinanceDataReaderProvider()


@app.post("/api/price/beta")
async def price_beta(request: Request) -> dict:
    """{ticker, market_ticker?, base_date, freq?, years?} → 회귀 β(look-ahead 가드).

    ticker=종목코드(005930), market_ticker 기본 KS11(KOSPI). 조정베타=0.67·raw+0.33.
    """
    from ingest.price_client import beta_from_prices
    d = await request.json()
    tk, base = str(d.get("ticker", "")).strip(), str(d.get("base_date", "")).strip()
    if not (tk and base):
        raise HTTPException(422, "ticker, base_date 필요")
    try:
        r = beta_from_prices(_fdr_provider(), tk, str(d.get("market_ticker", "KS11")),
                             base, freq=str(d.get("freq", "W")), years=float(d.get("years", 2)))
    except RuntimeError as e:                          # fdr 미설치
        raise HTTPException(503, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"raw": r.raw, "adjusted": r.adjusted, "r_squared": r.r_squared,
            "n": r.n, "freq": r.freq, "window_end": r.window_end}


@app.post("/api/price/marketcap")
async def price_marketcap(request: Request) -> dict:
    """{ticker, shares, base_date} → 시가총액(평가기준일 이하 최신 종가 × 발행주식수)."""
    from ingest.price_client import market_cap
    d = await request.json()
    tk, base = str(d.get("ticker", "")).strip(), str(d.get("base_date", "")).strip()
    try:
        shares = float(d["shares"])
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(422, f"shares 필요: {e}") from e
    if not (tk and base):
        raise HTTPException(422, "ticker, base_date 필요")
    try:
        mc = market_cap(_fdr_provider(), tk, shares=shares, base_date=base)
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"value": mc.value, "price": mc.price, "price_date": mc.price_date, "shares": mc.shares}


@app.post("/api/price/fx")
async def price_fx(request: Request) -> dict:
    """{pair, base_date} → 평가기준일 이하 최신 환율(look-ahead 가드). pair 예: USD/KRW."""
    d = await request.json()
    pair, base = str(d.get("pair", "USD/KRW")).strip(), str(d.get("base_date", "")).strip()
    if not base:
        raise HTTPException(422, "base_date 필요")
    try:
        prov = _fdr_provider()
        rows = [(dt, c) for dt, c in prov.closes(pair, "2000-01-01", base) if dt <= base]
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    if not rows:
        raise HTTPException(422, f"{pair}: 평가기준일 이하 환율 없음")
    dt, c = rows[-1]
    return {"pair": pair, "rate": c, "rate_date": dt}


# ── CSV/엑셀 업로드 → 정규화 그리드(복붙 대안: 한공회 β·Kd 매트릭스·신용등급 표) ──
def _cells_to_grid(cells: dict) -> list[list]:
    """{cell ref: RCell} → 2D 그리드(행·열 정렬). 빈 셀은 ''."""
    import re as _re2
    parsed, maxr, maxc = [], 0, 0
    for ref, cell in cells.items():
        m = _re2.match(r"([A-Z]+)(\d+)", ref)
        if not m:
            continue
        col = 0
        for ch in m.group(1):
            col = col * 26 + (ord(ch) - 64)
        row = int(m.group(2))
        val = cell.value if cell.value is not None else ""
        parsed.append((row, col, val))
        maxr, maxc = max(maxr, row), max(maxc, col)
    grid = [["" for _ in range(maxc)] for _ in range(maxr)]
    for row, col, val in parsed:
        grid[row - 1][col - 1] = val
    return grid


@app.post("/api/report/lint")
async def report_lint(request: Request) -> dict:
    """{"text"?, "notes"?} → 서사 표현 규칙 위반(WARN) 목록.

    숫자에는 게이트가 여럿인데 텍스트 산출물에는 없던 구멍을 메운다. 검사 대상은
    ① 근거 없는 단정(감사 trail 없이 결론 확정) ② 순환설명 ③ 무설명 상투어
    ④ 뭉뚱그리기 ⑤ Driver/Outlook/Action 슬롯 공란.

    **LLM 산출물 전용이 아니다** — 사람이 쓴 조서에도 같은 규범이 적용된다.
    전부 WARN: 표현이 나빠도 계산이 무효는 아니므로 진행을 막지 않고 표면화만 한다.
    """
    d = await request.json()
    rep = lint_report(d.get("text") or "", notes=d.get("notes") or {},
                      where=d.get("where") or "리포트")
    warns = [f for f in rep.findings if f.severity.value != "pass"]
    return {
        "ok": not warns,
        "count": len(warns),
        "findings": [{"rule": f.rule, "severity": f.severity.value,
                      "message": f.message, "detail": f.detail} for f in warns],
    }


# ── 거시 가정 (2.가정 › 거시) ─────────────────────────────────────────────
@app.post("/api/macro/series")
async def macro_series(request: Request,
                       x_ecos_key: str | None = Header(None)) -> dict:
    """거시 시계열 → 연율 시리즈 + vintage 가드 findings.

    두 경로:
      - `text`(복붙): EIU·전망보고서 '기간 값' 표 → `parse_paste_table`. stdlib, 항상 가능.
        예측 스냅샷이라 `vintage`(발행일)를 함께 받아 그 시점 전망으로 고정 보존한다.
      - ECOS(`X-Ecos-Key` + start/end): 한국은행 실적. **개정치만 반환**하므로 예측·
        최근연도는 복붙 경로가 정본(macro_client EcosProvider docstring 규칙).

    `base_date` 를 주면 look-ahead 가드를 건다 — 평가기준일 이후에 공표된 값은
    usable 에서 제외(기준일에 알 수 없던 정보로 과거를 평가하지 않는다).
    """
    d = await request.json()
    indicator = d.get("indicator") or CPI_INFLATION
    base_date = d.get("base_date")
    report = ValidationReport()

    if d.get("text"):
        series = parse_paste_table(
            d["text"], indicator,
            vintage=d.get("vintage") or (base_date or ""),
            is_forecast_from=d.get("is_forecast_from"),
            source=d.get("source") or "붙여넣기",
            report=report,
        )
    elif x_ecos_key:
        try:
            series = EcosProvider(api_key=x_ecos_key).fetch(
                indicator, str(d.get("start") or ""), str(d.get("end") or ""))
        except (ValueError, OSError, urllib.error.URLError) as e:
            raise HTTPException(422, f"ECOS 조회 실패: {e}") from e
    else:
        raise HTTPException(422, "text(복붙) 또는 X-Ecos-Key 헤더 필요")

    findings = list(report.findings)
    dropped: list[str] = []
    if base_date:
        findings.extend(check_macro_vintage(series, base_date))
        usable = usable_as_of(series, base_date)
        # 가드에 걸려 빠진 기간을 명시 — 조용히 사라지면 사용자는 전망을 넣었다고
        # 믿는데 값이 없는 상태가 된다(예: is_forecast_from 미기재 시 미래연도 전량).
        kept = {o.period for o in usable.observations}
        dropped = [o.period for o in series.observations if o.period not in kept]
        series = usable

    obs = [{"period": o.period, "value": o.value, "vintage": o.vintage,
            "source": o.source, "is_forecast": o.is_forecast}
           for o in series.observations]
    # 연도별 대표값(같은 해 복수 관측이면 마지막) — cost_build 의 cpi 연율 리스트용.
    annual: dict[str, float] = {}
    for o in series.observations:
        if o.period[:4].isdigit():
            annual[o.period[:4]] = o.value
    return {
        "indicator": series.indicator, "unit": series.unit,
        "observations": obs, "annual": annual, "dropped_periods": dropped,
        "findings": [{"rule": f.rule, "severity": f.severity.value, "message": f.message}
                     for f in findings],
    }


@app.post("/api/macro/pgr-suggest")
async def macro_pgr_suggest(request: Request) -> dict:
    """물가 시계열(복붙) → **영구성장률 앵커 제안**(R2). 제안일 뿐 확정은 평가인 몫.

    `{text, vintage?, base_date?, source?, years?}` — /api/macro/series 와 같은 복붙 경로를
    쓰되 **vintage 가드 통과분만** 평균한다(평가기준일 이후 공표값 배제).

    근거: 모델러스 정본 `F33 = AVERAGE(rInflation 10년)/100 = 1.62%` — PGR 을 감(感)이
    아니라 출처 있는 거시 통계의 함수로 만든다.
    """
    from ingest.macro_client import suggest_pgr_from_inflation
    d = await request.json()
    if not d.get("text"):
        raise HTTPException(422, "text(물가 시계열 복붙) 필요")
    base_date = d.get("base_date") or ""
    report = ValidationReport()
    series = parse_paste_table(
        d["text"], CPI_INFLATION,
        vintage=d.get("vintage") or base_date,
        is_forecast_from=d.get("is_forecast_from"),
        source=d.get("source") or "붙여넣기", report=report)
    # base_date 미지정이면 vintage 가드가 사실상 무력화된다(모든 관측이 usable) —
    # 조용히 통과시키지 않고 findings 에 명시한다.
    guard_note = None
    if not base_date:
        guard_note = {"rule": "pgr_anchor", "severity": "warn",
                      "message": "평가기준일(base_date) 미지정 — look-ahead 가드가 적용되지 "
                                 "않았다(기준일 이후 공표값이 섞일 수 있음)"}
    try:
        sug = suggest_pgr_from_inflation(series, base_date or "9999-12-31",
                                         years=int(d.get("years", 10)))
    except (TypeError, ValueError) as e:
        raise HTTPException(422, f"앵커 산출 오류: {e}") from e
    return {
        "value": sug.value, "basis": sug.basis,
        "n_observations": sug.n_observations, "periods": list(sug.periods),
        "source": sug.source,
        "findings": ([{"rule": f.rule, "severity": f.severity.value, "message": f.message}
                      for f in list(report.findings) + list(sug.findings)]
                     + ([guard_note] if guard_note else [])),
    }


# ── 감사인 트랙 ────────────────────────────────────────────────────────────
@app.post("/api/opinion/extract")
async def opinion_extract(request: Request) -> dict:
    """{"text"} 또는 {"pdf_b64"} → 외부평가의견서 유의적 가정 후보(고정양식 앵커).

    감사인 트랙 입구. 한글 라벨이 CID 로 깨져도 영문·수식 앵커(`WACC = Ke`,
    `(1+B)`, `Size Risk Premium`, iso4217)는 생존한다는 전제 — 뽑힌 값은 **후보**이며
    confidence·note 로 신뢰도를 표기한다(확정은 감사인 판단, 역할 3분할).

    pdf_b64 는 pdftotext 바이너리가 있을 때만. 없으면 의견서 텍스트를 복사해
    text 로 넣으라고 안내(로컬 환경 의존성을 조용히 삼키지 않는다).
    """
    d = await request.json()
    text = d.get("text")
    confidence = 1.0
    if not text and d.get("pdf_b64"):
        fd, path = tempfile.mkstemp(suffix=".pdf")
        with os.fdopen(fd, "wb") as f:
            f.write(_decode_xlsx(d["pdf_b64"]))         # base64 디코드 공통 헬퍼
        try:
            pages = pdftotext_layout(path)
        except (OSError, RuntimeError) as e:
            raise HTTPException(
                422, f"PDF 텍스트 추출 실패(pdftotext 미설치?): {e} — "
                     "의견서 텍스트를 복사해 붙여넣으세요") from e
        finally:
            os.unlink(path)
        text = "\n".join(p.text for p in pages)
        confidence = confidence_from_garble(text)
    if not text:
        raise HTTPException(422, "text 또는 pdf_b64 필요")

    ex = extract_opinion(text, garble_confidence=confidence)
    return {
        "entity_count": ex.entity_count,
        "terminal_growths": ex.terminal_growths,
        "size_premiums": ex.size_premiums,
        "currencies": ex.currencies,
        "is_sotp": ex.is_sotp,
        "confidence": ex.confidence,
        "note": ex.note,
        "chars": len(text),
    }


@app.post("/api/upload/sheet")
async def upload_sheet(request: Request) -> dict:
    """{csv} 또는 {xlsx_b64} → 탭 구분 텍스트(+2D rows). 복붙 textarea 에 드롭용.

    한공회 β·KOFIABOND Kd 매트릭스·신용등급 표 등을 파일로 올려 manual_paste 게이트로
    보낸다(복붙과 동일 검증). xlsx 는 첫 시트만. 값이 살아있는 수식은 캐시값 사용.
    """
    d = await request.json()
    if d.get("csv"):
        rows = [[c.strip() for c in ln.split(",")]
                for ln in str(d["csv"]).splitlines() if ln.strip()]
    elif d.get("xlsx_b64"):
        path = _write_temp_xlsx(_decode_xlsx(d["xlsx_b64"]))
        try:
            wb = read_workbook(path)
        except Exception as e:                        # noqa: BLE001
            raise HTTPException(422, f"xlsx 읽기 실패: {e}") from e
        finally:
            os.unlink(path)
        rows = _cells_to_grid(next(iter(wb.values()), {}))
    else:
        raise HTTPException(422, "csv 또는 xlsx_b64 필요")
    text = "\n".join("\t".join(str(c) for c in r) for r in rows)
    return {"text": text, "rows": rows, "n_rows": len(rows)}


# ── Damodaran 국가위험프리미엄(CRP) — WACC 마지막 입력 ──────────────────────
@app.get("/api/damodaran/crp")
def damodaran_crp(country: str | None = None) -> dict:
    """country 주면 그 국가 CRP, 없으면 등록국 목록. 미등록국은 crp=null(업로드 갱신)."""
    from ingest.damodaran import DAMODARAN_VINTAGE, country_detail, list_countries
    if country:
        d = country_detail(country)
        return {"detail": d, "vintage": DAMODARAN_VINTAGE,
                "crp": d["crp"] if d else None}
    return {"countries": list_countries(), "vintage": DAMODARAN_VINTAGE}


# ── 상대가치평가 (peer 배수 → 내재가치) ──────────────────────────────────────
@app.post("/api/bridge/check")
async def bridge_check(request: Request) -> dict:
    """{dcf:{net_debt,non_operating_assets,non_controlling_interest,shares_outstanding},
    relative:{net_debt,shares_outstanding,...}} → 교차방법 브리지 정합 findings.

    DCF 와 상대가치의 주당가치를 나란히 비교하기 전에 **브리지·주식수가 같은지** 검사.
    다르면 결과 차이가 관점 차이인지 정의 차이인지 분간 불가(모델러스 D3).
    """
    from calc_core.checks import bridge_net_position, check_cross_method_bridge
    d = await request.json()
    dcf, rel = d.get("dcf") or {}, d.get("relative") or {}
    if not dcf or not rel:
        raise HTTPException(422, "dcf·relative 브리지 양쪽 필요")
    try:
        findings = check_cross_method_bridge(dcf, rel)
    except (TypeError, ValueError) as e:
        raise HTTPException(422, f"브리지 형식 오류: {e}") from e
    return {
        "ok": all(f.severity.value != "warn" for f in findings),
        "dcf_net_position": bridge_net_position(dcf),
        "relative_net_position": bridge_net_position(rel),
        "findings": [{"rule": f.rule, "severity": f.severity.value,
                      "message": f.message, "detail": f.detail} for f in findings],
    }


@app.post("/api/relative/value")
async def relative_value(request: Request) -> dict:
    """{peers:[{name,per?,pbr?,ev_ebitda?}], target_eps?, target_bps?, target_ebitda?,
    net_debt?, shares_outstanding?, use?} → 방식별 내재 주당가치 + 5-10 Rule 경고."""
    from calc_core.multiples import PeerMultiple, relative_valuation
    d = await request.json()
    try:
        peers = [PeerMultiple(name=p.get("name", "?"),
                              per=p.get("per"), pbr=p.get("pbr"), ev_ebitda=p.get("ev_ebitda"))
                 for p in (d.get("peers") or [])]
    except (TypeError, AttributeError) as e:
        raise HTTPException(422, f"peers 형식 오류: {e}") from e
    if not peers:
        raise HTTPException(422, "peers 필요")
    r = relative_valuation(
        peers, target_eps=d.get("target_eps"), target_bps=d.get("target_bps"),
        target_ebitda=d.get("target_ebitda"), net_debt=float(d.get("net_debt", 0.0)),
        shares_outstanding=d.get("shares_outstanding"), use=str(d.get("use", "median")))
    return {"per": r.per, "pbr": r.pbr, "ev_ebitda": r.ev_ebitda, "warnings": r.warnings}


@app.post("/api/price/multiples")
async def price_multiples(request: Request) -> dict:
    """{tickers:[...], base_date} → 종목별 PER/PBR/EPS/BPS(pykrx). ⚠️ pykrx 는 KRX 로그인
    필요(KRX_ID/KRX_PW env) — 미설정 시 503, 수동/CSV 입력으로 대체."""
    from ingest.price_client import pykrx_fundamentals
    d = await request.json()
    base = str(d.get("base_date", "")).strip()
    tickers = [str(t).strip() for t in (d.get("tickers") or []) if str(t).strip()]
    if not (tickers and base):
        raise HTTPException(422, "tickers, base_date 필요")
    out, errors = [], []
    for tk in tickers:
        try:
            out.append(pykrx_fundamentals(tk, base))
        except RuntimeError as e:
            raise HTTPException(503, str(e)) from e
        except ValueError as e:
            errors.append({"ticker": tk, "error": str(e)})
    if not out and errors:
        raise HTTPException(503, "pykrx 배수 조회 실패(KRX 로그인 필요 가능) — 수동/CSV 입력 권장")
    return {"multiples": out, "errors": errors}


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


# 구용어 마이그레이션: ERP(주식위험프리미엄) → MRP(시장위험프리미엄) 개명 이전에
# 저장된 프로젝트의 provenance 키. 값 필드(`mrp`)는 이미 개명됐고 출처 2개만 남았다.
# 정규화하지 않으면 프론트가 `mrp_source` 를 못 찾아 빈 값으로 조립 → **F3(β/MRP
# 시장 정합) 게이트가 판정 근거를 잃는다**(조용한 provenance 유실).
_LEGACY_RENAMES = {"erp_source": "mrp_source", "erp_market": "mrp_market"}


def _migrate(obj):
    """저장본 읽기 시 구용어 키를 현행 키로 정규화(재귀). 현행 키가 있으면 보존."""
    if isinstance(obj, list):
        return [_migrate(v) for v in obj]
    if not isinstance(obj, dict):
        return obj
    out = {}
    for k, v in obj.items():
        new_k = _LEGACY_RENAMES.get(k, k)
        if new_k != k and new_k in obj:
            continue                                  # 현행 키가 이미 있으면 구키 버림
        out[new_k] = _migrate(v)
    return out


def _load_project(pid: str) -> dict:
    p = _proj_path(pid)
    if not p.exists():
        raise HTTPException(404, f"프로젝트 없음: {pid}")
    return _migrate(_json.loads(p.read_text(encoding="utf-8")))


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
