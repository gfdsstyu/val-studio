# -*- coding: utf-8 -*-
"""
P4 — 감사 스캔. 내러티브↔숫자 gap·provenance 없는 가정·내부 산술 이상치를 코퍼스 전체에서 집계.

A) 원장(smic/_ledger/*.yaml): finding·audit_flag·provenance 없는 가정 수집.
B) 파싱표(_extract/*.tables.json): 내부 산술 정합성 스캔
   - 영업이익 ≤ 매출액 (위반=불가능 → 검토/파서오류)
   - 영업이익률 = 영업이익/매출액 이 타당범위(-50%~60%) 밖 → flag
출력: docs/reference/감사스캔_리포트.md

사용: python scripts/audit_scan.py
"""
import os
import re
import glob
import json

import yaml

SMIC = r"D:/valuation-platform/docs/reference/smic"
LEDGER = os.path.join(SMIC, "_ledger")
EXTRACT = os.path.join(SMIC, "_extract")
OUT = r"D:/valuation-platform/docs/reference/감사스캔_리포트.md"

import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def scan_ledgers():
    findings, no_prov = [], []
    for p in sorted(glob.glob(os.path.join(LEDGER, "*.yaml"))):
        d = yaml.safe_load(open(p, encoding="utf-8"))
        comp = d.get("company", os.path.basename(p))
        for a in d.get("assumptions", []):
            if a.get("finding"):
                findings.append((comp, a["id"], a["finding"].strip().split("\n")[0]))
            if a.get("formula") and not a.get("provenance"):
                no_prov.append((comp, a["id"], a.get("driver_type", "?")))
    return findings, no_prov


def scan_tables():
    """내부 산술 이상치. 반환: [(slug, year, 매출, 영업이익, 영업이익률%, 사유)]"""
    anomalies = []
    files = glob.glob(os.path.join(EXTRACT, "*.tables.json"))
    scanned = 0
    for f in files:
        slug = os.path.basename(f).replace(".tables.json", "")
        d = json.load(open(f, encoding="utf-8"))
        kr = d.get("key_rows", {})
        rev = kr.get("매출액") or next((v for k, v in kr.items() if re.fullmatch(r"매출액?", k)), None)
        opi = kr.get("영업이익")
        if not rev or not opi:
            continue
        scanned += 1
        for y in rev:
            if y in opi and isinstance(rev[y], (int, float)) and isinstance(opi[y], (int, float)) and rev[y] > 0:
                margin = opi[y] / rev[y] * 100
                if opi[y] > rev[y]:
                    anomalies.append((slug, y, rev[y], opi[y], round(margin, 1), "영업이익>매출(불가능)"))
                elif margin > 60 or margin < -50:
                    anomalies.append((slug, y, rev[y], opi[y], round(margin, 1), "영업이익률 이상범위"))
    return anomalies, scanned


def main():
    findings, no_prov = scan_ledgers()
    anomalies, scanned = scan_tables()

    L = ["---",
         "topic: 감사 스캔 리포트 — 내러티브↔숫자 gap·provenance 결측·내부 산술 이상치",
         "keywords: [감사, audit, 내러티브 숫자 gap, provenance, 산술 정합성, 이상치, 검토필요, claimed applied]",
         "canonical_questions:",
         '  - "리포트에서 서술과 숫자가 어긋나는 가정은?"',
         '  - "출처(provenance) 없는 가정은?"',
         '  - "내부 산술이 이상한(검토 필요) 리포트는?"',
         "layer: practice", "parent: 가정원장_방법론", "doc_type: knowledge", "---",
         "# 감사 스캔 리포트", "",
         "> 자동생성(`scripts/audit_scan.py`). 감사·리뷰 트랙: 검토 우선순위 리스트.", "",
         f"## A. 내러티브↔숫자 gap (원장 finding) — {len(findings)}건", ""]
    if findings:
        for comp, aid, msg in findings:
            L.append(f"- **{comp}** `{aid}`: {msg}")
    else:
        L.append("- (없음 — 원장 확대 시 채워짐)")

    L += ["", f"## B. provenance 결측 가정 — {len(no_prov)}건", ""]
    L.append("- (없음)" if not no_prov else "")
    for comp, aid, dt in no_prov:
        L.append(f"- **{comp}** `{aid}` ({dt}) — 출처 미기재")

    L += ["", f"## C. 내부 산술 이상치 (표 {scanned}편 스캔) — {len(anomalies)}건", "",
          "> 영업이익>매출 또는 영업이익률 이상범위. 애널리스트 오류이거나 **표 파서 컬럼 오정렬**",
          "> (세그먼트 표 위험) 신호 — 둘 다 검토 대상.", "",
          "| 리포트 | 연도 | 매출 | 영업이익 | 이익률 | 사유 |", "|---|---|---|---|---|---|"]
    for slug, y, rev, opi, m, why in anomalies[:40]:
        L.append(f"| {slug} | {y} | {rev:,.0f} | {opi:,.0f} | {m}% | {why} |")

    L += ["", "## 관련",
          "[[가정원장_방법론]] · [[벤치마크_분포]] · [[감사인검토_WACC방법론]] · [[SMIC_기업리포트_코퍼스]]"]
    open(OUT, "w", encoding="utf-8").write("\n".join(L))
    print(f"생성: {OUT}")
    print(f"  A.gap {len(findings)}건 · B.provenance결측 {len(no_prov)}건 · "
          f"C.산술이상치 {len(anomalies)}건 (표 {scanned}편 스캔)")


if __name__ == "__main__":
    main()
