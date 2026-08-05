"""H_FS 시트 플랜 — 다년도 공시 재무제표를 '살아있는 수식' 2시트로 배치.

MS가치평가 비올 최종모델 `H_FS` 탭의 구조를 그대로 따른다(실측 역분석):

    BackData(공시 원문·원 단위)  ←  H_FS 는 전부 `=BackData!AB11/10^6` **참조만**
                                     ("key-in 금지" — 손으로 친 숫자가 0이어야 감사추적이 산다)
    H_FS 하단 체크행:  `자산 = 부채 + 자본` · `원본자료 Refer Check`(=값*10^6=원문셀)
    H_FS 상단 요약  :  버킷 태그(NOA/OA/FA/WC/OL/IBD) → SUMIF 로 집계, 자본총계와 대사

여기서는 그 구조를 결정론적으로 생성한다:

  `rFS`   원문 시트 — DART 응답 원 단위 값 + 계정 메타(sj_div·account_id·ord). 수정 금지.
  `H_FS`  작업 시트 — 공시 원형 순서·계층(전각공백 들여쓰기) + 연도 열 + 체크행.

시트를 나눈 이유(모델러스 `r` 접두사 격리 + 비올 BackData 분리, 두 골든이 일치):
  ① key-in 금지가 **시트 경계로 물리 강제**된다(원문/가공을 눈으로 구분하지 않는다).
  ② Refer Check(`=값*10^6=원문셀`)가 성립한다 — 같은 탭이면 자기참조라 검증이 아니다.
  ③ **재조회 갱신 경계** — rFS만 통째로 갈아끼우면 H_FS의 사람 판단(버킷 태그·재분류 메모)이 산다.
  ④ **단위 격리** — rFS=원 / H_FS=백만원. 한 탭에 두 단위가 섞이는 것이 단위규약 결함의 온상.

**항등식 SSOT 는 `ingest/fs_integrity.IDENTITIES` 하나다.** 서버는 그것으로 값을 판정하고,
이 모듈은 **같은 항등식을 엑셀 수식으로 다시 심는다**. 그래서 화면의 PASS 와 워크북의
TRUE 가 다른 규칙에서 나올 수 없다(세 표면 drift 를 구조적으로 차단).

산출 `WorkbookPlan` 은 두 소비처를 갖는다:
  ① Office.js Task Pane — `range.formulas` 에 그대로 넣는다("=" 로 시작하면 수식, 아니면 값).
  ② `write_xlsx()` — stdlib 라이터로 .xlsx 파일 생성(다운로드 경로).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ingest.dart_fs import FsAccount, MultiYearFs
from ingest.fs_integrity import A_EQUITY, IDENTITIES, find_account
from ingest.fs_mapper import classify

#: `r` 접두사 원자료 격리 규약(docs/reference/모델러스_통합모델_5.4.md §1.1) —
#: 외부에서 들어온 원자료는 `r*` 시트에만 존재하고 절대 수정하지 않는다. 모델 시트는 참조만.
RAW_SHEET = "rFS"
FS_SHEET = "H_FS"

#: 비올 H_FS 요약 블록의 버킷(표시 순서). fs_mapper 버킷을 자산/부채 측면으로 접어 만든다.
#: 마지막 `?` 는 자동 분류 미완 잔액 — 이게 있어야 합계가 자본총계와 대사된다.
SUMMARY_BUCKETS: tuple[str, ...] = ("NOA", "OA", "FA", "WC", "OL", "IBD", "?")

#: fs_mapper BS 버킷 → (자산측 태그, 부채측 태그). 자본은 태그 없음(요약 대사 상대편).
_BUCKET_MAP: dict[str, tuple[str | None, str | None]] = {
    "WC(운전자본)": ("WC", "WC"),
    "FA(유형자산)": ("FA", None),
    "NOA(비영업자산)": ("NOA", None),
    "IBD(이자부부채)": (None, "IBD"),
    "OAL(기타)": ("OA", "OL"),
    "EQU(자본)": (None, None),
}

#: BS 구간 앵커 — 이 계정을 만나면 이후 계정의 소속을 그 구간으로 **상속**한다.
#: ⚠️ 순서 가정 금지: DART 는 사업연도마다 표시순서를 바꿔 싣는다(삼성전자 2025년
#: 보고서는 `자산총계 → 유동자산 … → 자본총계 … → 유동부채` 즉 **자산→자본→부채** 순,
#: 2021년 보고서는 `유동자산 … → 자산총계 → 유동부채` 순). 단방향 상태기계
#: (자산→부채→자본)로 짜면 2025 배치에서 자본이 통째로 자산측에 섞여 SUMIF 버킷이 오염된다.
_SIDE_ANCHOR_IDS: dict[str, str] = {
    "ifrs-full_Assets": "asset", "ifrs-full_CurrentAssets": "asset",
    "ifrs-full_NoncurrentAssets": "asset",
    "ifrs-full_Liabilities": "liability", "ifrs-full_CurrentLiabilities": "liability",
    "ifrs-full_NoncurrentLiabilities": "liability",
    "ifrs-full_Equity": "equity",
    "ifrs-full_EquityAttributableToOwnersOfParent": "equity",
    "ifrs-full_NoncontrollingInterests": "equity",
}
_SIDE_ANCHOR_NAMES: dict[str, str] = {
    "자산": "asset", "유동자산": "asset", "비유동자산": "asset", "자산총계": "asset",
    "부채": "liability", "유동부채": "liability", "비유동부채": "liability", "부채총계": "liability",
    "자본": "equity", "자본총계": "equity", "지배기업소유주지분": "equity", "비지배지분": "equity",
}
#: 총계 성격이라 **앵커로 쓰면 안 되는** 계정(자기 자신만 표시).
_NOT_ANCHOR_IDS = frozenset({"ifrs-full_EquityAndLiabilities"})
_NOT_ANCHOR_NAMES = ("자본과부채총계", "부채와자본총계", "부채및자본총계")

#: 개별 계정을 표준계정코드 문자열로 직접 판정(앵커 상속보다 강한 증거). 앞에서부터 첫 매칭.
#: ⚠️ 일반 토큰 `Equity` 를 쓰면 **자산을 자본으로 오판**한다 — 실측:
#:   `ifrs-full_InvestmentAccountedForUsingEquityMethod`(관계기업 및 공동기업 투자, 자산)
#:   `ifrs-full_NoncurrentInvestmentsInEquityInstruments…`(기타포괄손익-공정가치금융자산, 자산)
#: 그래서 자본은 **구체 토큰만** 인정하고, 위 자산 예외를 앞에 둔다.
_ID_SIDE_RULES: tuple[tuple[str, str], ...] = (
    ("EquityAndLiabilities", ""),                  # 총계 — 판정 보류(상속에 맡김)
    ("InvestmentAccountedForUsingEquityMethod", "asset"),
    ("InvestmentsInEquityInstruments", "asset"),
    ("Liabilit", "liability"), ("Payable", "liability"), ("Borrowings", "liability"),
    ("Provision", "liability"), ("Bonds", "liability"), ("Debentures", "liability"),
    ("EquityAttributable", "equity"), ("StockholdersEquity", "equity"),
    ("RetainedEarnings", "equity"), ("IssuedCapital", "equity"),
    ("SharePremium", "equity"), ("TreasuryShares", "equity"),
    ("NoncontrollingInterests", "equity"),
    ("Assets", "asset"), ("Receivable", "asset"), ("Inventories", "asset"),
    ("CashAndCash", "asset"), ("Prepaid", "asset"),
)

#: 자동 분류가 안 된 개별계정에 붙는 태그. **버리지 않고 명시**한다 —
#: 무태그로 두면 SUMIF 에서 증발해 자본총계 대사가 조용히 깨지고, 원인이 '누락'인지
#: '오분류'인지 알 수 없다. `?` 잔액을 0으로 줄이는 것이 곧 사람의 계정분류 작업이다.
UNCLASSIFIED_TAG = "?"

#: 제표 표시명
_SJ_TITLE = {"BS": "재무상태표", "IS": "손익계산서", "CIS": "포괄손익계산서",
             "CF": "현금흐름표", "SCE": "자본변동표"}


@dataclass
class SheetPlan:
    """한 시트의 셀 격자. 문자열이 '=' 로 시작하면 수식, 그 외는 값."""
    name: str
    rows: list[list[object]] = field(default_factory=list)
    #: 고정틀 기준 셀(Office.js/xlsx 모두 선택 적용)
    freeze: str | None = None
    #: 열 너비 힌트(문자 수)
    widths: list[int] = field(default_factory=list)
    #: 굵게 표시할 1-based 행 번호(소계·체크행)
    bold_rows: list[int] = field(default_factory=list)
    #: 편집 금지 안내를 붙일 시트인가
    readonly_hint: bool = False


@dataclass
class WorkbookPlan:
    sheets: list[SheetPlan]
    meta: dict = field(default_factory=dict)


# ── 열 주소 ───────────────────────────────────────────────────────────────────
def col_letter(idx: int) -> str:
    """0-based 열 인덱스 → 엑셀 열 문자(A, B, ..., Z, AA...)."""
    s = ""
    n = idx + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _side_of(acc: FsAccount, inherited: str) -> tuple[str, str]:
    """BS 계정의 소속 구간 판정 → (이 계정의 side, 다음 계정이 상속할 side).

    **표시순서를 가정하지 않는다.** 판정 우선순위:
      ① 구간 앵커(자산총계·유동자산·부채총계·자본총계…) — 자기 판정 + 이후 상속 갱신
      ② 표준계정코드 문자열 규칙(`*Liabilit*`·`*Equity*`·`*Assets*`…) — 자기만 판정
      ③ 앵커 상속
    ①에서 `자본과부채총계` 류는 앵커에서 제외한다 — 표 끝의 총계라 이걸 앵커로 삼으면
    뒤따르는 것이 없는데도 구간을 바꿔버린다.
    """
    nm = acc.account_nm.replace(" ", "").strip()
    if acc.account_id in _NOT_ANCHOR_IDS or nm in _NOT_ANCHOR_NAMES:
        return inherited, inherited
    anchor = _SIDE_ANCHOR_IDS.get(acc.account_id) or _SIDE_ANCHOR_NAMES.get(nm)
    if anchor:
        return anchor, anchor
    for token, side in _ID_SIDE_RULES:
        if token in acc.account_id:
            return (side or inherited), inherited
    return inherited, inherited


def bucket_tag(acc: FsAccount, side: str) -> str:
    """계정 → 요약 버킷 태그. 소계·총계와 자본은 태그 없음(이중계상 방지).

    태그가 붙은 개별계정만 SUMIF 에 잡히므로, 총계 행에 태그가 붙으면 합계가 두 배가
    된다. 이것이 비올 H_FS 에서 총계 행의 태그 열이 비어 있는 이유다.

    자동 분류가 안 된 개별계정은 빈칸이 아니라 `?` 를 받는다 — 그래야
    `Σ버킷 = 자본총계` 대사가 성립하고, 대사가 깨졌을 때 원인이 '분류 미완'인지
    '오분류'인지가 구분된다(실측: 삼성전자 BS 에서 무태그 자산 30조가 조용히 증발했다).
    """
    if side == "equity" or acc.depth <= 1 or side not in ("asset", "liability"):
        return ""
    c = classify(acc.account_nm, "BS", account_id=acc.account_id or None)
    pair = _BUCKET_MAP.get(c.bucket, (None, None))
    tag = pair[0] if side == "asset" else pair[1]
    return tag or UNCLASSIFIED_TAG


# ── 플랜 생성 ─────────────────────────────────────────────────────────────────
def build_fs_sheets(fs: MultiYearFs, *, company: str = "",
                    raw_sheet: str = RAW_SHEET, fs_sheet: str = FS_SHEET) -> WorkbookPlan:
    """다년도 공시 재무제표 → (원문 시트, H_FS 시트) 플랜.

    연도 열은 **과거→최근**(왼→오) 순. 모델 관행이며 YoY 수식이 오른쪽으로 흐른다.
    """
    years = list(fs.years)
    raw, raw_row_of = _build_raw_sheet(fs, years, raw_sheet, company)
    hfs, blocks = _build_hfs_sheet(fs, years, raw_sheet, fs_sheet, raw_row_of, company)
    return WorkbookPlan(
        sheets=[raw, hfs],
        meta={"corp_code": fs.corp_code, "fs_div": fs.fs_div, "reprt_code": fs.reprt_code,
              "years": years, "accounts": len(fs.accounts),
              "raw_sheet": raw_sheet, "fs_sheet": fs_sheet,
              "notes": list(fs.notes),
              # 배치 미리보기 — 시트가 워크북에서 차지할 공간을 기입 전에 알 수 있게.
              "layout": [_layout_of(s, years) for s in (raw, hfs)],
              "blocks": blocks},
    )


def _layout_of(sheet: SheetPlan, years: list[int]) -> dict:
    """시트가 차지할 공간(행×열)과 연도 열 주소 — '공간이 맞는지' 를 기입 전에 답한다."""
    n_row = len(sheet.rows)
    n_col = max((len(r) for r in sheet.rows), default=0)
    first = 6 if sheet.readonly_hint else 2          # rFS 는 G열~, H_FS 는 C열~
    return {"name": sheet.name, "rows": n_row, "cols": n_col,
            "range": f"A1:{col_letter(max(n_col - 1, 0))}{n_row}",
            "year_cols": f"{col_letter(first)}:{col_letter(first + len(years) - 1)}"}


#: reprt_code → 사람이 읽는 보고서 종류.
_REPRT_NM = {"11011": "사업보고서", "11012": "반기보고서",
             "11013": "1분기보고서", "11014": "3분기보고서"}


def _status_line(fs: MultiYearFs, company: str, *, unit: str, span: str) -> str:
    """시트 2행 상태 헤더 — 모델러스 '시트 헤더 규약'(전 시트 공통 상태 표시)의 최소판.

    이 한 줄만 봐도 **무엇을·어느 기준으로·어느 단위로·몇 개년** 담았는지가 확정된다.
    연도 열 주소(span)를 함께 적는 이유: 다른 시트에서 이 표를 참조할 때 열이 어디부터
    어디까지인지 세지 않아도 되게 하려는 것.
    """
    return " · ".join([
        f"{company or fs.corp_code}({fs.corp_code})",
        "연결(CFS)" if fs.fs_div == "CFS" else "별도(OFS)",
        _REPRT_NM.get(fs.reprt_code, fs.reprt_code),
        f"단위: {unit}",
        span,
        "출처: 금융감독원 OpenDART(정확성 무보증)",
    ])


def _build_raw_sheet(fs: MultiYearFs, years: list[int], name: str,
                     company: str) -> tuple[SheetPlan, dict[tuple, int]]:
    """원문 시트 — DART 원 단위 값. H_FS 가 참조할 행 번호 맵을 함께 반환."""
    head = ["구분", "제표명", "표준계정코드", "계정명(원문)", "계층", "공시순서"]
    year_cols = [str(y) for y in years]
    first, last = col_letter(6), col_letter(5 + len(years))
    rows: list[list[object]] = [
        ["rFS — DART 공시 원자료 (fnlttSinglAcntAll)"],
        [_status_line(fs, company, unit="원(공시 원문)",
                      span=f"연도 {first}:{last} = {years[0]}~{years[-1]} {len(years)}개년")],
        ["이 시트는 수정하지 마세요. H_FS 는 전부 이 시트를 참조합니다(key-in 금지)."],
        head + year_cols + ["채택출처(사업연도)", "접수번호"],
    ]
    raw_row_of: dict[tuple, int] = {}
    for acc in fs.accounts:
        r = len(rows) + 1                      # 1-based 행 번호
        raw_row_of[acc.key] = r
        adopted = next((acc.adopted(y) for y in reversed(years) if acc.adopted(y)), None)
        vals: list[object] = []
        for y in years:
            o = acc.adopted(y)
            # 원 단위 정수로 되돌린다 — 백만원 Decimal × 1e6 은 오차 없이 원복된다.
            vals.append("" if (o is None or o.value is None) else int(o.value * Decimal("1e6")))
        rows.append([acc.sj_div, acc.sj_nm, acc.account_id, acc.account_nm,
                     acc.depth, acc.order] + vals
                    + [adopted.source_year if adopted else "",
                       adopted.rcept_no if adopted else ""])
    return SheetPlan(name=name, rows=rows, freeze="A5", readonly_hint=True,
                     widths=[6, 14, 30, 34, 6, 8] + [16] * len(years) + [14, 18],
                     bold_rows=[4]), raw_row_of


def _build_hfs_sheet(fs: MultiYearFs, years: list[int], raw_sheet: str, name: str,
                     raw_row_of: dict[tuple, int], company: str
                     ) -> tuple[SheetPlan, list[dict]]:
    """H_FS — 공시 원형 + 연도 열 + 버킷 태그 + 체크행. 값은 전부 원문 시트 참조.

    반환 blocks: 제표별 행 범위(화면 미리보기·후속 참조용).
    """
    n_year = len(years)
    first_col = 2                              # A=버킷태그, B=계정명, C~=연도
    year_letters = [col_letter(first_col + i) for i in range(n_year)]
    rows: list[list[object]] = []
    bold: list[int] = []
    # 계정 → H_FS 행 번호(항등식 수식이 참조)
    hfs_row_of: dict[tuple, int] = {}

    def emit(cells: list[object], *, strong: bool = False) -> int:
        rows.append(cells)
        r = len(rows)
        if strong:
            bold.append(r)
        return r

    stmt_names = " · ".join(_SJ_TITLE.get(k, k) for k in fs.statements)
    emit([f"H_FS — {stmt_names}"], strong=True)
    emit([_status_line(fs, company, unit="백만원",
                       span=f"연도 {year_letters[0]}:{year_letters[-1]} = "
                            f"{years[0]}~{years[-1]} {n_year}개년")], strong=True)
    emit([f"key-in 금지 — 모든 숫자는 {raw_sheet} 참조. 체크행이 TRUE 여야 원문과 일치합니다."])

    # ── 요약 블록(자리만 잡고, BS 블록 렌더 후 SUMIF 범위를 채운다) ─────────
    emit(["", "밸류에이션 버킷"] + [str(y) for y in years], strong=True)
    summary_rows = {
        b: emit(["", b] + [""] * n_year + (
            ["← 자동 분류 미완. 아래 표의 태그 열을 채우면 0 이 됩니다."]
            if b == UNCLASSIFIED_TAG else []))
        for b in SUMMARY_BUCKETS}
    summary_total_row = emit(["", "합계"] + [""] * n_year, strong=True)
    summary_check_row = emit(["", "자본총계 대사"] + [""] * n_year, strong=True)
    emit([])

    asset_span: list[int] = []
    liab_span: list[int] = []
    equity_row_ref: str | None = None
    blocks: list[dict] = []

    for sj_div, accounts in fs.statements.items():
        if not accounts:
            continue
        title = _SJ_TITLE.get(sj_div, sj_div)
        emit([f"* {title}", f"({sj_div}) {len(accounts)}계정 · 공시 표시순서·계층 보존"],
             strong=True)
        emit(["버킷", "구분"] + [str(y) for y in years], strong=True)
        start = len(rows) + 1
        state = "asset"
        for acc in accounts:
            side = ""
            tag = ""
            if sj_div == "BS":
                side, state = _side_of(acc, state)
                tag = bucket_tag(acc, side)
            raw_r = raw_row_of[acc.key]
            cells: list[object] = [tag, acc.label()]
            for i, y in enumerate(years):
                o = acc.adopted(y)
                if o is None or o.value is None:
                    cells.append("")
                else:
                    cells.append(f"={raw_sheet}!{col_letter(6 + i)}{raw_r}/10^6")
            r = emit(cells, strong=(acc.depth <= 1))
            hfs_row_of[acc.key] = r
            if sj_div == "BS":
                if side == "asset":
                    asset_span.append(r)
                elif side == "liability":
                    liab_span.append(r)
        end = len(rows)

        # 원본 대사 — 비올의 'Refer Check' 를 블록 전체로 확장한 형태.
        # 백만원으로 나눈 값을 다시 원으로 돌려 원문 셀과 **전 계정** 정확일치를 요구한다.
        refer = ["", "원본자료 Refer Check(전 계정)"]
        raw_start, raw_end = raw_row_of[accounts[0].key], raw_row_of[accounts[-1].key]
        for i, letter in enumerate(year_letters):
            raw_letter = col_letter(6 + i)
            refer.append(
                f"=SUMPRODUCT(--(ROUND({letter}{start}:{letter}{end}*10^6,0)"
                f"<>{raw_sheet}!{raw_letter}{raw_start}:{raw_letter}{raw_end}))=0")
        blocks.append({"sj_div": sj_div, "title": title, "accounts": len(accounts),
                       "start": start, "end": end,
                       "range": f"A{start}:{year_letters[-1]}{end}"})
        emit(refer, strong=True)
        emit([])

    # ── 항등식 체크행 — fs_integrity.IDENTITIES 를 엑셀 수식으로 재현 ────────
    _emit_identity_checks(fs, year_letters, hfs_row_of, emit)

    # ── 요약 블록 SUMIF 채우기(BS 구간이 확정된 뒤) ─────────────────────────
    equity_acc = find_account(fs, A_EQUITY)
    if equity_acc is not None and equity_acc.key in hfs_row_of:
        equity_row_ref = str(hfs_row_of[equity_acc.key])
    _fill_summary(rows, summary_rows, summary_total_row, summary_check_row,
                  year_letters, asset_span, liab_span, equity_row_ref)

    return SheetPlan(name=name, rows=rows, freeze="C5",
                     widths=[8, 40] + [15] * n_year, bold_rows=bold), blocks


def _runs(rows: list[int]) -> list[tuple[int, int]]:
    """정렬된 행 번호 목록 → 연속 구간 [(시작, 끝), ...].

    자산·부채 구간을 min~max 하나로 잡으면, 공시 배치가 `자산 → 자본 → 부채` 인 해에는
    (실측: 삼성전자 2025년 보고서) 그 사이에 낀 자본 행까지 SUMIF 범위에 들어간다.
    구간을 쪼개 더하면 배치가 어떻든 정확하다.
    """
    out: list[tuple[int, int]] = []
    for r in sorted(rows):
        if out and r == out[-1][1] + 1:
            out[-1] = (out[-1][0], r)
        else:
            out.append((r, r))
    return out


def _fill_summary(rows: list[list[object]], summary_rows: dict[str, int],
                  total_row: int, check_row: int, year_letters: list[str],
                  asset_span: list[int], liab_span: list[int],
                  equity_row: str | None) -> None:
    """버킷 요약 = Σ SUMIF(자산구간) − Σ SUMIF(부채구간). 비올 H_FS 와 동일 형태.

    자산은 +, 부채는 − 로 접어 **투하자본 관점의 순액**을 만든다. 그래서 합계가
    자본총계와 같아야 하고(대사행), 어긋나면 태그 누락·중복이 있다는 뜻이다.
    """
    if not asset_span:
        return
    a_runs, l_runs = _runs(asset_span), _runs(liab_span)
    for bucket, r in summary_rows.items():
        for i, letter in enumerate(year_letters):
            tag_ref = f"$B${r}"
            plus = "+".join(f"SUMIF($A${s}:$A${e},{tag_ref},{letter}${s}:{letter}${e})"
                            for s, e in a_runs)
            minus = "".join(f"-SUMIF($A${s}:$A${e},{tag_ref},{letter}${s}:{letter}${e})"
                            for s, e in l_runs)
            rows[r - 1][2 + i] = f"={plus}{minus}"
    for i, letter in enumerate(year_letters):
        first, last = min(summary_rows.values()), max(summary_rows.values())
        rows[total_row - 1][2 + i] = f"=SUM({letter}{first}:{letter}{last})"
        rows[check_row - 1][2 + i] = (
            f"=ROUND({letter}{total_row},6)=ROUND({letter}{equity_row},6)"
            if equity_row else "자본총계 앵커 부재 — 대사 불가")


def _emit_identity_checks(fs: MultiYearFs, year_letters: list[str],
                          hfs_row_of: dict[tuple, int], emit) -> int:
    """서버 항등식(IDENTITIES)을 그대로 엑셀 체크행으로 심는다.

    앵커가 H_FS 에 없으면 그 항등식은 **행 자체를 만들지 않는다** — 계산 못 하는 체크를
    FALSE 로 띄우면 진짜 결함과 구분이 안 된다(허위 경보 금지).
    """
    emitted = 0
    header_done = False
    for ident in IDENTITIES:
        refs_l = [hfs_row_of.get(a.key) if (a := find_account(fs, anc)) else None
                  for anc in ident.lhs]
        refs_r = [hfs_row_of.get(a.key) if (a := find_account(fs, anc)) else None
                  for anc in ident.rhs]
        opt = {anc.label for anc in ident.optional}
        lhs = [(anc.label, r) for anc, r in zip(ident.lhs, refs_l)]
        rhs = [(anc.label, r) for anc, r in zip(ident.rhs, refs_r)]
        if any(r is None for lbl, r in lhs + rhs if lbl not in opt):
            continue
        if not header_done:
            emit(["* 정합성 체크", "서버 판정(fs_integrity)과 같은 항등식 — TRUE 여야 정상"],
                 strong=True)
            header_done = True
        cells: list[object] = ["", ident.title]
        for letter in year_letters:
            l_expr = "+".join(f"{letter}{r}" for _, r in lhs if r is not None)
            r_expr = "+".join(f"{letter}{r}" for _, r in rhs if r is not None)
            cells.append(f"=ROUND({l_expr},6)=ROUND({r_expr},6)")
        emit(cells, strong=True)
        emitted += 1
    return emitted


# ── 소비처 ────────────────────────────────────────────────────────────────────
def plan_to_json(plan: WorkbookPlan) -> dict:
    """Office.js 로 넘길 직렬화 — `range.formulas` 에 그대로 넣을 수 있는 격자."""
    return {
        "meta": plan.meta,
        "sheets": [{
            "name": s.name,
            "rows": [[("" if c is None else c) for c in row] for row in s.rows],
            "freeze": s.freeze, "widths": s.widths,
            "bold_rows": s.bold_rows, "readonly_hint": s.readonly_hint,
        } for s in plan.sheets],
    }


def write_xlsx(plan: WorkbookPlan, path: str) -> str:
    """플랜 → .xlsx 파일(stdlib 라이터). 수식은 캐시값 없이 기입 — 열면 재계산된다."""
    from .xlsx_writer import Workbook
    wb = Workbook()
    for sp in plan.sheets:
        sh = wb.add_sheet(sp.name)
        for r, row in enumerate(sp.rows, start=1):
            for c, val in enumerate(row):
                if val is None or val == "":
                    continue
                ref = f"{col_letter(c)}{r}"
                if isinstance(val, str) and val.startswith("="):
                    sh.formula(ref, val[1:])
                elif isinstance(val, (int, float, Decimal)):
                    sh.num(ref, float(val))
                else:
                    sh.text(ref, str(val))
    wb.save(path)
    return path
