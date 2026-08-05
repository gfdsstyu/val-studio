"""DART 공시서류 원문(document.xml) 파서 — 네트워크 없이 canned XML 로 전량 검증.

픽스처는 삼성전자 20250311001085 감사보고서의 **실측 구조를 축약**해 재현한다
(COLSPAN 헤더 · 들여쓰기 열 오프셋 · 주석 참조 열 · SECTION-2 주석 흐름).
stdlib: `python tests/test_dart_document.py`
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ingest.dart_document import (  # noqa: E402
    DocumentError, check_document, classify_statement, decode_document,
    parse_document, parse_document_zip, to_dict, to_multiyear,
)
from ingest.validators import Severity  # noqa: E402

# ── 픽스처 ────────────────────────────────────────────────────────────────────
_HEADER = (
    '<TR><TH>과                        목</TH><TH>주석</TH>'
    '<TH COLSPAN="2">제 56 (당) 기</TH><TH COLSPAN="2">제 55 (전) 기</TH></TR>'
)


def _row(label, note, cur, prior, *, total=False):
    """소계면 뒤 서브칼럼, 개별계정이면 앞 서브칼럼에 금액을 쓴다(실측 규약)."""
    if total:
        cells = f"<TD>{label}</TD><TD>{note}</TD><TD></TD><TD>{cur}</TD><TD></TD><TD>{prior}</TD>"
    else:
        cells = f"<TD>{label}</TD><TD>{note}</TD><TD>{cur}</TD><TD></TD><TD>{prior}</TD><TD></TD>"
    return f"<TR>{cells}</TR>"


#: 표제 표 — 표제·기간·단위가 본표 **직전 표**에 모여 있다.
def _lead(title):
    return ("<TABLE><TBODY>"
            f"<TR><TD>{title}</TD></TR>"
            "<TR><TD>제 56 기 : 2024년 12월 31일 현재</TD></TR>"
            "<TR><TD>제 55 기 : 2023년 12월 31일 현재</TD></TR>"
            "<TR><TD>테스트주식회사</TD><TD>(단위 : 백만원)</TD></TR>"
            "</TBODY></TABLE>")


_BS = _lead("재 무 상 태 표") + "<TABLE><TBODY>" + _HEADER + "".join([
    _row("자 산", "", "", ""),
    _row("Ⅰ. 유 동 자 산", "", "5,000", "3,500", total=True),
    _row("1. 현금및현금성자산", "4, 28", "3,000", "2,000"),
    _row("2. 매출채권", "4, 5, 7", "2,000", "1,500"),
    _row("Ⅱ. 비 유 동 자 산", "", "4,000", "3,500", total=True),
    _row("1. 유형자산", "10", "4,000", "3,500"),
    _row("자  산  총  계", "", "9,000", "7,000", total=True),
    _row("부 채", "", "", ""),
    _row("Ⅰ. 유 동 부 채", "", "1,500", "1,500", total=True),
    _row("1. 매입채무", "4", "1,000", "800"),
    _row("2. 단기차입금", "4, 17", "500", "700"),
    _row("Ⅱ. 비유동부채", "", "1,000", "500", total=True),
    _row("1. 장기차입금", "17", "1,000", "500"),
    _row("부  채  총  계", "", "2,500", "2,000", total=True),
    _row("자 본", "", "", ""),
    _row("Ⅰ. 자 본 금", "", "1,000", "1,000", total=True),
    _row("Ⅱ. 이익잉여금", "", "5,500", "4,000", total=True),
    _row("자  본  총  계", "", "6,500", "5,000", total=True),
    _row("부채와자본총계", "", "9,000", "7,000", total=True),
]) + "</TBODY></TABLE>"

_IS = _lead("손 익 계 산 서") + "<TABLE><TBODY>" + _HEADER + "".join([
    _row("Ⅰ. 매 출 액", "20", "10,000", "8,000", total=True),
    _row("Ⅱ. 매 출 원 가", "21", "6,000", "5,000", total=True),
    _row("Ⅲ. 매출총이익", "", "4,000", "3,000", total=True),
    _row("Ⅳ. 판매비와관리비", "22", "2,500", "2,000", total=True),
    _row("Ⅴ. 영 업 이 익", "", "1,500", "1,000", total=True),
    _row("Ⅵ. 당 기 순 이 익", "", "1,500", "1,000", total=True),
]) + "</TBODY></TABLE>"

_CF = _lead("현 금 흐 름 표") + "<TABLE><TBODY>" + _HEADER + "".join([
    _row("Ⅰ. 영업활동 현금흐름", "", "2,000", "1,800", total=True),
    _row("Ⅱ. 투자활동 현금흐름", "", "-700", "-600", total=True),
    _row("Ⅲ. 재무활동 현금흐름", "", "-300", "-200", total=True),
    _row("Ⅳ. 외화환산으로 인한 현금의 변동", "", "0", "0", total=True),
    _row("Ⅴ. 현금및현금성자산의 순증가", "", "1,000", "1,000", total=True),
    _row("Ⅵ. 기초 현금및현금성자산", "", "2,000", "1,000", total=True),
    _row("Ⅶ. 기말 현금및현금성자산", "", "3,000", "2,000", total=True),
]) + "</TBODY></TABLE>"

_NOTES = (
    '<SECTION-2><TITLE>주석</TITLE>'
    '<P>테스트주식회사</P>'
    '<P>1. 일반적 사항:</P>'
    '<P>회사는 2000년에 설립되었습니다.</P>'
    '<P>2. 중요한 회계처리방침:</P>'
    '<P>2.1 재무제표 작성기준</P>'
    '<P>한국채택국제회계기준에 따라 작성되었습니다.</P>'
    '<P>4. 범주별 금융상품:</P>'
    '<TABLE><TBODY><TR><TH>구분</TH><TH>당기말</TH></TR>'
    '<TR><TD>현금및현금성자산</TD><TD>3,000</TD></TR></TBODY></TABLE>'
    '</SECTION-2>'
)

_DOC = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<DOCUMENT><DOCUMENT-NAME ACODE="00760">감사보고서</DOCUMENT-NAME>'
    '<COMPANY-NAME AREGCIK="00126380">테스트주식회사</COMPANY-NAME>'
    '<BODY><SECTION-1><TITLE>(첨부)재 무 제 표</TITLE>'
    + _BS + _IS + _CF + _NOTES +
    '</SECTION-1></BODY></DOCUMENT>'
)


def _zip_bytes(*docs):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i, d in enumerate(docs):
            z.writestr(f"20250311001085_0076{i}.xml", d.encode("utf-8"))
    return buf.getvalue()


def _doc():
    return parse_document(_DOC, filename="test.xml")


# ── 디코딩 ────────────────────────────────────────────────────────────────────
def test_decode_prefers_declared_utf8():
    """FORMULA-VERSION 6.0 문서는 UTF-8 — cp949 를 먼저 쓰면 조용한 모지바케가 된다."""
    raw = _DOC.encode("utf-8")
    assert "감사보고서" in decode_document(raw)


def test_decode_falls_back_to_cp949():
    raw = ('<?xml version="1.0"?><DOCUMENT><DOCUMENT-NAME ACODE="00760">'
           '감사보고서</DOCUMENT-NAME></DOCUMENT>').encode("cp949")
    assert "감사보고서" in decode_document(raw)


# ── 표 파싱 ───────────────────────────────────────────────────────────────────
def test_metadata_and_statements_detected():
    d = _doc()
    assert d.acode == "00760" and d.kind == "감사보고서"
    assert d.company == "테스트주식회사"
    assert [s.sj_div for s in d.statements] == ["BS", "IS", "CF"]
    assert [s.title for s in d.statements] == ["재무상태표", "손익계산서", "현금흐름표"]
    assert all(s.unit == "백만원" for s in d.statements)
    assert all(s.periods == ["제 56 (당) 기", "제 55 (전) 기"] for s in d.statements)


def test_indent_column_offset_is_handled():
    """**핵심 함정** — 소계는 뒤 서브칼럼, 개별계정은 앞 서브칼럼에 금액이 있다.

    'N번째 칸 = 당기'로 읽으면 소계 금액이 통째로 어긋난다.
    """
    bs = _doc().statements[0]
    by = {r.label: r for r in bs.rows}
    assert float(by["Ⅰ. 유 동 자 산"].values["제 56 (당) 기"]) == 5000      # 소계(뒤칸)
    assert float(by["1. 현금및현금성자산"].values["제 56 (당) 기"]) == 3000   # 개별(앞칸)
    assert float(by["자 산 총 계"].values["제 55 (전) 기"]) == 7000


def test_note_refs_and_depth():
    bs = _doc().statements[0]
    by = {r.label: r for r in bs.rows}
    assert by["1. 현금및현금성자산"].note_refs == (4, 28)
    assert by["2. 매출채권"].note_refs == (4, 5, 7)
    assert by["자 산"].depth == 0                    # 제목행
    assert by["Ⅰ. 유 동 자 산"].depth == 1           # 로마숫자 대분류
    assert by["1. 현금및현금성자산"].depth == 2       # 아라비아 소분류
    assert by["Ⅰ. 유 동 자 산"].is_total


def test_note_map_links_accounts_to_notes():
    """`fnlttSinglAcntAll` 로는 절대 못 얻는 연결고리 — 원문 파싱의 존재 이유."""
    nm = _doc().note_map
    assert nm["현금및현금성자산"] == (4, 28)
    assert nm["매출채권"] == (4, 5, 7)
    assert "자산" not in nm                          # 참조 없는 제목행은 안 들어간다


def test_blank_cell_is_none_not_zero():
    by = {r.label: r for r in _doc().statements[0].rows}
    assert by["자 산"].values["제 56 (당) 기"] is None


# ── 주석 ─────────────────────────────────────────────────────────────────────
def test_notes_parsed_with_tables():
    notes = _doc().notes
    assert [n.number for n in notes] == ["1", "2", "4"]
    assert notes[0].title == "일반적 사항"
    # 하위 번호(2.1)는 새 주석이 아니라 문단 — 회사마다 체계가 달라 계층화하지 않는다.
    assert "2.1 재무제표 작성기준" in notes[1].paragraphs
    assert notes[2].tables and notes[2].tables[0][0] == ["구분", "당기말"]


# ── 제표 판정 ────────────────────────────────────────────────────────────────
def test_classify_uses_content_not_title():
    """표제는 비거나 흔들린다 — 판정은 내용으로."""
    d = _doc()
    for st in d.statements:
        st.title = ""
    assert [classify_statement(s) for s in d.statements] == ["BS", "IS", "CF"]


# ── 연도 축 ──────────────────────────────────────────────────────────────────
def test_period_years_from_lead_and_order_preserved():
    """당기 금액이 당기 연도에 붙어야 한다.

    공시는 당기→전기 순으로 적고 우리 축은 오름차순이라, 정렬된 축에 그냥 zip 하면
    당기 금액이 전기로 간다. **정합성 항등식은 열이 통째로 바뀌어도 성립하므로 이
    오류를 못 잡는다** — 그래서 별도 회귀가 필요하다.
    """
    fs = to_multiyear(_doc())
    assert fs.years == [2023, 2024]
    cash = next(a for a in fs.statement("BS") if a.account_nm == "현금및현금성자산")
    assert float(cash.value(2024)) == 3000      # 당기
    assert float(cash.value(2023)) == 2000      # 전기


def test_relative_axis_when_years_absent():
    doc = parse_document(_DOC.replace("2024년 12월 31일", "당기말")
                             .replace("2023년 12월 31일", "전기말"))
    fs = to_multiyear(doc)
    assert fs.years == [-1, 0]                  # 상대 기수 폴백
    assert any("연도 미확정" in n for n in fs.notes)


# ── 정합성(같은 SSOT 재사용) ─────────────────────────────────────────────────
def test_integrity_checks_pass_on_consistent_document():
    findings, summary = check_document(_doc())
    bad = [f for f in findings if f.severity is not Severity.PASS]
    assert not bad, [f.message for f in bad]
    assert summary["ok"] and summary["fail"] == 0 and summary["checked"] > 0


def test_integrity_catches_column_offset_regression():
    """열 오프셋을 잘못 읽으면 대차가 즉시 깨진다 — 항등식이 파서의 회귀 그물."""
    broken = _DOC.replace(
        '<TD>자  산  총  계</TD><TD></TD><TD></TD><TD>9,000</TD>',
        '<TD>자  산  총  계</TD><TD></TD><TD></TD><TD>9,900</TD>')
    findings, summary = check_document(parse_document(broken))
    fails = [f for f in findings if f.severity is Severity.FAIL]
    assert fails and any(f.rule == "bs_balance" for f in fails)
    assert not summary["ok"]


def test_fx_anchor_matches_document_wording():
    """원문은 '외화환산으로 인한 현금의 변동' — 앵커가 좁으면 CF 합계가 통째로 WARN."""
    findings, _ = check_document(_doc())
    cf = [f for f in findings if f.rule == "cf_sections"]
    assert cf and all(f.severity is Severity.PASS for f in cf)


# ── zip 진입점 ───────────────────────────────────────────────────────────────
def test_parse_zip_filters_documents_without_statements():
    empty = ('<?xml version="1.0" encoding="utf-8"?><DOCUMENT>'
             '<DOCUMENT-NAME ACODE="11011">사업보고서</DOCUMENT-NAME>'
             '<BODY><P>본문</P></BODY></DOCUMENT>')
    docs = parse_document_zip(_zip_bytes(_DOC, empty))
    assert [d.acode for d in docs] == ["00760"]
    both = parse_document_zip(_zip_bytes(_DOC, empty), only_financial=False)
    assert len(both) == 2


def test_note_column_label_variant_is_accepted():
    """헤더 라벨 표기는 회사마다 다르다 — 삼성 '주석' / 리노공업 '주석번호'.

    회귀 대상: `^주\\s*석$` 로 못 박아 뒀더니 리노공업 감사보고서의 본표가 전부 탈락하고,
    statements=0 이 되면서 only_financial 필터가 문서를 통째로 버려 **정상 파싱된 주석
    26만자까지 함께 증발**했다. 헤더 라벨 하나에 회사 전체가 걸린다.
    """
    doc = parse_document(_DOC.replace("<TH>주석</TH>", "<TH>주석번호</TH>"),
                         filename="rino.xml")
    assert doc.statements, "'주석번호' 표기도 본표로 인식해야 한다"
    assert doc.statements[0].rows


def test_near_miss_header_is_surfaced_not_silently_dropped():
    """'과 목'+기수는 갖췄는데 주석 열만 못 읽은 표 = 본표일 가능성이 높다 → 표면화.

    조용히 None 을 돌려주면 새 표기 변형이 나올 때마다 회사 하나가 통째로 사라지는데
    아무도 모른다(리노공업 사례가 정확히 그랬다).
    """
    doc = parse_document(_DOC.replace("<TH>주석</TH>", "<TH>비고</TH>"), filename="x.xml")
    assert not doc.statements
    msgs = [f.message for f in doc.report.findings]
    assert any("주석 열 라벨을 인식하지 못해" in m and "비고" in m for m in msgs)


def test_sce_like_table_without_periods_does_not_warn():
    """자본변동표는 애초에 주석 열이 없다 — 근접 실패 경고를 내면 잡음이 된다."""
    sce = _DOC.replace(
        '<TH>주석</TH><TH COLSPAN="2">제 56 (당) 기</TH><TH COLSPAN="2">제 55 (전) 기</TH>',
        "<TH>자 본 금</TH><TH>이익잉여금</TH>")
    doc = parse_document(sce, filename="sce.xml")
    assert not any("주석 열 라벨" in f.message for f in doc.report.findings)


def test_no_statement_error_names_what_was_in_the_zip():
    """본표가 없을 때 zip 안에 무엇이 있었는지를 버리지 않는다.

    회귀 대상: "접수번호가 사업보고서/감사보고서인지 확인하세요"만 던지면, 실제로는
    사업보고서 본문만 담긴 zip 이라는 사실을 이미 알면서 사용자에게 접수번호를
    바꿔가며 찍어보게 만든다(본표·주석은 감사보고서 첨부에만 있다).
    """
    only_body = ('<?xml version="1.0" encoding="utf-8"?><DOCUMENT>'
                 '<DOCUMENT-NAME ACODE="11011">사업보고서</DOCUMENT-NAME>'
                 '<BODY><P>본문</P></BODY></DOCUMENT>')
    try:
        parse_document_zip(_zip_bytes(only_body))
    except DocumentError as e:
        msg = str(e)
        assert "사업보고서" in msg and "11011" in msg      # 무엇이 들어 있었나
        assert "00760" in msg and "00761" in msg          # 어디에 본표가 있나
    else:
        raise AssertionError("본표 없는 zip 은 DocumentError 여야 한다")


def test_parse_zip_raises_when_no_statement_anywhere():
    empty = ('<?xml version="1.0" encoding="utf-8"?><DOCUMENT>'
             '<DOCUMENT-NAME ACODE="11011">사업보고서</DOCUMENT-NAME>'
             '<BODY><P>본문</P></BODY></DOCUMENT>')
    try:
        parse_document_zip(_zip_bytes(empty))
        raise AssertionError("DocumentError 미발생")
    except DocumentError as e:
        assert "재무제표 본표" in str(e)


def test_bad_zip_raises_document_error():
    try:
        parse_document_zip(b"not a zip")
        raise AssertionError("DocumentError 미발생")
    except DocumentError:
        pass


def test_to_dict_serializable():
    import json
    blob = json.dumps(to_dict(_doc()), ensure_ascii=False)
    assert "note_map" in blob and "현금및현금성자산" in blob


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
