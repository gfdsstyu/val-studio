"""실적 시계열 어셈블리 — DART 커넥터 산출 → FinancialHistory (L3 분석적 절차 입력).

/api/dart/financials 연도별 응답(accounts)을 fs_mapper 분류(택사노미 앵커 우선,
계정명 키워드 폴백)로 매출액·매출원가·판관비 시계열로 접고, /api/dart/employee
연도별 응답(headcount·total_salary)을 인당 인건비 검사 입력으로 붙인다.

설계 원칙 (dcf_inputs·wacc_inputs 와 동일):
  - 결정론 — LLM 없음. 분류는 fs_mapper 규칙, 무매칭은 필드 제외 + note 로 표면화.
  - "있는 것만" — 한 연도라도 매칭 실패한 필드는 통째로 None (부분 시계열로
    가짜 연속성을 만들지 않는다). L3 는 부재 필드를 PASS(정보)로 강등하므로 안전.
  - 매출(Sales) 무매칭 연도는 연도 자체를 제외 — 매출이 모든 비율의 분모(백본).
"""
from __future__ import annotations

from calc_core.analytical import FinancialHistory
from ingest.fs_mapper import classify

# 손익 계열 sj_div. IS(손익계산서) 우선, 없으면 CIS(포괄손익 — 단일계산서 공시) 폴백.
_PL_DIVS = ("IS", "CIS")
# fs_mapper 버킷 → FinancialHistory 필드
_BUCKETS = {"Sales": "revenue", "COGS": "cogs", "SGA": "sga"}


def _pick(accounts: list[dict], bucket: str) -> float | None:
    """공시 순서상 첫 매칭 계정의 값 — 총계 라인이 세부 라인보다 먼저 온다는
    fnlttSinglAcntAll 관행에 기댄다(합산하면 세부 라인 이중계상 위험이라 첫 매칭).
    IS 전량을 먼저 훑고, 무매칭일 때만 CIS 를 훑는다."""
    for div in _PL_DIVS:
        for a in accounts:
            if a.get("sj_div") != div or a.get("value") is None:
                continue
            c = classify(str(a.get("name", "")), "PL",
                         account_id=a.get("account_id"))
            if c.bucket == bucket:
                return float(a["value"])
    return None


def history_from_dart(
    fin_years: list[dict],
    employee_years: list[dict] | None = None,
) -> tuple[FinancialHistory, list[str]]:
    """연도별 재무(+선택 직원현황) 응답 → (FinancialHistory, 어셈블리 노트).

    fin_years: [{"year": int, "accounts": [{"name","sj_div","value","account_id"?}]}]
        — /api/dart/financials 응답 그대로(연도별 1건).
    employee_years: [{"year": int, "headcount": float, "total_salary": float}]
        — /api/dart/employee 응답에서 발췌. 전 연도 커버 시에만 시계열로 채택.

    노트는 제외·폴백 결정의 감사추적("있는 것만" 원칙의 표면화) — 응답에 동봉해
    유저가 어셈블리 결과를 검수할 수 있게 한다(판단 보조 원칙).
    """
    if not fin_years:
        raise ValueError("fin_years 비어 있음")
    notes: list[str] = []
    rows = []
    for fy in sorted(fin_years, key=lambda x: int(x.get("year", 0))):
        year = int(fy.get("year", 0))
        accounts = fy.get("accounts") or []
        rev = _pick(accounts, "Sales")
        if rev is None:
            notes.append(f"{year}: 매출액 무매칭 — 연도 제외(매출=비율 백본)")
            continue
        rows.append({"year": year, "revenue": rev,
                     "cogs": _pick(accounts, "COGS"),
                     "sga": _pick(accounts, "SGA")})
    if not rows:
        raise ValueError("매출액이 매칭된 연도가 없음 — history 구성 불가")

    years = [r["year"] for r in rows]
    fields: dict[str, list[float] | None] = {"revenue": [r["revenue"] for r in rows]}
    for f in ("cogs", "sga"):
        gaps = [r["year"] for r in rows if r[f] is None]
        if gaps:
            notes.append(f"{f}: {gaps} 무매칭 — 필드 제외(부분 시계열 금지)")
            fields[f] = None
        else:
            fields[f] = [float(r[f]) for r in rows]

    headcount = labor = None
    if employee_years:
        emp = {int(e["year"]): e for e in employee_years if e.get("year") is not None}
        missing = [y for y in years if y not in emp]
        if missing:
            notes.append(f"직원현황: {missing} 부재 — 인당 인건비 검사 제외")
        else:
            try:
                headcount = [float(emp[y]["headcount"]) for y in years]
                labor = [float(emp[y]["total_salary"]) for y in years]
            except (KeyError, TypeError, ValueError):
                notes.append("직원현황: headcount/total_salary 결측 — 제외")
                headcount = labor = None

    return FinancialHistory(years=years, revenue=fields["revenue"],
                            cogs=fields["cogs"], sga=fields["sga"],
                            headcount=headcount, labor_cost=labor), notes
