#!/usr/bin/env python
"""평가목적 재분류 검증 (Skill 도구, W3).

정합성 확보된 표준계정(W2)을 밸류에이션 관점 유형으로 재분류할 때, **파티션 보존**을
결정론으로 검증한다 — 원본 계정이 유형 버킷으로 재배치되되 누락·중복·금액변경이 없어야 한다.
유형 판정(영업성·현금성·자본성)은 평가인, 이 스크립트는 파티션 무결성만 검산·표면화.

세 연산 구분(같은 계정): W2 무결성(검증) / W2.5 세분(분해) / **W3 재분류(집계=유형 파티션)**.

BS 6유형: WC(운전자본) / FA(유형자산) / NOA(비영업자산) / IBD(이자부채) / OAL(기타부채) / EQU(자본)
PL 4유형: Sales / COGS / SGA / NO(영업외)

**순수 표준 라이브러리** — calc_core 미의존.

입력 (stdin, JSON):
  {
    "items": [{"account": "매출채권", "amount": 100, "type": "WC"}, ...],
    "original_total": 5000,          # 원본 FS 합계(자산총계 등) — tie-out 기준. 생략시 sum(items)
    "valid_types": ["WC","FA",...],  # 선택(기본=BS 6 + PL 4 전체 허용)
    "tol": 0.5
  }
출력 (stdout, JSON):
  {
    "by_type": {"WC": 300, ...},
    "total": <합>,
    "duplicates": [account...],
    "unclassified": [account...],       # type 없음/빈값
    "invalid_types": [{account, type}],
    "issues": [{severity, code, message, detail}],
    "gate_ok": bool                     # 분류합==원본 AND 중복0 AND 미분류0 AND 유형정상
  }
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_BS_TYPES = ("WC", "FA", "NOA", "IBD", "OAL", "EQU")
_PL_TYPES = ("Sales", "COGS", "SGA", "NO")
_DEFAULT_TYPES = _BS_TYPES + _PL_TYPES
_TOL = 0.5


def run_reclass(payload: dict) -> dict:
    issues: list[dict] = []
    items = payload.get("items", [])
    tol = float(payload.get("tol", _TOL))
    valid = set(payload.get("valid_types") or _DEFAULT_TYPES)

    if not items:
        issues.append({"severity": "FAIL", "code": "no_input",
                       "message": "items 가 비어 있음.", "detail": {}})
        return {"by_type": {}, "total": 0.0, "duplicates": [], "unclassified": [],
                "invalid_types": [], "issues": issues, "gate_ok": False}

    by_type: dict[str, float] = {}
    seen: dict[str, int] = {}
    duplicates: list[str] = []
    unclassified: list[str] = []
    invalid_types: list[dict] = []
    total = 0.0

    for it in items:
        acc = str(it.get("account", "?")).strip()
        amt = it.get("amount")
        typ = (it.get("type") or "").strip()
        amt = 0.0 if amt is None else float(amt)
        total += amt

        seen[acc] = seen.get(acc, 0) + 1
        if seen[acc] == 2:                       # 두 번째 등장 시 1회만 기록
            duplicates.append(acc)

        if not typ:
            unclassified.append(acc)
            continue
        if typ not in valid:
            invalid_types.append({"account": acc, "type": typ})
            continue
        by_type[typ] = round(by_type.get(typ, 0.0) + amt, 6)

    total = round(total, 6)
    original_total = payload.get("original_total")
    original_total = total if original_total is None else round(float(original_total), 6)

    # ── 게이트 판정 ──
    if duplicates:
        issues.append({"severity": "FAIL", "code": "duplicate_account",
                       "message": f"중복 분류 계정: {', '.join(sorted(set(duplicates)))}",
                       "detail": {"duplicates": sorted(set(duplicates))}})
    if unclassified:
        issues.append({"severity": "FAIL", "code": "unclassified",
                       "message": f"유형 미지정(누락): {', '.join(unclassified)}",
                       "detail": {"unclassified": unclassified}})
    if invalid_types:
        issues.append({"severity": "FAIL", "code": "invalid_type",
                       "message": f"허용되지 않는 유형: {invalid_types}",
                       "detail": {"invalid_types": invalid_types, "valid": sorted(valid)}})
    if abs(total - original_total) > tol:
        issues.append({"severity": "FAIL", "code": "total_mismatch",
                       "message": f"분류합 {total} ≠ 원본 FS합 {original_total} "
                                  f"(차 {round(total - original_total, 6)}) — 누락/금액변경 의심",
                       "detail": {"classified_total": total, "original_total": original_total}})

    gate_ok = not any(i["severity"] == "FAIL" for i in issues)
    return {
        "by_type": by_type,
        "total": total,
        "duplicates": sorted(set(duplicates)),
        "unclassified": unclassified,
        "invalid_types": invalid_types,
        "issues": issues,
        "gate_ok": gate_ok,
    }


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    raw = Path(sys.argv[1]).read_text(encoding="utf-8") if len(sys.argv) > 1 else sys.stdin.read()
    print(json.dumps(run_reclass(json.loads(raw)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
