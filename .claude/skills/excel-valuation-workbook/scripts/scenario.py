#!/usr/bin/env python
"""시나리오 분석 (W7 도구) — Upside/Base/Downside 다중 입력세트 + 가중 종합.

시나리오 구성(무엇을 낙관/비관으로)은 평가인 판단, 계산·집계는 결정론. 가중치는
유저 승인 값만(합=1 완전일치 요구 — 부분·잔여배분 금지).

사용:
  echo '{"cases":{"Base":{...DcfSpineInput...},"Up":{...}},"weights":{"Base":0.5,"Up":0.5}}' | python scenario.py
출력: 시나리오별 주당가치·EV·TV비중 + spread + weighted_per_share(가중치 완비 시).
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401

from calc_core import DcfSpineInput  # noqa: E402
from calc_core.scenario import run_scenarios  # noqa: E402

_FIELDS = {f.name for f in dataclasses.fields(DcfSpineInput)}


def _mk(d: dict) -> DcfSpineInput:
    return DcfSpineInput(**{k: v for k, v in d.items() if k in _FIELDS})


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    raw = Path(sys.argv[1]).read_text(encoding="utf-8") if len(sys.argv) > 1 else sys.stdin.read()
    payload = json.loads(raw)
    cases = {name: _mk(d) for name, d in payload["cases"].items()}
    weights = payload.get("weights")
    analysis = run_scenarios(cases, weights)
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
