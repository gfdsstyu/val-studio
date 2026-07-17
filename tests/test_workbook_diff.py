"""워크북 왕복 diff 테스트 — 3버킷 분류·R1C1 정규화·외딴 편집·앵커 가드.

stdlib: `python tests/test_workbook_diff.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from excel.workbook_diff import (  # noqa: E402
    check_formula_hardcodes, check_row_uniformity, diff_workbooks, to_r1c1,
)
from excel.xlsx_reader import RCell  # noqa: E402


def _wb(**sheets):
    return {name: cells for name, cells in sheets.items()}


BASE = _wb(DCF={
    "B5": RCell(value="매출액"),
    "C5": RCell(value=100.0),                       # 입력(hard)
    "D5": RCell(value=110.0, formula="C5*1.1"),
    "E5": RCell(value=121.0, formula="D5*1.1"),
    "F5": RCell(value=133.1, formula="E5*1.1"),
    "C37": RCell(value=0.22),                       # 메타셀(세율)
})


def test_input_only_change_is_safe():
    new = {k: dict(v) for k, v in BASE.items()}
    new["DCF"]["C5"] = RCell(value=120.0)           # 입력만 수정
    d = diff_workbooks(BASE, new)
    assert d.safe
    assert [c.ref for c in d.input_changes] == ["C5"]
    assert "자동 반영 가능" in d.to_markdown()


def test_formula_edit_flags_review():
    new = {k: dict(v) for k, v in BASE.items()}
    new["DCF"]["E5"] = RCell(value=115.0, formula="D5*1.05")   # 로직 변경
    d = diff_workbooks(BASE, new)
    assert not d.safe
    assert [c.ref for c in d.formula_changes] == ["E5"]


def test_same_formula_cached_value_diff_ignored():
    # 수식 동일·캐시값만 다름(재계산 전 상태) → 변경 아님
    new = {k: dict(v) for k, v in BASE.items()}
    new["DCF"]["D5"] = RCell(value=None, formula="C5*1.1")
    d = diff_workbooks(BASE, new)
    assert d.safe and not d.input_changes


def test_anchor_guard_detects_moved_template():
    anchors = {"DCF": {"B5": "매출액"}}
    ok = diff_workbooks(BASE, BASE, anchors=anchors)
    assert not ok.structure_changes
    moved = {k: dict(v) for k, v in BASE.items()}
    moved["DCF"]["B5"] = RCell(value="Revenue")     # 라벨 변경(행 이동 시그널)
    d = diff_workbooks(BASE, moved, anchors=anchors)
    assert d.structure_changes and d.structure_changes[0].kind == "anchor"
    assert not d.safe


def test_sheet_add_remove_not_safe():
    new = dict(BASE)
    new["몰래추가"] = {"A1": RCell(value=1.0)}
    d = diff_workbooks(BASE, new)
    assert d.sheets_added == ["몰래추가"] and not d.safe


# ── R1C1 정규화 + 외딴 편집 감지 ─────────────────────────────────────────────
def test_r1c1_same_pattern_across_cells():
    assert to_r1c1("C5*1.1", "D5") == to_r1c1("D5*1.1", "E5")   # 같은 상대 패턴
    assert to_r1c1("$B$2+C5", "D5") == "R2C2+R[0]C[-1]"


def test_lone_edit_mid_row_detected():
    wb = _wb(S={
        "C9": RCell(value=1.0, formula="C8*2"),
        "D9": RCell(value=1.0, formula="D8*2"),
        "E9": RCell(value=1.0, formula="E8*3"),     # 외딴 편집!
        "F9": RCell(value=1.0, formula="F8*2"),
        "G9": RCell(value=1.0, formula="G8*2"),
    })
    warns = check_row_uniformity(wb)
    assert len(warns) == 1 and "E9" in warns[0]


def test_formula_hardcode_detected():
    wb = _wb(S={
        "D5": RCell(value=1.0, formula="C5*1.05"),          # 성장률 하드코딩!
        "E5": RCell(value=1.0, formula="D5*(1+$B$6)"),      # 정상(가정 셀 참조)
        "F5": RCell(value=1.0, formula="SUM(C5:E5)/1000"),  # 단위 환산 — 무해
        "G5": RCell(value=1.0, formula='IF(A1="x",B1,C1)'), # 문자열 — 무해
    })
    warns = check_formula_hardcodes(wb)
    assert len(warns) == 1 and "D5" in warns[0] and "1.05" in warns[0]


def test_uniform_row_no_warning():
    wb = _wb(S={f"{c}9": RCell(value=1.0, formula=f"{c}8*2") for c in "CDEFG"})
    assert check_row_uniformity(wb) == []


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
