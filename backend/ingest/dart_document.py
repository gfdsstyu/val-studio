"""DART 공시서류 원문(document.xml) 파서 — 재무제표 본표 + **주석 전문** 구조화.

OpenDART 에는 **주석 조회 API 가 없다**(`docs/plan/dart_disclosure_ingest.md` 실사 결론).
`fnlttSinglAcntAll`(→ `dart_fs.py`)은 계정·금액·표준코드까지만 준다. 주석 본문과
**계정↔주석번호 매핑**은 접수번호 원문(`/api/dart/document` 가 이미 받아오는 zip)에만 있다.
여기가 그 zip 을 읽는 파서다.

실측 해부(삼성전자 20250311001085 사업보고서 zip, FORMULA-VERSION 6.0):

  zip = 본보고서 1 + 첨부 N.  각 XML 의 `<DOCUMENT-NAME ACODE="...">` 로 종류 식별
        11011 사업보고서 / 00760 감사보고서(별도) / 00761 연결감사보고서
  구조 = XHTML 유사. `SECTION-1/2` + `TITLE` + `P` + `TABLE/TR/TD/TH/COLGROUP`
        DART 고유: `TE`(ACODE 태깅 셀) · `TU`(기간) · `EXTRACTION`(문서 메타)

**계획 문서 정정 2건**(실측이 뒤집음):
  ① 인코딩은 **UTF-8**이다. "EUC-KR 우선"은 구 서식 기준 — XML 선언을 존중하고
     UTF-8→cp949 순으로 폴백한다. cp949 로 먼저 읽으면 조용히 모지바케가 된다.
  ② "SGML 이라 표 복원이 험하다"가 아니라 **정상 표 마크업**이다(COLGROUP 폭 정의까지 있음).

⚠️ **핵심 함정 — 들여쓰기가 열 오프셋으로 표현된다.** 재무제표 본표는 6열이고 헤더가
COLSPAN=2 로 기수를 덮는다. 같은 기수 안에서 **개별계정은 앞 서브칼럼, 소계는 뒤
서브칼럼**에 금액을 쓴다:

    <TH>과 목</TH><TH>주석</TH><TH COLSPAN=2>제 56 (당) 기</TH><TH COLSPAN=2>제 55 (전) 기</TH>
    Ⅰ. 유 동 자 산   |        |          | 82,320,322 |           | 68,548,442
    1. 현금및현금성자산 | 4, 28  | 1,653,766 |            | 6,061,451 |

'N번째 칸 = 당기'로 읽으면 **소계 금액이 통째로 어긋난다**. 그래서 기수를 열 **구간**으로
잡고 그 구간에서 비어있지 않은 셀을 값으로 취한다(구간 폭이 곧 들여쓰기 단계다).
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal
from io import BytesIO

from .validators import Severity, ValidationReport, parse_number

#: 문서 종류(ACODE) → 사람이 읽는 이름. 필요한 것만; 미지의 코드는 그대로 노출한다.
DOC_KINDS = {
    "11011": "사업보고서", "11012": "반기보고서",
    "11013": "1분기보고서", "11014": "3분기보고서",
    "00760": "감사보고서", "00761": "연결감사보고서",
}
#: 재무제표 본표로 판정하는 헤더 조합(둘 다 있어야 한다 — '주석' 열이 결정적 표식).
#
# ⚠️ 라벨 표기는 회사마다 다르다 — 실측: 삼성전자 '주석' / 리노공업 **'주석번호'**.
# `^주\s*석$` 로 못 박아 뒀더니 리노공업 감사보고서의 본표 4개(BS·CIS·SCE·CF)가 전부
# 탈락했고, statements=0 이 되면서 `parse_document_zip(only_financial=True)` 가 문서를
# 통째로 버려 **정상 파싱된 주석 26만자까지 함께 증발**했다. 헤더 라벨 하나에 회사 전체가
# 걸린다. 알려진 변형을 명시 열거하고, 근접 실패는 §_parse_statement 가 표면화한다.
_FS_HEADER_ACCOUNT = re.compile(r"^과\s*목$")
_FS_HEADER_NOTE = re.compile(r"^주\s*석(\s*번\s*호)?$")
#: 로마숫자 대분류(Ⅰ. 유 동 자 산) / 아라비아 소분류(1. 현금및현금성자산)
#: 기수 열 라벨('제 30 (당) 기', '제 29 (전) 기말'). 본표 근접 실패 판별에만 쓴다.
_PERIOD_LABEL = re.compile(r"제\s*\d+\s*[\(（]?\s*[당전]")
_ROMAN = re.compile(r"^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩIVX]{1,6}\s*[.．]")
_ARABIC = re.compile(r"^\d{1,2}\s*[.．]\s*\S")
#: 주석 최상위 항목: `4. 현금및현금성자산` — `2.1 …`(하위)은 점 뒤 공백이 없어 걸리지 않는다.
_NOTE_HEAD = re.compile(r"^(\d{1,2})\s*\.\s+(\S.*)$")
#: 계정에 붙은 주석 참조: "4, 5, 7, 28"
_NOTE_REFS = re.compile(r"\d{1,2}")
#: (단위 : 백만원) / (단위: 천원)
_UNIT = re.compile(r"\(\s*단위\s*[:：]\s*([가-힣]+)\s*\)")


class DocumentError(RuntimeError):
    """원문 zip/XML 자체를 읽을 수 없는 상황."""


@dataclass(frozen=True)
class DocRow:
    """재무제표 본표의 한 행 — 공시 표시 그대로."""
    label: str
    depth: int
    note_refs: tuple[int, ...]
    values: dict[str, Decimal | None]      # 기수 라벨 → 금액(표 단위 → 백만원 정규화)
    raw: dict[str, str]                    # 기수 라벨 → 원문 문자열(감사추적)

    @property
    def is_total(self) -> bool:
        return self.depth <= 1


@dataclass
class StatementTable:
    """재무제표 본표 하나(재무상태표·손익계산서·…)."""
    title: str
    periods: list[str]                     # ['제 56 (당) 기', '제 55 (전) 기']
    unit: str | None
    rows: list[DocRow] = field(default_factory=list)
    #: 내용 기반 제표 판정(BS/IS/CIS/CF/SCE) — `fs_integrity` 가 이 축으로 항등식을 건다.
    sj_div: str = ""
    #: 기수별 사업연도. 표제 표의 '제 56 기 : 2024년 12월 31일 현재'에서 뽑는다.
    years: list[int] = field(default_factory=list)


@dataclass
class Note:
    """주석 1개 — 번호·제목·문단·표."""
    number: str
    title: str
    paragraphs: list[str] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)
    #: 표별·행별 colspan(= `tables` 와 인덱스 1:1). 화면·전송용 원형 보존.
    spans: list[list[list[int]]] = field(default_factory=list)
    #: **병합을 푼 직사각 격자**(colspan·rowspan 해소, = `tables` 와 인덱스 1:1).
    #: 정합성 검사(`note_check`)의 정본 입력 — 헤더 단수·부분 병합·다중 라벨 열을
    #: 가정 없이 다룰 수 있는 유일한 형태다.
    grids: list[list[list[str]]] = field(default_factory=list)


@dataclass
class ParsedDocument:
    """원문 XML 1개의 구조화 결과."""
    filename: str
    acode: str
    doc_name: str
    kind: str
    company: str
    statements: list[StatementTable] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)
    report: ValidationReport = field(default_factory=ValidationReport)

    @property
    def note_map(self) -> dict[str, tuple[int, ...]]:
        """계정명 → 주석번호 — `fnlttSinglAcntAll` 로는 절대 못 얻는 연결고리.

        같은 계정명이 여러 표에 나오면 참조를 합집합으로 모은다(재무상태표·손익계산서에
        같은 이름이 도는 경우가 있다).
        """
        out: dict[str, set[int]] = {}
        for st in self.statements:
            for r in st.rows:
                if r.note_refs:
                    out.setdefault(_norm(r.label), set()).update(r.note_refs)
        return {k: tuple(sorted(v)) for k, v in sorted(out.items())}


# ── 텍스트 유틸 ───────────────────────────────────────────────────────────────
def _strip(s: str) -> str:
    """태그 제거 + 공백 정규화. `&nbsp;` 류 엔티티도 공백으로 접는다."""
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\s+", " ", s).strip()


def _norm(s: str) -> str:
    """계정명 비교용 정규화 — 공시는 '유 동 자 산'처럼 자간 공백을 넣는다."""
    return re.sub(r"[\s.．]", "", re.sub(r"^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩIVX\d]{1,6}\s*[.．]\s*", "", s))


def decode_document(raw: bytes) -> str:
    """XML 선언의 encoding 을 존중해 디코딩. 미선언·실패 시 UTF-8 → cp949 폴백.

    실측: FORMULA-VERSION 6.0 문서는 UTF-8 이다. cp949 로 먼저 읽으면 예외가 아니라
    **조용한 모지바케**('연결감사보고서'→'뿰寃곌컧…')가 되므로 순서가 중요하다.
    """
    head = raw[:200].decode("ascii", errors="ignore")
    m = re.search(r'encoding\s*=\s*["\']([\w-]+)["\']', head, re.I)
    order = [m.group(1)] if m else []
    order += ["utf-8", "cp949", "euc-kr"]
    for enc in order:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


# ── 표 파싱 ───────────────────────────────────────────────────────────────────
def _cells_full(row_html: str) -> list[tuple[str, int, int]]:
    """<TR> → [(셀 텍스트, colspan, rowspan)]."""
    out: list[tuple[str, int, int]] = []
    for m in re.finditer(r"<T[DH]\b([^>]*)>(.*?)</T[DH]>", row_html, re.S | re.I):
        attrs = m.group(1)
        cs = re.search(r'COLSPAN\s*=\s*["\']?(\d+)', attrs, re.I)
        rs = re.search(r'ROWSPAN\s*=\s*["\']?(\d+)', attrs, re.I)
        out.append((_strip(m.group(2)),
                    int(cs.group(1)) if cs else 1, int(rs.group(1)) if rs else 1))
    return out


def _cells(row_html: str) -> list[tuple[str, int]]:
    """<TR> → [(셀 텍스트, colspan)]."""
    return [(t, c) for t, c, _ in _cells_full(row_html)]


def _table_grid(table_html: str) -> list[list[str]]:
    """표 → **병합을 푼 직사각 격자**(colspan·rowspan 모두 해소, 값은 복제).

    주석 표는 헤더가 1~3단이고 병합이 부분적이라, 줄 단위 문자열 결합으로는 어느 열이
    어느 상위 라벨에 속하는지 복원할 수 없다. 특히 **ROWSPAN 된 라벨 열('구분')** 때문에
    하위 헤더 행은 앞칸이 통째로 비어 있어 위치를 잃는다.

    표준 HTML 표 재구성(점유 격자)으로 풀면 모든 행이 같은 폭이 되고, 열 j 의 정체는
    "헤더 행들의 j 번째 칸을 위에서 아래로 읽은 스택"이 된다 — 헤더가 몇 단이든 무관해진다.
    """
    grid: list[list[str | None]] = []
    for r_i, rh in enumerate(re.findall(r"<TR\b[^>]*>(.*?)</TR>", table_html, re.S | re.I)):
        while len(grid) <= r_i:
            grid.append([])
        col = 0
        for text, cspan, rspan in _cells_full(rh):
            row = grid[r_i]
            while col < len(row) and row[col] is not None:   # 위 행의 rowspan 이 점유
                col += 1
            for dr in range(max(1, rspan)):
                while len(grid) <= r_i + dr:
                    grid.append([])
                tgt = grid[r_i + dr]
                while len(tgt) < col + cspan:
                    tgt.append(None)
                for dc in range(max(1, cspan)):
                    tgt[col + dc] = text
            col += max(1, cspan)
    width = max((len(r) for r in grid), default=0)
    return [[("" if c is None else c) for c in r] + [""] * (width - len(r)) for r in grid]


def _columns(cells: list[tuple[str, int]]) -> list[tuple[str, int, int]]:
    """[(텍스트, colspan)] → [(텍스트, 시작열, 끝열)] (끝열 미포함)."""
    out, col = [], 0
    for text, span in cells:
        out.append((text, col, col + span))
        col += span
    return out


def _period_spans(header: list[tuple[str, int]]) -> list[tuple[str, int, int]]:
    """헤더 → 기수별 열 구간. '과 목'·'주석' 열은 제외한다."""
    return [(t, a, b) for t, a, b in _columns(header)
            if t and not _FS_HEADER_ACCOUNT.match(t) and not _FS_HEADER_NOTE.match(t)]


def _depth(label: str) -> int:
    """0=제목행(자 산/부 채/자 본) · 1=로마숫자 대분류 · 2=아라비아 소분류 · 3=그 외."""
    if _ROMAN.match(label):
        return 1
    if _ARABIC.match(label):
        return 2
    if len(_norm(label)) <= 6 and not any(ch.isdigit() for ch in label):
        return 0
    return 3


def _parse_statement(table_html: str, title: str, unit: str | None,
                     report: ValidationReport) -> StatementTable | None:
    """재무제표 본표 1개 파싱. 헤더에 '과 목'+'주석'이 없으면 본표가 아니다(None)."""
    rows_html = re.findall(r"<TR\b[^>]*>(.*?)</TR>", table_html, re.S | re.I)
    if not rows_html:
        return None
    header = _cells(rows_html[0])
    texts = [t for t, _ in header]
    has_account = any(_FS_HEADER_ACCOUNT.match(t) for t in texts)
    has_note = any(_FS_HEADER_NOTE.match(t) for t in texts)
    if not (has_account and has_note):
        # ⚠️ 근접 실패는 조용히 버리지 않는다 — '과 목' + 기수 열을 갖췄는데 주석 열
        # 라벨만 못 읽은 표는 **본표일 가능성이 매우 높다**(리노공업 '주석번호' 사례).
        # 헤더 라벨을 그대로 남겨 새 변형이 즉시 눈에 띄게 한다. 자본변동표처럼 애초에
        # 주석 열이 없는 표는 기수 라벨이 없어 여기에 걸리지 않는다.
        if has_account and not has_note and any(_PERIOD_LABEL.search(t) for t in texts):
            report.add(_finding(
                "doc_header_variant",
                f"'{title or '무제'}': '과 목'+기수 헤더인데 주석 열 라벨을 인식하지 못해 "
                f"본표에서 제외했습니다 — 실제 헤더 {texts[:6]} "
                "(_FS_HEADER_NOTE 변형 추가 필요)"))
        return None
    spans = _period_spans(header)
    note_col = next((a for t, a, _ in _columns(header) if _FS_HEADER_NOTE.match(t)), 1)
    st = StatementTable(title=title, periods=[t for t, _, _ in spans], unit=unit)

    for rh in rows_html[1:]:
        cols = _columns(_cells(rh))
        if not cols:
            continue
        label = cols[0][0]
        if not label:
            continue
        note_txt = next((t for t, a, b in cols if a <= note_col < b), "")
        refs = tuple(int(n) for n in _NOTE_REFS.findall(note_txt)) if note_txt else ()
        values: dict[str, Decimal | None] = {}
        raws: dict[str, str] = {}
        for plabel, a, b in spans:
            # 기수가 덮는 열 구간에서 **비어있지 않은 셀** 하나 — 어느 서브칼럼에
            # 쓰였는지가 곧 들여쓰기 단계다(위 도입부 함정 참조).
            cell = next((t for t, ca, cb in cols if ca >= a and cb <= b and t), "")
            raws[plabel] = cell
            values[plabel] = (parse_number(cell, unit=unit, report=report,
                                           field_name=f"{title}:{label}:{plabel}")
                              if cell else None)
        st.rows.append(DocRow(label=label, depth=_depth(label), note_refs=refs,
                              values=values, raw=raws))
    return st if st.rows else None


def _table_rows(table_html: str) -> list[list[str]]:
    """주석 안 표 → 순수 텍스트 격자(구조 보존, 해석은 하지 않는다)."""
    return [[t for t, _ in _cells(rh)]
            for rh in re.findall(r"<TR\b[^>]*>(.*?)</TR>", table_html, re.S | re.I)]


def _table_spans(table_html: str) -> list[list[int]]:
    """같은 표의 colspan 격자(`_table_rows` 와 인덱스 1:1)."""
    return [[c for _, c in _cells(rh)]
            for rh in re.findall(r"<TR\b[^>]*>(.*?)</TR>", table_html, re.S | re.I)]


# ── 문서 파싱 ─────────────────────────────────────────────────────────────────
def parse_document(text: str, *, filename: str = "") -> ParsedDocument:
    """원문 XML 1개 → 재무제표 본표 + 주석."""
    report = ValidationReport()
    acode = _attr(text, "DOCUMENT-NAME", "ACODE") or ""
    doc_name = _first_text(text, "DOCUMENT-NAME")
    company = _first_text(text, "COMPANY-NAME")
    doc = ParsedDocument(filename=filename, acode=acode, doc_name=doc_name,
                         kind=DOC_KINDS.get(acode, doc_name or acode),
                         company=company, report=report)

    # 표제(재 무 상 태 표)·기간·단위는 본표 **직전 표** 안에 들어 있다 —
    # 표끼리 맞붙어 있어 사이 마크업이 사실상 비어 있다(실측 lead 길이 2자).
    prev_text = ""
    for m in re.finditer(r"<TABLE\b.*?</TABLE>", text, re.S | re.I):
        title, unit = _lead_title_unit(prev_text)
        st = _parse_statement(m.group(0), title, unit, report)
        lead = prev_text
        prev_text = _strip(m.group(0))
        if st:
            st.sj_div = classify_statement(st)
            st.years = _lead_years(lead, len(st.periods))
            doc.statements.append(st)
    doc.notes = _parse_notes(text)
    if not doc.statements:
        report.add(_finding("doc_no_statement_table",
                            f"{filename or doc_name}: '과 목'+'주석' 헤더를 가진 본표를 찾지 못했습니다"
                            " — 감사보고서(ACODE 00760/00761) 첨부를 확인하세요."))
    return doc


def _parse_notes(text: str) -> list[Note]:
    """`<SECTION-2>` TITLE='주석' 구획에서 주석 번호·제목·문단·표 추출.

    최상위 주석(`4. 현금및현금성자산`)만 새 항목으로 끊고 하위(`2.1 …`)는 문단으로 남긴다
    — 회사마다 하위 번호 체계가 달라 기계적으로 계층을 세우면 오히려 왜곡된다.
    """
    sec = _section_by_title(text, "주석")
    if not sec:
        return []
    notes: list[Note] = []
    cur: Note | None = None
    for m in re.finditer(r"<(P|TABLE)\b[^>]*>(.*?)</\1>", sec, re.S | re.I):
        kind = m.group(1).upper()
        if kind == "TABLE":
            if cur:
                cur.tables.append(_table_rows(m.group(0)))
                cur.spans.append(_table_spans(m.group(0)))
                cur.grids.append(_table_grid(m.group(0)))
            continue
        body = _strip(m.group(2))
        if not body:
            continue
        head = _NOTE_HEAD.match(body)
        if head and len(body) < 80:
            cur = Note(number=head.group(1), title=head.group(2).rstrip(":： "))
            notes.append(cur)
        elif cur:
            cur.paragraphs.append(body)
    return notes


def _section_by_title(text: str, want: str) -> str | None:
    """TITLE 이 want 인 SECTION-1/2 구획 본문. 목차의 동명 문자열에 속지 않는다."""
    for tag in ("SECTION-2", "SECTION-1"):
        bounds = [m.start() for m in re.finditer(rf"<{tag}\b[^>]*>", text, re.I)]
        for i, start in enumerate(bounds):
            end = bounds[i + 1] if i + 1 < len(bounds) else len(text)
            t = re.search(r"<TITLE\b[^>]*>(.*?)</TITLE>", text[start:end], re.S | re.I)
            if t and _strip(t.group(1)).replace(" ", "") == want.replace(" ", ""):
                return text[start:end]
    return None


#: 표제 후보 — 공시는 '재 무 상 태 표'처럼 자간을 벌리므로 공백 제거 후 매칭한다.
_STATEMENT_TITLES = (
    ("재무상태표", "BS"), ("손익계산서", "IS"), ("포괄손익계산서", "CIS"),
    ("현금흐름표", "CF"), ("자본변동표", "SCE"),
)


def _lead_title_unit(lead_text: str) -> tuple[str, str | None]:
    """본표 **직전 표의 평문**에서 표제와 단위를 줍는다.

    실측: 표제·보고기간·단위는 본표 바로 위의 작은 표 한 장에 모여 있고, 표와 표 사이
    마크업은 비어 있다. 그래서 '직전 마크업'이 아니라 '직전 표 텍스트'가 lead 다.
    """
    if not lead_text:
        return "", None
    unit = None
    for m in _UNIT.finditer(lead_text):
        unit = m.group(1)
    flat = lead_text.replace(" ", "")
    title = ""
    for name, _ in _STATEMENT_TITLES:
        if name in flat:
            title = name          # 뒤쪽(더 구체적인 '포괄손익계산서')이 이기도록 계속 훑는다
    return title, unit


def _lead_years(lead_text: str, n_period: int) -> list[int]:
    """표제 표에서 기수별 사업연도. '제 56 기 : 2024년 12월 31일 현재 / 제 55 기 : 2023년…'

    등장 순서를 그대로 쓴다(공시가 당기→전기 순으로 적는다). 기수 수와 안 맞으면
    빈 리스트를 돌려 호출부가 상대 기수로 폴백하게 한다 — 억지로 맞추면 열이 밀린다.
    """
    ys = [int(y) for y in re.findall(r"(20\d{2})\s*년", lead_text or "")]
    seen: list[int] = []
    for y in ys:
        if y not in seen:
            seen.append(y)
    return seen if len(seen) == n_period else []


def classify_statement(st: StatementTable) -> str:
    """제표 종류 판정 — **표제가 아니라 내용**으로. 표제는 비거나 흔들린다.

    `fs_integrity.IDENTITIES` 가 sj_div 축으로 앵커를 찾으므로 이 판정이 곧 검사 대상
    결정이다. 순서가 중요하다: 자본변동표는 열 자체가 기수가 아니라 자본 구성이고,
    포괄손익계산서는 손익계산서의 상위집합이라 먼저 걸러야 한다.
    """
    labels = "".join(_norm(r.label) for r in st.rows)
    periods = "".join(st.periods).replace(" ", "")
    if "지배기업소유주지분" in periods or "비지배지분" in periods or "자본변동" in st.title:
        return "SCE"
    if "영업활동" in labels and "현금흐름" in labels:
        return "CF"
    if "자산총계" in labels or "유동자산" in labels:
        return "BS"
    if "총포괄손익" in labels or "기타포괄손익" in labels:
        return "CIS"
    if "매출" in labels or "영업이익" in labels:
        return "IS"
    for name, div in _STATEMENT_TITLES:
        if name in st.title.replace(" ", ""):
            return div
    return ""


def _attr(text: str, tag: str, attr: str) -> str | None:
    m = re.search(rf"<{tag}\b([^>]*)>", text, re.I)
    if not m:
        return None
    a = re.search(rf'{attr}\s*=\s*["\']([^"\']*)', m.group(1), re.I)
    return a.group(1) if a else None


def _first_text(text: str, tag: str) -> str:
    m = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", text, re.S | re.I)
    return _strip(m.group(1)) if m else ""


def _finding(rule: str, message: str):
    from .validators import Finding
    return Finding(rule=rule, severity=Severity.WARN, message=message, detail={})


# ── zip 진입점 ────────────────────────────────────────────────────────────────
def parse_document_zip(blob: bytes, *, only_financial: bool = True) -> list[ParsedDocument]:
    """`/api/dart/document` 가 받아오는 원본 zip → 문서별 파싱 결과.

    only_financial=True 면 재무제표 본표가 실제로 잡힌 문서만 돌려준다 —
    사업보고서 본문(6MB)에는 본표가 없고 감사보고서 첨부에만 있어서, 전부 돌려주면
    호출부가 매번 골라내야 한다. 사업보고서까지 필요하면 False.
    """
    try:
        z = zipfile.ZipFile(BytesIO(blob))
    except zipfile.BadZipFile as e:
        raise DocumentError(f"원본 zip 을 열 수 없습니다: {e}") from e
    parsed: list[ParsedDocument] = []
    for name in z.namelist():
        if not name.lower().endswith(".xml"):
            continue
        parsed.append(parse_document(decode_document(z.read(name)), filename=name))
    out = [d for d in parsed if d.statements] if only_financial else list(parsed)
    if not out:
        # ⚠️ zip 안에 무엇이 있었는지를 버리지 않는다 — "확인하세요"만 던지면 사용자는
        # 접수번호를 바꿔가며 찍어볼 수밖에 없다. 본표는 감사보고서 첨부에만 있으므로,
        # 실제로 들어 있던 문서 종류를 보여주면 원인이 한 줄로 드러난다.
        seen = ", ".join(
            f"{d.doc_name or d.filename}({d.acode or 'ACODE 없음'})" for d in parsed[:6])
        more = f" 외 {len(parsed) - 6}건" if len(parsed) > 6 else ""
        raise DocumentError(
            "재무제표 본표를 가진 문서가 없습니다. 이 zip 의 문서: "
            + (seen + more if parsed else "(xml 문서 없음)")
            + ". 본표·주석은 **감사보고서(00760)·연결감사보고서(00761) 첨부**에만 있습니다 "
              "— 사업보고서 본문만 담긴 접수번호이거나 주요사항보고서일 수 있습니다.")
    return out


# ── 정합성 검사 연결 ─────────────────────────────────────────────────────────
def to_multiyear(doc: ParsedDocument) -> "object":
    """파싱된 원문 → `dart_fs.MultiYearFs` 로 변환해 **같은 항등식 SSOT** 를 태운다.

    원문 파싱은 `fnlttSinglAcntAll` 과 **독립된 두 번째 출처**다. 그러므로
    `fs_integrity.IDENTITIES`(대차·손익체인·CF 롤포워드)를 그대로 걸면 두 가지를 동시에
    얻는다: ①공시 자체의 정합성 ②**우리 파서가 표를 옳게 읽었는지**. 열 오프셋 함정
    (개별계정 앞칸 / 소계 뒷칸)을 잘못 처리하면 대차가 즉시 깨지므로, 이 검사가
    파서의 회귀 그물이 된다.

    연도 축: 원문은 '제 56 (당) 기'처럼 기수로 쓰므로 표제·기간 텍스트에서 연도를
    뽑고, 실패하면 최신 기수를 0, 그 앞을 -1…로 **상대 연도**로 둔다(연도 자체가
    목적이 아니라 열을 가르는 축이다).
    """
    from .dart_fs import FsAccount, MultiYearFs, Observation

    notes, axis = _period_years(doc)
    accounts: list[FsAccount] = []
    order = 0.0
    for st in doc.statements:
        if st.sj_div in ("", "SCE"):        # 자본변동표는 열이 기수가 아니라 자본 구성
            continue
        # ⚠️ 기수→연도는 **문서 순서 그대로** 짝지어야 한다. 공시는 당기→전기 순으로
        # 적고 우리 축(years)은 과거→최근 오름차순이라, 정렬된 축에 그냥 zip 하면
        # 당기 금액이 전기에 붙는다. 정합성 항등식은 열이 통째로 바뀌어도 각 열 안에서
        # 성립하므로 **이 오류를 잡아주지 못한다** — 여기서 명시적으로 맞춘다.
        st_years = st.years if len(st.years) == len(st.periods) else \
            sorted(axis, reverse=True)[:len(st.periods)]
        for r in st.rows:
            order += 1
            acc = FsAccount(
                sj_div=st.sj_div, sj_nm=st.title or st.sj_div,
                account_id="", account_nm=_clean_label(r.label), account_detail="",
                order=order, depth=r.depth, depth_basis="doc:outline",
                merge_key=("doc", st.sj_div, r.label, order),
            )
            for plabel, y in zip(st.periods, st_years):
                v = r.values.get(plabel)
                acc.obs[y] = [Observation(year=y, value=v, raw=r.raw.get(plabel),
                                          source_year=y, column="document",
                                          rcept_no=None)]
            accounts.append(acc)
    return MultiYearFs(corp_code="", fs_div="", reprt_code="", years=list(axis),
                       accounts=accounts, notes=[f"원문 파싱({doc.kind})", *notes])


def _period_years(doc: ParsedDocument) -> tuple[list[str], list[int]]:
    """기수 라벨 → 사업연도. 표제 표에서 뽑은 연도를 쓰고, 없으면 상대 기수로 폴백."""
    notes: list[str] = []
    st = next((s for s in doc.statements if s.sj_div == "BS"), None)
    n = len(st.periods) if st else 2
    if st and len(st.years) == n:
        notes.append(f"연도: 표제에서 {st.years}")
        return notes, sorted(st.years)
    notes.append("연도 미확정 — 상대 기수(0=당기, -1=전기)로 축을 세움")
    return notes, sorted(range(0, -n, -1))


def _clean_label(label: str) -> str:
    """'Ⅰ. 유 동 자 산' → '유동자산' — 앵커 매칭이 자간 공백·번호에 걸리지 않게."""
    s = re.sub(r"^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩIVX\d]{1,6}\s*[.．]\s*", "", label)
    return re.sub(r"\s+", "", s)


def check_document(doc: ParsedDocument) -> tuple[list, dict]:
    """원문 파싱 결과에 `fs_integrity` 항등식을 적용 → (findings, summary)."""
    from .fs_integrity import check_statements, summarize
    fs = to_multiyear(doc)
    findings = check_statements(fs)
    return findings, summarize(findings)


def to_dict(doc: ParsedDocument) -> dict:
    """API 응답용 직렬화(수제 dict 규약 — Pydantic 미사용)."""
    return {
        "filename": doc.filename, "acode": doc.acode, "kind": doc.kind,
        "doc_name": doc.doc_name, "company": doc.company,
        "statements": [{
            "title": st.title, "sj_div": st.sj_div, "years": st.years,
            "periods": st.periods, "unit": st.unit,
            "rows": [{
                "label": r.label, "depth": r.depth, "is_total": r.is_total,
                "note_refs": list(r.note_refs),
                "values": {k: (None if v is None else float(v)) for k, v in r.values.items()},
                "raw": r.raw,
            } for r in st.rows],
        } for st in doc.statements],
        "notes": [{"number": n.number, "title": n.title,
                   "paragraphs": n.paragraphs, "tables": n.tables} for n in doc.notes],
        "note_map": {k: list(v) for k, v in doc.note_map.items()},
        "findings": [{"rule": f.rule, "severity": f.severity.value, "message": f.message}
                     for f in doc.report.findings],
    }
