#!/usr/bin/env python
"""감사인 트랙 — 독립 재계산 + 차이·민감도 (감사인 도구, 검증 에이전트 씨앗).

외부평가의견서/모델의 가정을 우리 엔진으로 **독립 재계산**하고, 주장된 주당가치와
비교, 어느 가정이 차이를 만드는지 민감도·구조버그 가설로 짚는다.

사용: python audit.py <inputs.json> [claimed_per_share]
출력: 독립 주당가치 · 차이(%) · audit 경고 · WACC/g 민감도 · gap_diagnosis.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401

from calc_core import DcfSpineInput, run  # noqa: E402
from calc_core.checks import audit_dcf, diagnose_dcf_gap  # noqa: E402

_FIELDS = {f.name for f in dataclasses.fields(DcfSpineInput)}


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    if len(sys.argv) < 2:
        raise SystemExit("사용: python audit.py <inputs.json> [claimed_per_share]")
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    inp = DcfSpineInput(**{k: v for k, v in data.items() if k in _FIELDS})
    res = run(inp)
    rep = audit_dcf(inp, res)

    out = {
        "independent_per_share": round(res.per_share, 2),
        "tv_weight_pct": round(res.terminal_value_pv / res.enterprise_value * 100, 1)
        if res.enterprise_value else None,
        "audit_warnings": [
            {"rule": f.rule, "severity": f.severity.value, "message": f.message}
            for f in rep.findings if f.severity.value in ("warn", "fail")
        ],
        "sensitivity": res.sensitivity.get("per_share"),
        "sensitivity_axes": {"wacc": res.sensitivity.get("wacc_axis"),
                             "g": res.sensitivity.get("g_axis")},
    }
    if len(sys.argv) > 2:
        claimed = float(sys.argv[2])
        diff = res.per_share - claimed
        out["claimed_per_share"] = claimed
        out["difference"] = round(diff, 2)
        out["difference_pct"] = round(diff / claimed * 100, 2) if claimed else None
        out["verdict"] = ("일치(±2%)" if abs(diff / claimed) <= 0.02
                          else "괴리 — 가정 재검토 필요") if claimed else None
        diag = diagnose_dcf_gap(inp, res, claimed)
        out["gap_diagnosis"] = {"severity": diag.severity.value,
                                "message": diag.message,
                                "hypotheses": diag.detail.get("hypotheses")}
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
