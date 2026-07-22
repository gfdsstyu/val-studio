"""사업보고서 프로파일 테스트 — XBRL fact → 핵심 재무계정.

합성 XbrlFact + 실 삼성 XBRL 스모크. stdlib: `python tests/test_business_report.py`
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ingest.profiles.business_report import extract_business_report  # noqa: E402


# XbrlFact 최소 스텁(context.period·consolidation·concept·unit·value)
@dataclass
class _Ctx:
    period: str
    _con: str
    @property
    def consolidation(self): return self._con


@dataclass
class _Fact:
    concept: str
    context: _Ctx
    unit: str
    value: str
    @property
    def qname(self): return f"ifrs-full:{self.concept}"


def _facts():
    cur = _Ctx("2026-01-01~2026-03-31", "ConsolidatedMember")
    prior = _Ctx("2025-01-01~2025-03-31", "ConsolidatedMember")
    bs = _Ctx("2026-03-31", "ConsolidatedMember")
    return [
        _Fact("Revenue", cur, "KRW", "79000000000000"),
        _Fact("Revenue", prior, "KRW", "71000000000000"),   # 구기간(선택 안 됨)
        _Fact("OperatingIncomeLoss", cur, "KRW", "6700000000000"),
        _Fact("Assets", bs, "KRW", "567000000000000"),
        _Fact("Liabilities", bs, "KRW", "130000000000000"),
    ]


def test_extracts_key_accounts_latest_period():
    fin = extract_business_report(_facts())
    assert fin.get("revenue") == 79_000_000          # 79조원 → 백만원
    assert fin.get("operating_income") == 6_700_000
    assert fin.get("total_assets") == 567_000_000
    assert fin.period == "2026-01-01~2026-03-31"      # 최신기간 선택
    assert fin.consolidation == "ConsolidatedMember"


def test_missing_accounts_absent():
    fin = extract_business_report(_facts())
    assert fin.get("net_income") is None              # 없는 계정
    assert "revenue" in fin.source_concepts


def test_real_samsung_xbrl_smoke():
    x = Path(r"D:/valuation-platform/scratch/xbrl")
    hits = list(x.glob("*.xbrl")) if x.exists() else []
    if not hits:
        print("  (skip: 삼성 XBRL 없음)"); return
    from ingest.parsers.xbrl import XbrlParser
    p = XbrlParser("삼성")
    p.extract(str(hits[0]))
    fin = extract_business_report(p.primary_facts(), p.labels)
    # 삼성 주요계정 존재 + 조 단위 규모
    assert fin.get("revenue") and fin.get("revenue") > 10_000_000       # >10조
    assert fin.get("total_assets") and fin.get("total_assets") > 100_000_000
    print(f"  삼성: 매출 {fin.get('revenue'):,.0f}백만 · 자산 {fin.get('total_assets'):,.0f}백만 "
          f"[{fin.period}] {fin.labels.get('revenue')}")


def test_router_auto_applies_business_report():
    x = Path(r"D:/valuation-platform/scratch/xbrl")
    hits = list(x.glob("*.xbrl")) if x.exists() else []
    if not hits:
        print("  (skip)"); return
    from ingest.router import ingest
    from ingest.profiles.business_report import BusinessFinancials
    r = ingest(str(hits[0]))
    assert isinstance(r.profile, BusinessFinancials)   # XBRL 사업보고서 → 프로파일 자동
    assert r.profile.get("revenue")


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
