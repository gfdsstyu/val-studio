"""주석 표 정합성 — 표 내부 산술(A) + 연도 간 대조(B).

주석은 **XBRL 로 나오지 않는다**. `fnlttSinglAcntAll` 이 주는 건 본표뿐이라, 주석은
원문 파싱(`dart_document`)이 유일한 경로이고 따라서 **자기 검산 수단도 스스로 만들어야
한다**. 본표는 다년도 API 응답끼리 대조할 수 있지만(`dart_fs` 의 연도 중복관측) 주석에는
그런 공짜 대조가 없다.

검증 두 축:
  **A. 표 내부**(문서 1개면 됨)
    A1 소계 정합 — Σ개별 = 소계/합계. 소계가 계층으로 쌓이는 표가 실재하므로
       (실측: 미수금·미수수익 → '유동자산 소계' → 보증금 → '비유동자산 소계' → '합계')
       "전부 더하면 합계"로 짜면 이중계상으로 틀린다.
    A2 롤포워드 — 기초 + Σ변동 = 기말(유형자산·무형자산·충당부채 표의 표준형).
  **B. 연도 간**(문서 2개)
    당해 보고서의 **전기 열** ↔ 직전 보고서의 **당기 열**. 어긋나면 재작성·재분류다.

⚠️ 단위 변환을 하지 않는다. 표 안 산술 정합성은 단위와 무관하고, 백만원으로 정규화하면
반올림 잔차가 끼어들어 "맞는데 틀렸다"가 나온다. 원문 숫자를 그대로 Decimal 로 본다.

⚠️ 주석에는 표준 계정코드가 없다 — 매칭 키가 **행 라벨 하나뿐**이다. `dart_fs` 가
"단일 키는 반드시 깨진다"를 실측한 그 상황이 여기서는 불가피하므로, **매칭 실패와 값
불일치를 반드시 분리**한다(이름이 바뀐 것을 금액 오류로 보고하면 경고가 신뢰를 잃는다).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from .validators import Finding, Severity, ValidationReport

#: 합계·소계 행 라벨. '순장부금액' 처럼 **차감으로 만들어지는** 라벨은 일부러 제외한다
#: (총장부금액 − 손실충당금 = 순장부금액은 합이 아니다 — 합계로 오인하면 오보가 난다).
_TOTAL = re.compile(r"^(합\s*계|총\s*계|계|.*소\s*계)$")
_UNIT = re.compile(r"\(\s*단위\s*[:：]\s*([가-힣]+)\s*\)")
_NUM = re.compile(r"^\(?\s*-?[\d,]+(?:\.\d+)?\s*\)?$")
#: 기수 귀속 — '당기말'·'당분기'·'제30기' 등.
_CURRENT = re.compile(r"당\s*(기|분기|반기)")
_PRIOR = re.compile(r"전\s*(기|분기|반기)")
_OPENING = re.compile(r"^기\s*초$")
_CLOSING = re.compile(r"^기\s*말$")
#: 번호가 붙은 상위 항목('1. 법정적립금' · 'Ⅰ. 미처분이익잉여금'). 번호 없는 뒤따르는
#: 행은 그 **하위 내역**이라 합산 대상이 아니다 — 같이 더하면 이중계상이 된다
#: (실측: 이익잉여금 주석에서 이익준비금·기업합리화적립금이 상위와 함께 더해져
#:  합계가 4,329,874,817 원 어긋나는 오탐이 났다).
_NUMBERED = re.compile(r"^\s*(\d{1,2}|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+)\s*[.．]")


def to_decimal(cell: str) -> Decimal | None:
    """주석 셀 → Decimal. 괄호음수 `(1,234)` → -1234, `-` → 0, 빈칸/문자 → None.

    `-` 를 0 으로 보는 것은 한국 재무제표 표기 관행이다(해당 없음 = 0). None 과 구분해
    두어야 "값이 없다"와 "0 이다"가 섞이지 않는다.
    """
    s = (cell or "").strip().replace(" ", "")
    if s in ("-", "–", "—"):
        return Decimal(0)
    if not s or not _NUM.match(s):
        return None
    neg = s.startswith("(")
    s = s.strip("()").replace(",", "")
    try:
        v = Decimal(s)
    except InvalidOperation:
        return None
    return -v if neg else v


@dataclass(frozen=True)
class NoteColumn:
    """데이터 행의 값 1개에 대응하는 열."""
    label: str                 # 결합 라벨('당기말/취득원가' 또는 '기초')
    group: str = ""            # 상위 헤더(2단일 때)
    period: str = ""           # 'current' | 'prior' | ''


@dataclass
class NoteRow:
    label: str
    values: list[Decimal | None] = field(default_factory=list)
    raw: list[str] = field(default_factory=list)

    @property
    def is_total(self) -> bool:
        return bool(_TOTAL.match(self.label.strip()))


@dataclass
class NoteTable:
    """구조화된 주석 표."""
    note_no: str = ""
    title: str = ""
    unit: str | None = None
    columns: list[NoteColumn] = field(default_factory=list)
    rows: list[NoteRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def column_index(self, period: str) -> list[int]:
        return [i for i, c in enumerate(self.columns) if c.period == period]

    @property
    def is_rollforward(self) -> bool:
        labs = [c.label for c in self.columns]
        return any(_OPENING.match(x) for x in labs) and any(_CLOSING.match(x) for x in labs)


def _period_of(label: str) -> str:
    if _CURRENT.search(label):
        return "current"
    if _PRIOR.search(label):
        return "prior"
    return ""


def _is_num(cell: str) -> bool:
    return bool(_NUM.match((cell or "").strip()))


def _dedup(seq: list[str]) -> list[str]:
    """연속 중복 제거 — 병합 해소로 복제된 라벨을 한 번만 남긴다."""
    out: list[str] = []
    for s in seq:
        if s and (not out or out[-1] != s):
            out.append(s)
    return out


def parse_note_table(
    grid: list[list[str]], *, note_no: str = "", title: str = "",
) -> NoteTable | None:
    """**병합을 푼 직사각 격자**(dart_document._table_grid) → NoteTable.

    헤더를 "몇 줄인지" 세지 않는다. 격자가 직사각이므로 열 j 의 정체는 **헤더 행들의
    j 번째 칸을 위에서 아래로 읽은 스택**이고, 이 방식은 헤더가 1~3단이든 부분 병합이든
    똑같이 성립한다(종전의 '마지막 2줄 결합 + 첫 칸은 라벨' 가정이 8표를 포기시켰다).

    라벨 열 개수도 가정하지 않고 **데이터에서 추론**한다 — 숫자를 가진 행들의 '앞쪽
    연속 비숫자 칸 수'의 최솟값. 실측: 기타금융자산 주석은 라벨 열이 '구분'+'종목명' 2개다.
    """
    tbl = NoteTable(note_no=note_no, title=title)
    if not grid:
        return None

    header: list[list[str]] = []
    data_from: int | None = None
    for i, row in enumerate(grid):
        cells = [c.strip() for c in row]
        if not any(cells):
            continue
        m = _UNIT.search(" ".join(_dedup(cells)))
        if m and len(_dedup(cells)) <= 2:
            tbl.unit = m.group(1)
            continue
        if any(_is_num(c) for c in cells):
            data_from = i
            break
        # 값 없는 **한 칸짜리 행**(병합 해소로 같은 값이 전 열에 복제된다)은 헤더가 아니라
        # 블록 구분자다('유동자산 :'). 헤더로 먹으면 전 열 라벨이 그 문자열이 된다.
        if header and len(_dedup(cells)) == 1:
            data_from = i
            break
        header.append(cells)
    if data_from is None:
        return None

    data = [[c.strip() for c in r] for r in grid[data_from:] if any(str(c).strip() for c in r)]
    numeric_rows = [r for r in data if any(_is_num(c) for c in r)]
    if not numeric_rows:
        return None
    # 라벨 열 수 = 숫자를 가진 행들의 선행 비숫자 칸 수 중 최솟값(블록 구분자는 제외됨).
    n_label = min(
        next((j for j, c in enumerate(r) if _is_num(c)), len(r)) for r in numeric_rows)
    n_label = max(1, n_label)

    width = max(len(r) for r in grid)
    for j in range(n_label, width):
        stack = _dedup([h[j] if j < len(h) else "" for h in header])
        period = next((p for p in (_period_of(s) for s in stack) if p), "")
        tbl.columns.append(NoteColumn(
            label="/".join(stack), group=stack[0] if len(stack) > 1 else "", period=period))

    for r in data:
        label = " ".join(_dedup(r[:n_label]))
        if not label:
            continue
        vals = r[n_label:]
        tbl.rows.append(NoteRow(label=label, raw=vals,
                                values=[to_decimal(v) for v in vals]))
    if not tbl.rows:
        return None
    if not any(c.label for c in tbl.columns):
        tbl.warnings.append("열이름을 찾지 못해 기수 귀속 불가")
    return tbl


# ── A1. 소계 정합 ────────────────────────────────────────────────────────────
def check_subtotals(tbl: NoteTable, *, report: ValidationReport | None = None,
                    ) -> ValidationReport:
    """Σ개별 = 소계/합계 (열별로 독립 검증).

    소계가 계층으로 쌓이는 표를 위해 두 후보를 모두 본다:
      ①직전 소계 이후의 개별 행 합   ②앞선 소계들의 합
    둘 중 하나와 맞으면 통과다 — 어느 쪽이 맞는지는 표마다 다르고, 하나만 보면
    멀쩡한 표가 FAIL 로 뜬다.
    """
    report = report or ValidationReport()
    n_col = len(tbl.columns)
    # 번호 항목이 2개 이상이면 **계층 표**다 — 번호 붙은 행만 합산하고 그 사이의
    # 번호 없는 행은 하위 내역으로 보아 제외한다. 번호가 없는 평면 표는 전부 합산.
    numbered = [r for r in tbl.rows if _NUMBERED.match(r.label) and not r.is_total]
    hierarchical = len(numbered) >= 2
    for ci in range(n_col):
        running: list[Decimal] = []          # 직전 소계 이후의 개별 값
        subtotals: list[Decimal] = []        # 앞서 나온 소계 값
        for row in tbl.rows:
            # ⚠️ **행 그룹 헤더**(값이 하나도 없는 라벨 행 — '금융자산:', '유동자산 :')가
            # 블록을 나눈다. 이걸 무시하면 자산 블록의 개별값이 부채 소계에 딸려 들어가
            # 자릿수가 통째로 다른 오탐이 난다(실측: 소계 131억 vs 개별합 5,517억).
            if all(v is None for v in row.values):
                running, subtotals = [], []
                continue
            v = row.values[ci] if ci < len(row.values) else None
            if not row.is_total:
                # 계층 표에서 번호 없는 행 = 직전 상위 항목의 내역 → 합산 제외.
                if hierarchical and not _NUMBERED.match(row.label):
                    continue
                if v is not None:
                    running.append(v)
                continue
            if v is None:
                continue
            cand_a = sum(running) if running else None
            cand_b = sum(subtotals) if subtotals else None
            ok = (cand_a is not None and cand_a == v) or (cand_b is not None and cand_b == v)
            col = tbl.columns[ci].label
            if not ok:
                report.add(Finding(
                    "note_subtotal", Severity.FAIL,
                    f"주석{tbl.note_no} '{tbl.title[:20]}' [{col}] '{row.label}' "
                    f"표기 {v:,} ≠ 개별합 {cand_a if cand_a is None else f'{cand_a:,}'}"
                    f" / 소계합 {cand_b if cand_b is None else f'{cand_b:,}'}",
                    {"note": tbl.note_no, "column": col, "label": row.label,
                     "stated": str(v), "sum_items": str(cand_a), "sum_subtotals": str(cand_b)}))
            subtotals.append(v)
            running = []
    return report


# ── A2. 롤포워드 ─────────────────────────────────────────────────────────────
def check_rollforward(tbl: NoteTable, *, report: ValidationReport | None = None,
                      ) -> ValidationReport:
    """기초 + Σ변동 = 기말 (행별). 롤포워드 표가 아니면 아무것도 하지 않는다."""
    report = report or ValidationReport()
    if not tbl.is_rollforward:
        return report
    labs = [c.label for c in tbl.columns]
    o = next(i for i, x in enumerate(labs) if _OPENING.match(x))
    c = next(i for i, x in enumerate(labs) if _CLOSING.match(x))
    mid = [i for i in range(len(labs)) if i not in (o, c)]
    for row in tbl.rows:
        if max(o, c) >= len(row.values):
            continue
        beg, end = row.values[o], row.values[c]
        if beg is None or end is None:
            continue
        delta = sum(row.values[i] for i in mid
                    if i < len(row.values) and row.values[i] is not None)
        if beg + delta != end:
            report.add(Finding(
                "note_rollforward", Severity.FAIL,
                f"주석{tbl.note_no} '{tbl.title[:20]}' '{row.label}' 롤포워드 불일치 — "
                f"기초 {beg:,} + 변동 {delta:,} = {beg + delta:,} ≠ 기말 {end:,}",
                {"note": tbl.note_no, "label": row.label, "opening": str(beg),
                 "delta": str(delta), "closing": str(end)}))
    return report


# ── B. 연도 간 대조 ──────────────────────────────────────────────────────────
@dataclass
class PeriodDiff:
    """당해 보고서의 전기 열 ↔ 직전 보고서의 당기 열 대조 결과 1건."""
    kind: str          # restated | sign_convention | unmatched | matched
    label: str
    column: str
    current_prior: Decimal | None = None      # 당해 보고서가 말하는 '전기'
    prior_current: Decimal | None = None      # 직전 보고서가 말하는 '당기'


def compare_periods(cur: NoteTable, prev: NoteTable) -> tuple[list[PeriodDiff], ValidationReport]:
    """당해 표의 prior 열 ↔ 직전 표의 current 열.

    판정 4종. **매칭 실패(`unmatched`)를 값 불일치로 보고하지 않는다** — 주석은 계정코드가
    없어 이름이 바뀌면 기계가 이을 수 없고, 그걸 '재작성'이라 부르면 오보가 된다.
    개별은 어긋나는데 **합계는 맞는** 경우는 재분류이지 재작성이 아니므로 따로 표시한다.
    """
    report = ValidationReport()
    diffs: list[PeriodDiff] = []
    ci, pi = cur.column_index("prior"), prev.column_index("current")
    if not ci or not pi:
        report.add(Finding(
            "note_period_axis", Severity.WARN,
            f"주석{cur.note_no}: 기수 열을 특정하지 못해 연도 간 대조를 건너뜀 "
            f"(당해 prior={len(ci)}열 · 직전 current={len(pi)}열)",
            {"note": cur.note_no}))
        return diffs, report

    prev_rows = {r.label.strip(): r for r in prev.rows}
    n = min(len(ci), len(pi))
    # ⚠️ '재분류'는 **합계가 실제로 일치할 때만** 할 수 있는 주장이다. 합계 행이 아예
    # 없는 표에서 개별 불일치를 재분류로 부르면 근거 없는 단정이 된다 → total_seen 필수.
    total_seen = False
    total_ok = True
    for row in cur.rows:
        other = prev_rows.get(row.label.strip())
        col = cur.columns[ci[0]].label
        if other is None:
            diffs.append(PeriodDiff("unmatched", row.label, col))
            continue
        for k in range(n):
            a = row.values[ci[k]] if ci[k] < len(row.values) else None
            b = other.values[pi[k]] if pi[k] < len(other.values) else None
            col = cur.columns[ci[k]].label
            if a is None or b is None or a == b:
                diffs.append(PeriodDiff("matched", row.label, col, a, b))
                continue
            kind = "sign_convention" if a == -b else "restated"
            diffs.append(PeriodDiff(kind, row.label, col, a, b))
            if row.is_total:
                total_ok = False
        if row.is_total and row.label.strip() in prev_rows:
            total_seen = True

    restated = [d for d in diffs if d.kind == "restated"]
    unmatched = [d for d in diffs if d.kind == "unmatched"]
    signs = [d for d in diffs if d.kind == "sign_convention"]

    if restated and total_seen and total_ok:
        # 개별은 어긋나는데 합계는 맞다 → 금액이 아니라 **분류**가 바뀐 것이다.
        report.add(Finding(
            "note_reclassified", Severity.WARN,
            f"주석{cur.note_no} '{cur.title[:20]}': 개별 {len(restated)}건이 전기와 다른데 "
            "합계는 일치 — 재작성이 아니라 재분류로 보입니다(구성만 바뀜)",
            {"note": cur.note_no, "labels": [d.label for d in restated][:10]}))
    elif restated:
        for d in restated[:20]:
            report.add(Finding(
                "note_restated", Severity.WARN,
                f"주석{cur.note_no} '{d.label}' [{d.column}] 전기 재작성 — "
                f"당해 보고서 {d.current_prior:,} ≠ 직전 보고서 {d.prior_current:,}",
                {"note": cur.note_no, "label": d.label,
                 "current_prior": str(d.current_prior),
                 "prior_current": str(d.prior_current)}))
    if signs:
        # 심각도는 `dart_fs.fs_sign_convention` 과 맞춘다 — 같은 현상, 같은 취급.
        report.add(Finding(
            "note_sign_convention", Severity.WARN,
            f"주석{cur.note_no}: 크기는 같고 부호만 반대인 항목 {len(signs)}건 — "
            "표시규약 차이(재작성 아님)",
            {"note": cur.note_no, "labels": [d.label for d in signs][:10]}))
    if unmatched:
        report.add(Finding(
            "note_unmatched", Severity.WARN,
            f"주석{cur.note_no}: 직전 보고서에 없는 행 {len(unmatched)}건 — "
            "재명명·신설 가능성(불일치가 아니라 짝을 못 지은 것)",
            {"note": cur.note_no, "labels": [d.label for d in unmatched][:10]}))
    return diffs, report


# ── A3. 주석 합계 ↔ 본표 계정 ────────────────────────────────────────────────
#: 단위 표기 → 원 배수. 주석은 표마다 단위를 따로 선언한다.
_UNIT_SCALE = {"원": 1, "천원": 1_000, "백만원": 1_000_000,
               "십억원": 1_000_000_000, "억원": 100_000_000}
#: 본표는 이미 백만원으로 정규화돼 있다(parse_number). 대사 허용오차도 그 단위 기준
#: (excel CHECK_TOL 과 같은 0.001 백만원 = 1,000원 — 반올림은 흡수하고 실제 차이는 잡는다).
NOTE_TIEOUT_TOL = Decimal("0.001")


def check_notes_vs_statements(doc, *, report: ValidationReport | None = None,
                              ) -> ValidationReport:
    """본표 계정 ↔ 그 계정이 가리키는 주석의 합계 대사(당기만).

    연결 고리는 `ParsedDocument.note_map` 의 원천인 **행별 주석번호**다 —
    `fnlttSinglAcntAll` 로는 절대 얻을 수 없고 원문에만 있는 정보라, 이 대사는 원문
    파싱 경로에서만 가능하다.

    ⚠️ **"주석의 합계가 본표와 같다"는 전제는 틀렸다** — 실측으로 두 번 깨졌다:
      ① 주석번호는 **다대다**다. '매출채권'이 주석 [4,5,7,30,32] 를 가리키는데 그중
         명세는 7 뿐이고 나머지는 범주·공정가치·특수관계자다.
      ② 본표와 일치하는 값이 '합계' 라벨이 아닐 수 있다 — 매출채권은 총장부금액에서
         손실충당금을 뺀 **'순장부금액'** 이 본표 값이다(합계가 아니라 차감 결과).
    그래서 검사의 실질은 **"본표 값이 그 주석 어딘가에 실제로 나타나는가"** 다.
    맞으면 대사 성립(PASS), 못 찾으면 **개별 경고를 내지 않고 집계로만** 알린다 —
    대응을 특정하지 못한 것을 불일치라고 부르면 오탐 14건이 쏟아진다(실측).
    """
    report = report or ValidationReport()
    notes = {n.number: n for n in getattr(doc, "notes", [])}
    unmatched: list[str] = []
    for st in getattr(doc, "statements", []):
        if not st.periods:
            continue
        cur_period = st.periods[0]                    # 첫 기수 = 당기
        for row in st.rows:
            if not row.note_refs:
                continue
            stated = row.values.get(cur_period)
            if stated is None:
                continue
            target = Decimal(str(stated))
            hit: tuple[str, str] | None = None       # (주석번호, 행 라벨)
            n_scanned = 0
            for ref in row.note_refs:
                note = notes.get(str(ref))
                if note is None:
                    continue
                for grid in getattr(note, "grids", []) or []:
                    tbl = parse_note_table(grid, note_no=note.number, title=note.title)
                    if tbl is None or tbl.warnings:
                        continue
                    scale = Decimal(_UNIT_SCALE.get(tbl.unit or "", 0))
                    if not scale:
                        continue
                    for r in tbl.rows:
                        for ci in tbl.column_index("current"):
                            v = r.values[ci] if ci < len(r.values) else None
                            if v is None:
                                continue
                            n_scanned += 1
                            if abs(v * scale / Decimal(1_000_000) - target) <= NOTE_TIEOUT_TOL:
                                hit = (note.number, r.label)
                                break
                        if hit:
                            break
                    if hit:
                        break
                if hit:
                    break
            if hit:
                report.add(Finding(
                    "note_tieout", Severity.PASS,
                    f"{st.sj_div or st.title[:10]} '{row.label}' = 주석{hit[0]} "
                    f"'{hit[1]}' ({stated:,} 백만원) — 대사 성립",
                    {"label": row.label, "note": hit[0], "note_label": hit[1],
                     "value": str(stated)}))
            elif n_scanned:
                unmatched.append(f"{row.label}(주석 {list(row.note_refs)})")
    if unmatched:
        # 개별 경고를 내지 않는다 — 주석번호가 다대다라 '대응을 못 찾음'과 '값이 다름'을
        # 구분할 수 없고, 그걸 불일치로 부르면 오탐이 된다. 침묵하지도 않는다(집계로 알림).
        report.add(Finding(
            "note_tieout_unmatched", Severity.WARN,
            f"주석 대사 미확인 {len(unmatched)}건 — 본표 값과 같은 숫자를 해당 주석에서 "
            "찾지 못했습니다(주석번호가 다대다라 대응 특정 불가. 불일치와는 다릅니다): "
            + ", ".join(unmatched[:8]) + ("…" if len(unmatched) > 8 else ""),
            {"labels": unmatched}))
    return report


def _note_key(title: str) -> str:
    """주석 짝짓기 키 — 제목 앞부분(공백 제거).

    주석 **번호는 연도마다 바뀐다**(정책 신설·삭제로 밀린다). 제목이 그나마 안정적이라
    제목으로 짝을 짓고, 못 지은 주석은 '없어졌다'가 아니라 '짝을 못 지었다'로 보고한다.
    """
    return re.sub(r"\s+", "", title or "")[:12]


def compare_documents(cur_doc, prev_doc) -> tuple[ValidationReport, dict]:
    """당해 문서 ↔ 직전 문서 전 주석 대조 → (report, 요약).

    표는 **인덱스로 짝**짓는다(표 순서는 대체로 유지된다). 표 개수가 다르면 겹치는
    만큼만 보고 그 사실을 남긴다 — 억지로 맞추면 엉뚱한 표끼리 비교하게 된다.
    """
    report = ValidationReport()
    prev_by_key = {_note_key(n.title): n for n in getattr(prev_doc, "notes", [])}
    paired = compared = 0
    unpaired: list[str] = []
    for note in getattr(cur_doc, "notes", []):
        other = prev_by_key.get(_note_key(note.title))
        if other is None:
            unpaired.append(f"{note.number} {note.title[:18]}")
            continue
        paired += 1
        a_grids = getattr(note, "grids", []) or []
        b_grids = getattr(other, "grids", []) or []
        if len(a_grids) != len(b_grids):
            report.add(Finding(
                "note_table_count", Severity.WARN,
                f"주석{note.number} '{note.title[:18]}': 표 개수가 다름 "
                f"(당해 {len(a_grids)} / 직전 {len(b_grids)}) — 겹치는 만큼만 대조",
                {"note": note.number}))
        for i in range(min(len(a_grids), len(b_grids))):
            a = parse_note_table(a_grids[i], note_no=note.number, title=note.title)
            b = parse_note_table(b_grids[i], note_no=other.number, title=other.title)
            if a is None or b is None:
                continue
            _, rep = compare_periods(a, b)
            for f in rep.findings:
                report.add(f)
            compared += 1
    if unpaired:
        report.add(Finding(
            "note_unpaired", Severity.WARN,
            f"직전 보고서에서 짝을 찾지 못한 주석 {len(unpaired)}건 — 제목 변경·신설 "
            "가능성(사라진 것과 다릅니다): " + ", ".join(unpaired[:8])
            + ("…" if len(unpaired) > 8 else ""),
            {"notes": unpaired}))
    return report, {"paired": paired, "compared_tables": compared,
                    "unpaired": len(unpaired),
                    "restated": sum(1 for f in report.findings if f.rule == "note_restated"),
                    "reclassified": sum(1 for f in report.findings
                                        if f.rule == "note_reclassified")}


# ── 문서 단위 실행 ───────────────────────────────────────────────────────────
def check_document_notes(doc, *, report: ValidationReport | None = None) -> ValidationReport:
    """ParsedDocument 의 전 주석에 A1·A2·A3 를 건다."""
    report = report or ValidationReport()
    check_notes_vs_statements(doc, report=report)
    for note in getattr(doc, "notes", []):
        # 정합성 검사의 입력은 **병합을 푼 격자**다(원형 tables 는 화면·전송용).
        for raw in getattr(note, "grids", []) or []:
            tbl = parse_note_table(raw, note_no=note.number, title=note.title)
            if tbl is None:
                continue
            # ⚠️ 열 귀속이 불확실한 표에 산술 검사를 돌리면 **오탐이 쏟아진다**(실측:
            # 한 회사에서 9건 중 대부분이 헤더 오독발). 오탐은 경고 전체의 신뢰를
            # 무너뜨리므로, 검사를 하지 않고 **"검사하지 못했다"를 명시**한다 —
            # 조용히 통과시키는 것과도 다르다.
            if tbl.warnings:
                report.add(Finding(
                    "note_table_unparsed", Severity.WARN,
                    f"주석{tbl.note_no} '{tbl.title[:20]}' 표 구조를 확신할 수 없어 "
                    f"정합성 검사를 건너뛰었습니다 — {'; '.join(tbl.warnings)}",
                    {"note": tbl.note_no, "warnings": tbl.warnings}))
                continue
            check_subtotals(tbl, report=report)
            check_rollforward(tbl, report=report)
    return report
