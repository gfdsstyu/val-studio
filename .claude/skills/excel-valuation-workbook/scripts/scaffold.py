#!/usr/bin/env python
"""워크북 시트 생성 (W0 스파인 + W1~W5 단계 뼈대) — 풀모델 점진 성장.

W0(기본): build_dcf_sheet 재사용 + `_VS_STATE`. stdin=DcfSpineInput.
W1~W5(--stage): 해당 단계 시트 뼈대(stage_sheets). stdin 불요(빈 뼈대).

두 출력 모드(공통):
  --xlsx out.xlsx : 파일 생성 (Claude Code 경로)
  --emit-cells    : {sheet, ref, value|formula, cached} JSON (Claude for Excel 이 열린
                    워크북에 직접 기입 — 파일 생성 불가 환경)

사용:
  echo '{...DcfSpineInput...}' | python scaffold.py --xlsx out.xlsx     # W0 스파인
  echo '{...}' | python scaffold.py --emit-cells                        # W0 (셀 JSON)
  python scaffold.py --stage W1 --emit-cells                            # W1 Research 뼈대
  python scaffold.py --stage W4 --xlsx fcst.xlsx                        # W4 추정 4시트
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401

import stage_sheets  # noqa: E402
from calc_core import DcfSpineInput, run  # noqa: E402
from excel.dcf_export import build_dcf_sheet  # noqa: E402
from excel.xlsx_writer import Workbook  # noqa: E402

_FIELDS = {f.name for f in dataclasses.fields(DcfSpineInput)}
SKILL_VERSION = "1.0"


def _add_state_sheet(wb, inp: DcfSpineInput) -> None:
    """_VS_STATE 숨김 상태 시트 — 워크북=상태 규약(SKILL.md 1.7). 무상태 세션 재개용."""
    s = wb.add_sheet("_VS_STATE")
    kv = [
        ("skill_version", SKILL_VERSION),
        ("mode", "B"),                 # 백지 스캐폴딩
        ("stage", "W0"),
        ("last_gate_passed", "W0:scaffold"),
        ("engine_tieout_per_share", round(run(inp).per_share, 4)),
        ("n_years", inp.n_years()),
    ]
    for i, (k, v) in enumerate(kv, start=1):
        s.text(f"A{i}", k)
        if isinstance(v, str):
            s.text(f"B{i}", v)
        else:
            s.num(f"B{i}", v)
    # 가정 대장 헤더(1.6 provenance) — 이후 단계가 채움
    hdr = len(kv) + 2
    s.text(f"A{hdr}", "── 가정 대장(provenance) ──")
    for col, label in zip("ABCDE", ["가정명", "값", "출처유형", "근거", "승인상태"]):
        s.text(f"{col}{hdr + 1}", label)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = sys.argv[1:]
    mode_xlsx = None
    emit = False
    stage = None
    rest = []
    i = 0
    while i < len(args):
        if args[i] == "--xlsx":
            mode_xlsx = args[i + 1]
            i += 2
        elif args[i] == "--emit-cells":
            emit = True
            i += 1
        elif args[i] == "--stage":
            stage = args[i + 1]
            i += 2
        else:
            rest.append(args[i])
            i += 1

    if stage:
        # W1~W5 단계 뼈대(빈 시트) — stdin 불요. n_years 선택.
        n = 5
        if rest or not sys.stdin.isatty():
            try:
                payload = json.loads(Path(rest[0]).read_text(encoding="utf-8") if rest
                                     else sys.stdin.read() or "{}")
                n = int(payload.get("n_years", 5))
            except (ValueError, json.JSONDecodeError):
                pass
        wb = Workbook()
        made = stage_sheets.build_stage(wb, stage, n)
        _emit_or_save(wb, mode_xlsx, emit, per_share=None, made=made)
        return

    raw = Path(rest[0]).read_text(encoding="utf-8") if rest else sys.stdin.read()
    data = {k: v for k, v in json.loads(raw).items() if k in _FIELDS}
    inp = DcfSpineInput(**data)
    res = run(inp)
    wb = build_dcf_sheet(inp, res)
    _add_state_sheet(wb, inp)
    _emit_or_save(wb, mode_xlsx, emit, per_share=round(res.per_share, 2))


def _emit_or_save(wb, mode_xlsx, emit, *, per_share, made=None):
    meta = {"sheets": [s.name for s in wb.sheets]}
    if per_share is not None:
        meta["per_share"] = per_share
    if made is not None:
        meta["stage_sheets"] = made
    if mode_xlsx:
        wb.save(mode_xlsx)
        print(json.dumps({"saved": mode_xlsx, **meta}, ensure_ascii=False, indent=2))
    elif emit:
        cells = []
        for sh in wb.sheets:
            for ref, c in sh.cells.items():
                entry = {"sheet": sh.name, "ref": ref}
                if c.formula is not None:
                    entry["formula"] = c.formula
                    entry["cached"] = c.cached
                else:
                    entry["value"] = c.value
                cells.append(entry)
        print(json.dumps({"cells": cells, **meta}, ensure_ascii=False, indent=2))
    else:
        raise SystemExit("사용: scaffold.py (--xlsx out.xlsx | --emit-cells [--stage W1..W5])")


if __name__ == "__main__":
    main()
