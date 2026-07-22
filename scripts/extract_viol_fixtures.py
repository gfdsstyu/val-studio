"""비올 DCF Model 최종본.xlsx → 골든 픽스처 추출.

원본 엑셀(자기완결, externalLinks 0)에서 모든 시트의 셀(값+수식)을 구조화 덤프.
표준 라이브러리만 사용(zipfile + xml) — openpyxl/pip 불필요.

출력:
  fixtures/viol/raw_dump.json  — 전 시트 전 셀 {ref, value, formula}
  (inputs.json / expected.json 은 raw_dump 를 사람이 큐레이션해 생성)

재현 기준 파일이 자기완결이므로 이 덤프가 calc_core 골든 테스트의 SSOT.
"""
from __future__ import annotations
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
R_OFF = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

SRC = Path(
    r"D:\Valuation\DCF_비올\(DCF연수1기)정종범_비올_DCF Model_최종본.xlsx"
)
OUT_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "viol"


def col_to_idx(col: str) -> int:
    """엑셀 열문자(A, B, ..., AA) → 0-based 인덱스."""
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n - 1


def split_ref(ref: str) -> tuple[str, int]:
    """'AB12' → ('AB', 12)."""
    m = re.match(r"([A-Z]+)(\d+)", ref)
    return m.group(1), int(m.group(2))


def load_shared_strings(z: zipfile.ZipFile) -> list[str]:
    ss: list[str] = []
    if "xl/sharedStrings.xml" not in z.namelist():
        return ss
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    for si in root.findall(f"{{{M}}}si"):
        # 텍스트 런(t) 전부 이어붙임
        ss.append("".join(t.text or "" for t in si.iter(f"{{{M}}}t")))
    return ss


def sheet_name_to_file(z: zipfile.ZipFile) -> dict[str, str]:
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    relmap = {
        r.get("Id"): r.get("Target")
        for r in rels.findall(f"{{{R_PKG}}}Relationship")
    }
    out: dict[str, str] = {}
    for s in wb.iter(f"{{{M}}}sheet"):
        target = relmap[s.get(f"{{{R_OFF}}}id")]
        out[s.get("name")] = "xl/" + target.lstrip("/")
    return out


def dump_sheet(z: zipfile.ZipFile, path: str, ss: list[str]) -> dict:
    root = ET.fromstring(z.read(path))
    dim_el = root.find(f"{{{M}}}dimension")
    dim = dim_el.get("ref") if dim_el is not None else None
    cells: dict[str, dict] = {}
    for c in root.iter(f"{{{M}}}c"):
        ref = c.get("r")
        if not ref:
            continue
        t = c.get("t")  # 's'=shared string, 'str'=formula string, 'b', None=number
        v_el = c.find(f"{{{M}}}v")
        f_el = c.find(f"{{{M}}}f")
        value = None
        if v_el is not None:
            raw = v_el.text
            if t == "s":
                value = ss[int(raw)]
            elif t == "b":
                value = bool(int(raw))
            else:
                # 숫자면 float, 아니면 원문
                try:
                    value = float(raw)
                except (ValueError, TypeError):
                    value = raw
        formula = f_el.text if f_el is not None else None
        if value is None and formula is None:
            continue
        entry: dict = {}
        if value is not None:
            entry["v"] = value
        if formula is not None:
            entry["f"] = formula
        cells[ref] = entry
    return {"dimension": dim, "cells": cells}


def main() -> int:
    if not SRC.exists():
        print(f"ERROR: source not found: {SRC}", file=sys.stderr)
        return 1
    z = zipfile.ZipFile(SRC)
    ss = load_shared_strings(z)
    name2file = sheet_name_to_file(z)

    dump = {
        "_source": str(SRC),
        "_note": "비올 DCF Model 최종본 전 시트 덤프. calc_core 골든 테스트 SSOT.",
        "sheets": {},
    }
    for name, path in name2file.items():
        dump["sheets"][name] = dump_sheet(z, path, ss)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "raw_dump.json"
    out_path.write_text(
        json.dumps(dump, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    # 요약 출력
    total = sum(len(s["cells"]) for s in dump["sheets"].values())
    print(f"OK → {out_path}")
    print(f"sheets={len(dump['sheets'])}  cells={total}")
    for name, s in dump["sheets"].items():
        nf = sum(1 for c in s["cells"].values() if "f" in c)
        print(f"  {name:16s} dim={s['dimension']!s:12s} cells={len(s['cells']):5d} formulas={nf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
