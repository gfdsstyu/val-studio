#!/usr/bin/env python
"""W6 hard number 승격 — DCF 스파인 입력셀 → Fcst 계 참조 + per_share tie-out.

W4 에서 세분 롤업(Σ세분=계)으로 만든 `Fcst_Rev`/`Fcst_Cost`의 계 값을, DCF 스파인의
매출/매출원가/판관비 **입력셀(Blue)** 을 상류 참조 수식(`=Fcst_Rev!C12`, Green)으로
교체(승격)한다. "hard number 는 최초 1곳만" 원칙의 절차적 구현.

**게이트 = 교체 전후 per_share 불변(tie-out)**: Fcst 세분을 바텀업으로 쌓은 계가 스파인
포캐스트와 일치하면 per_share 가 안 바뀐다(순수 구조 승격). 바뀌면 세분 롤업이 스파인과
불일치 → 라인·연도별 델타로 표면화(판단은 평가인: 스파인 기대치 갱신 or 세분 수정).

셀 주소는 template_schema(ROW·FCST) SSOT — export/import/Fcst 뼈대와 동일 소스.

입력 (stdin JSON):
  {
    "spine": {...DcfSpineInput...},                       # 현재 DCF 스파인(승격 전)
    "fcst_totals": {"rev": [y1..yn], "cogs": [...], "sga": [...]},  # 제공된 라인만 승격
    "tol": 1e-6                                            # 선택: per_share 상대오차
  }
출력 (stdout JSON):
  {
    "promoted_cells": [{sheet, ref, formula, cached}],    # DCF 스파인 셀 → Fcst 참조(Green)
    "original_per_share", "promoted_per_share",
    "tie_out": bool,                                       # 승격 전후 per_share 불변
    "line_deltas": {"rev":[...], ...},                     # fcst-스파인(연도별); 0=순수 구조 승격
    "issues": [{severity, code, message, detail}],
    "gate_ok": bool                                        # tie_out AND FAIL 0
  }

사용:
  echo '{"spine":{...},"fcst_totals":{"rev":[...]}}' | python promote.py
"""
from __future__ import annotations

import dataclasses
import json
import math
import sys
from pathlib import Path

import _bootstrap  # noqa: F401

from calc_core import DcfSpineInput, run  # noqa: E402
from excel.template_schema import PROMOTABLE, ROW, YEAR_COLS, fcst_total_cell  # noqa: E402

_FIELDS = {f.name for f in dataclasses.fields(DcfSpineInput)}


def run_promote(payload: dict) -> dict:
    issues: list[dict] = []
    raw_spine = payload.get("spine", {})
    data = {k: v for k, v in raw_spine.items() if k in _FIELDS}
    try:
        spine = DcfSpineInput(**data)
    except (TypeError, ValueError) as e:
        issues.append({"severity": "FAIL", "code": "bad_spine",
                       "message": f"spine 파싱 실패: {e}", "detail": {}})
        return {"promoted_cells": [], "original_per_share": None,
                "promoted_per_share": None, "tie_out": False, "line_deltas": {},
                "issues": issues, "gate_ok": False}

    fcst = payload.get("fcst_totals", {})
    tol = float(payload.get("tol", 1e-6))
    n = spine.n_years()
    cols = YEAR_COLS[:n]
    original = run(spine)

    promoted_cells: list[dict] = []
    line_deltas: dict[str, list] = {}
    new_vals: dict[str, list] = {}

    for line, total in fcst.items():
        if line not in PROMOTABLE:
            issues.append({"severity": "INFO", "code": "not_promotable",
                           "message": f"'{line}'은 스파인 승격 대상 아님(무시). 대상={list(PROMOTABLE)}",
                           "detail": {"line": line}})
            continue
        if not isinstance(total, list) or len(total) != n:
            issues.append({"severity": "FAIL", "code": "length_mismatch",
                           "message": f"fcst_totals['{line}'] 길이 {len(total) if isinstance(total, list) else '?'} "
                                      f"≠ 스파인 연도수 {n}", "detail": {"line": line}})
            continue
        field = PROMOTABLE[line]
        cur = getattr(spine, field)
        totals = [float(x) for x in total]
        line_deltas[line] = [round(totals[j] - cur[j], 6) for j in range(n)]
        new_vals[field] = totals
        for j, c in enumerate(cols):
            promoted_cells.append({
                "sheet": "DCF", "ref": f"{c}{ROW[line]}",
                "formula": "=" + fcst_total_cell(line, c), "cached": round(totals[j], 6),
            })

    if not promoted_cells and not any(i["severity"] == "FAIL" for i in issues):
        issues.append({"severity": "WARN", "code": "nothing_to_promote",
                       "message": "승격할 라인 없음(fcst_totals 비었거나 대상 라인 부재).",
                       "detail": {}})

    new_spine = dataclasses.replace(spine, **new_vals) if new_vals else spine
    promoted = run(new_spine)
    tie_out = math.isclose(promoted.per_share, original.per_share, rel_tol=tol, abs_tol=1e-6)
    if not tie_out:
        issues.append({"severity": "WARN", "code": "per_share_changed",
                       "message": f"승격 후 per_share 변동: {round(original.per_share, 4)} → "
                                  f"{round(promoted.per_share, 4)} — 세분 롤업이 스파인과 불일치. "
                                  f"line_deltas 확인(평가인: 스파인 갱신 or 세분 수정).",
                       "detail": {"line_deltas": line_deltas}})

    has_fail = any(i["severity"] == "FAIL" for i in issues)
    return {
        "promoted_cells": promoted_cells,
        "original_per_share": round(original.per_share, 6),
        "promoted_per_share": round(promoted.per_share, 6),
        "tie_out": tie_out,
        "line_deltas": line_deltas,
        "issues": issues,
        "gate_ok": tie_out and not has_fail,
    }


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows cp949 방지
    except (AttributeError, ValueError):
        pass
    raw = Path(sys.argv[1]).read_text(encoding="utf-8") if len(sys.argv) > 1 else sys.stdin.read()
    payload = json.loads(raw)
    print(json.dumps(run_promote(payload), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
