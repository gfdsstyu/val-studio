#!/usr/bin/env python
"""주석 성격별 원가 추출 (Skill 도구, W2.5 ①단 — 세분화의 원천자료 앞단).

`fs_disagg.py`(②세분 검증)는 "이미 쪼갠 children"이 합보존하는지만 검산한다. 그 children
을 **무엇으로 채울지**가 비어 있었고, 지금까지는 평가인이 주석 표를 눈으로 보고 손으로
입력해야 했다 — 원천 추적(어느 주석 몇 번째 글자)이 유실되는 지점.

이 스크립트가 그 앞단을 채운다: 사업보고서 '비용의 성격별 분류'(판관비)·제조원가명세서
(매출원가) 주석 표를 붙여넣으면
  ① 성격별 금액을 **결정론으로 추출**(char span provenance, 원문 불변)
  ② 각 성격에 W4 드라이버(headcount·fa_dep·cpi·growth·ratio)를 **제안**(판정은 평가인)
  ③ Σ성격별 == IS 표기 판관비/매출원가 **tie-out** (FAIL 게이트)
  ④ `fs_disagg.py` 로 그대로 파이프할 payload 방출 → ①→② 사슬이 닫힌다

**과립도 원칙 자동 준수**(SKILL.md W2.5): 주석에서 뽑은 만큼만 쪼개지므로 과립도가 원천
자료로 자동 뒷받침된다 — 억지 분해가 구조적으로 불가능하다. 주석이 없으면 추출 결과가
비고, 총액 유지 + `[성격별 미확보]` 로 남기면 된다.

원칙: **추출=결정론, 판정(카테고리·드라이버)=평가인 승인.** 카테고리가 애매한 성격
(감가상각비 = 제조/판관 배분)은 `uncertain` 으로 표면화하고 자동 확정하지 않는다.

입력 (stdin, JSON):
  {
    "text": "구분  2024  2023\\n급여  12,340  11,200\\n...",   # 주석 표 복붙(필수)
    "note_no": 24,            # 선택: 주석 번호(provenance locator)
    "unit": "백만원",          # 선택: 표 단위(천원/백만원/억원…)
    "year": "2024",           # 선택: tie-out 기준연도(기본=첫 열)
    "stated_sga": 15840,      # 선택: IS 표기 판관비 → Σ성격별 tie-out
    "stated_cogs": null,      # 선택: IS 표기 매출원가 → Σ성격별 tie-out
    "parent_sga": "판매비와관리비",   # 선택: fs_disagg 블록 parent 라벨
    "parent_cogs": "매출원가"
  }

출력 (stdout, JSON):
  {
    "natures": [{name, category, method, confidence, uncertain, amounts, note}],
    "drafts":  [...],              # W4 CostLine 초안(base·method 시드)
    "years":   ["2024","2023"],
    "issues":  [{severity, code, message, detail}],   # fs_clean/fs_disagg 와 동일 계약
    "disagg_payload": {"blocks":[...]},               # → fs_disagg.py 파이프
    "gate_ok": bool                                    # FAIL 0
  }

사용:
  echo '{"text":"...","stated_sga":15840}' | python footnote_costs.py
  python footnote_costs.py input.json
  # ①→② 사슬:
  python footnote_costs.py in.json | python -c "import json,sys;print(json.dumps(json.load(sys.stdin)['disagg_payload'],ensure_ascii=False))" | python fs_disagg.py
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import _bootstrap  # noqa: F401

from ingest.footnote_costs import (  # noqa: E402
    FootnoteCostParser, costs_tieout, to_cost_line_drafts, to_disagg_block,
)

# 엔진 Severity(소문자) → 스킬 이슈 계약(대문자, fs_clean/fs_disagg 와 동일)
_SEV = {"fail": "FAIL", "warn": "WARN", "pass": "INFO"}


def _issues(report, *, only_problems: bool = True) -> list[dict]:
    """ValidationReport → 스킬 이슈 리스트. pass 는 기본 제외(문제만 표면화)."""
    out = []
    for f in report.findings:
        sev = _SEV.get(f.severity.value, "INFO")
        if only_problems and sev == "INFO":
            continue
        out.append({"severity": sev, "code": f.rule, "message": f.message,
                    "detail": f.detail})
    return out


def _nature_dict(n) -> dict:
    return {
        "name": n.name,
        "category": n.category,              # None = uncertain(평가인 지정)
        "method": n.method,                  # W4 드라이버 제안
        "confidence": n.method_confidence,
        "uncertain": n.uncertain,
        "amounts": {k: float(v) for k, v in n.amounts.items()},
        "note": n.note,
    }


def _blocks(natures, years, payload) -> list[dict]:
    """카테고리별 fs_disagg 블록 — stated 총액이 있으면 total 채워 합보존 검증 가능하게."""
    blocks = []
    for cat, parent_key, default_parent, stated_key in (
        ("sga", "parent_sga", "판매비와관리비", "stated_sga"),
        ("cogs", "parent_cogs", "매출원가", "stated_cogs"),
    ):
        if not any(n.category == cat for n in natures):
            continue
        parent = payload.get(parent_key) or default_parent
        blk = to_disagg_block(natures, cat, parent=parent, years=years,
                              unit=payload.get("unit") or "백만원")
        stated = payload.get(stated_key)
        if stated is not None:
            # tie-out 기준연도에만 총액 주입(다른 연도 IS 값은 호출측이 채움).
            y = str(payload.get("year") or (years[0] if years else ""))
            if y in blk["periods"]:
                blk["periods"][y]["total"] = str(stated)
        blocks.append(blk)
    return blocks


def run_footnote_costs(payload: dict) -> dict:
    """주석 표 → 성격별 추출 + 드라이버 제안 + tie-out + fs_disagg payload."""
    text = payload.get("text") or ""
    if not str(text).strip():
        return {"natures": [], "drafts": [], "years": [], "disagg_payload": {"blocks": []},
                "issues": [{"severity": "FAIL", "code": "no_input",
                            "message": "text(주석 표)가 비어 있음.", "detail": {}}],
                "gate_ok": False}

    p = FootnoteCostParser(payload.get("source_id", "주석"),
                           note_no=payload.get("note_no"), unit=payload.get("unit"))
    p.extract(text)
    natures, years = p.natures, p.years
    issues = _issues(p.result.report)

    # tie-out: Σ성격별(카테고리별) == IS 표기 총액. 준 것만 검증.
    s_sga, s_cogs = payload.get("stated_sga"), payload.get("stated_cogs")
    if (s_sga is not None or s_cogs is not None) and years:
        rpt = costs_tieout(
            natures, year=str(payload.get("year") or years[0]),
            stated_sga=Decimal(str(s_sga)) if s_sga is not None else None,
            stated_cogs=Decimal(str(s_cogs)) if s_cogs is not None else None)
        issues += _issues(rpt)

    if not natures:
        issues.append({"severity": "WARN", "code": "no_nature",
                       "message": "성격 행을 하나도 못 읽음 — 표 형태 확인, "
                                  "또는 총액 유지 + [성격별 미확보] 표면화(억지 분해 금지).",
                       "detail": {}})

    return {
        "natures": [_nature_dict(n) for n in natures],
        "drafts": to_cost_line_drafts(natures, years),
        "years": years,
        "issues": issues,
        "disagg_payload": {"blocks": _blocks(natures, years, payload)},
        "gate_ok": not any(i["severity"] == "FAIL" for i in issues),
    }


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows cp949 방지
    except (AttributeError, ValueError):
        pass
    raw = Path(sys.argv[1]).read_text(encoding="utf-8") if len(sys.argv) > 1 else sys.stdin.read()
    print(json.dumps(run_footnote_costs(json.loads(raw)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
