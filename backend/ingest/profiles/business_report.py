"""사업보고서 시맨틱 프로파일 — XBRL fact → DCF 엔진용 핵심 재무계정.

XBRL 은 기계태그라 IFRS 표준 개념코드(ifrs-full:Revenue 등)로 계정을 특정한다 —
한글 라벨 불요(의견서 프로파일이 garble 앵커에 의존한 것과 정반대). 3000+ fact →
~10 핵심계정(매출·영업이익·자산·부채·자본·영업현금흐름)으로 압축해 엔진·감사인 트랙에 넘긴다.

입력: XbrlParser.primary_facts()(연결 주재무제표). 개념코드별 최신기간 fact 선택.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# IFRS/DART 개념코드(QName local) → 정규 필드. 여러 후보는 우선순위 순.
_CONCEPT_MAP: list[tuple[str, tuple[str, ...]]] = [
    ("revenue", ("Revenue",)),
    ("operating_income", ("OperatingIncomeLoss",)),
    ("profit_before_tax", ("ProfitLossBeforeTax",)),
    ("net_income", ("ProfitLoss",)),
    ("net_income_owners", ("ProfitLossAttributableToOwnersOfParent",)),
    ("total_assets", ("Assets",)),
    ("total_liabilities", ("Liabilities",)),
    ("equity", ("Equity", "EquityAttributableToOwnersOfParent")),
    ("operating_cf", ("CashFlowsFromUsedInOperatingActivities",)),
    ("cash", ("CashAndCashEquivalents",)),
]


@dataclass
class BusinessFinancials:
    """사업보고서에서 뽑은 정규 재무계정(백만원). 값 없으면 None."""
    period: str | None = None
    consolidation: str | None = None
    values: dict[str, float] = field(default_factory=dict)   # 필드→백만원
    labels: dict[str, str] = field(default_factory=dict)     # 필드→한글계정명
    source_concepts: dict[str, str] = field(default_factory=dict)  # 필드→QName

    def get(self, field_name: str) -> float | None:
        return self.values.get(field_name)


def _latest(facts: list) -> dict[str, object]:
    """개념코드(local)별 최신 endDate fact. period 'YYYY-...~YYYY-MM-DD' 또는 instant."""
    best: dict[str, object] = {}
    for f in facts:
        key = f.concept
        end = f.context.period.split("~")[-1]         # duration 끝 or instant
        cur = best.get(key)
        if cur is None or end > cur.context.period.split("~")[-1]:
            best[key] = f
    return best


def extract_business_report(facts: list, labels: dict[str, str] | None = None) -> BusinessFinancials:
    """XbrlParser.primary_facts() → BusinessFinancials(핵심계정, 백만원).

    개념코드별 최신기간 fact 선택 후 정규 필드에 매핑. 원(KRW)→백만원 환산.
    """
    labels = labels or {}
    latest = _latest(facts)
    out = BusinessFinancials()
    # 대표 기간·연결구분(매출 기준, 없으면 자산)
    anchor = latest.get("Revenue") or latest.get("Assets")
    if anchor is not None:
        out.period = anchor.context.period
        out.consolidation = anchor.context.consolidation

    for field_name, concepts in _CONCEPT_MAP:
        for concept in concepts:
            f = latest.get(concept)
            if f is None:
                continue
            unit_scale = 1e-6 if f.unit == "KRW" else 1.0   # 원→백만원
            try:
                out.values[field_name] = float(f.value) * unit_scale
            except ValueError:
                continue
            out.labels[field_name] = labels.get(concept, f.qname)
            out.source_concepts[field_name] = f.qname
            break
    return out
