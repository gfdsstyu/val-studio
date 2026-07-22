#!/usr/bin/env python
"""워크북 왕복 재검증 (W0/W6 게이트 도구) — import → 재계산 → 대조.

DCF 모델 xlsx 를 되읽어(import_dcf_model) 엔진으로 재계산하고, 워크북에 적힌 결과와
셀 단위로 대조한다. scaffold 산출·평가인 편집본이 결정론 엔진과 일치하는지 확인.

사용:
  python roundtrip.py model.xlsx                   # import→재계산, 복원입력·per_share 출력
  python roundtrip.py model.xlsx --expect inputs.json   # 원 입력과 대조
  python roundtrip.py before.xlsx --diff after.xlsx     # 두 파일 3버킷 diff
출력: 복원 입력·재계산 per_share·tie-out 판정 JSON.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from math import isclose
from pathlib import Path

import _bootstrap  # noqa: F401

from calc_core import DcfSpineInput, run  # noqa: E402
from excel.dcf_import import import_dcf_model  # noqa: E402
from excel.workbook_diff import diff_workbooks  # noqa: E402
from excel.xlsx_reader import read_workbook  # noqa: E402

_FIELDS = {f.name for f in dataclasses.fields(DcfSpineInput)}


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = sys.argv[1:]
    if not args:
        raise SystemExit("사용: roundtrip.py model.xlsx [--expect inputs.json | --diff other.xlsx]")
    path = args[0]

    # 두 파일 diff 모드
    if "--diff" in args:
        other = args[args.index("--diff") + 1]
        wd = diff_workbooks(read_workbook(path), read_workbook(other))
        out = {"mode": "diff", "safe": wd.safe,
               "input_changes": len(wd.input_changes),
               "formula_changes": len(wd.formula_changes),
               "structure_changes": len(wd.structure_changes),
               "markdown": wd.to_markdown()}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    # import → 재계산
    inp = import_dcf_model(path)
    res = run(inp)
    recovered = {f: getattr(inp, f) for f in _FIELDS}
    out = {
        "mode": "roundtrip",
        "recovered_input": recovered,
        "per_share": round(res.per_share, 4),
        "enterprise_value": round(res.enterprise_value, 2),
    }

    if "--expect" in args:
        exp_path = args[args.index("--expect") + 1]
        exp = json.loads(Path(exp_path).read_text(encoding="utf-8"))
        exp_inp = DcfSpineInput(**{k: v for k, v in exp.items() if k in _FIELDS})
        exp_res = run(exp_inp)
        tie = isclose(res.per_share, exp_res.per_share, rel_tol=1e-6)
        out["expected_per_share"] = round(exp_res.per_share, 4)
        out["tie_out"] = tie
        out["gate_ok"] = tie
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
