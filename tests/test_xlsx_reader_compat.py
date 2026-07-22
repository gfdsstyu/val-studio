"""xlsx_reader 외부 파일 호환 테스트 — sharedStrings·수식 문자열 결과(t="str").

버그 실측(2026-07-17): 실무 리포트 xlsx 의 `=CHOOSE(...)` 문자열 결과("Downside")를
숫자로 강제 변환하다 크래시. 합성 xlsx 로 회귀 고정 + 실파일 있으면 스모크.
stdlib: `python tests/test_xlsx_reader_compat.py`
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from excel.xlsx_reader import read_workbook  # noqa: E402

_CT = """<?xml version="1.0"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="xml" ContentType="application/xml"/>
 <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
 <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
 <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>"""
_RELS = """<?xml version="1.0"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""
_WB = """<?xml version="1.0"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
 <sheets><sheet name="S" sheetId="1" r:id="rId1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/></sheets>
</workbook>"""
_SST = """<?xml version="1.0"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="2" uniqueCount="2">
 <si><t>시나리오</t></si><si><r><t>주당</t></r><r><t>가치</t></r></si>
</sst>"""
_SHEET = """<?xml version="1.0"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
 <sheetData><row r="1">
  <c r="A1" t="s"><v>0</v></c>
  <c r="B1" t="s"><v>1</v></c>
  <c r="C1" t="str"><f>CHOOSE(1,"Downside","Base")</f><v>Downside</v></c>
  <c r="D1"><v>36376.69</v></c>
  <c r="E1" t="b"><v>1</v></c>
  <c r="F1" t="e"><f>1/0</f><v>#DIV/0!</v></c>
 </row></sheetData>
</worksheet>"""


def _make(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", _CT)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("xl/workbook.xml", _WB)
        z.writestr("xl/sharedStrings.xml", _SST)
        z.writestr("xl/worksheets/sheet1.xml", _SHEET)


def test_shared_and_formula_strings(tmp_dir: Path | None = None) -> None:
    import tempfile
    d = tmp_dir or Path(tempfile.mkdtemp())
    p = d / "compat.xlsx"
    _make(p)
    wb = read_workbook(str(p))
    s = wb["S"]
    assert s["A1"].value == "시나리오"          # sharedStrings
    assert s["B1"].value == "주당가치"          # 서식 run 이어붙임
    assert s["C1"].value == "Downside"          # t="str" — 버그 케이스
    assert s["C1"].formula and "CHOOSE" in s["C1"].formula
    assert s["D1"].number == 36376.69
    assert s["E1"].number == 1.0                # bool → 1.0
    assert s["F1"].value == "#DIV/0!"           # 에러 텍스트 보존


def test_real_report_smoke() -> None:
    """실무 리포트 xlsx 스모크 — 경로는 env VAL_REPORT_XLSX (미설정 시 skip)."""
    import os
    p = os.environ.get("VAL_REPORT_XLSX")
    real = Path(p) if p else None
    if real is None or not real.exists():
        print("  (VAL_REPORT_XLSX 미설정/없음 — skip)")
        return
    wb = read_workbook(str(real))
    assert "6.시나리오" in wb
    # 컨트롤 스위치 CHOOSE 수식과 driver 서사(문자열 셀)가 살아 있어야
    scen = wb["6.시나리오"]
    assert any(c.formula and "CHOOSE" in c.formula for c in scen.values())
    assert any(isinstance(c.value, str) and "Downside" in str(c.value)
               for c in scen.values())


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
