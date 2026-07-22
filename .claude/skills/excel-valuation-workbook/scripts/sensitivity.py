#!/usr/bin/env python
"""W8 민감도 그리드 (Skill 도구) — WACC×PGR 5×5 살아있는 수식.

stdin=DcfSpineInput → Sens 시트(셀마다 독립 DCF 재계산 수식 + 엔진 캐시값). 중심 셀 ==
base 주당가치. FCFF·기간은 DCF 행 참조(고정), 할인·터미널만 축값 반응 — 엔진 대수와 동일.

출력 모드:
  --xlsx out.xlsx : DCF + Sens 동봉 파일(Claude Code)
  --emit-cells    : Sens 셀만 JSON(Claude for Excel — DCF 있는 워크북에 Sens 추가)

사용:
  echo '{...DcfSpineInput...}' | python sensitivity.py --emit-cells
  echo '{...}' | python sensitivity.py --xlsx sens.xlsx
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401

from calc_core import DcfSpineInput  # noqa: E402
from excel.sensitivity_grid import build_sensitivity  # noqa: E402

_FIELDS = {f.name for f in dataclasses.fields(DcfSpineInput)}


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = sys.argv[1:]
    mode_xlsx = None
    emit = False
    rest = []
    i = 0
    while i < len(args):
        if args[i] == "--xlsx":
            mode_xlsx = args[i + 1]
            i += 2
        elif args[i] == "--emit-cells":
            emit = True
            i += 1
        else:
            rest.append(args[i])
            i += 1

    raw = Path(rest[0]).read_text(encoding="utf-8") if rest else sys.stdin.read()
    data = {k: v for k, v in json.loads(raw).items() if k in _FIELDS}
    inp = DcfSpineInput(**data)
    wb = build_sensitivity(inp)                    # DCF + Sens
    center = next(c for s in wb.sheets if s.name == "Sens"
                  for ref, c in s.cells.items() if ref == "F7")
    meta = {"sheets": [s.name for s in wb.sheets], "center_per_share": center.cached}

    if mode_xlsx:
        wb.save(mode_xlsx)
        print(json.dumps({"saved": mode_xlsx, **meta}, ensure_ascii=False, indent=2))
    elif emit:
        # Sens 셀만(DCF 는 라이브 워크북에 이미 존재) — 참조는 DCF! 로 해소
        cells = []
        sens = next(s for s in wb.sheets if s.name == "Sens")
        for ref, c in sens.cells.items():
            entry = {"sheet": "Sens", "ref": ref}
            if c.formula is not None:
                entry["formula"] = c.formula
                entry["cached"] = c.cached
            else:
                entry["value"] = c.value
            cells.append(entry)
        print(json.dumps({"cells": cells, **meta}, ensure_ascii=False, indent=2))
    else:
        raise SystemExit("사용: sensitivity.py (--xlsx out.xlsx | --emit-cells)")


if __name__ == "__main__":
    main()
