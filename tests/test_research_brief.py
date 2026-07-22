"""research_brief 프로파일 테스트 — 합성 XBRL fact 로 ②④⑩ 프리필 검증.

stdlib: `python tests/test_research_brief.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ingest.parsers.xbrl import Context, XbrlFact  # noqa: E402
from ingest.profiles.research_brief import (  # noqa: E402
    extract_research_brief, render_brief_md,
)


class FakeParser:
    """XbrlParser 최소 대역: facts/labels/primary_facts 만."""
    def __init__(self, facts, labels=None):
        self.facts = facts
        self.labels = labels or {}

    def primary_facts(self, consolidation="ConsolidatedMember"):
        return [f for f in self.facts
                if f.context.consolidation == consolidation
                and not f.context.non_consolidation_dims]


def _ctx(cid, period, **dims):
    return Context(cid, period, "~" not in period, dims)


_CONS = {"ConsolidatedAndSeparateFinancialStatementsAxis": "ConsolidatedMember"}


def _fact(concept, value, period, unit="KRW", extra_dims=None, prefix="ifrs-full"):
    dims = dict(_CONS)
    dims.update(extra_dims or {})
    return XbrlFact(concept, prefix, _ctx(f"c{id(object())}", period, **dims),
                    unit, None, str(value))


LABELS = {
    "DxSeg": "DX부문", "DsSeg": "DS부문",
    "OrdinarySharesMember": "보통주 [구성요소]",
    "CNMember": "중국",
}

FACTS = [
    # ⑩ 두 기간 손익 + 재무상태
    _fact("Revenue", 133_900_000_000_000, "2026-01-01~2026-03-31"),
    _fact("Revenue", 133_900_000_000_000, "2026-01-01~2026-03-31"),   # 중복 fact
    _fact("Revenue", 79_100_000_000_000, "2025-01-01~2025-03-31"),
    _fact("OperatingIncomeLoss", 20_000_000_000_000, "2026-01-01~2026-03-31"),
    _fact("Assets", 600_000_000_000_000, "2026-03-31"),
    # ④ 사업부문(게이트 축 필요) + 지역
    _fact("Revenue", 90_000_000_000_000, "2026-01-01~2026-03-31",
          extra_dims={"SegmentConsolidationItemsAxis": "OperatingSegmentsMember",
                      "SegmentsAxis": "DxSeg"}),
    _fact("Revenue", 40_000_000_000_000, "2026-01-01~2026-03-31",
          extra_dims={"SegmentConsolidationItemsAxis": "OperatingSegmentsMember",
                      "SegmentsAxis": "DsSeg"}),
    _fact("Revenue", 9_000_000_000_000, "2026-01-01~2026-03-31",
          extra_dims={"GeographicalAreasAxis": "CNMember"}),
    # ② 주식수 — 최신 instant 가 이겨야 함
    _fact("NumberOfSharesIssued", 5_969_782_550, "2026-03-31", unit="SHARES",
          extra_dims={"ClassesOfShareCapitalAxis": "OrdinarySharesMember"}),
    _fact("SharesInEntityHeldByEntityOrByItsSubsidiariesOrAssociates",
          91_828_987, "2025-12-31", unit="SHARES",
          extra_dims={"ClassesOfShareCapitalAxis": "OrdinarySharesMember"}),
    _fact("SharesInEntityHeldByEntityOrByItsSubsidiariesOrAssociates",
          29_700_000, "2026-03-31", unit="SHARES",
          extra_dims={"ClassesOfShareCapitalAxis": "OrdinarySharesMember"}),
    # ② 엔티티(비숫자)
    XbrlFact("EntityHomepage", "dart-gcd", _ctx("e1", "2026-03-31", **_CONS),
             None, None, "https://www.samsung.com/sec"),
]

P = FakeParser(FACTS, LABELS)
PRE = extract_research_brief(P)


def test_financials_multi_period_and_dedupe():
    assert PRE.financials["2026-01-01~2026-03-31"]["revenue"] == 133_900_000.0  # 백만원
    assert PRE.financials["2025-01-01~2025-03-31"]["revenue"] == 79_100_000.0
    assert PRE.financials["2026-03-31"]["total_assets"] == 600_000_000.0
    assert PRE.doc_period == "2026-03-31"          # 최신 기간


def test_segments_gated_and_labeled():
    assert len(PRE.segments) == 2
    labs = {s.label for s in PRE.segments}
    assert labs == {"DX부문", "DS부문"}
    # 지역축은 segments 가 아니라 regions 로
    assert len(PRE.regions) == 1 and PRE.regions[0].label == "중국"


def test_shares_latest_instant_wins():
    assert PRE.issued_shares["보통주"] == 5_969_782_550
    assert PRE.treasury_shares["보통주"] == 29_700_000    # 2026-03-31 > 2025-12-31
    fr = PRE.floating_ratio()
    assert abs(fr["보통주"] - (1 - 29_700_000 / 5_969_782_550)) < 1e-12


def test_entity_meta():
    assert PRE.homepage == "https://www.samsung.com/sec"


def test_render_md_structure():
    md = render_brief_md(PRE, company_hint="삼성전자")
    assert md.startswith("# Company Brief — 삼성전자")
    for sec in ["## ① Summary", "## ④ 사업부문", "## ⑩ Financials"]:
        assert sec in md, sec
    assert "DX부문" in md and "133,900,000" in md
    assert "유통비율" in md
    assert md.count("_(LLM") >= 7                   # LLM 슬롯이 남아 있어야(경계 표시)


def test_empty_parser_no_crash():
    pre = extract_research_brief(FakeParser([]))
    assert pre.financials == {} and pre.segments == []
    md = render_brief_md(pre, company_hint="X")
    assert "# Company Brief — X" in md


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    ok = 0
    for fn in fns:
        try:
            fn(); ok += 1; print(f"  ok  {fn.__name__}")
        except Exception:
            print(f"  FAIL {fn.__name__}"); traceback.print_exc()
    print(f"\n{ok}/{len(fns)} passed")
