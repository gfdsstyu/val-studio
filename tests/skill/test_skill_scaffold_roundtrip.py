"""스킬 scaffold → roundtrip 왕복 검증 + _VS_STATE 존재.

scaffold 로 xlsx 생성 → roundtrip 으로 import·재계산·tie-out. emit-cells 모드도 확인.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".claude" / "skills" / "excel-valuation-workbook" / "scripts"
VIOL = ROOT / "fixtures" / "viol" / "inputs.json"


def _run(script: str, *args: str, stdin: str | None = None) -> dict:
    r = subprocess.run(
        [sys.executable, str(SKILL / script), *args],
        input=stdin, capture_output=True, text=True, encoding="utf-8",
        cwd=tempfile.gettempdir(),
    )
    assert r.returncode == 0, f"{script} 실패:\n{r.stderr}"
    return json.loads(r.stdout)


def test_scaffold_xlsx_and_roundtrip():
    inputs = VIOL.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as td:
        xlsx = str(Path(td) / "scaffold.xlsx")
        saved = _run("scaffold.py", "--xlsx", xlsx, stdin=inputs)
        assert "DCF" in saved["sheets"]
        assert "_VS_STATE" in saved["sheets"]        # 상태 시트 동봉
        assert Path(xlsx).exists()

        rt = _run("roundtrip.py", xlsx, "--expect", str(VIOL))
        assert rt["tie_out"] is True
        assert rt["gate_ok"] is True
        assert abs(rt["per_share"] - rt["expected_per_share"]) < 1e-4


def test_scaffold_emit_cells():
    inputs = VIOL.read_text(encoding="utf-8")
    out = _run("scaffold.py", "--emit-cells", stdin=inputs)
    cells = out["cells"]
    # DCF 가정 셀(C3=WACC) + _VS_STATE 존재
    sheets = {c["sheet"] for c in cells}
    assert {"DCF", "_VS_STATE"} <= sheets
    c3 = next(c for c in cells if c["sheet"] == "DCF" and c["ref"] == "C3")
    assert "value" in c3                              # WACC 입력셀
    # 수식 셀도 있어야(살아있는 수식)
    assert any("formula" in c for c in cells if c["sheet"] == "DCF")


def test_scaffold_stage_generators():
    """W1~W5 단계 뼈대 생성 — 각 단계가 규약 시트를 만든다(stdin 불요)."""
    expected = {
        "W1": ["Research"], "W2": ["FS_Hist"], "W3": ["Reclass"],
        "W4": ["Fcst_Rev", "Fcst_Cost", "Capex_Dep", "WC"], "W5": ["WACC"],
    }
    for stage, sheets in expected.items():
        out = _run("scaffold.py", "--stage", stage, "--emit-cells")
        assert out["stage_sheets"] == sheets, f"{stage}: {out['stage_sheets']}"
        made = {c["sheet"] for c in out["cells"]}
        assert set(sheets) <= made
        # 뼈대는 범례(규약)를 담는다
        assert any("범례" in str(c.get("value", "")) for c in out["cells"])


def test_scaffold_stage_xlsx():
    """단계 뼈대를 xlsx 로도 저장 가능(Claude Code 경로)."""
    import tempfile as _tf
    with _tf.TemporaryDirectory() as td:
        xlsx = str(Path(td) / "w4.xlsx")
        out = _run("scaffold.py", "--stage", "W4", "--xlsx", xlsx)
        assert Path(xlsx).exists()
        assert set(out["stage_sheets"]) == {"Fcst_Rev", "Fcst_Cost", "Capex_Dep", "WC"}


if __name__ == "__main__":
    test_scaffold_xlsx_and_roundtrip()
    print("PASS test_scaffold_xlsx_and_roundtrip")
    test_scaffold_emit_cells()
    print("PASS test_scaffold_emit_cells")
    test_scaffold_stage_generators()
    print("PASS test_scaffold_stage_generators")
    test_scaffold_stage_xlsx()
    print("PASS test_scaffold_stage_xlsx")
    print("\n4 tests passed.")
