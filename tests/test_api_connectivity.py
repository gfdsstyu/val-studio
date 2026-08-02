"""연결성 진단 API(/api/xlsx/connectivity) 테스트 — FastAPI TestClient.

표준 export 워크북은 target 자동(DCF!C33), 비표준은 422 로 지정 요구.
표준 워크북의 기대 상태를 고정한다: 시트 하나짜리 스파인은 **끊긴 시트가 없어야**
하고(거짓양성 방지), 입력 행은 상수 잎으로 잡혀야 한다(승격 후보 표시의 근거).
"""
from __future__ import annotations

import base64
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402
from calc_core import DcfSpineInput, run  # noqa: E402
from excel import export_dcf  # noqa: E402

client = TestClient(app)
FX = ROOT / "fixtures" / "viol"


def _viol_b64() -> str:
    d = json.loads((FX / "inputs.json").read_text(encoding="utf-8"))
    inp = DcfSpineInput(
        wacc=d["wacc"], terminal_growth=d["terminal_growth"],
        revenue=d["revenue"], cogs=d["cogs"], sga=d["sga"],
        dep_amort=d["dep_amort"], capex=d["capex"],
        delta_nwc_cash_adj=d["delta_nwc_cash_adj"],
        non_operating_assets=d["non_operating_assets"], net_debt=d["net_debt"],
        shares_outstanding=d["shares_outstanding"],
        mid_year_periods=d.get("mid_year_periods"),
        terminal_discount_period=d.get("terminal_discount_period"),
    )
    path = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False).name
    export_dcf(inp, run(inp), path)
    return base64.b64encode(Path(path).read_bytes()).decode()


def test_standard_export_auto_target_and_no_false_breaks():
    r = client.post("/api/xlsx/connectivity", json={"xlsx_b64": _viol_b64()})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["target"] == "DCF!C33"                 # 표준 레이아웃 자동 인식
    assert d["dead_sheets"] == []                   # 단일 스파인 — 끊김 없어야(거짓양성 방지)
    assert d["sheet_summary"]["DCF"]["reaching"] > 0
    assert d["values_only_suspect"] is False
    # 입력 행(매출·원가 등 하드값)은 경로상 상수 잎으로 잡힌다 — 승격 후보 표시 근거
    assert d["constant_inputs_total"] > 0
    cells = {c["cell"] for c in d["constant_inputs_in_path"]}
    assert "DCF!C3" in cells                        # WACC 가정 셀
    assert d["cycles"] == []


def test_custom_target_and_bad_target():
    b64 = _viol_b64()
    ok = client.post("/api/xlsx/connectivity",
                     json={"xlsx_b64": b64, "target": "DCF!C31"})   # EV 셀
    assert ok.status_code == 200 and ok.json()["target"] == "DCF!C31"
    bad = client.post("/api/xlsx/connectivity",
                      json={"xlsx_b64": b64, "target": "DCF!ZZ999"})
    assert bad.status_code == 422


def test_nonstandard_without_target_422():
    """비표준 워크북 + target 미지정 → 422 (조용한 추측 금지)."""
    from excel.xlsx_writer import Workbook
    wb = Workbook()
    s = wb.add_sheet("Sheet1")
    s.num("A1", 1.0)
    s.formula("A2", "A1*2", 2.0)
    path = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False).name
    wb.save(path)
    b64 = base64.b64encode(Path(path).read_bytes()).decode()
    r = client.post("/api/xlsx/connectivity", json={"xlsx_b64": b64})
    assert r.status_code == 422
    assert "목표 셀" in r.json()["detail"]
    # target 을 주면 동작한다
    ok = client.post("/api/xlsx/connectivity",
                     json={"xlsx_b64": b64, "target": "Sheet1!A2"})
    assert ok.status_code == 200
    assert ok.json()["sheet_summary"]["Sheet1"]["reaching"] == 1


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
