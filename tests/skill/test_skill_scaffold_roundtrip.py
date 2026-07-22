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
        "W1": ["Research", "Assumption"], "W2": ["FS_Hist"], "W2.5": ["FS_Disagg"], "W3": ["Reclass"],
        "W4": ["Fcst_Rev", "Fcst_Cost", "Capex_Dep", "WC"], "W5": ["Peer", "WACC"],
    }
    for stage, sheets in expected.items():
        out = _run("scaffold.py", "--stage", stage, "--emit-cells")
        assert out["stage_sheets"] == sheets, f"{stage}: {out['stage_sheets']}"
        made = {c["sheet"] for c in out["cells"]}
        assert set(sheets) <= made
        # 뼈대는 범례(규약)를 담는다
        assert any("범례" in str(c.get("value", "")) for c in out["cells"])


def test_scaffold_w4_rollup_wiring():
    """W4 추정 시트가 FS_Disagg 세분 라인과 동일 성격으로 배선되고, 계=Σ 살아있는 SUM
    롤업 수식으로 DCF 스파인에 합보존 연결되는지(② 배선)."""
    out = _run("scaffold.py", "--stage", "W4", "--emit-cells")
    cells = out["cells"]

    def sheet_cells(name):
        return [c for c in cells if c["sheet"] == name]

    rev = sheet_cells("Fcst_Rev")
    # FS_Disagg 매출 세분과 동일 성격 라인(제품매출 등)이 행 라벨로
    rev_labels = {c.get("value") for c in rev}
    assert "제품매출" in rev_labels and "상품매출" in rev_labels
    # 계 = Σ세분 살아있는 SUM 수식 + DCF!매출 롤업 표기
    rev_formulas = [c["formula"] for c in rev if "formula" in c]
    assert any(f.startswith("SUM(") for f in rev_formulas), "매출 계 SUM 롤업 없음"
    assert any("DCF!매출" in str(c.get("value", "")) for c in rev), "→ DCF!매출 롤업 표기 없음"

    cost = sheet_cells("Fcst_Cost")
    cost_labels = {c.get("value") for c in cost}
    assert "재료비" in cost_labels and "급여" in cost_labels    # 원가·판관비 성격별 세분
    cost_formulas = [c["formula"] for c in cost if "formula" in c]
    # 매출원가 계 + 판관비 계 = 두 개의 SUM 롤업
    assert sum(1 for f in cost_formulas if f.startswith("SUM(")) >= 2, "원가·판관비 계 SUM 롤업 부족"


def test_scaffold_w5_peer_and_wacc_live_formulas():
    """W5 = Peer(4-step 퍼널 + Hamada 무부채화) + WACC(빌드업). 둘 다 살아있는 수식."""
    out = _run("scaffold.py", "--stage", "W5", "--emit-cells")
    peer = [c for c in out["cells"] if c["sheet"] == "Peer"]
    wacc = [c for c in out["cells"] if c["sheet"] == "WACC"]
    pf = [c["formula"] for c in peer if "formula" in c]
    wf = [c["formula"] for c in wacc if "formula" in c]
    # Peer: Hamada 무부채화(/(1+(1-t)·D/E) + 평균
    assert any("/(1+(1-" in f for f in pf), "Peer Hamada 무부채화 없음"
    assert any(f.startswith("AVERAGE(") for f in pf), "Peer 평균행 없음"
    # Peer: 4-step 퍼널 컬럼(판정·생존스텝) + peer.py 게이트
    pv = {str(c.get("value")) for c in peer}
    assert any("판정" in v for v in pv) and any("생존스텝" in v for v in pv)
    assert any("peer.py" in v and "Step" in v for v in pv)
    # WACC: 재부채화·Ke·WACC 조립(가중합)
    assert any("*(1+(1-" in f for f in wf), "WACC 재부채화 없음"
    assert any("*" in f and "+" in f for f in wf), "Ke/WACC 조립 없음"
    assert any("시장위험프리미엄 MRP" in str(c.get("value")) for c in wacc)   # ERP 아님


def test_scaffold_w4_detail_live_formulas():
    """② 상세화: Capex_Dep 상각 스케줄·WC 회전율·Fcst_Cost 영업이익 = 살아있는 수식."""
    out = _run("scaffold.py", "--stage", "W4", "--emit-cells")

    def sf(name):
        return [c["formula"] for c in out["cells"] if c["sheet"] == name and "formula" in c]

    cap, wc, fc = sf("Capex_Dep"), sf("WC"), sf("Fcst_Cost")
    # Capex_Dep: 기초=전기기말·기말=기초+CAPEX−상각·신규상각=누적/연수
    assert any("/$C$13" in f for f in cap), "상각연수 정액 배분 없음"
    assert any("+" in f and "-" in f for f in cap), "기말=기초+CAPEX−상각 없음"
    # WC: 회전일→잔액(×일/365)·ΔNWC 차분
    assert any("/365" in f for f in wc), "회전일→잔액(×/365) 없음"
    assert any("+" in f and "-" in f for f in wc), "NWC=AR+재고−AP 없음"
    # Fcst_Cost 영업이익: 매출(Fcst_Rev 참조) − 원가 − 판관비
    assert any("Fcst_Rev!" in f and "-" in f for f in fc), "영업이익 크로스시트 롤업 없음"


def test_scaffold_w1_assumption_ssot():
    """W1 = Research + Assumption(가정 SSOT). Assumption 은 순수 입력(하류 참조 대상)."""
    out = _run("scaffold.py", "--stage", "W1", "--emit-cells")
    assert out["stage_sheets"] == ["Research", "Assumption"]
    av = {str(c.get("value")) for c in out["cells"] if c["sheet"] == "Assumption"}
    assert any("가정 SSOT" in v for v in av)
    assert any("CAPEX(% of sales)" in v for v in av) and any("MRP" in v for v in av)


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
    test_scaffold_w4_rollup_wiring()
    print("PASS test_scaffold_w4_rollup_wiring")
    test_scaffold_w5_peer_and_wacc_live_formulas()
    print("PASS test_scaffold_w5_peer_and_wacc_live_formulas")
    test_scaffold_w4_detail_live_formulas()
    print("PASS test_scaffold_w4_detail_live_formulas")
    test_scaffold_w1_assumption_ssot()
    print("PASS test_scaffold_w1_assumption_ssot")
    test_scaffold_stage_xlsx()
    print("PASS test_scaffold_stage_xlsx")
    print("\n8 tests passed.")
