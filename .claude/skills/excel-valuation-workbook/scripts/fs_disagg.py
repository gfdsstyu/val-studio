#!/usr/bin/env python
"""손익 계정 세분화 검증 (Skill 도구, W2.5).

러프한 공시 손익계산서(매출액·매출원가·판관비·영업외손익이 한 줄씩)를 성격별·유형별로
분해한 뒤, **합보존(세분 합 == 원계정)**과 **구성비 추이**를 결정론으로 검증한다.
세분 매핑안 제시·성격(변동/고정) 판정은 Claude·평가인의 몫이고, 이 스크립트는
"분해가 원계정을 보존하는가"와 "연도 간 구성비가 급변하는가"만 검산·표면화한다.

세 연산의 구분(같은 과거 IS, 다른 방향):
  W2   무결성 = 합이 맞나 **검증**(러프한 계정 그대로)       → fs_clean.py
  W2.5 세분화 = 한 줄 → 여러 성격으로 **분해**(coarse→fine)  → 이 스크립트
  W3   평가재분류 = 성격 → 평가유형으로 **집계**(fine→type)

**순수 표준 라이브러리** — 값 정규화는 fs_clean 재사용(둘 다 stdlib, DRY).

입력 (stdin, JSON):
  {
    "blocks": [
      {
        "parent": "매출액",              # 원계정(FS_Hist 라인)
        "unit": "백만원"|"천원"|"원"|null,  # 선택(null=자동감지, 블록 단위)
        "periods": {                     # 연도 -> {total, children{...}}
          "2024": {"total": "1,234", "children": {"제품매출": "800", "상품매출": "434"}},
          "2023": {"total": "1,100", "children": {"제품매출": "700", "상품매출": "400"}}
        }
      },
      ...
    ],
    "tol": 0.5,             # 선택: 합보존 허용오차(정규화 단위=백만원, 기본 0.5)
    "mix_swing_warn": 0.15  # 선택: YoY 구성비 절대변화 WARN 임계(기본 0.15=15%p)
  }

출력 (stdout, JSON):
  {
    "disaggregated": {"<parent>": {"<year>": {"<child>": v, "_total": t, "_residual": r}}},
    "mix": {"<parent>": {"<year>": {"<child>": ratio}}},
    "issues": [{severity, code, message, detail}],
    "gate_ok": bool   # 합보존 FAIL 0건 (구성비 급변 WARN 은 차단 안 함)
  }

사용:
  echo '{"blocks":[...]}' | python fs_disagg.py
  python fs_disagg.py input.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# 값 정규화·단위 감지는 fs_clean 과 동일 규약 — 재사용(둘 다 같은 scripts/ 디렉터리, stdlib).
from fs_clean import detect_unit, normalize_value, UNIT_SCALE

_TOL = 0.5           # 합보존 허용오차(백만원)
_MIX_SWING = 0.15    # YoY 구성비 절대변화 WARN 임계(15%p)


def _norm_block_unit(block: dict, issues: list[dict]) -> tuple[float, str]:
    """블록 단위 결정 — 명시값 우선, 없으면 total·children 전체로 자동감지."""
    label = block.get("parent", "?")
    unit = block.get("unit")
    if unit is not None:
        return UNIT_SCALE.get(unit, 1.0), unit
    # detect_unit 은 {year: {account: raw}} 형태를 받는다 — total+children 을 펼쳐 넘김.
    flat: dict[str, dict] = {}
    for year, blk in block.get("periods", {}).items():
        row = dict(blk.get("children", {}))
        if "total" in blk:
            row["__total__"] = blk["total"]
        flat[year] = row
    unit = detect_unit(flat)
    issues.append({
        "severity": "INFO", "code": "unit_detected",
        "message": f"['{label}'] 단위 자동감지 → {unit}. 원문 단위 확인 권장.",
        "detail": {"parent": label, "unit": unit},
    })
    return UNIT_SCALE.get(unit, 1.0), unit


def _disagg_block(block: dict, tol: float, mix_warn: float,
                  issues: list[dict]) -> tuple[dict, dict]:
    """한 블록(parent) 세분 검증 → (연도별 세분값, 연도별 구성비).

    합보존: |total - Σchildren| > tol → FAIL. 결측 자식(None)은 롤업 제외(잔차에 반영).
    """
    parent = block.get("parent", "?")
    scale, _unit = _norm_block_unit(block, issues)
    periods = block.get("periods", {})

    disagg: dict[str, dict] = {}
    mix: dict[str, dict] = {}

    for year in sorted(periods.keys()):
        blk = periods[year]
        total = normalize_value(blk.get("total"))
        children_raw = blk.get("children", {})
        children: dict[str, float] = {}
        missing: list[str] = []
        for name, raw in children_raw.items():
            v = normalize_value(raw)
            if v is None:
                missing.append(name.strip())
                continue
            children[name.strip()] = round(v * scale, 6)

        total_s = None if total is None else round(total * scale, 6)
        child_sum = round(sum(children.values()), 6)
        residual = None if total_s is None else round(total_s - child_sum, 6)

        row = dict(children)
        row["_total"] = total_s
        row["_residual"] = residual
        disagg[year] = row

        if missing:
            issues.append({
                "severity": "WARN", "code": "child_missing",
                "message": f"['{parent}'] {year} 결측 자식: {', '.join(missing)} "
                           f"(롤업 제외 — 잔차에 반영, 자료 보강 권장)",
                "detail": {"parent": parent, "year": year, "missing": missing},
            })

        if total_s is None:
            issues.append({
                "severity": "WARN", "code": "no_total",
                "message": f"['{parent}'] {year} 원계정(total) 결측 — 합보존 검증 불가.",
                "detail": {"parent": parent, "year": year},
            })
        elif abs(residual) > tol:
            issues.append({
                "severity": "FAIL", "code": "disagg_imbalance",
                "message": f"['{parent}'] {year} 세분 합보존 실패: 원계정 {total_s} ≠ "
                           f"세분합 {child_sum} (잔차 {residual}) — 누수·중복 확인",
                "detail": {"parent": parent, "year": year, "total": total_s,
                           "child_sum": child_sum, "residual": residual},
            })

        # 구성비(mix) — total 이 유효할 때만
        if total_s not in (None, 0):
            mix[year] = {name: round(v / total_s, 6) for name, v in children.items()}

    _check_mix_trend(parent, mix, mix_warn, issues)
    return disagg, mix


def _check_mix_trend(parent: str, mix: dict, mix_warn: float, issues: list[dict]) -> None:
    """교차연도 구성비 추이 — 인접 연도 |Δratio| > 임계면 WARN(급변, 재검토·재분류 신호)."""
    years = sorted(mix.keys())
    for prev, cur in zip(years, years[1:]):
        names = set(mix[prev]) | set(mix[cur])
        for name in names:
            r0 = mix[prev].get(name, 0.0)
            r1 = mix[cur].get(name, 0.0)
            delta = round(r1 - r0, 6)
            if abs(delta) > mix_warn:
                issues.append({
                    "severity": "WARN", "code": "mix_swing",
                    "message": f"['{parent}'] '{name}' 구성비 급변 {prev}→{cur}: "
                               f"{round(r0 * 100, 1)}% → {round(r1 * 100, 1)}% "
                               f"(Δ{round(delta * 100, 1)}%p) — 사업 변화/재분류 여부 확인",
                    "detail": {"parent": parent, "child": name, "from_year": prev,
                               "to_year": cur, "from_ratio": r0, "to_ratio": r1,
                               "delta": delta},
                })


def run_disagg(payload: dict) -> dict:
    issues: list[dict] = []
    blocks = payload.get("blocks", [])
    tol = float(payload.get("tol", _TOL))
    mix_warn = float(payload.get("mix_swing_warn", _MIX_SWING))
    if not blocks:
        issues.append({"severity": "FAIL", "code": "no_input",
                       "message": "blocks 가 비어 있음.", "detail": {}})
        return {"disaggregated": {}, "mix": {}, "issues": issues, "gate_ok": False}

    disaggregated: dict[str, dict] = {}
    mix_all: dict[str, dict] = {}
    for block in blocks:
        parent = block.get("parent", f"block{len(disaggregated)}")
        d, m = _disagg_block(block, tol, mix_warn, issues)
        disaggregated[parent] = d
        mix_all[parent] = m

    has_fail = any(i["severity"] == "FAIL" for i in issues)
    return {
        "disaggregated": disaggregated,
        "mix": mix_all,
        "issues": issues,
        "gate_ok": not has_fail,   # 합보존만 게이트. mix_swing(WARN)은 표면화만.
    }


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows cp949 방지
    except (AttributeError, ValueError):
        pass
    raw = Path(sys.argv[1]).read_text(encoding="utf-8") if len(sys.argv) > 1 else sys.stdin.read()
    payload = json.loads(raw)
    result = run_disagg(payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
