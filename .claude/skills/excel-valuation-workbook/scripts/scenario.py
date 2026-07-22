#!/usr/bin/env python
"""시나리오 분석 (W7 도구) — Upside/Base/Downside 다중 입력세트 + 가중 종합.

시나리오 구성(무엇을 낙관/비관으로)은 평가인 판단, 계산·집계는 결정론. 가중치는
유저 승인 값만(합=1 완전일치 요구 — 부분·잔여배분 금지).

사용:
  echo '{"cases":{"Base":{...DcfSpineInput...},"Up":{...}},"weights":{"Base":0.5,"Up":0.5}}' | python scenario.py
  echo '{...}' | python scenario.py --emit-cells      # Scenario 시트 셀 JSON(가중 SUMPRODUCT live)
  echo '{...}' | python scenario.py --emit-cells --switch   # + CHOOSE 단일선택 스위치 블록
  echo '{...}' | python scenario.py --xlsx sc.xlsx     # Scenario 시트 파일
출력(기본): 시나리오별 주당가치·EV·TV비중 + spread + weighted_per_share(가중치 완비 시).
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401

from calc_core import DcfSpineInput  # noqa: E402
from calc_core.scenario import run_scenarios  # noqa: E402
from excel.scenario_sheet import add_scenario_sheet  # noqa: E402
from excel.xlsx_writer import Workbook  # noqa: E402

_FIELDS = {f.name for f in dataclasses.fields(DcfSpineInput)}


def _mk(d: dict) -> DcfSpineInput:
    return DcfSpineInput(**{k: v for k, v in d.items() if k in _FIELDS})


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = sys.argv[1:]
    mode_xlsx = None
    emit = False
    switch = False        # R13: CHOOSE 단일선택 스위치 블록 동봉(가중 종합과 병행)
    rest = []
    i = 0
    while i < len(args):
        if args[i] == "--xlsx":
            mode_xlsx = args[i + 1]
            i += 2
        elif args[i] == "--emit-cells":
            emit = True
            i += 1
        elif args[i] == "--switch":
            switch = True
            i += 1
        else:
            rest.append(args[i])
            i += 1

    raw = Path(rest[0]).read_text(encoding="utf-8") if rest else sys.stdin.read()
    payload = json.loads(raw)
    cases = {name: _mk(d) for name, d in payload["cases"].items()}
    weights = payload.get("weights")
    analysis = run_scenarios(cases, weights)

    if mode_xlsx or emit:
        wb = Workbook()
        add_scenario_sheet(wb, analysis, switch=switch)
        if mode_xlsx:
            wb.save(mode_xlsx)
            print(json.dumps({"saved": mode_xlsx, "sheets": [s.name for s in wb.sheets]},
                             ensure_ascii=False, indent=2))
        else:
            sc = wb.sheets[0]
            cells = []
            for ref, c in sc.cells.items():
                entry = {"sheet": "Scenario", "ref": ref}
                if c.formula is not None:
                    entry["formula"] = c.formula
                    entry["cached"] = c.cached
                else:
                    entry["value"] = c.value
                cells.append(entry)
            print(json.dumps({"cells": cells}, ensure_ascii=False, indent=2))
        return

    out = {
        "rows": [
            {**r, "per_share": round(r["per_share"], 2),
             "enterprise_value": round(r["enterprise_value"], 1),
             "tv_weight": round(r["tv_weight"], 4)}
            for r in analysis.to_rows()
        ],
        "spread": [round(v, 2) for v in analysis.spread],
        "weighted_per_share": (round(analysis.weighted_per_share, 2)
                               if analysis.weighted_per_share is not None else None),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
