#!/usr/bin/env python
"""WACC 산정 (W5 도구) — CAPM 빌드업 + β/MRP 정합 검증.

판단(β 출처·규모)은 평가인, 산식은 이 스크립트. vendor/calc_core.wacc 얇은 호출.

사용: echo '{"risk_free":0.03,"market_risk_premium":0.08,"unlevered_beta":1.0,
  "target_debt_to_equity":0.3,"tax_rate":0.22,"pre_tax_cost_of_debt":0.05,
  "size_premium":0.02,"beta_source":"kicpa","beta_market":"KOSPI",
  "mrp_market":"KOSPI","market_cap_musd":500}' | python wacc.py
market_cap_musd 주면 Kroll size premium 자동 제안.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401

from calc_core.checks import check_beta_mrp_consistency, check_beta_provenance  # noqa: E402
from calc_core.wacc import WaccInputs, build_wacc, kroll_size_decile  # noqa: E402

_FIELDS = {f.name for f in dataclasses.fields(WaccInputs)}


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    raw = Path(sys.argv[1]).read_text(encoding="utf-8") if len(sys.argv) > 1 else sys.stdin.read()
    data = json.loads(raw)
    mktcap = data.pop("market_cap_musd", None)
    inp = WaccInputs(**{k: v for k, v in data.items() if k in _FIELDS})
    res = build_wacc(inp)

    out = {
        "wacc": round(res.wacc, 4),
        "cost_of_equity": round(res.cost_of_equity, 4),
        "after_tax_cost_of_debt": round(res.after_tax_cost_of_debt, 4),
        "relevered_beta": round(res.relevered_beta, 4),
        "equity_weight": round(res.equity_weight, 3),
        "checks": [
            {"rule": f.rule, "severity": f.severity.value, "message": f.message}
            for f in (check_beta_provenance(inp), check_beta_mrp_consistency(inp))
            if f.severity.value != "pass"
        ],
    }
    if mktcap is not None:
        label, prem = kroll_size_decile(float(mktcap))
        out["kroll_size_premium_suggested"] = {"decile": label, "premium": prem,
                                               "used": inp.size_premium}
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
