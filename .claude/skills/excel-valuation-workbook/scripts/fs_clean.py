#!/usr/bin/env python
"""과거 재무제표 정합성·무결성 체크 (Skill 도구, W2).

붙여넣은 FS 원문을 결정론적으로 정규화하고, 사업연도 간 재분류·재작성을 탐지해
과거 시계열의 정합성을 검증한다. 판단(재분류 확정)은 평가인, 이 스크립트는 표면화만.

**순수 표준 라이브러리** — calc_core 미의존(샌드박스 독립 동작).

입력 (stdin, JSON):
  {
    "sources": [
      {
        "label": "FY2024",              # 선택
        "unit": "백만원"|"천원"|"원"|null,  # 선택(null=자동감지)
        "periods": {                     # 연도 -> {계정명: 원시값}
          "2024": {"매출액": "1,234", "매출원가": "(567)", "자산총계": "5,000", ...},
          "2023": {"매출액": "1,100", ...}
        }
      },
      ...
    ],
    "balance_tol": 0.5   # 선택: 대차/합계 허용오차(정규화 단위, 기본 0.5=백만원 반올림)
  }

출력 (stdout, JSON):
  {
    "normalized": {"<year>": {"<account>": <float|null>}},
    "cross_period": [{account, year, a_label, b_label, a_value, b_value, diff}],
    "reclass_candidates": [{year, from, to, amount, confidence, basis}],
    "unresolved": [{year, account, delta, note}],
    "issues": [{severity, code, message, detail}],
    "gate_ok": bool   # FAIL 0건 AND unresolved 0건
  }

사용:
  echo '{"sources":[...]}' | python fs_clean.py
  python fs_clean.py input.json
"""
from __future__ import annotations

import json
import re
import sys
from itertools import combinations
from pathlib import Path

# ── 상수 ──────────────────────────────────────────────────────────────────
UNIT_SCALE = {"원": 1e-6, "천원": 1e-3, "백만원": 1.0, "십억원": 1e3, "억원": 1e2}
_TOTAL_KEYS = ("총계", "합계", "총액")  # 소계/총계 계정 — 재분류 추적에서 제외
_MATCH_TOL = 0.5       # 재분류 금액 매칭 허용오차(백만원)
_MAX_COMBO = 3         # 1:多 매칭 최대 결합 수(폭발 방지)

# 자주 재분류되는 계정 관계(account_dictionary.md 정본). 원 계정 → 흔한 이관처.
# 매칭 로직은 이걸 쓰지 않는다(금액 보존이 1차) — 미해결(다대다 등) 표면화 시
# "가능성 있는 이관처" 힌트로만 사용(오탐 없이 평가인 확인을 돕는다).
_RECLASS_HINTS: dict[str, tuple[str, ...]] = {
    "기타유동자산": ("단기금융상품", "미수금", "선급금", "선급비용"),
    "단기금융상품": ("현금및현금성자산", "기타유동자산"),
    "매출채권": ("매출채권및기타채권", "미수금"),
    "기타비유동자산": ("장기금융상품", "보증금", "이연법인세자산"),
    "유형자산": ("사용권자산",),
    "기타유동부채": ("미지급금", "미지급비용", "예수금", "계약부채"),
    "선수금": ("계약부채",),
    "매입채무": ("매입채무및기타채무",),
    "장기차입금": ("유동성장기부채",),
}
# 역방향(이관처 → 원 계정) — 증가 계정에서 출처를 역추적.
_RECLASS_HINTS_REV: dict[str, list[str]] = {}
for _src, _dsts in _RECLASS_HINTS.items():
    for _d in _dsts:
        _RECLASS_HINTS_REV.setdefault(_d, []).append(_src)


def _reclass_hint(account: str, direction: str) -> str | None:
    """account_dictionary 관계로 이관 힌트 생성(정확 일치 우선, 부분 일치 폴백).

    direction='from'(감소) → 흔한 이관처; 'to'(증가) → 흔한 출처.
    """
    fwd = _RECLASS_HINTS if direction == "from" else _RECLASS_HINTS_REV
    key = account.strip()
    cands = fwd.get(key)
    if cands is None:  # 부분 일치(명칭 변이 흡수)
        for k, v in fwd.items():
            if k in key or key in k:
                cands = v
                break
    if not cands:
        return None
    verb = "흔히 이관됨" if direction == "from" else "흔한 출처"
    return f"account_dictionary: '{account}' {verb} → {', '.join(cands)} (확인 권장)"


# ── 값 정규화 ─────────────────────────────────────────────────────────────
def normalize_value(raw) -> float | None:
    """원시 셀값 → 숫자. 콤마·통화·공백 제거, 괄호는 음수, 결측은 None.

    반환 None = 결측(수집 안 됨), 0.0 = 명시적 0/대시.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if s == "" or s.upper() in ("N/A", "NA", "-", "—", "–"):
        return 0.0 if s in ("-", "—", "–") else None
    neg = False
    # 괄호 = 회계 음수 표기
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1].strip()
    # 선행 마이너스
    if s.startswith("-") or s.startswith("△") or s.startswith("▲"):
        neg = True
        s = s.lstrip("-△▲").strip()
    # 통화기호·콤마·공백·단위꼬리 제거
    s = re.sub(r"[₩$,\s]", "", s)
    s = re.sub(r"(원|천원|백만원|억원|십억원)$", "", s)
    if s in ("", "."):
        return None
    try:
        val = float(s)
    except ValueError:
        return None
    return -val if neg else val


def detect_unit(periods: dict) -> str:
    """단위 자동 감지 — 최대 절대값 자릿수 휴리스틱. 값이 크면 원, 작으면 백만원.

    보수적: 확신 없으면 '백만원'(계산 코어 단위) 반환하고 INFO로 표면화.
    """
    vals = []
    for accs in periods.values():
        for v in accs.values():
            n = normalize_value(v)
            if n is not None and n != 0:
                vals.append(abs(n))
    if not vals:
        return "백만원"
    mx = max(vals)
    # 매출총계급이 1e11↑이면 '원', 1e8~1e11 '천원', 그 이하 '백만원' 추정
    if mx >= 1e11:
        return "원"
    if mx >= 1e8:
        return "천원"
    return "백만원"


def is_total(account: str) -> bool:
    return any(k in account for k in _TOTAL_KEYS)


# ── 정규화 파이프라인 ──────────────────────────────────────────────────────
def normalize_sources(sources: list[dict], issues: list[dict]) -> dict[str, dict[str, dict]]:
    """sources → {label: {year: {account: normalized_value(백만원)}}}. 단위 정규화 포함."""
    out: dict[str, dict[str, dict]] = {}
    for i, src in enumerate(sources):
        label = src.get("label") or f"source{i}"
        periods = src.get("periods", {})
        unit = src.get("unit")
        if unit is None:
            unit = detect_unit(periods)
            issues.append({
                "severity": "INFO", "code": "unit_detected",
                "message": f"[{label}] 단위 자동감지 → {unit}. 원문 단위 확인 권장.",
                "detail": {"label": label, "unit": unit},
            })
        scale = UNIT_SCALE.get(unit, 1.0)
        norm_periods: dict[str, dict] = {}
        for year, accs in periods.items():
            norm: dict[str, float | None] = {}
            for acc, raw in accs.items():
                v = normalize_value(raw)
                norm[acc.strip()] = None if v is None else round(v * scale, 6)
            norm_periods[str(year)] = norm
        out[label] = norm_periods
    return out


# ── 정합성 검사 ────────────────────────────────────────────────────────────
def check_balance(by_label: dict, tol: float, issues: list[dict]) -> None:
    """BS 대차: 자산총계 == 부채총계 + 자본총계 (계정명 휴리스틱). 미검출은 조용히 skip."""
    for label, periods in by_label.items():
        for year, accs in periods.items():
            asset = _find(accs, "자산총계", "자산 총계", "총자산")
            liab = _find(accs, "부채총계", "부채 총계", "총부채")
            equity = _find(accs, "자본총계", "자본 총계", "총자본", "자기자본총계")
            if asset is None or liab is None or equity is None:
                continue
            diff = asset - (liab + equity)
            if abs(diff) > tol:
                issues.append({
                    "severity": "FAIL", "code": "bs_imbalance",
                    "message": f"[{label}] {year} B/S 대차 불일치: 자산 {asset} ≠ 부채+자본 {liab + equity} (차 {diff})",
                    "detail": {"label": label, "year": year, "asset": asset,
                               "liab": liab, "equity": equity, "diff": diff},
                })


def _find(accs: dict, *names: str):
    for n in names:
        if n in accs and accs[n] is not None:
            return accs[n]
    # 부분일치 폴백
    for key, v in accs.items():
        if v is not None and any(n.replace(" ", "") == key.replace(" ", "") for n in names):
            return v
    return None


def cross_period_tie(by_label: dict, tol: float, issues: list[dict]) -> list[dict]:
    """당기/전기 교차 대조 — 같은 연도가 여러 source에 나타나면 계정별 대조.

    불일치 = 회계처리 변경에 따른 재분류 흔적(재작성). WARN + cross_period 레코드.
    """
    # year -> [(label, accs)]
    year_map: dict[str, list] = {}
    for label, periods in by_label.items():
        for year, accs in periods.items():
            year_map.setdefault(year, []).append((label, accs))

    mismatches: list[dict] = []
    for year, entries in year_map.items():
        if len(entries) < 2:
            continue
        # 첫 source를 기준(a), 나머지를 비교(b)
        base_label, base_accs = entries[0]
        for b_label, b_accs in entries[1:]:
            accounts = set(base_accs) | set(b_accs)
            for acc in accounts:
                if is_total(acc):
                    continue
                av = base_accs.get(acc)
                bv = b_accs.get(acc)
                if av is None or bv is None:
                    continue
                if abs(av - bv) > tol:
                    rec = {"account": acc, "year": year, "a_label": base_label,
                           "b_label": b_label, "a_value": av, "b_value": bv,
                           "diff": round(bv - av, 6)}
                    mismatches.append(rec)
                    issues.append({
                        "severity": "WARN", "code": "cross_period_mismatch",
                        "message": f"{year} '{acc}' 교차 불일치: {base_label}={av} vs {b_label}={bv} "
                                   f"(재분류/재작성 의심 — 이관 추적 필요)",
                        "detail": rec,
                    })
    return mismatches


# ── 재분류 추적 (금액 보존 매칭) ────────────────────────────────────────────
def trace_reclass(mismatches: list[dict], tol: float) -> tuple[list[dict], list[dict]]:
    """교차 불일치 계정에서 '어느 계정이 어디로 이관됐나' 후보 생성.

    금액 보존 가정: 순수 재분류면 감소분 합 ≈ 증가분 합(net≈0). 1:1·1:多만 결정론
    후보로 내고, 다대다·net≠0은 unresolved 로 표면화(판단은 평가인).
    """
    candidates: list[dict] = []
    unresolved: list[dict] = []

    # 연도별 그룹
    by_year: dict[str, list] = {}
    for m in mismatches:
        by_year.setdefault(m["year"], []).append(m)

    for year, recs in by_year.items():
        decreases = [(r["account"], -r["diff"]) for r in recs if r["diff"] < -tol]  # 사라진 크기(양수)
        increases = [(r["account"], r["diff"]) for r in recs if r["diff"] > tol]     # 생긴 크기(양수)
        net = sum(d for _, d in increases) - sum(d for _, d in decreases)
        if abs(net) > tol:
            # 순수 재분류가 아님(실제 수치 재작성 가능성) — 전부 표면화
            for acc, amt in decreases:
                unresolved.append({"year": year, "account": acc, "delta": round(-amt, 6),
                                   "note": f"net={round(net, 6)} — 금액 미보존(수치 재작성 의심)",
                                   "hint": _reclass_hint(acc, "from")})
            for acc, amt in increases:
                unresolved.append({"year": year, "account": acc, "delta": round(amt, 6),
                                   "note": f"net={round(net, 6)} — 금액 미보존(수치 재작성 의심)",
                                   "hint": _reclass_hint(acc, "to")})
            continue

        used_inc = [False] * len(increases)
        # 1:1 매칭
        for acc_d, amt_d in decreases:
            matched = False
            for j, (acc_i, amt_i) in enumerate(increases):
                if not used_inc[j] and abs(amt_i - amt_d) <= tol:
                    candidates.append({"year": year, "from": acc_d, "to": acc_i,
                                       "amount": round(amt_d, 6), "confidence": "high",
                                       "basis": "1:1 금액 일치"})
                    used_inc[j] = True
                    matched = True
                    break
            if matched:
                continue
            # 1:多 매칭 (사라진 하나 = 생긴 여럿 합)
            remaining = [(j, increases[j][0], increases[j][1]) for j in range(len(increases)) if not used_inc[j]]
            found = _match_combo(amt_d, remaining, tol)
            if found:
                tos = [name for _, name, _ in found]
                for j, _, _ in found:
                    used_inc[j] = True
                candidates.append({"year": year, "from": acc_d, "to": tos,
                                   "amount": round(amt_d, 6), "confidence": "medium",
                                   "basis": f"1:{len(found)} 금액합 일치"})
                matched = True
            if not matched:
                unresolved.append({"year": year, "account": acc_d, "delta": round(-amt_d, 6),
                                   "note": "감소분 매칭 실패(다대다 가능) — 평가인 확인",
                                   "hint": _reclass_hint(acc_d, "from")})
        # 매칭 안 된 증가분
        for j, (acc_i, amt_i) in enumerate(increases):
            if not used_inc[j]:
                unresolved.append({"year": year, "account": acc_i, "delta": round(amt_i, 6),
                                   "note": "증가분 매칭 실패(다대다 가능) — 평가인 확인",
                                   "hint": _reclass_hint(acc_i, "to")})
    return candidates, unresolved


def _match_combo(target: float, remaining: list, tol: float):
    """remaining 중 합이 target±tol 인 최소 결합(최대 _MAX_COMBO) 반환, 없으면 None."""
    for r in range(2, min(_MAX_COMBO, len(remaining)) + 1):
        for combo in combinations(remaining, r):
            if abs(sum(c[2] for c in combo) - target) <= tol:
                return list(combo)
    return None


# ── 메인 ──────────────────────────────────────────────────────────────────
def run_clean(payload: dict) -> dict:
    issues: list[dict] = []
    sources = payload.get("sources", [])
    tol = float(payload.get("balance_tol", _MATCH_TOL))
    if not sources:
        issues.append({"severity": "FAIL", "code": "no_input",
                       "message": "sources 가 비어 있음.", "detail": {}})
        return {"normalized": {}, "cross_period": [], "reclass_candidates": [],
                "unresolved": [], "issues": issues, "gate_ok": False}

    by_label = normalize_sources(sources, issues)

    # normalized 병합 뷰(연도별) — 여러 source 있으면 첫 등장 우선, 충돌은 cross_period 가 잡음
    normalized: dict[str, dict] = {}
    for periods in by_label.values():
        for year, accs in periods.items():
            normalized.setdefault(year, {})
            for acc, v in accs.items():
                normalized[year].setdefault(acc, v)

    check_balance(by_label, tol, issues)
    mismatches = cross_period_tie(by_label, tol, issues)
    candidates, unresolved = trace_reclass(mismatches, tol)

    has_fail = any(i["severity"] == "FAIL" for i in issues)
    gate_ok = (not has_fail) and (len(unresolved) == 0)

    return {
        "normalized": normalized,
        "cross_period": mismatches,
        "reclass_candidates": candidates,
        "unresolved": unresolved,
        "issues": issues,
        "gate_ok": gate_ok,
    }


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows cp949 방지
    except (AttributeError, ValueError):
        pass
    raw = Path(sys.argv[1]).read_text(encoding="utf-8") if len(sys.argv) > 1 else sys.stdin.read()
    payload = json.loads(raw)
    result = run_clean(payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
