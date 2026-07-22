"""유사회사 선정 4-step 워크플로우 테스트 — 퍼널·검증게이트·감사 산출물.

stdlib: `python tests/test_peer_selection.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ingest.peer_selection import (  # noqa: E402
    PeerCandidate, Step2Judgment, codes_from_seed_peers, normalize_ticker, select_peers,
)

# 클래시스 스타일 미니 퍼널: 6후보 → step1에서 1·step2에서 1·step3에서 1·step4에서 1 탈락 → 2사
CANDS = [
    PeerCandidate("100001", "미용기기A", "C2719", 0.90, 5.0),
    PeerCandidate("100002", "미용기기B", "C2719", 0.85, 3.0),
    PeerCandidate("100003", "타업종C", "C1010", 0.95, 9.0),          # step1 탈락
    PeerCandidate("100004", "유통사D", "C2719", 0.80, 4.0),          # step2 탈락(비유사)
    PeerCandidate("100005", "겸업E", "C2719", 0.40, 6.0),            # step3 탈락(비중 40%)
    PeerCandidate("100006", "신규상장F", "C2719", 0.88, 0.8),        # step4 탈락(0.8년)
]

JUDG = [
    Step2Judgment("100001", True, "사업보고서: 피부미용 의료기기 제조 주력"),
    Step2Judgment("100002", True, "홈페이지·DART: HIFU 장비/소모품"),
    Step2Judgment("100004", False, "사업보고서: 의료기기 '유통'만, 제조 아님"),
    Step2Judgment("100005", True, "일부 사업부 미용기기 제조"),
    Step2Judgment("100006", True, "동종 장비 제조"),
]


def _run(**over):
    kw = dict(target_industry_codes={"C2719"}, judgments=JUDG)
    kw.update(over)
    return select_peers(CANDS, **kw)


def test_funnel_counts():
    """target_ticker 미지정이면 step0 행 자체가 없다(기능 미실행을 정직하게 표기)."""
    r = _run()
    assert list(r.funnel.values()) == [6, 5, 4, 3, 2]
    assert "step0 자기제외" not in r.funnel


def test_final_selection_and_traces():
    r = _run()
    assert [c.ticker for c in r.selected] == ["100001", "100002"]
    drops = {t.candidate.ticker: t.dropped_at for t in r.traces if t.dropped_at}
    assert drops == {"100003": "step1", "100004": "step2",
                     "100005": "step3", "100006": "step4"}
    # 탈락 사유가 전량 비어있지 않아야(감사 방어)
    assert all(t.reason for t in r.traces if t.dropped_at)


def test_step2_missing_judgment_rejected():
    # 생존 후보(100005) 판정 누락 → 게이트가 막아야
    partial = [j for j in JUDG if j.ticker != "100005"]
    try:
        _run(judgments=partial)
        raise AssertionError("누락 판정이 통과됨")
    except ValueError as e:
        assert "100005" in str(e)


def test_step2_unreasoned_judgment_rejected():
    bad = JUDG[:-1] + [Step2Judgment("100006", True, "  ")]
    try:
        _run(judgments=bad)
        raise AssertionError("무사유 판정이 통과됨")
    except ValueError as e:
        assert "사유" in str(e)


def test_no_judgments_skips_step2():
    # LLM 판정 미주입(judgments=None) → step2 통과(사전 스크리닝 용도)
    r = _run(judgments=None)
    assert r.funnel["step2 사업유사성"] == r.funnel["step1 산업코드"]


def test_missing_data_warns_not_drops():
    cands = [PeerCandidate("200001", "결측사", "C2719", None, None)]
    r = select_peers(cands, target_industry_codes={"C2719"})
    assert r.selected and len(r.traces[0].warnings) == 2   # 비중·상장연수 경고 2건


def test_markdown_report():
    md = _run().to_markdown()
    assert "step4 상장·거래 | 2" in md
    assert "유통사D(100004) — step2: 사업 비유사 — 사업보고서" in md
    assert "유저 승인" in md


def test_uncertain_goes_to_review_not_dropped():
    # LLM 원칙: 애매하면 자동 탈락 금지 → 유저 결정 큐(needs_review)로
    judg = [j for j in JUDG if j.ticker != "100002"] + [
        Step2Judgment("100002", False, "장비는 동종이나 매출 절반이 타업종 — 애매",
                      uncertain=True)]
    r = _run(judgments=judg)
    assert [c.ticker for c in r.selected] == ["100001"]          # 확정은 A만
    assert [t.candidate.ticker for t in r.needs_review] == ["100002"]
    md = r.to_markdown()
    assert "⚖️ 애매 — 유저 판단 필요" in md and "애매" in md
    # 퍼널에선 생존으로 집계(탈락 아님) — step1 후 5, step2 는 비유사 D만 탈락 → 4
    assert r.funnel["step2 사업유사성"] == 4


def test_codes_from_seed_peers_union():
    # 실무 플로우: rough 시드 유사회사들의 KSIC 역산 → 코드 2~3개 union 이 모집단 기준
    seeds = [PeerCandidate("300001", "시드A", "C2719"),
             PeerCandidate("300002", "시드B", "C2720"),
             PeerCandidate("300003", "시드C", "C2719"),
             PeerCandidate("300004", "코드결측", None)]
    codes = codes_from_seed_peers(seeds)
    assert codes == {"C2719", "C2720"}
    # 역산 코드로 모집단 필터 — 두 코드 어느 쪽이든 생존
    cands = CANDS + [PeerCandidate("100007", "인접코드G", "C2720", 0.9, 5.0)]
    judg = JUDG + [Step2Judgment("100007", True, "인접 KSIC 이나 동일 제품군 제조")]
    r = select_peers(cands, target_industry_codes=codes, judgments=judg)
    assert "100007" in [c.ticker for c in r.selected]


def test_threshold_params_bind():
    r = _run(revenue_share_threshold=0.95, min_listed_years=4.0)
    # 0.95 임계 → A(0.90)·B(0.85)도 step3 탈락 → 최종 0
    assert not r.selected
    assert r.params["revenue_share_threshold"] == 0.95


# ── R11 자기제외 (모델러스 D4) ────────────────────────────────────────────────
def test_self_exclusion_drops_target():
    """평가대상 자신은 step0 에서 탈락 — peer 통계 자기포함은 순환논법."""
    cands = [
        PeerCandidate(ticker="A145020", name="Hugel", industry_code="2110",
                      revenue_share_related=0.9, listed_years=8),
        PeerCandidate(ticker="A086900", name="Medytox", industry_code="2110",
                      revenue_share_related=0.9, listed_years=8),
    ]
    r = select_peers(cands, target_ticker="A145020", target_industry_codes={"2110"})
    assert [c.ticker for c in r.selected] == ["A086900"]
    self_trace = next(t for t in r.traces if t.candidate.ticker == "A145020")
    assert self_trace.dropped_at == "step0"
    assert "자기 자신" in self_trace.reason


def test_self_exclusion_normalizes_ticker_prefix():
    """'A145020'(FnGuide) 과 '145020'(KRX/DART) 표기 차이로 자기제외가 뚫리면 안 된다."""
    cands = [PeerCandidate(ticker="145020", name="Hugel", industry_code="2110",
                           revenue_share_related=0.9, listed_years=8)]
    r = select_peers(cands, target_ticker="A145020", target_industry_codes={"2110"})
    assert r.selected == []
    # 역방향도 동일
    cands2 = [PeerCandidate(ticker="A145020", name="Hugel", industry_code="2110",
                            revenue_share_related=0.9, listed_years=8)]
    assert select_peers(cands2, target_ticker="145020",
                        target_industry_codes={"2110"}).selected == []


def test_no_target_ticker_is_noop():
    """target_ticker 미지정이면 아무도 탈락하지 않는다(기존 호출자 호환)."""
    cands = [PeerCandidate(ticker="A145020", name="Hugel", industry_code="2110",
                           revenue_share_related=0.9, listed_years=8)]
    r = select_peers(cands, target_industry_codes={"2110"})
    assert len(r.selected) == 1
    # 기능 미실행 → 퍼널에 행이 없어야 한다(있으면 "돌렸는데 탈락 0"으로 오독)
    assert "step0 자기제외" not in r.funnel
    # 공백만 준 경우도 no-op — 티커 결측 후보를 전량 오탈락시키면 안 된다
    blank = select_peers(
        [PeerCandidate(ticker="", name="티커결측", industry_code="2110",
                       revenue_share_related=0.9, listed_years=8)],
        target_ticker="   ", target_industry_codes={"2110"})
    assert len(blank.selected) == 1, [t.reason for t in blank.traces]


def test_self_excluded_target_needs_no_step2_judgment():
    """자기제외된 대상은 step2 판정 대상에서 빠진다(누락 ValueError 안 남)."""
    cands = [
        PeerCandidate(ticker="A145020", name="Hugel", industry_code="2110",
                      revenue_share_related=0.9, listed_years=8),
        PeerCandidate(ticker="A086900", name="Medytox", industry_code="2110",
                      revenue_share_related=0.9, listed_years=8),
    ]
    r = select_peers(cands, target_ticker="A145020", target_industry_codes={"2110"},
                     judgments=[Step2Judgment("A086900", True, "동일 톡신 사업")])
    assert [c.ticker for c in r.selected] == ["A086900"]


def test_normalize_ticker_alphanumeric_korean_code():
    """신형우선주 등 6자리 **영숫자** 코드도 A 접두를 흡수해야 한다.

    'A00104K' vs '00104K' 가 갈리면 같은 종목인데 자기제외가 조용히 미발동한다.
    """
    assert normalize_ticker("A00104K") == normalize_ticker("00104K") == "00104K"
    assert normalize_ticker("A145020") == normalize_ticker("145020") == "145020"
    assert normalize_ticker(" a145020 ") == "145020"
    assert normalize_ticker("AAPL") == "AAPL"        # 미국 티커는 건드리지 않는다
    assert normalize_ticker("ABCDEFG") == "ABCDEFG"  # 숫자 없으면 코드로 보지 않는다


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
