"""서사 표현 가드 — 안티패턴 검출과 오탐 억제.

근거: 앤트로픽_금융스킬_벤치마크 §4 variance 서사 규격(Driver/Outlook/Action)과
안티패턴 3종 + 회계 실무의 '근거 없는 단정 금지'.

가드의 성패는 **오탐 억제**에 달렸다 — 정상 문장이 자주 걸리면 사람이 경고를
무시하게 되고 그 순간 가드는 죽는다. 그래서 정상 문장 회귀를 함께 고정한다.
"""
from __future__ import annotations

from ingest.validators import Severity
from report import check_finding_note, check_language, lint_report


def _rules(rep) -> set[str]:
    return {f.detail.get("rule") for f in rep.findings if f.severity is Severity.WARN}


def _warns(rep) -> list:
    return [f for f in rep.findings if f.severity is Severity.WARN]


# ── 안티패턴 검출 ────────────────────────────────────────────────────────────
def test_detects_unhedged_assertion():
    rep = check_language("검토 결과 본 건은 분식회계입니다.")
    assert "assertion" in _rules(rep)


def test_detects_circular_explanation():
    rep = check_language("매출원가율이 예상보다 높게 나타났다.")
    assert "circular" in _rules(rep)


def test_detects_non_explanation():
    rep = check_language("차이 원인은 시기 차이로 판단.")
    assert "non_explanation" in _rules(rep)


def test_detects_vague_aggregation():
    rep = check_language("나머지는 기타 소액 항목으로 구성된다.")
    assert "vague" in _rules(rep)


def test_reports_match_span_and_context():
    """왜 걸렸는지 즉시 보이지 않으면 사람이 고칠 수 없다."""
    text = "전기 대비 판관비가 증가했다. 본 건은 분식입니다. 추가 확인 예정."
    hit = next(f for f in _warns(check_language(text)) if f.detail["rule"] == "assertion")
    lo, hi = hit.detail["span"]
    assert text[lo:hi] == hit.detail["match"]
    assert "분식" in hit.detail["context"]


# ── 오탐 억제 ────────────────────────────────────────────────────────────────
def test_hedged_language_is_not_assertion():
    """실무 표현(가능성·확인 필요·권고)은 통과해야 한다 — 가드의 존재 이유가 이 대비다."""
    ok = [
        "분식회계 가능성을 배제할 수 없어 추가 확인이 필요하다.",
        "매출 인식 시점에 대한 검토가 필요한 것으로 판단된다.",
        "해당 가정의 근거가 확실하지 않아 스트레스 테스트를 권고한다.",
    ]
    for s in ok:
        assert not _warns(check_language(s)), f"오탐: {s}"


def test_clean_variance_narrative_passes():
    rep = check_language(
        "판관비: 불리 1,240백만원(+8.3%) / Driver: 신규 물류센터 임차료 반영 / "
        "Outlook: 계약기간 3년간 지속 / Action: 예산 재편성 검토")
    assert not _warns(rep)
    assert rep.findings[0].severity is Severity.PASS


def test_empty_text_passes():
    assert check_language("").findings[0].severity is Severity.PASS


# ── 필수 슬롯 ────────────────────────────────────────────────────────────────
def test_missing_slots_are_flagged():
    rep = check_finding_note({"driver": "", "outlook": None, "action": "  "})
    assert len([f for f in _warns(rep) if f.rule == "language_slot_missing"]) == 3


def test_placeholder_counts_as_missing():
    """UI 기본값·템플릿 잔재가 '채웠다'로 통과하면 규격이 무의미해진다."""
    rep = check_finding_note({"driver": "_(감사인 기재 필요)_", "outlook": "TBD",
                              "action": "-"})
    assert len([f for f in _warns(rep) if f.rule == "language_slot_missing"]) == 3


def test_filled_slots_pass_but_content_is_linted():
    rep = check_finding_note({"driver": "예상보다 높았음", "outlook": "일회성",
                              "action": "모니터"})
    assert not [f for f in _warns(rep) if f.rule == "language_slot_missing"]
    assert "circular" in _rules(rep), "슬롯을 채워도 내용은 검사해야"


# ── 통합 진입점 ──────────────────────────────────────────────────────────────
def test_lint_report_combines_body_and_notes():
    rep = lint_report(
        "본 건은 분식입니다.",
        notes={"gap": {"driver": "", "outlook": "지속", "action": "조사"}},
        where="조서")
    rules = {f.rule for f in _warns(rep)}
    assert "language_assertion" in rules and "language_slot_missing" in rules
    assert all("조서" in f.message or "finding:gap" in f.message for f in _warns(rep))


def test_lint_report_clean_is_all_pass():
    rep = lint_report(
        "WACC 가정의 근거 문서가 확인되지 않아 보완을 권고한다.",
        notes={"tv": {"driver": "터미널 성장률 2.5% 적용", "outlook": "지속",
                      "action": "민감도 재검토"}},
        where="조서")
    assert rep.ok and not _warns(rep)


# ── API 계약 ─────────────────────────────────────────────────────────────────
def test_api_report_lint():
    """프론트(감사인 서사 화면)·스킬 W9 가 소비하는 계약 고정."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        from fastapi.testclient import TestClient
        from backend.api.main import app
    except ImportError:
        return                                       # fastapi 미설치 환경은 skip
    c = TestClient(app)

    d = c.post("/api/report/lint", json={
        "text": "본 건은 분식입니다.",
        "notes": {"gap": {"driver": "", "outlook": "지속", "action": "조사"}},
        "where": "조서"}).json()
    assert not d["ok"] and d["count"] >= 2
    rules = {f["rule"] for f in d["findings"]}
    assert {"language_assertion", "language_slot_missing"} <= rules

    clean = c.post("/api/report/lint",
                   json={"text": "추가 확인이 필요한 것으로 판단된다."}).json()
    assert clean["ok"] and clean["count"] == 0


def test_spurious_precision_rounding_convention():
    """R16 허위정밀 — 주당가치를 원 단위까지 제시하면 모델 정밀도를 넘어선 확신을 준다.

    관행: DCF=천원(ROUND(...,-3)), 상대가치=백원(ROUND(...,-2)) 반올림.
    """
    from report.language_guard import lint_report

    def hit(text):
        return any(f.rule == "language_spurious_precision"
                   for f in lint_report(text).findings if f.severity.value != "pass")

    assert hit("본 평가의 주당가치는 144,283원으로 산정되었다.")
    assert hit("목표주가 159349원")
    assert hit("주당 8,413원")
    # 반올림 규약을 지킨 금액은 면제 — 오탐이 나면 규칙이 무시된다
    assert not hit("본 평가의 주당가치는 144,000원으로 산정되었다.")
    assert not hit("목표주가 159,300원")
    assert not hit("내재가치 118,400원")
