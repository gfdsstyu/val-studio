"""XBRL 파서 테스트 — fact⋈context 조인·차원 필터·라벨·단위환산.

합성 XBRL instance 로 파싱 로직 검증(실 파일 불요). 실 삼성전자 파일은 별도 스모크.
stdlib: `python tests/test_xbrl.py`
"""
from __future__ import annotations

import sys
import tempfile
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ingest.parsers.xbrl import XbrlParser, parse_contexts, parse_facts  # noqa: E402
import xml.etree.ElementTree as ET  # noqa: E402

# 합성 XBRL: 연결 당기 매출 + 별도 매출 + 세그먼트 매출 + 비숫자 fact
SYNTH = """<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
  xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
  xmlns:ifrs-full="http://xbrl.ifrs.org/taxonomy/2021-03-24/ifrs-full"
  xmlns:dart="http://dart.fss.or.kr/taxonomy/2024-06-30/ifrs/dart">
  <xbrli:context id="CFY_C">
    <xbrli:period><xbrli:startDate>2026-01-01</xbrli:startDate><xbrli:endDate>2026-03-31</xbrli:endDate></xbrli:period>
    <xbrli:entity><xbrli:segment><xbrldi:explicitMember dimension="ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis">ifrs-full:ConsolidatedMember</xbrldi:explicitMember></xbrli:segment></xbrli:entity>
  </xbrli:context>
  <xbrli:context id="CFY_S">
    <xbrli:period><xbrli:startDate>2026-01-01</xbrli:startDate><xbrli:endDate>2026-03-31</xbrli:endDate></xbrli:period>
    <xbrli:entity><xbrli:segment><xbrldi:explicitMember dimension="ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis">ifrs-full:SeparateMember</xbrldi:explicitMember></xbrli:segment></xbrli:entity>
  </xbrli:context>
  <xbrli:context id="CFY_SEG">
    <xbrli:period><xbrli:startDate>2026-01-01</xbrli:startDate><xbrli:endDate>2026-03-31</xbrli:endDate></xbrli:period>
    <xbrli:entity><xbrli:segment>
      <xbrldi:explicitMember dimension="ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis">ifrs-full:ConsolidatedMember</xbrldi:explicitMember>
      <xbrldi:explicitMember dimension="ifrs-full:SegmentsAxis">entity:DX</xbrldi:explicitMember>
    </xbrli:segment></xbrli:entity>
  </xbrli:context>
  <xbrli:unit id="KRW"><xbrli:measure>iso4217:KRW</xbrli:measure></xbrli:unit>
  <ifrs-full:Revenue contextRef="CFY_C" unitRef="KRW" decimals="-6">79140503000000</ifrs-full:Revenue>
  <ifrs-full:Revenue contextRef="CFY_S" unitRef="KRW" decimals="-6">50000000000000</ifrs-full:Revenue>
  <ifrs-full:Revenue contextRef="CFY_SEG" unitRef="KRW" decimals="-6">51717211000000</ifrs-full:Revenue>
  <dart:ReportTitle contextRef="CFY_C">분기보고서</dart:ReportTitle>
</xbrli:xbrl>
"""


def _write(text: str) -> str:
    f = tempfile.NamedTemporaryFile("w", suffix=".xbrl", delete=False, encoding="utf-8")
    f.write(text); f.close()
    return f.name


def test_context_period_and_dims():
    root = ET.fromstring(SYNTH)
    ctx = parse_contexts(root)
    assert ctx["CFY_C"].period == "2026-01-01~2026-03-31"
    assert ctx["CFY_C"].consolidation == "ConsolidatedMember"
    assert ctx["CFY_S"].consolidation == "SeparateMember"
    # 주재무제표(세그먼트 없음) vs 세그먼트
    assert ctx["CFY_C"].non_consolidation_dims == {}
    assert "SegmentsAxis" in ctx["CFY_SEG"].non_consolidation_dims


def test_facts_join_context():
    root = ET.fromstring(SYNTH)
    ctx = parse_contexts(root)
    facts = parse_facts(root, ctx)
    revs = [f for f in facts if f.concept == "Revenue"]
    assert len(revs) == 3                    # 연결·별도·세그먼트
    assert all(f.unit == "KRW" for f in revs)


def test_primary_facts_excludes_segments_and_separate():
    p = XbrlParser("synth")
    p.extract(_write(SYNTH))
    prim = p.primary_facts("ConsolidatedMember")
    revs = [f for f in prim if f.concept == "Revenue"]
    assert len(revs) == 1                     # 연결 + 세그먼트 제외 = 1개
    assert revs[0].value == "79140503000000"


def test_won_to_million_conversion():
    p = XbrlParser("synth")
    res = p.extract(_write(SYNTH))
    # 연결 매출 79,140,503,000,000원 → 79,140,503 백만원
    v = res.by_name("ConsolidatedMember:Revenue")  # 라벨 없으면 QName fallback... 아래로 탐색
    if v is None:
        v = next(x for x in res.values if "Revenue" in x.field_name and x.field_name.startswith("Consolidated") and x.value == Decimal("79140503"))
    assert v.value == Decimal("79140503")


def test_nonnumeric_fact_not_emitted():
    # ReportTitle(unitRef 없음)은 방출 안 됨 → 게이트 통과
    p = XbrlParser("synth")
    res = p.extract(_write(SYNTH))
    assert res.ok
    assert not any("ReportTitle" in v.field_name for v in res.values)
    assert len(p.numeric_facts) == 3          # Revenue 3개만 숫자


def test_provenance_has_qname_and_period():
    p = XbrlParser("synth")
    res = p.extract(_write(SYNTH))
    v = next(x for x in res.values if x.value == Decimal("79140503"))
    assert v.provenance.locator.account_id == "ifrs-full:Revenue"
    assert "2026-01-01~2026-03-31" in (v.provenance.note or "")
    assert v.provenance.method.value == "structured"


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
