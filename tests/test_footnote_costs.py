"""성격별 원가 주석 추출 백본 테스트 — 추출(결정론)·분류제안·tie-out 게이트·하류 배선.

stdlib: `python tests/test_footnote_costs.py`.
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ingest.footnote_costs import (  # noqa: E402
    FootnoteCostParser, costs_tieout, parse_footnote_costs, suggest_driver,
    to_cost_line_drafts, to_disagg_block,
)
from ingest.provenance import ExtractMethod, SourceKind  # noqa: E402
from ingest.validators import Severity  # noqa: E402

_TABLE = (
    "구분        2024      2023\n"
    "급여        12,340    11,200\n"
    "퇴직급여     1,500     1,300\n"
    "감가상각비   3,200     3,000\n"
    "지급수수료   2,000     1,900\n"
)


def test_extraction_and_year_header():
    natures, res = parse_footnote_costs(_TABLE, note_no=24)
    assert res.ok                                     # 숫자형 게이트 통과
    names = [n.name for n in natures]
    assert names == ["급여", "퇴직급여", "감가상각비", "지급수수료"]
    급여 = natures[0]
    assert 급여.amounts["2024"] == Decimal("12340")
    assert 급여.amounts["2023"] == Decimal("11200")
    # 출처: FOOTNOTE + REGEX + note_no
    pv = 급여.values[0]
    assert pv.provenance.source_kind is SourceKind.FOOTNOTE
    assert pv.provenance.method is ExtractMethod.REGEX
    assert pv.provenance.locator.note_no == 24


def test_charspan_invariant():
    # 원문 불변: text[char_start:char_end] == raw_text (감사추적 provenance 핵심)
    p = FootnoteCostParser("주석24", note_no=24)
    p.extract(_TABLE)
    checked = 0
    for n in p.natures:
        for pv in n.values:
            pr = pv.provenance
            if pr.char_start is not None:
                assert p.text[pr.char_start:pr.char_end] == pr.raw_text
                checked += 1
    assert checked == 8                               # 4성격 × 2연도


def test_driver_suggestion_and_uncertain():
    # 급여=headcount(sga 확정), 감가상각=fa_dep(카테고리 애매→uncertain), 수수료=cpi(sga)
    assert suggest_driver("급여")[:2] == ("sga", "headcount")
    assert suggest_driver("퇴직급여")[:2] == ("sga", "headcount")
    assert suggest_driver("감가상각비")[:2] == (None, "fa_dep")   # cogs/sga 애매
    assert suggest_driver("지급수수료")[:2] == ("sga", "cpi")
    assert suggest_driver("원재료비")[:2] == ("cogs", "growth")
    # 무매칭 → uncertain
    cat, method, conf, _ = suggest_driver("듣도보도못한비용")
    assert cat is None and conf == 0.0

    natures, _ = parse_footnote_costs(_TABLE)
    dep = next(n for n in natures if n.name == "감가상각비")
    assert dep.uncertain and dep.category is None     # 유저가 cogs/sga 배분 지정해야


def test_tieout_pass_when_sum_matches():
    # sga 확정 성격(급여+퇴직급여+지급수수료) = 15,840 == 표기 판관비 → PASS
    natures, _ = parse_footnote_costs(_TABLE)
    rpt = costs_tieout(natures, year="2024", stated_sga=Decimal("15840"))
    # 감가상각비(uncertain) 는 롤업 제외 → WARN 1건, 하지만 sga tie-out 은 PASS
    assert any(f.rule == "by_nature_tieout" and f.severity is Severity.WARN
               for f in rpt.findings)
    assert any(f.rule == "sum" and f.severity is Severity.PASS for f in rpt.findings)
    assert rpt.ok                                     # FAIL 없음(게이트 통과)


def test_tieout_fails_on_mismatch():
    # 표기 판관비를 조작(20,000) → Σ성격별 ≠ 표기 → FAIL 게이트
    natures, _ = parse_footnote_costs(_TABLE)
    rpt = costs_tieout(natures, year="2024", stated_sga=Decimal("20000"))
    assert not rpt.ok
    assert any(f.rule == "sum" and f.severity is Severity.FAIL for f in rpt.findings)


def test_unreadable_row_warns_and_tieout_catches():
    # 값이 안 읽히는 성격 행(급여=ABC)은 추출서 누락되지만 WARN 으로 표면화,
    # 그리고 남은 성격 합이 표기와 어긋나 tie-out(clean-truth 오라클)이 FAIL 로 잡는다.
    bad = "구분  2024\n급여  ABC\n퇴직급여  1,500\n"
    natures, res = parse_footnote_costs(bad)
    names = [n.name for n in natures]
    assert "급여" not in names and "퇴직급여" in names          # ABC 행 드롭
    assert any(f.rule == "numeric" and f.severity is Severity.WARN
               for f in res.report.findings)                    # 조용히 안 사라짐
    # 표기 판관비 3,000 인데 읽힌 sga 는 퇴직급여 1,500 뿐 → tie-out FAIL
    rpt = costs_tieout(natures, year="2024", stated_sga=Decimal("3000"))
    assert not rpt.ok
    assert any(f.rule == "sum" and f.severity is Severity.FAIL for f in rpt.findings)


def test_disagg_block_bridge():
    # sga 카테고리 → fs_disagg 블록(children). total 은 상위에서 주입(None 시드)
    natures, _ = parse_footnote_costs(_TABLE)
    block = to_disagg_block(natures, "sga", parent="판매비와관리비",
                            years=["2024", "2023"])
    assert block["parent"] == "판매비와관리비"
    ch = block["periods"]["2024"]["children"]
    assert "급여" in ch and "감가상각비" not in ch      # uncertom(감가) 은 sga 블록서 제외
    assert ch["급여"] == "12340"


def test_cost_line_drafts_seed():
    natures, _ = parse_footnote_costs(_TABLE)
    drafts = to_cost_line_drafts(natures, ["2024", "2023"])
    d = {x["name"]: x for x in drafts}
    assert d["급여"]["method"] == "headcount" and d["급여"]["base"] == 12340.0
    assert d["감가상각비"]["uncertain"] is True        # 카테고리 유저 지정 필요
    assert d["급여"]["category"] == "sga"


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
