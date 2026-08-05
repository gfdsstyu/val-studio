"""주석 표 정합성 — 표 내부(A) + 연도 간(B).

픽스처는 파서가 실제로 받는 형태, 즉 **병합을 푼 직사각 격자**다
(`dart_document._table_grid` 산출 — colspan·rowspan 해소, 값 복제).
리노공업 2025 사업보고서 실측 구조를 그대로 옮겼다.

stdlib: `py -3.12 tests/test_note_check.py` 또는 pytest.
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from ingest.dart_document import _table_grid  # noqa: E402
from ingest.note_check import (  # noqa: E402
    check_rollforward, check_subtotals, compare_periods, parse_note_table, to_decimal,
)


def _pad(rows: list[list[str]]) -> list[list[str]]:
    """폭이 같은 직사각 격자로(빈칸 패딩) — 병합 없는 표의 축약 표기."""
    w = max(len(r) for r in rows)
    return [r + [""] * (w - len(r)) for r in rows]


# 재고자산 — 2단 헤더('당기말'이 3열 덮음) + '구분'이 ROWSPAN=2 → 해소하면 전부 7열
_INV = [
    ["(단위 : 원)"] * 7,
    ["구분", "당기말", "당기말", "당기말", "전기말", "전기말", "전기말"],
    ["구분", "취득원가", "평가충당금", "장부금액", "취득원가", "평가충당금", "장부금액"],
    ["상품", "495,266,211", "-", "495,266,211", "649,504,210", "-", "649,504,210"],
    ["제품", "3,535,242,257", "-", "3,535,242,257", "3,120,661,591", "-", "3,120,661,591"],
    ["합계", "4,030,508,468", "-", "4,030,508,468", "3,770,165,801", "-", "3,770,165,801"],
]

# 매출채권 기타채권 — 1단 헤더 + 소계 계층
_RECV = _pad([
    ["(단위 : 원)"] * 3,
    ["구분", "당기말", "전기말"],
    ["미수금", "5,617,122,480", "2,104,402,343"],
    ["미수수익", "1,413,922,978", "1,375,820,933"],
    ["유동자산 소계", "7,031,045,458", "3,480,223,276"],
    ["보증금", "71,640,326", "65,625,830"],
    ["비유동자산 소계", "71,640,326", "65,625,830"],
    ["합계", "7,102,685,784", "3,545,849,106"],
])


def _inv():
    return parse_note_table(_INV, note_no="9", title="재고자산")


def _recv():
    return parse_note_table(_RECV, note_no="7", title="매출채권")


# ── 숫자 ─────────────────────────────────────────────────────────────────────
def test_to_decimal_handles_korean_fs_notation():
    assert to_decimal("52,969,407,256") == Decimal("52969407256")
    assert to_decimal("(116,226,231)") == Decimal("-116226231")
    assert to_decimal("-") == Decimal(0)          # 관행: 해당 없음 = 0
    assert to_decimal("") is None                 # 값 없음은 0 과 구분한다
    assert to_decimal("주1") is None


# ── 병합 해소 격자 ───────────────────────────────────────────────────────────
def test_table_grid_resolves_rowspan_and_colspan():
    """ROWSPAN 된 라벨 열 때문에 하위 헤더 행은 앞칸이 비어 위치를 잃는다 — 격자가 복원한다."""
    html = (
        '<TABLE><TR><TD ROWSPAN="2">구분</TD><TD COLSPAN="2">당기말</TD></TR>'
        '<TR><TD>취득원가</TD><TD>장부금액</TD></TR>'
        '<TR><TD>상품</TD><TD>10</TD><TD>10</TD></TR></TABLE>'
    )
    g = _table_grid(html)
    assert g == [["구분", "당기말", "당기말"],
                 ["구분", "취득원가", "장부금액"],
                 ["상품", "10", "10"]]


def test_table_grid_handles_partial_second_header_row():
    """부분 2단 — '변동'만 하위 2칸으로 쪼개진다(이연법인세 주석 실측 형태)."""
    html = (
        '<TABLE><TR><TD ROWSPAN="2">계정</TD><TD ROWSPAN="2">기초</TD>'
        '<TD COLSPAN="2">변동</TD><TD ROWSPAN="2">기말</TD></TR>'
        '<TR><TD>당기손익</TD><TD>기타포괄손익</TD></TR>'
        '<TR><TD>미수수익</TD><TD>1</TD><TD>2</TD><TD>3</TD><TD>6</TD></TR></TABLE>'
    )
    g = _table_grid(html)
    assert g[0] == ["계정", "기초", "변동", "변동", "기말"]
    assert g[1] == ["계정", "기초", "당기손익", "기타포괄손익", "기말"]
    t = parse_note_table(g, note_no="26")
    assert [c.label for c in t.columns] == ["기초", "변동/당기손익", "변동/기타포괄손익", "기말"]
    assert not t.warnings


# ── 구조화 ───────────────────────────────────────────────────────────────────
def test_column_stack_from_multi_level_header():
    t = _inv()
    assert t is not None and not t.warnings
    assert [c.label for c in t.columns] == [
        "당기말/취득원가", "당기말/평가충당금", "당기말/장부금액",
        "전기말/취득원가", "전기말/평가충당금", "전기말/장부금액"]
    assert t.column_index("current") == [0, 1, 2]
    assert t.column_index("prior") == [3, 4, 5]


def test_single_row_header_and_unit():
    t = _recv()
    assert t.unit == "원"
    assert [c.period for c in t.columns] == ["current", "prior"]
    assert t.rows[0].label == "미수금"


def test_label_column_count_is_inferred_not_assumed():
    """라벨 열이 2개인 표가 실재한다('구분'+'종목명') — 1개로 가정하면 값이 밀린다."""
    g = _pad([
        ["구분", "종목명", "당기말", "전기말"],
        ["단기금융상품", "금융기관예치금", "365,042,000,000", "320,042,000,000"],
        ["회사채", "한국동서발전", "4,999,999,620", "-"],
        ["합계", "합계", "370,041,999,620", "320,042,000,000"],
    ])
    t = parse_note_table(g, note_no="8")
    assert [c.label for c in t.columns] == ["당기말", "전기말"]
    assert t.rows[0].label == "단기금융상품 금융기관예치금"
    assert t.rows[-1].label == "합계"          # 병합 복제는 한 번만 남는다
    assert not check_subtotals(t).findings


# ── A1. 소계 ─────────────────────────────────────────────────────────────────
def test_subtotal_passes_on_clean_tables():
    assert not check_subtotals(_inv()).findings
    assert not check_subtotals(_recv()).findings


def test_subtotal_detects_real_mismatch():
    rows = [r[:] for r in _RECV]
    rows[-1] = ["합계", "9,999,999,999", "3,545,849,106"]
    f = check_subtotals(parse_note_table(rows, note_no="7")).findings
    assert len(f) == 1 and f[0].rule == "note_subtotal" and "합계" in f[0].message


def test_numbered_hierarchy_does_not_double_count_children():
    """번호 항목 아래 내역을 함께 더하면 이중계상 — 이익잉여금 주석 실측 형태.

    회귀 대상: '1. 법정적립금' 과 그 내역 '이익준비금' 을 둘 다 더해 합계가
    4,329,874,817 원 어긋난다는 오탐이 났다(실제 공시는 정확히 맞는 표였다).
    """
    g = _pad([
        ["(단위 : 원)"] * 2,
        ["구분", "당기말"],
        ["1. 법정적립금(*1)", "3,810,592,500"],
        ["이익준비금", "3,810,592,500"],
        ["2. 임의적립금(*2)", "519,282,317"],
        ["기업합리화적립금", "519,282,317"],
        ["3. 종업원급여 재측정요소", "(6,548,534,724)"],
        ["4. 미처분이익잉여금", "722,568,133,183"],
        ["합계", "720,349,473,276"],
    ])
    assert not check_subtotals(parse_note_table(g, note_no="19")).findings


def test_flat_table_still_sums_every_row():
    """번호가 없는 평면 표에서는 계층 규칙이 발동하면 안 된다."""
    ok = _pad([["구분", "당기말"], ["상품", "10"], ["제품", "20"], ["합계", "30"]])
    assert not check_subtotals(parse_note_table(ok, note_no="9")).findings
    bad = _pad([["구분", "당기말"], ["상품", "10"], ["제품", "20"], ["합계", "99"]])
    assert check_subtotals(parse_note_table(bad, note_no="9")).findings


def test_block_divider_row_is_not_treated_as_header():
    """값 없는 한 칸짜리 행('유동자산 :')을 헤더로 먹으면 전 열 라벨이 그 문자열이 된다."""
    g = [
        ["(단위 : 원)"] * 3,
        ["구분", "당기말", "전기말"],
        ["유동자산 :", "유동자산 :", "유동자산 :"],
        ["금융기관예치금", "100", "90"],
        ["합계", "100", "90"],
    ]
    t = parse_note_table(g, note_no="8")
    assert [c.label for c in t.columns] == ["당기말", "전기말"]
    assert t.column_index("prior") == [1]
    assert not check_subtotals(t).findings


def test_block_header_resets_accumulation():
    """블록이 나뉘면 누적도 리셋 — 자산 개별이 부채 소계에 딸려가면 자릿수가 다르다."""
    g = _pad([
        ["구분", "당기말"],
        ["금융자산:", ""],
        ["현금", "100"],
        ["매출채권", "200"],
        ["금융자산 소계", "300"],
        ["금융부채:", ""],
        ["매입채무", "50"],
        ["금융부채 소계", "50"],
    ])
    assert not check_subtotals(parse_note_table(g, note_no="5")).findings


# ── A2. 롤포워드 ─────────────────────────────────────────────────────────────
_ROLL = _pad([
    ["(단위 : 원)"] * 6,
    ["구분", "기초", "취득", "처분", "감가상각", "기말"],
    ["건물", "30,541,604,151", "-", "-", "(946,350,019)", "29,595,254,132"],
])


def test_rollforward_checks_opening_plus_delta():
    t = parse_note_table(_ROLL, note_no="11", title="유형자산")
    assert t.is_rollforward
    assert not check_rollforward(t).findings


def test_rollforward_detects_break():
    rows = [r[:] for r in _ROLL]
    rows[2] = ["건물", "30,541,604,151", "-", "-", "(946,350,019)", "29,000,000,000"]
    f = check_rollforward(parse_note_table(rows, note_no="11")).findings
    assert len(f) == 1 and f[0].rule == "note_rollforward"


def test_non_rollforward_table_is_untouched():
    assert not check_rollforward(_recv()).findings


# ── B. 연도 간 ───────────────────────────────────────────────────────────────
def _pair(cur_prior: str, prev_current: str):
    """당해 보고서의 전기 열 / 직전 보고서의 당기 열만 바꿔 만든 두 표."""
    cur = _pad([["구분", "당기말", "전기말"], ["미수금", "100", cur_prior]])
    prev = _pad([["구분", "당기말", "전기말"], ["미수금", prev_current, "50"]])
    return (parse_note_table(cur, note_no="7", title="매출채권"),
            parse_note_table(prev, note_no="7", title="매출채권"))


def test_period_match_is_silent():
    diffs, rep = compare_periods(*_pair("80", "80"))
    assert not rep.findings and all(d.kind == "matched" for d in diffs)


def test_period_restatement_is_reported():
    diffs, rep = compare_periods(*_pair("80", "90"))
    assert any(d.kind == "restated" for d in diffs)
    assert any(f.rule == "note_restated" for f in rep.findings)


def test_sign_convention_is_not_called_restatement():
    """크기가 같고 부호만 반대면 표시규약이다 — 재작성으로 부르면 오보."""
    diffs, rep = compare_periods(*_pair("(80)", "80"))
    assert any(d.kind == "sign_convention" for d in diffs)
    assert not any(f.rule == "note_restated" for f in rep.findings)


def test_renamed_row_is_unmatched_not_mismatch():
    """주석엔 계정코드가 없다 — 이름이 바뀐 것을 금액 오류로 보고하면 경고가 신뢰를 잃는다."""
    cur = parse_note_table(_pad([["구분", "당기말", "전기말"], ["미수금", "100", "80"]]), note_no="7")
    prev = parse_note_table(_pad([["구분", "당기말", "전기말"], ["미수채권", "80", "50"]]), note_no="7")
    diffs, rep = compare_periods(cur, prev)
    assert [d.kind for d in diffs] == ["unmatched"]
    assert any(f.rule == "note_unmatched" for f in rep.findings)
    assert not any(f.rule == "note_restated" for f in rep.findings)


def test_reclassification_detected_when_total_holds():
    """개별은 어긋나는데 합계는 맞다 = 금액이 아니라 구성이 바뀐 것."""
    cur = parse_note_table(_pad([["구분", "당기말", "전기말"],
                                 ["가", "10", "30"], ["나", "10", "20"], ["합계", "20", "50"]]),
                           note_no="7")
    prev = parse_note_table(_pad([["구분", "당기말", "전기말"],
                                  ["가", "20", "1"], ["나", "30", "1"], ["합계", "50", "2"]]),
                            note_no="7")
    _, rep = compare_periods(cur, prev)
    assert any(f.rule == "note_reclassified" for f in rep.findings)
    assert not any(f.rule == "note_restated" for f in rep.findings)


def test_missing_period_axis_skips_instead_of_guessing():
    cur = parse_note_table(_pad([["구분", "취득원가"], ["가", "10"]]), note_no="7")
    prev = parse_note_table(_pad([["구분", "취득원가"], ["가", "10"]]), note_no="7")
    diffs, rep = compare_periods(cur, prev)
    assert diffs == [] and any(f.rule == "note_period_axis" for f in rep.findings)


# ── A3. 본표 ↔ 주석 대사 ────────────────────────────────────────────────────
class _Row:
    def __init__(self, label, refs, values):
        self.label, self.note_refs, self.values = label, refs, values


class _St:
    def __init__(self, rows):
        self.sj_div, self.title, self.periods, self.rows = "BS", "재무상태표", ["당기말"], rows


class _Note:
    def __init__(self, number, title, grids):
        self.number, self.title, self.grids = number, title, grids


class _Doc:
    def __init__(self, statements, notes):
        self.statements, self.notes = statements, notes


def _doc_for_tieout(bs_value):
    """본표 재고자산(백만원) + 재고자산 주석(원 단위 합계 15,514,548,353)."""
    grid = _pad([
        ["(단위 : 원)"] * 2,
        ["구분", "당기말"],
        ["상품", "495,266,211"],
        ["합계", "15,514,548,353"],
    ])
    return _Doc([_St([_Row("재고자산", (9,), {"당기말": bs_value})])],
                [_Note("9", "재고자산", [grid])])


def test_statement_tieout_matches_across_units():
    """주석은 원, 본표는 백만원 — 단위를 맞춰야 대사가 성립한다."""
    from ingest.note_check import check_notes_vs_statements
    rep = check_notes_vs_statements(_doc_for_tieout(15514.548353))
    hits = [f for f in rep.findings if f.rule == "note_tieout"]
    assert len(hits) == 1 and "주석9" in hits[0].message
    assert not any(f.rule == "note_tieout_unmatched" for f in rep.findings)


def test_statement_tieout_unmatched_is_aggregated_not_per_row():
    """대응을 못 찾은 것은 불일치가 아니다 — 개별 경고 대신 집계 1건.

    회귀 대상: 주석번호가 다대다라(매출채권 → 주석 4·5·7·30·32) 개별 WARN 을 내면
    실측에서 오탐 14건이 쏟아졌다.
    """
    from ingest.note_check import check_notes_vs_statements
    rep = check_notes_vs_statements(_doc_for_tieout(99999.0))
    assert not any(f.rule == "note_tieout" for f in rep.findings)
    agg = [f for f in rep.findings if f.rule == "note_tieout_unmatched"]
    assert len(agg) == 1 and "재고자산" in agg[0].message


def test_statement_tieout_accepts_non_total_row():
    """본표 값이 '합계'가 아닌 행일 수 있다 — 매출채권은 '순장부금액'이 본표 값이다."""
    from ingest.note_check import check_notes_vs_statements
    grid = _pad([
        ["(단위 : 원)"] * 2,
        ["구분", "당기말"],
        ["총장부금액", "52,969,407,256"],
        ["손실충당금", "(116,226,231)"],
        ["순장부금액", "52,853,181,025"],
    ])
    doc = _Doc([_St([_Row("매출채권", (7,), {"당기말": 52853.181025})])],
               [_Note("7", "매출채권", [grid])])
    rep = check_notes_vs_statements(doc)
    assert any(f.rule == "note_tieout" and "순장부금액" in f.message for f in rep.findings)


# ── 문서 단위 연도 간 대조 ───────────────────────────────────────────────────
def _yr_grid(cur: str, prior: str):
    return _pad([["구분", "당기말", "전기말"], ["미수금", cur, prior]])


def test_compare_documents_pairs_notes_by_title_not_number():
    """주석 번호는 연도마다 밀린다 — 제목으로 짝지어야 한다."""
    from ingest.note_check import compare_documents
    cur = _Doc([], [_Note("8", "매출채권 및 기타채권", [_yr_grid("100", "80")])])
    prev = _Doc([], [_Note("7", "매출채권 및 기타채권", [_yr_grid("80", "50")])])
    rep, summary = compare_documents(cur, prev)
    assert summary["paired"] == 1 and summary["compared_tables"] == 1
    assert summary["restated"] == 0 and not summary["unpaired"]
    assert not rep.findings


def test_compare_documents_reports_restatement():
    from ingest.note_check import compare_documents
    cur = _Doc([], [_Note("7", "매출채권", [_yr_grid("100", "80")])])
    prev = _Doc([], [_Note("7", "매출채권", [_yr_grid("90", "50")])])
    rep, summary = compare_documents(cur, prev)
    assert summary["restated"] == 1
    assert any(f.rule == "note_restated" for f in rep.findings)


def test_compare_documents_unpaired_note_is_not_called_missing():
    from ingest.note_check import compare_documents
    cur = _Doc([], [_Note("7", "새로 생긴 주석", [_yr_grid("1", "1")])])
    prev = _Doc([], [_Note("7", "매출채권", [_yr_grid("1", "1")])])
    rep, summary = compare_documents(cur, prev)
    assert summary["unpaired"] == 1 and summary["paired"] == 0
    f = next(f for f in rep.findings if f.rule == "note_unpaired")
    assert "사라진 것과 다릅니다" in f.message


def test_compare_documents_notes_table_count_change():
    """표가 늘거나 줄면 겹치는 만큼만 본다 — 억지로 맞추면 엉뚱한 표끼리 비교한다."""
    from ingest.note_check import compare_documents
    cur = _Doc([], [_Note("7", "매출채권", [_yr_grid("1", "1"), _yr_grid("2", "2")])])
    prev = _Doc([], [_Note("7", "매출채권", [_yr_grid("1", "1")])])
    rep, summary = compare_documents(cur, prev)
    assert summary["compared_tables"] == 1
    assert any(f.rule == "note_table_count" for f in rep.findings)


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
