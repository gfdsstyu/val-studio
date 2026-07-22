"""LibreOffice headless recalc 게이트 — <f> 수식이 실제 스프레드시트 엔진에서
우리 엔진 캐시값과 같게 재계산되는지 검증(수식 문자열 정확성).

배경: 우리 export 는 `s.formula(ref, expr, cached)` 로 <f>수식</f><v>엔진캐시값</v> 를
함께 쓴다. 지금까지 테스트는 cached(엔진값)만 봐왔고, <f> 수식 자체가 옳은지 —
셀참조·연산자·중첩 IF·`^`·크로스시트 참조가 진짜 Excel/Calc 엔진에서 그 값으로
계산되는지는 검증한 적이 없다. 이 게이트가 그 갭을 닫는다.

방법(오탐 방지 핵심): **cached 를 제거한 '수식만' xlsx** 를 만들어 LibreOffice 를
"로드 시 항상 재계산"(OOXMLRecalcMode=0) 프로필로 열어 recalc → 계산된 <v> 를 읽어
엔진값과 대조. cached 를 남겨두면 recalc 미동작 시 캐시를 echo 해 false pass 가 되므로
반드시 제거한다. recalc 가 안 되면 값이 비어(number=None) 실패한다(조용한 통과 방지).

LibreOffice 필요. 미설치면 find_soffice()=None → 호출부가 skip.
설치(Windows): winget install TheDocumentFoundation.LibreOffice

CLI:
  python scripts/recalc_gate.py model.xlsx            # recalc 후 DCF 셀 값 JSON
  python scripts/recalc_gate.py model.xlsx --sheet DCF
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from excel.xlsx_writer import Workbook  # noqa: E402
from excel.xlsx_reader import read_workbook  # noqa: E402

# soffice 흔한 설치 경로(Windows). 환경변수 VS_SOFFICE 가 최우선.
_COMMON = [
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/usr/bin/soffice",
    "/opt/libreoffice/program/soffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
]

# 로드 시 항상 재계산 — OOXML(xlsx)·ODF 둘 다 0(Always). 신규 프로필에 주입.
_RECALC_XCU = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" \
xmlns:xs="http://www.w3.org/2001/XMLSchema" \
xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
 <item oor:path="/org.openoffice.Office.Calc/Formula/Load">
  <prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>0</value></prop>
 </item>
 <item oor:path="/org.openoffice.Office.Calc/Formula/Load">
  <prop oor:name="ODFRecalcMode" oor:op="fuse"><value>0</value></prop>
 </item>
</oor:items>
"""


def find_soffice() -> str | None:
    """soffice 실행 파일 경로. 없으면 None(호출부는 skip)."""
    env = os.environ.get("VS_SOFFICE")
    if env and Path(env).exists():
        return env
    for name in ("soffice", "soffice.exe", "libreoffice"):
        p = shutil.which(name)
        if p:
            return p
    for p in _COMMON:
        if Path(p).exists():
            return p
    return None


def strip_cached(wb: Workbook) -> None:
    """모든 수식 셀의 캐시값 제거 → '수식만' 워크북(recalc 강제, 오탐 방지)."""
    for sh in wb.sheets:
        for c in sh.cells.values():
            if c.formula is not None:
                c.cached = None


def _file_url(p: Path) -> str:
    """로컬 경로 → file URL(Windows 백슬래시·드라이브 대응)."""
    return "file:///" + str(p.resolve()).replace("\\", "/")


def recalc(in_xlsx: str, *, soffice: str | None = None, timeout: int = 120) -> dict:
    """xlsx 를 LibreOffice 로 recalc-on-load 시켜 재계산 → {sheet: {ref: number}} 반환.

    RuntimeError: soffice 없음 / 변환 실패 / 산출 파일 부재.
    """
    soffice = soffice or find_soffice()
    if not soffice:
        raise RuntimeError("soffice 없음 — LibreOffice 설치 필요(VS_SOFFICE 로 경로 지정 가능)")

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        # 신규 프로필(recalc-always) — 사용자 LO 인스턴스와 잠금 충돌 회피.
        prof = tdp / "profile"
        (prof / "user").mkdir(parents=True)
        (prof / "user" / "registrymodifications.xcu").write_text(_RECALC_XCU, encoding="utf-8")
        outdir = tdp / "out"
        outdir.mkdir()

        cmd = [
            soffice, "--headless", "--norestore", "--nolockcheck", "--nodefault",
            f"-env:UserInstallation={_file_url(prof)}",
            "--convert-to", "xlsx:Calc MS Excel 2007 XML",
            "--outdir", str(outdir), str(Path(in_xlsx).resolve()),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out_file = outdir / (Path(in_xlsx).stem + ".xlsx")
        if not out_file.exists():
            raise RuntimeError(f"recalc 변환 실패:\n{r.stdout}\n{r.stderr}")

        wb = read_workbook(str(out_file))
        result: dict[str, dict] = {}
        for name in wb:
            cells = wb[name]
            result[name] = {ref: c.number for ref, c in cells.items()
                            if getattr(c, "number", None) is not None}
        return result


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = sys.argv[1:]
    if not args:
        raise SystemExit("사용: python scripts/recalc_gate.py model.xlsx [--sheet DCF]")
    in_xlsx = args[0]
    sheet = None
    if "--sheet" in args:
        sheet = args[args.index("--sheet") + 1]
    if not find_soffice():
        print(json.dumps({"skipped": True, "reason": "LibreOffice(soffice) 미설치"},
                         ensure_ascii=False, indent=2))
        return
    vals = recalc(in_xlsx)
    print(json.dumps(vals.get(sheet, vals) if sheet else vals,
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
