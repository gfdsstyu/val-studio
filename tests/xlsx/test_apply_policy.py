"""apply-정책 엔진 + xlsx 왕복 검증 (페이즈2).

합성 워크북으로 diff 3버킷 분류를 통제 검증하고, viol export→import 재계산 tie-out,
FastAPI 앱 import 스모크(xlsx 라우트 배선)까지. stdlib 만으로 실행 가능.
"""
from __future__ import annotations

import sys
import tempfile
from math import isclose
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core import DcfSpineInput, run  # noqa: E402
from excel import build_dcf_sheet, import_dcf_model, read_workbook  # noqa: E402
from excel.apply_policy import build_apply_plan  # noqa: E402
from excel.workbook_diff import diff_workbooks  # noqa: E402
from excel.xlsx_writer import Workbook  # noqa: E402

VIOL = ROOT / "fixtures" / "viol" / "inputs.json"


def _viol_input() -> DcfSpineInput:
    import json
    d = json.loads(VIOL.read_text(encoding="utf-8"))
    fields = {f for f in DcfSpineInput.__dataclass_fields__}
    return DcfSpineInput(**{k: v for k, v in d.items() if k in fields})


def _save_read(wb: Workbook) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name
    wb.save(path)
    try:
        return read_workbook(path)
    finally:
        Path(path).unlink()


# ── apply-plan 분류 (통제 워크북) ────────────────────────────────────────────
def _base_wb() -> Workbook:
    wb = Workbook()
    s = wb.add_sheet("DCF")
    s.num("C3", 0.1)                 # 입력셀(WACC)
    s.num("C11", 1000)               # 입력셀(매출)
    s.formula("C15", "C11-C12", 800)  # 수식셀(EBIT)
    return wb


def test_input_only_change_is_safe():
    before = _save_read(_base_wb())
    wb2 = _base_wb()
    wb2.sheets[0].num("C3", 0.11)    # WACC 입력만 변경
    after = _save_read(wb2)
    plan = build_apply_plan(diff_workbooks(before, after))
    assert plan.safe is True
    assert len(plan.auto_apply) == 1
    assert plan.auto_apply[0]["ref"] == "C3"
    assert plan.review_queue == []
    assert plan.blocked == []


def test_formula_change_goes_to_review():
    before = _save_read(_base_wb())
    wb2 = _base_wb()
    wb2.sheets[0].formula("C15", "C11-C12-C14", 700)  # EBIT 수식 변경
    after = _save_read(wb2)
    plan = build_apply_plan(diff_workbooks(before, after))
    assert plan.safe is False
    assert len(plan.review_queue) == 1
    assert plan.review_queue[0]["ref"] == "C15"


def test_sheet_added_is_blocked():
    before = _save_read(_base_wb())
    wb2 = _base_wb()
    wb2.add_sheet("Extra").num("A1", 1)
    after = _save_read(wb2)
    plan = build_apply_plan(diff_workbooks(before, after))
    assert plan.safe is False
    assert any(b["kind"] == "sheet_added" for b in plan.blocked)


# ── viol export → import 재계산 tie-out ──────────────────────────────────────
def test_export_import_recompute_tie_out():
    inp = _viol_input()
    res = run(inp)
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name
    build_dcf_sheet(inp, res).save(path)
    try:
        recovered = import_dcf_model(path)
    finally:
        Path(path).unlink()
    re_res = run(recovered)
    assert isclose(re_res.per_share, res.per_share, rel_tol=1e-6)
    assert isclose(re_res.per_share, 8413.380552, rel_tol=1e-6)


# ── 앱 import 스모크 (xlsx 라우트 배선) ──────────────────────────────────────
def test_app_routes_wired():
    from api.main import app
    paths = {r.path for r in app.routes}
    assert {"/api/xlsx/export", "/api/xlsx/import", "/api/xlsx/diff"} <= paths


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed.")
