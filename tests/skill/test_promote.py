"""promote.py (W6 승격) 검증 — 스파인 셀→Fcst 참조 승격 + per_share tie-out.

calc_core 의존이라 스킬 스크립트를 subprocess 로 실행(벤더 격리). viol 골든 사용.
`python tests/skill/test_promote.py` 또는 pytest.
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


def _run(payload: dict) -> dict:
    r = subprocess.run(
        [sys.executable, str(SKILL / "promote.py")],
        input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8",
        cwd=tempfile.gettempdir(),
    )
    assert r.returncode == 0, f"promote 실패:\n{r.stderr}"
    return json.loads(r.stdout)


def _spine() -> dict:
    return json.loads(VIOL.read_text(encoding="utf-8"))


def test_pure_structural_promotion_ties_out():
    """Fcst 계 == 스파인 값 → per_share 불변(순수 구조 승격), 델타 0, gate_ok."""
    sp = _spine()
    out = _run({"spine": sp, "fcst_totals": {
        "rev": sp["revenue"], "cogs": sp["cogs"], "sga": sp["sga"]}})
    assert out["tie_out"] is True
    assert out["gate_ok"] is True
    assert abs(out["promoted_per_share"] - out["original_per_share"]) < 1e-6
    assert all(d == 0 for line in out["line_deltas"].values() for d in line)


def test_promoted_cell_refs_and_formulas():
    """승격 셀: 매출=DCF!C11.. → '=Fcst_Rev!C12', 캐시=Fcst 계 값."""
    sp = _spine()
    out = _run({"spine": sp, "fcst_totals": {"rev": sp["revenue"]}})
    cells = {c["ref"]: c for c in out["promoted_cells"]}
    assert "C11" in cells and "G11" in cells                 # ROW['rev']=11, 5개년 C..G
    assert cells["C11"]["formula"] == "=Fcst_Rev!C12"        # rev 계 = Fcst_Rev 행12
    assert cells["C11"]["cached"] == round(sp["revenue"][0], 6)
    # 매출만 승격 → cogs/sga 셀 없음
    assert all(c["sheet"] == "DCF" for c in out["promoted_cells"])
    assert not any(c["ref"].startswith("C12") for c in out["promoted_cells"])  # cogs 미승격


def test_cost_lines_target_correct_totals():
    """cogs→Fcst_Cost!C12(매출원가 계), sga→Fcst_Cost!C20(판관비 계)."""
    sp = _spine()
    out = _run({"spine": sp, "fcst_totals": {"cogs": sp["cogs"], "sga": sp["sga"]}})
    f = {c["ref"]: c["formula"] for c in out["promoted_cells"]}
    assert f["C12"] == "=Fcst_Cost!C12"                      # ROW['cogs']=12 → 매출원가 계 행12
    assert f["C14"] == "=Fcst_Cost!C20"                      # ROW['sga']=14  → 판관비 계 행20


def test_value_change_breaks_tieout():
    """Fcst 계가 스파인과 다르면(매출 +10%) per_share 변동 → tie_out False, WARN, gate 차단."""
    sp = _spine()
    bumped = [x * 1.1 for x in sp["revenue"]]
    out = _run({"spine": sp, "fcst_totals": {"rev": bumped}})
    assert out["tie_out"] is False
    assert out["gate_ok"] is False
    assert out["promoted_per_share"] > out["original_per_share"]
    assert any(i["code"] == "per_share_changed" for i in out["issues"])
    assert any(d != 0 for d in out["line_deltas"]["rev"])


def test_length_mismatch_fails():
    sp = _spine()
    out = _run({"spine": sp, "fcst_totals": {"rev": sp["revenue"][:-1]}})   # 4개 (n=5)
    assert out["gate_ok"] is False
    assert any(i["code"] == "length_mismatch" and i["severity"] == "FAIL" for i in out["issues"])


def test_nothing_to_promote_warns():
    sp = _spine()
    out = _run({"spine": sp, "fcst_totals": {}})
    assert any(i["code"] == "nothing_to_promote" for i in out["issues"])
    assert out["promoted_cells"] == []


def test_unknown_line_ignored():
    sp = _spine()
    out = _run({"spine": sp, "fcst_totals": {"capex": sp["capex"]}})   # capex 승격 대상 아님
    assert any(i["code"] == "not_promotable" for i in out["issues"])
    assert out["promoted_cells"] == []


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed.")
