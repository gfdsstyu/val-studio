#!/usr/bin/env python
"""DCF 결정론 계산 + 가정 타당성 검증 (Skill 도구).

판단은 LLM(계정분류·가정 도출), 계산·검증은 이 스크립트(결정론). calc_core 를 얇게 호출.

사용:
  echo '{"wacc":0.09,"terminal_growth":0.01,"revenue":[...],...}' | python dcf.py
  python dcf.py inputs.json
출력: 주당가치·EV·지분가치 + audit 경고(PGR≤GDP·TV비중·재투자·β/MRP) JSON.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _find_backend() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "backend" / "calc_core").is_dir():
            return parent / "backend"
    raise SystemExit("backend/ 를 찾을 수 없음 — 레포 안에서 실행하세요.")


sys.path.insert(0, str(_find_backend()))

import dataclasses  # noqa: E402

from calc_core import DcfSpineInput, run  # noqa: E402
from calc_core.checks import audit_dcf  # noqa: E402

_FIELDS = {f.name for f in dataclasses.fields(DcfSpineInput)}


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows cp949 방지
    except (AttributeError, ValueError):
        pass
    raw = Path(sys.argv[1]).read_text(encoding="utf-8") if len(sys.argv) > 1 else sys.stdin.read()
    # DcfSpineInput 실제 필드만 취함(메타키·여분키 무시 → 견고)
    data = {k: v for k, v in json.loads(raw).items() if k in _FIELDS}
    inp = DcfSpineInput(**data)
    res = run(inp)
    rep = audit_dcf(inp, res, wacc_inputs=None)
    out = {
        "per_share": round(res.per_share, 2),
        "enterprise_value": round(res.enterprise_value, 1),
        "equity_value": round(res.equity_value, 1),
        "tv_weight_pct": round(res.terminal_value_pv / res.enterprise_value * 100, 1)
        if res.enterprise_value else None,
        "audit": [
            {"rule": f.rule, "severity": f.severity.value, "message": f.message}
            for f in rep.findings if f.severity.value != "pass"
        ],
        "gate_ok": rep.ok,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
