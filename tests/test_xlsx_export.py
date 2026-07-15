"""xlsx export 왕복 검증 — 비올 스파인 → 살아있는 수식 xlsx → 재읽기 대조.

검증 항목:
  1) 결과 셀(EBIT·FCFF·주당가치 등)이 **수식(<f>)** 으로 기록됐는가(감사 추적성).
  2) 각 수식 셀의 **캐시값(<v>)** 이 calc_core 출력과 일치하는가.
  3) 법인세 셀이 계단식 IF 수식인가.
(정식 recalc 검증(pycel/xlcalculator)은 이후 페이즈. 여기선 무의존 왕복.)
"""
from __future__ import annotations

import json
import math
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core import DcfSpineInput, run  # noqa: E402
from excel import export_dcf  # noqa: E402

FX = ROOT / "fixtures" / "viol"
M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _load_spine():
    d = json.loads((FX / "inputs.json").read_text(encoding="utf-8"))
    return DcfSpineInput(
        wacc=d["wacc"], terminal_growth=d["terminal_growth"], revenue=d["revenue"],
        cogs=d["cogs"], sga=d["sga"], dep_amort=d["dep_amort"], capex=d["capex"],
        delta_nwc_cash_adj=d["delta_nwc_cash_adj"],
        non_operating_assets=d["non_operating_assets"], net_debt=d["net_debt"],
        shares_outstanding=d["shares_outstanding"],
        mid_year_periods=d.get("mid_year_periods"),
        terminal_discount_period=d.get("terminal_discount_period"),
    )


def _read_cells(path: str):
    """xlsx → {ref: {'f': formula|None, 'v': cached|None}} (DCF 시트)."""
    z = zipfile.ZipFile(path)
    root = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    out = {}
    for c in root.iter(f"{{{M}}}c"):
        ref = c.get("r")
        f_el = c.find(f"{{{M}}}f")
        v_el = c.find(f"{{{M}}}v")
        out[ref] = {
            "f": f_el.text if f_el is not None else None,
            "v": float(v_el.text) if v_el is not None and v_el.text else None,
        }
    return out


def test_xlsx_export_roundtrip():
    inp = _load_spine()
    res = run(inp)
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "viol_dcf.xlsx")
        export_dcf(inp, res, path)
        cells = _read_cells(path)

    def close(a, b):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-6)

    fails = []
    # 1) 결과 셀은 수식이어야 함
    for ref in ["C15", "C21", "C31", "C32", "C33"]:  # EBIT, FCFF, EV, equity, per-share
        if cells.get(ref, {}).get("f") is None:
            fails.append(f"{ref}: 수식이 아님(하드값)")
    # 2) 법인세는 계단식 IF
    tax_f = cells.get("C16", {}).get("f", "") or ""
    if not tax_f.startswith("IF(") or "0.24" not in tax_f:
        fails.append(f"C16 법인세 수식 이상: {tax_f[:40]}")
    # 3) 캐시값 == calc_core
    checks = {
        "C15": res.ebit[0], "C16": res.tax[0], "C17": res.noplat[0],
        "C21": res.fcff[0], "C24": res.pv_fcff[0],
        "C31": res.enterprise_value, "C32": res.equity_value, "C33": res.per_share,
    }
    for ref, exp in checks.items():
        got = cells.get(ref, {}).get("v")
        if got is None or not close(got, exp):
            fails.append(f"{ref}: 캐시값 {got} != calc_core {exp}")

    assert not fails, "xlsx 왕복 불일치:\n  " + "\n  ".join(fails)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    test_xlsx_export_roundtrip()
    print("PASS — 살아있는 수식 xlsx export 왕복 검증 통과")
    print("  결과 셀 수식 기록 + 캐시값 = calc_core (주당가치 포함)")
