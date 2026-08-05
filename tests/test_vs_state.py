"""`_VS_STATE`·`Claude Log` 상태 시트 — 4버킷 분류와 증적 이관.

병용(Claude for Excel 스킬 + 로컬웹) 왕복의 전제 회귀:
스킬이 워크북에 남긴 상태·로그 시트가 **구조변경으로 오분류되어 자동반영을
영구 차단하면 안 된다**(감사 2026-07-19 마찰 1호). 상태 변경은 ④ 버킷으로
빠지고 safe 판정에서 제외되며, 내용은 감사증적으로 이관된다.
"""
from __future__ import annotations

from excel.vs_state import STATE_SCHEMA_VERSION, parse_vs_state
from excel.workbook_diff import diff_workbooks, is_known_state_sheet, is_state_sheet
from excel.xlsx_writer import Workbook
from excel.xlsx_reader import read_workbook
from excel.apply_policy import build_apply_plan


def _read(wb: Workbook, tmp_path, name: str) -> dict:
    p = tmp_path / name
    wb.save(str(p))
    return read_workbook(str(p))


def _model_wb(wacc: float = 0.113) -> Workbook:
    """최소 모델 워크북(입력 1셀 + 수식 1셀)."""
    wb = Workbook()
    s = wb.add_sheet("DCF")
    s.num("C3", wacc)
    s.formula("C4", "C3*2", wacc * 2)
    return wb


def _with_state(wb: Workbook, *, stage: str = "W4", per_share: float = 8413.38) -> Workbook:
    """스킬 `_VS_STATE` 시트 부착(scaffold.py 레이아웃 미러)."""
    s = wb.add_sheet("_VS_STATE")
    for i, (k, v) in enumerate([("skill_version", "1.0"), ("mode", "B"),
                                ("stage", stage), ("last_gate_passed", "W3:reclass")], start=1):
        s.text(f"A{i}", k)
        s.text(f"B{i}", str(v))
    s.text("A5", "engine_tieout_per_share")
    s.num("B5", per_share)
    s.text("A7", "── 가정 대장(provenance) ──")
    for col, label in zip("ABCDE", ["가정명", "값", "출처유형", "근거", "승인상태"]):
        s.text(f"{col}8", label)
    # 승인된 가정 / 미승인 AI 제안 / 근거 공란 — 게이트 3케이스
    s.text("A9", "영구성장률"); s.num("B9", 0.01)
    s.text("C9", "research"); s.text("D9", "한은 장기전망"); s.text("E9", "승인")
    s.text("A10", "COGS율"); s.num("B10", 0.29)
    s.text("C10", "suggested"); s.text("D10", "peer 중위값"); s.text("E10", "")
    return wb


def test_is_state_sheet_normalizes():
    assert is_state_sheet("_VS_STATE") and is_state_sheet("Claude Log")
    assert is_state_sheet("claude log") and is_state_sheet("_vs_state")
    assert not is_state_sheet("DCF") and not is_state_sheet("Research")


def test_state_sheet_addition_is_not_structural(tmp_path):
    """웹 export ↔ 스킬 워크북: `_VS_STATE` 존재만으로 blocked 되면 안 된다."""
    plain = _read(_model_wb(), tmp_path, "web.xlsx")
    skill = _read(_with_state(_model_wb()), tmp_path, "skill.xlsx")

    d = diff_workbooks(plain, skill)
    assert d.safe, "상태 시트 추가는 구조변경이 아니다"
    assert not d.sheets_added and not d.structure_changes
    assert d.state_changes and all(c.sheet == "_VS_STATE" for c in d.state_changes)

    counts = build_apply_plan(d).to_dict()["counts"]
    assert counts["blocked"] == 0 and counts["state"] > 0


def test_state_cell_edits_do_not_break_safe(tmp_path):
    """스킬이 단계·tie-out 을 갱신해도 입력 자동반영은 살아있어야 한다."""
    before = _read(_with_state(_model_wb(), stage="W4"), tmp_path, "b.xlsx")
    # 평가인이 엑셀에서 WACC 편집(0.113→0.12) + 스킬이 단계·tie-out 갱신
    after = _read(_with_state(_model_wb(0.12), stage="W6", per_share=7863.09),
                  tmp_path, "a.xlsx")

    d = diff_workbooks(before, after)
    assert d.safe
    assert [c.ref for c in d.input_changes] == ["C3"]
    assert {c.ref for c in d.state_changes} == {"B3", "B5"}   # stage·tie-out 갱신


def test_parse_vs_state_extracts_ledger_and_warns(tmp_path):
    wb = _read(_with_state(_model_wb()), tmp_path, "s.xlsx")
    st = parse_vs_state(wb)

    assert st.present
    assert st.keys["stage"] == "W4"
    assert st.keys["skill_version"] == "1.0"
    assert st.to_dict()["engine_tieout_per_share"] == 8413.38
    assert [a["name"] for a in st.assumptions] == ["영구성장률", "COGS율"]
    # 미승인 suggested 는 표면화(SKILL.md 1.6 게이트가 웹으로 이관될 때도 유지)
    assert any("COGS율" in w and "미승인" in w for w in st.warnings)
    assert not any("영구성장률" in w for w in st.warnings)


def test_parse_claude_log(tmp_path):
    wb = _model_wb()
    s = wb.add_sheet("Claude Log")
    s.text("A1", "2026-07-19 14:02"); s.text("B1", "W4 매출 드라이버 수식 기입 (Fcst_Rev!C5:G5)")
    s.text("A2", "2026-07-19 14:11"); s.text("B2", "W5 peer 4-step 퍼널 실행 — 6사 확정")
    st = parse_vs_state(_read(wb, tmp_path, "log.xlsx"))

    assert len(st.log) == 2
    assert "peer 4-step" in st.log[1]


def test_no_state_sheet_is_absent(tmp_path):
    """웹 단독 워크북 — 상태 없음이 정상 경로(에러 아님)."""
    st = parse_vs_state(_read(_model_wb(), tmp_path, "plain.xlsx"))
    assert not st.present and st.to_dict()["stage"] is None


# ── 술어 판정 + 미등록 원장 (P3-F) ───────────────────────────────────────────
def test_state_predicate_covers_unregistered_vs_ledgers():
    """열거가 아니라 술어 — 새 원장이 생겨도 왕복이 죽지 않아야 한다."""
    # `_VS_NOTES` = 아직 파서가 없는 가상의 원장(등재는 파서와 함께 온다)
    assert is_state_sheet("_VS_NOTES") and is_state_sheet("_vs_anything")
    assert not is_known_state_sheet("_VS_NOTES")
    assert is_known_state_sheet("_VS_STATE") and is_known_state_sheet("_VS_FACTS")
    # 정규화 후 startswith 로 짰다면 오탐될 업무 시트들
    assert not is_state_sheet("VS 분석") and not is_state_sheet("DCF")


def test_unregistered_ledger_warns_but_never_blocks(tmp_path):
    """미등록 `_VS_*` 는 차단하지 않되 '해석 못 함'을 표면화한다.

    차단하면 마찰 1호(자동반영 영구 차단)가 재발하고, 침묵하면 "읽었는데 없었다"와
    "읽을 줄 몰랐다"가 구분되지 않는다.
    """
    before = _read(_model_wb(), tmp_path, "b.xlsx")
    wb = _model_wb()
    s = wb.add_sheet("_VS_NOTES")
    s.text("A1", "seq"); s.text("B1", "key")
    after = _read(wb, tmp_path, "a.xlsx")

    d = diff_workbooks(before, after)
    assert d.safe and not d.sheets_added and not d.structure_changes
    assert any("미등록 상태 시트" in w for w in d.warnings)

    plan = build_apply_plan(d).to_dict()
    assert plan["counts"]["blocked"] == 0
    assert any("_VS_NOTES" in w for w in plan["warnings"])


def test_unknown_ledger_is_not_parsed_as_state(tmp_path):
    """파서는 해석 가능한 원장만 읽는다 — 모르는 시트를 _VS_STATE 로 착각하면 안 된다."""
    wb = _model_wb()
    s = wb.add_sheet("_VS_NOTES")
    s.text("A1", "seq"); s.text("B1", "17")
    st = parse_vs_state(_read(wb, tmp_path, "f.xlsx"))
    assert not st.present and "seq" not in st.keys


# ── 열이름 기반 파싱 (P2-D) ──────────────────────────────────────────────────
def _with_ledger(wb: Workbook, headers: list[str], row: list[object]) -> Workbook:
    """임의 열 구성의 가정 대장을 가진 `_VS_STATE`."""
    s = wb.add_sheet("_VS_STATE")
    s.text("A1", "stage"); s.text("B1", "W5")
    s.text("A3", "── 가정 대장(provenance) ──")
    cols = "ABCDEFGH"
    for c, label in zip(cols, headers):
        s.text(f"{c}4", label)
    for c, v in zip(cols, row):
        if isinstance(v, (int, float)):
            s.num(f"{c}5", v)
        else:
            s.text(f"{c}5", str(v))
    return wb


def test_ledger_parsed_by_header_not_position(tmp_path):
    """열을 중간에 끼워도 필드가 밀리지 않는다 — 위치 결합의 조용한 오독 회귀."""
    wb = _with_ledger(
        _model_wb(),
        ["가정명", "값", "비고", "출처유형", "근거", "승인상태"],   # '비고'가 C에 끼어듦
        ["영구성장률", 0.01, "메모", "research", "한은 장기전망", "승인"])
    st = parse_vs_state(_read(wb, tmp_path, "h.xlsx"))

    a = st.assumptions[0]
    assert a["source_type"] == "research"      # 위치로 읽었다면 '메모'가 들어온다
    assert a["basis"] == "한은 장기전망" and a["approval"] == "승인"
    assert a["x_비고"] == "메모"                # 모르는 열은 버리지 않고 보존
    assert not any("위치(A~E)" in w for w in st.warnings)


def test_ledger_falls_back_to_position_with_warning(tmp_path):
    """열이름 행이 깨진 구버전 워크북 — 폴백하되 침묵하지 않는다."""
    wb = _model_wb()
    s = wb.add_sheet("_VS_STATE")
    s.text("A1", "stage"); s.text("B1", "W5")
    s.text("A3", "── 가정 대장(provenance) ──")
    # 열이름 행(4행) 없음 — 곧바로 데이터
    s.text("A5", "COGS율"); s.num("B5", 0.29)
    s.text("C5", "suggested"); s.text("D5", "peer 중위값"); s.text("E5", "")
    st = parse_vs_state(_read(wb, tmp_path, "old.xlsx"))

    assert [a["name"] for a in st.assumptions] == ["COGS율"]
    assert any("위치(A~E)" in w for w in st.warnings)


def test_higher_schema_version_warns_but_still_parses(tmp_path):
    """하위 리더가 상위 워크북을 만나는 건 정상 — 죽지 말고 알리기만."""
    wb = _with_ledger(_model_wb(), ["가정명", "값"], ["PGR", 0.01])
    wb.sheets[-1].text("A2", "state_schema")
    wb.sheets[-1].num("B2", STATE_SCHEMA_VERSION + 1)
    st = parse_vs_state(_read(wb, tmp_path, "v2.xlsx"))

    assert [a["name"] for a in st.assumptions] == ["PGR"]     # 계속 읽는다
    assert any("스키마 v" in w for w in st.warnings)


def test_current_schema_version_is_silent(tmp_path):
    wb = _with_ledger(_model_wb(), ["가정명", "값"], ["PGR", 0.01])
    wb.sheets[-1].text("A2", "state_schema")
    wb.sheets[-1].num("B2", STATE_SCHEMA_VERSION)
    st = parse_vs_state(_read(wb, tmp_path, "v1.xlsx"))
    assert not any("스키마 v" in w for w in st.warnings)
