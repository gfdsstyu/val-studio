"""다년도 공시 재무제표 수집 — 공시 원형(계정 순서·계층) 보존 + 재작성 교차대사.

`dart_client.financial_statements` 는 **당기 금액 한 열**만 방출한다(단년 매핑용).
여기서는 밸류에이션 모델의 H_FS 탭(MS가치평가 비올 최종모델)처럼 **여러 사업연도를
공시 원형 그대로 한 판에** 올리기 위해 필요한 것을 전부 살린다:

  ① 3개 금액열   — fnlttSinglAcntAll 한 응답에 당기/전기/전전기가 함께 실린다.
                    2021~2025 를 각 연도 보고서로 받으면 **연도마다 최대 3회 중복 관측**된다.
  ② 공시 정렬순서 — `ord` + `sj_nm`. 계정을 알파벳/버킷으로 재배열하면 공시 원형이 깨진다.
  ③ 계층(depth)  — 제목행/소계/개별계정. H_FS 의 전각공백 들여쓰기를 복원한다.

**중복 관측이 곧 검증**이다. 같은 연도 같은 계정이 서로 다른 보고서에서 다른 값으로
오면 그것이 전기 재작성·재분류의 실측 증거다(WARN 으로 표면화, 채택값은 **가장 최근
공시**). 이는 skill `fs_clean.py` 의 cross_period_tie 와 같은 사상이며, 차이는 사람이
붙여넣는 대신 **API 응답에서 공짜로 나온다**는 점이다.

정직 원칙: 공시 원문이 안 맞으면 그것은 사실이므로 지우지 않는다. 우리가 만든 값
(단위환산·집계)이 안 맞으면 그것은 결함이므로 FAIL 로 막는다. 판정은 fs_integrity 가 한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .dart_client import FS_CONSOLIDATED, REPRT_ANNUAL, DartClient
from .validators import Finding, Severity, ValidationReport, parse_number

# 한 응답에 실리는 금액열 → 기준 사업연도로부터의 역년(offset).
# 사업보고서(11011)에서만 성립한다 — 분·반기는 thstrm_amount 가 3개월 값이라
# 연도 귀속이 다르므로 확장하지 않는다(아래 `_amount_columns` 게이트).
_ANNUAL_COLS: tuple[tuple[str, int], ...] = (
    ("thstrm_amount", 0),
    ("frmtrm_amount", 1),
    ("bfefrmtrm_amount", 2),
)

#: 공시 제표 표시 순서. 회사별로 IS/CIS 중 하나만 있을 수 있다.
STATEMENT_ORDER: tuple[str, ...] = ("BS", "IS", "CIS", "CF", "SCE")

#: 기본 수집 제표 — 재무상태표·손익·포괄손익·현금흐름표(모델이 쓰는 3표).
#: SCE(자본변동표)는 차원(멤버)별로 같은 계정명이 수십 번 반복돼 표를 압도하므로 기본 제외.
#: 필요하면 `statements=("BS","IS","CIS","CF","SCE")` 로 명시해 포함한다.
DEFAULT_STATEMENTS: tuple[str, ...] = ("BS", "IS", "CIS", "CF")

#: 재무상태표 제목행(대분류) — depth 0
_TITLE_NAMES = ("자산", "부채", "자본")
#: 소계·총계 앵커 — depth 1. account_id 우선, 명칭은 폴백.
_SUBTOTAL_IDS = frozenset({
    "ifrs-full_Assets", "ifrs-full_CurrentAssets", "ifrs-full_NoncurrentAssets",
    "ifrs-full_Liabilities", "ifrs-full_CurrentLiabilities",
    "ifrs-full_NoncurrentLiabilities", "ifrs-full_Equity",
    "ifrs-full_EquityAndLiabilities",
})
_SUBTOTAL_SUFFIXES = ("총계", "합계", "총액")
_SUBTOTAL_NAMES = ("유동자산", "비유동자산", "유동부채", "비유동부채")

#: 표준계정코드를 쓰지 않은 회사 확장계정 표식(DART 고정 문자열).
NON_STANDARD_ID = "-표준계정코드 미사용-"


class MultiYearFsError(RuntimeError):
    """다년도 수집 자체가 불가능한 상황(연도 전량 실패 등)."""


@dataclass(frozen=True)
class Observation:
    """한 계정·한 연도의 관측치 1건 — '어느 보고서의 어느 열에서 왔나'."""
    year: int
    value: Decimal | None      # 백만원
    raw: str | None            # 원문 문자열(원 단위, 콤마 포함 그대로)
    source_year: int           # 이 값을 실어온 보고서의 사업연도
    column: str                # thstrm_amount / frmtrm_amount / bfefrmtrm_amount
    rcept_no: str | None

    @property
    def is_current(self) -> bool:
        """당기열 관측 — 재작성 대사에서 '가장 원본에 가까운 값'."""
        return self.column == "thstrm_amount"


@dataclass
class FsAccount:
    """공시 재무제표의 한 행(계정) — 다년도 값 + 공시 원형 메타."""
    sj_div: str
    sj_nm: str
    account_id: str
    account_nm: str
    account_detail: str = ""
    order: float = 0.0             # 정렬키(최신 보고서 ord 기준, 삽입분은 소수)
    depth: int = 2
    depth_basis: str = "default"
    currency: str | None = None
    obs: dict[int, list[Observation]] = field(default_factory=dict)
    #: 같은 보고서 안에서 (제표·계정명·상세)가 반복될 때의 출현 순번(0-based).
    occurrence: int = 0
    #: 연도별 account_id 이력 — 표준코드 교체 추적(실측 흔한 현상).
    id_history: dict[int, str] = field(default_factory=dict)
    #: 연도별 표시명 이력 — 계정 재명명 추적.
    name_history: dict[int, str] = field(default_factory=dict)
    #: 확정된 병합키(alias 해소 결과). 생성 시 주입된다.
    merge_key: tuple = ()

    @property
    def key(self) -> tuple:
        """병합키 — `_resolve_alias` 가 **표준코드 우선, 계정명 폴백**으로 정한 정본 키.

        단일 키로는 풀리지 않는다(둘 다 실측):
          - **id 변경** — 삼성전자 BS 7건이 `-표준계정코드 미사용-`→`ifrs-full_*`.
            id 를 키에 넣으면 같은 '미수금'이 두 줄로 쪼개진다.
          - **이름 변경** — `관계종속기업투자자산-지분법`→`관계기업 및 공동기업 투자`
            (표준코드는 동일). 이름을 키에 넣으면 이번엔 이쪽이 쪼개져 **자산이 8.9조
            이중계상**된다.
        그래서 id 로 먼저 이어붙이고, id 가 비표준이거나 새로 등장하면 이름으로 잇는다.
        둘 다 바뀐 경우는 기계가 판정할 수 없으므로 병합하지 않고 `fs_duplicate_suspect`
        로 표면화한다(판단은 사람).
        """
        return self.merge_key

    @property
    def is_standard(self) -> bool:
        return bool(self.account_id) and self.account_id != NON_STANDARD_ID

    def value(self, year: int) -> Decimal | None:
        """채택값 — 가장 최근 공시의 관측(재작성 반영본)을 채택.

        같은 source_year 안에서는 당기열을 비교열보다 우선한다(원본에 더 가깝다).
        """
        best = self.adopted(year)
        return best.value if best else None

    def adopted(self, year: int) -> Observation | None:
        obs = [o for o in self.obs.get(year, []) if o.value is not None]
        if not obs:
            obs = self.obs.get(year, [])
        if not obs:
            return None
        return max(obs, key=lambda o: (o.source_year, o.is_current))

    def label(self) -> str:
        """H_FS 표기용 계정명 — 전각공백 들여쓰기로 계층을 복원."""
        return "　" * self.depth + self.account_nm


@dataclass
class MultiYearFs:
    """다년도 공시 재무제표 — 제표별 계정(공시 순서) + 수집 리포트."""
    corp_code: str
    fs_div: str
    reprt_code: str
    years: list[int]
    accounts: list[FsAccount]
    report: ValidationReport = field(default_factory=ValidationReport)
    notes: list[str] = field(default_factory=list)
    #: 연도 → 그 연도 데이터를 실어온 보고서들의 rcept_no
    sources: dict[int, list[str]] = field(default_factory=dict)

    def statement(self, sj_div: str) -> list[FsAccount]:
        return [a for a in self.accounts if a.sj_div == sj_div]

    @property
    def statements(self) -> dict[str, list[FsAccount]]:
        """제표별 계정 — 공시 표시 순서. 존재하는 제표만 담는다."""
        out: dict[str, list[FsAccount]] = {}
        for a in self.accounts:
            out.setdefault(a.sj_div, []).append(a)
        return {k: out[k] for k in STATEMENT_ORDER if k in out} | {
            k: v for k, v in out.items() if k not in STATEMENT_ORDER}

    @property
    def ok(self) -> bool:
        return self.report.ok


# ── 수집 ──────────────────────────────────────────────────────────────────────
def fetch_multi_year(
    client: DartClient,
    corp_code: str,
    years: list[int] | tuple[int, ...],
    *,
    fs_div: str = FS_CONSOLIDATED,
    reprt_code: str = REPRT_ANNUAL,
    tolerate_missing: bool = True,
    statements: tuple[str, ...] | None = DEFAULT_STATEMENTS,
) -> MultiYearFs:
    """사업연도 목록을 한 번에 조회해 하나의 다년도 표로 병합.

    연도당 API 1콜(fnlttSinglAcntAll). 각 응답이 3개년을 싣기 때문에 요청 연도보다
    과거 연도도 관측치로 함께 쌓이지만, 최종 표의 열은 `years` 로 한정한다
    (요청하지 않은 연도가 조용히 끼어들면 모델 열 수가 흔들린다).

    tolerate_missing=True 면 개별 연도 조회 실패를 note 로 남기고 계속한다
    (신규 상장·합병 등으로 특정 연도만 없는 경우가 흔하다). 전 연도 실패면 예외.
    """
    from .dart_client import DartError  # 지역 import — 순환 회피

    want = sorted({int(y) for y in years})
    if not want:
        raise MultiYearFsError("years 가 비어 있음")
    reports: list[dict] = []
    notes: list[str] = []
    for y in sorted(want, reverse=True):          # 최신부터 — 정렬 앵커가 최신 공시
        try:
            rows = client.financial_statement_rows(
                corp_code, y, reprt_code=reprt_code, fs_div=fs_div)
        except DartError as e:
            if not tolerate_missing:
                raise
            notes.append(f"{y}: 조회 실패({e.status} {e.message}) — 해당 보고서 제외")
            continue
        if not rows:
            notes.append(f"{y}: 응답 계정 0건 — 제외(금융업 XBRL 미제공 등)")
            continue
        reports.append({"bsns_year": y, "rows": rows})
    if not reports:
        # ⚠️ 여기서 notes 를 버리면 안 된다 — 연도별 DART 상태코드를 이미 손에 쥐고 있는데
        # "확인하세요"만 던지면 사용자는 corp_code·fs_div·연도 중 무엇이 문제인지 알 길이
        # 없다(그 셋을 다 바꿔가며 재조회하게 된다). 본 사유를 그대로 싣는다.
        detail = " / ".join(notes) if notes else "사유 미상"
        # 전 연도가 '데이터 없음(013)'인데 연결을 요청했다면 원인이 거의 확정적이다:
        # 종속회사가 없어 **연결재무제표를 작성하지 않는 회사**다(별도만 제출).
        hint = ""
        if fs_div == FS_CONSOLIDATED and len([n for n in notes if "(013" in n]) == len(want):
            hint = (" · 전 연도가 '데이터 없음(013)'입니다 — 연결재무제표를 제출하지 않는"
                    " 회사일 수 있으니 **별도(OFS)** 로 다시 조회하세요")
        raise MultiYearFsError(
            f"요청 연도 {want} 전량 조회 실패(fs_div={fs_div}): {detail}{hint}")
    fs = build_multi_year(reports, corp_code=corp_code, fs_div=fs_div,
                          reprt_code=reprt_code, years=want, statements=statements)
    fs.notes = notes + fs.notes
    return fs


# ── 병합(순수 함수 — 네트워크 없이 전량 테스트 가능) ──────────────────────────
def build_multi_year(
    reports: list[dict],
    *,
    corp_code: str = "",
    fs_div: str = FS_CONSOLIDATED,
    reprt_code: str = REPRT_ANNUAL,
    years: list[int] | None = None,
    statements: tuple[str, ...] | None = DEFAULT_STATEMENTS,
) -> MultiYearFs:
    """연도별 fnlttSinglAcntAll 응답들 → 다년도 표.

    reports:    [{"bsns_year": 2025, "rows": [<fnlttSinglAcntAll list 원소>...]}]
                순서 무관(내부에서 최신순 정렬).
    years:      최종 표의 열. None 이면 관측된 전 연도.
    statements: 담을 제표. None 이면 전량(SCE 포함).
    """
    report = ValidationReport()
    notes: list[str] = []
    ordered = sorted(reports, key=lambda r: -int(r["bsns_year"]))
    cols = _amount_columns(reprt_code, notes)

    accounts: dict[tuple, FsAccount] = {}
    order_map: dict[tuple, float] = {}
    alias: dict[tuple, tuple] = {}          # alias 키(id계/이름계) → 정본 병합키
    sources: dict[int, set[str]] = {}
    currencies: set[str] = set()

    for rep in ordered:
        base_year = int(rep["bsns_year"])
        rows = rep["rows"]
        seen_this_report: list[tuple[tuple, float | None]] = []
        occ_id: dict[tuple[str, str, str], int] = {}   # 이 보고서 안 id 기준 출현 순번
        occ_nm: dict[tuple[str, str, str], int] = {}   # 이름 기준 출현 순번
        for row in rows:
            if statements is not None and str(row.get("sj_div", "")).strip() not in statements:
                continue
            key, acc = _row_account(row, alias, occ_id, occ_nm)
            existing = accounts.get(key)
            if existing is None:
                accounts[key] = acc
                existing = acc
            # 최신 보고서가 먼저 처리되므로 메타(sj_nm·account_id·표시명)는 최신본을 유지한다.
            # 연도별 id·이름 이력은 남긴다 — 교체 사실 자체가 감사추적이고 분류에 영향을 준다.
            if acc.account_id:
                existing.id_history[base_year] = acc.account_id
            existing.name_history[base_year] = acc.account_nm
            if row.get("currency"):
                currencies.add(str(row["currency"]).strip())
                existing.currency = existing.currency or str(row["currency"]).strip()
            raw_ord = _to_float(row.get("ord"))
            seen_this_report.append((key, raw_ord))

            for col, offset in cols:
                if col not in row:
                    continue
                year = base_year - offset
                if years is not None and year not in years:
                    continue
                raw = row.get(col)
                val = parse_number(raw, unit="원", report=report,
                                   field_name=f"{key[0]}:{existing.account_nm}:{year}")
                existing.obs.setdefault(year, []).append(Observation(
                    year=year, value=val, raw=None if raw is None else str(raw),
                    source_year=base_year, column=col,
                    rcept_no=(str(row["rcept_no"]) if row.get("rcept_no") else None),
                ))
                if row.get("rcept_no"):
                    sources.setdefault(year, set()).add(str(row["rcept_no"]))

        _merge_order(order_map, seen_this_report, is_newest=(rep is ordered[0]))

    for key, acc in accounts.items():
        acc.order = order_map.get(key, 0.0)
        _assign_depth(acc)

    all_years = sorted({y for a in accounts.values() for y in a.obs})
    final_years = [y for y in (years if years is not None else all_years) if y in all_years]
    if years is not None:
        missing = [y for y in years if y not in all_years]
        if missing:
            notes.append(f"관측 없는 연도 제외: {missing}")

    ordered_accounts = sorted(
        accounts.values(),
        key=lambda a: (_statement_rank(a.sj_div), a.order, a.account_nm))

    _check_currency(currencies, report, notes)
    _check_restatement(ordered_accounts, final_years, report)
    _check_duplicates(ordered_accounts, final_years, report)

    return MultiYearFs(
        corp_code=corp_code, fs_div=fs_div, reprt_code=reprt_code,
        years=final_years, accounts=ordered_accounts, report=report, notes=notes,
        sources={y: sorted(v) for y, v in sources.items() if y in final_years},
    )


def _amount_columns(reprt_code: str, notes: list[str]) -> tuple[tuple[str, int], ...]:
    """연간 보고서에서만 3개년 확장. 분·반기는 당기열만(누적/3개월 혼동 차단)."""
    if reprt_code == REPRT_ANNUAL:
        return _ANNUAL_COLS
    notes.append(
        f"reprt_code={reprt_code}(비 사업보고서) — thstrm_amount 는 분기값이라 "
        "전기·전전기열을 연도로 귀속하지 않습니다(당기열만 채택).")
    return (("thstrm_amount", 0),)


def _row_account(row: dict, alias: dict[tuple, tuple],
                 occ_id: dict[tuple[str, str, str], int],
                 occ_nm: dict[tuple[str, str, str], int]) -> tuple[tuple, FsAccount]:
    """응답 1행 → (정본 병합키, FsAccount 껍데기).

    **alias 해소 2단**: 이 행의 `("id", 표준코드, 상세, 순번)` 이 이미 알려진 정본에
    연결돼 있으면 그것을, 아니면 `("nm", 계정명, 상세, 순번)` 으로 잇는다. 처음 보는
    계정이면 이름 키를 정본으로 삼고 **두 alias 를 모두 등록**해, 이후 보고서가 이름을
    바꿔 오든 코드를 바꿔 오든 같은 줄로 합류하게 한다.

    출현 순번은 id 계열·이름 계열을 따로 센다 — 한 보고서 안에서 같은 이름이 반복되는
    경우(자본변동표의 멤버별 '배당')를 안전하게 가르기 위해서다.
    """
    sj_div = str(row.get("sj_div", "")).strip()
    raw_nm = str(row.get("account_nm", ""))
    nm = raw_nm.strip() or str(row.get("account_id", "?"))
    detail = str(row.get("account_detail", "") or "").strip()
    detail = "" if detail in ("-", "—") else detail
    acc_id = str(row.get("account_id", "") or "").strip()

    nm_base = (sj_div, nm, detail)
    n_nm = occ_nm.get(nm_base, 0)
    occ_nm[nm_base] = n_nm + 1
    nm_key = ("nm", sj_div, nm, detail, n_nm)

    id_key = None
    if acc_id and acc_id != NON_STANDARD_ID:
        id_base = (sj_div, acc_id, detail)
        n_id = occ_id.get(id_base, 0)
        occ_id[id_base] = n_id + 1
        id_key = ("id", sj_div, acc_id, detail, n_id)

    canon = (alias.get(id_key) if id_key else None) or alias.get(nm_key)
    if canon is None:
        canon = nm_key
    if id_key:
        alias.setdefault(id_key, canon)
    alias.setdefault(nm_key, canon)

    return canon, FsAccount(
        sj_div=sj_div,
        sj_nm=str(row.get("sj_nm", "") or "").strip(),
        account_id=acc_id, account_nm=nm, account_detail=detail, occurrence=n_nm,
        merge_key=canon,
        depth_basis="raw:" + raw_nm[: len(raw_nm) - len(raw_nm.lstrip())].replace(" ", "s"),
    )


def _merge_order(order_map: dict, seen: list, *, is_newest: bool) -> None:
    """공시 표시 순서 병합 — 최신 보고서 ord 가 1차 정본.

    구 보고서에만 있는 계정(폐지 계정)은 **그 보고서에서의 앞뒤 이웃 사이**에 소수
    순번으로 끼워 넣는다. 그래야 폐지 계정이 표 맨 끝으로 밀려 공시 원형이 깨지지 않는다.
    """
    if is_newest:
        for i, (key, raw_ord) in enumerate(seen):
            order_map.setdefault(key, raw_ord if raw_ord is not None else float(i))
        return
    n = len(seen)
    for i, (key, _) in enumerate(seen):
        if key in order_map:
            continue
        prev = next((order_map[seen[j][0]] for j in range(i - 1, -1, -1)
                     if seen[j][0] in order_map), None)
        nxt = next((order_map[seen[j][0]] for j in range(i + 1, n)
                    if seen[j][0] in order_map), None)
        if prev is not None and nxt is not None and nxt > prev:
            pos = (prev + nxt) / 2
        elif prev is not None:
            pos = prev + 0.001
        elif nxt is not None:
            pos = nxt - 0.001
        else:
            pos = (max(order_map.values()) + 1) if order_map else float(i)
        order_map[key] = pos


def _assign_depth(acc: FsAccount) -> None:
    """계정 계층 추정 — 근거를 depth_basis 에 남긴다(추정임을 숨기지 않는다).

    ① indent  : 원문 account_nm 의 선행 공백(회사가 제출한 들여쓰기가 살아있는 경우)
    ② anchor  : 제목행(자산/부채/자본)=0, 소계·총계=1
    ③ default : 그 외 개별계정=2
    현금흐름표는 구간 헤더(영업/투자/재무활동현금흐름)를 1, 나머지를 2로 둔다.
    """
    basis = acc.depth_basis
    if basis.startswith("raw:") and basis[4:]:
        acc.depth = min(len(basis[4:]), 3)
        acc.depth_basis = "indent"
        return
    nm = acc.account_nm.strip()
    if acc.sj_div == "BS" and nm in _TITLE_NAMES:
        acc.depth, acc.depth_basis = 0, "anchor:title"
        return
    if (acc.account_id in _SUBTOTAL_IDS or nm in _SUBTOTAL_NAMES
            or nm.endswith(_SUBTOTAL_SUFFIXES)):
        acc.depth, acc.depth_basis = 1, "anchor:subtotal"
        return
    if acc.sj_div == "CF" and nm.endswith("현금흐름"):
        acc.depth, acc.depth_basis = 1, "anchor:cf_section"
        return
    acc.depth, acc.depth_basis = 2, "default"


def _statement_rank(sj_div: str) -> int:
    return STATEMENT_ORDER.index(sj_div) if sj_div in STATEMENT_ORDER else len(STATEMENT_ORDER)


def _to_float(v: object) -> float | None:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


# ── 수집 단계 게이트 ──────────────────────────────────────────────────────────
def _check_currency(currencies: set[str], report: ValidationReport, notes: list[str]) -> None:
    """통화 게이트 — KRW 아닌 값이 섞이면 백만원 환산이 거짓이 된다(단위규약 계열 결함)."""
    non_krw = {c for c in currencies if c and c.upper() != "KRW"}
    if non_krw:
        report.add(Finding(
            rule="fs_currency_not_krw", severity=Severity.FAIL,
            message=f"KRW 아닌 통화 {sorted(non_krw)} 포함 — 원→백만원 환산이 성립하지 않습니다.",
            detail={"currencies": sorted(currencies)}))
    elif currencies:
        notes.append(f"통화 {sorted(currencies)} 확인")


def _check_duplicates(accounts: list[FsAccount], years: list[int],
                      report: ValidationReport) -> None:
    """계정명·표준코드가 **둘 다** 바뀌어 alias 로 못 이은 같은 계정을 탐지.

    판별은 두 조건의 **동시 충족**이다:
      ① **출처 보고서가 서로 배타적** — 어느 한 보고서에도 둘이 같이 실린 적이 없다.
         이게 결정적이다. 같은 보고서가 둘을 나란히 실었다면 회사가 별개 계정으로 표시한
         것이므로 중복이 아니다. 이 조건이 없으면 **소계와 그 유일한 하위 계정**
         (비유동부채=장기차입금 하나뿐인 흔한 경우)이 전부 오탐으로 걸린다.
      ② 값이 있는 연도가 하나 이상 겹치고, **겹치는 전 연도의 값이 동일**.

    자동 병합은 하지 않는다(진짜로 금액이 같은 별개 계정일 수 있다). WARN 으로 짝을
    지목하면 한 줄을 지웠을 때 `Σ버킷 = 자본총계` 대사가 TRUE 로 돌아온다.

    실측: 삼성전자 2021 재무상태표에서 `관계기업 및 공동기업 투자`↔`관계종속기업투자자산
    -지분법`(8.93조), `기타포괄손익-공정가치 측정 비유동금융자산`↔`기타포괄손익-공정가치
    금융자산`(13.97조)이 이중계상되어 자산이 22.9조 과대였다.
    """
    by_div: dict[str, list[FsAccount]] = {}
    for a in accounts:
        by_div.setdefault(a.sj_div, []).append(a)

    def _src(a: FsAccount) -> set[int]:
        return {o.source_year for lst in a.obs.values() for o in lst}

    for sj_div, group in by_div.items():
        vals = [{y: a.value(y) for y in years if a.value(y) is not None} for a in group]
        srcs = [_src(a) for a in group]
        for i, a in enumerate(group):
            for j in range(i + 1, len(group)):
                b = group[j]
                if srcs[i] & srcs[j]:            # ① 한 보고서가 둘을 나란히 실었다 → 별개
                    continue
                shared = set(vals[i]) & set(vals[j])
                if not shared or any(vals[i][y] != vals[j][y] for y in shared):
                    continue                     # ② 겹치는 연도의 값이 다르면 별개
                if all(vals[i][y] == 0 for y in shared):
                    continue                     # 전부 0 인 껍데기끼리는 근거가 못 된다
                report.add(Finding(
                    rule="fs_duplicate_suspect", severity=Severity.WARN,
                    message=(f"'{a.account_nm}' 와 '{b.account_nm}'({sj_div}) 가 "
                             f"{sorted(shared)} 연도에서 값이 동일하고 같은 보고서에 함께 실린 적이 "
                             "없습니다 — 계정명·표준코드가 함께 바뀐 같은 계정일 수 있습니다"
                             "(이중계상되면 요약 대사가 깨집니다). 한 줄을 제거할지 판단하세요."),
                    detail={"sj_div": sj_div, "years": sorted(shared),
                            "accounts": [
                                {"name": x.account_nm, "account_id": x.account_id,
                                 "source_years": sorted(s),
                                 "id_history": {str(k): v for k, v in sorted(x.id_history.items())},
                                 "name_history": {str(k): v for k, v in sorted(x.name_history.items())}}
                                for x, s in ((a, srcs[i]), (b, srcs[j]))],
                            "values": {str(y): str(vals[i][y]) for y in sorted(shared)}}))


def _check_restatement(accounts: list[FsAccount], years: list[int],
                       report: ValidationReport) -> None:
    """같은 연도·같은 계정의 중복 관측 불일치 = 전기 재작성·재분류의 실측 증거.

    공시 원문 사이의 차이이므로 **WARN**(사실은 사실대로). 채택값은 최신 공시이며
    어느 보고서에서 무엇이 달랐는지를 detail 로 남겨 감사추적을 만든다.

    ⚠️ **부호 반전은 따로 센다**(`fs_sign_convention`). 현금흐름표·자본변동표의 차감항목은
    당기열과 비교열에서 부호 규약이 흔들리는 사례가 실측된다(삼성전자 '비지배지분의 증감'
    2023년보고서 −9,118 vs 2024년보고서 +9,118). 이걸 재작성으로 뭉뚱그리면 경보가 노이즈가
    되어 **진짜 재작성이 묻힌다** — 크기는 같고 부호만 다르면 표시규약 문제로 분리한다.
    """
    for acc in accounts:
        for y in years:
            obs = [o for o in acc.obs.get(y, []) if o.value is not None]
            if len(obs) < 2:
                continue
            vals = {o.value for o in obs}
            if len(vals) == 1:
                continue
            adopted = acc.adopted(y)
            detail = ", ".join(
                f"{o.source_year}년보고서 {o.column.replace('_amount','')}={o.value}"
                for o in sorted(obs, key=lambda o: -o.source_year))
            sign_only = len({abs(v) for v in vals}) == 1
            if sign_only:
                report.add(Finding(
                    rule="fs_sign_convention", severity=Severity.WARN,
                    message=(f"{y} '{acc.account_nm}'({acc.sj_div}) 부호만 상반 — {detail}. "
                             f"채택={adopted.source_year}년보고서 {adopted.value} "
                             "(당기열/비교열 표시규약 차이로 보임 — 금액 재작성 아님)"),
                    detail={"year": y, "sj_div": acc.sj_div, "account": acc.account_nm,
                            "adopted": str(adopted.value),
                            "adopted_source_year": adopted.source_year,
                            "observations": [
                                {"source_year": o.source_year, "column": o.column,
                                 "value": str(o.value), "rcept_no": o.rcept_no}
                                for o in sorted(obs, key=lambda o: -o.source_year)]}))
                continue
            report.add(Finding(
                rule="fs_restated", severity=Severity.WARN,
                message=(f"{y} '{acc.account_nm}'({acc.sj_div}) 공시값 불일치 — {detail}. "
                         f"채택={adopted.source_year}년보고서 {adopted.value} "
                         "(전기 재작성·재분류 가능 — 원인 확인 권장)"),
                detail={"year": y, "sj_div": acc.sj_div, "account": acc.account_nm,
                        "account_id": acc.account_id,
                        "adopted": str(adopted.value),
                        "adopted_source_year": adopted.source_year,
                        "observations": [
                            {"source_year": o.source_year, "column": o.column,
                             "value": str(o.value), "rcept_no": o.rcept_no}
                            for o in sorted(obs, key=lambda o: -o.source_year)]}))
