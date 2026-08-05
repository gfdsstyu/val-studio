"""공시 재무제표 정합성 체크 — 3표 내부 항등식 + 표 간 교차대사.

`dart_fs.MultiYearFs`(공시 원형 다년도 표)를 받아 **공시 자체가 성립하는지**를 연도별로
검사한다. 밸류에이션 모델의 H_FS 탭이 셀 수식으로 걸어두는 체크행
(`자산 = 부채 + 자본`, `=raw?`, `원본자료 Refer Check`)의 서버측 등가물이며,
엑셀로 내보낼 때는 `excel/fs_sheet.py` 가 같은 항등식을 **살아있는 수식**으로 다시 심는다.

심각도 규약(중요):
  - **FAIL** = 성립하지 않을 수 없는 항등식이 깨진 것 = 대개 *우리 수집·환산의 결함*.
    대차(자산=부채+자본)가 대표. 게이트가 막아야 한다.
  - **WARN** = 공시 표시 관행 차이로 정당하게 어긋날 수 있는 것.
    (예: 기능별/성격별 표시 차이로 매출총이익 미표시, 연결범위·사용제한예금으로 CF 기말현금 ≠ BS 현금)
    사실이므로 지우지 않고 표면화만 한다.
  - 피연산자 중 하나라도 부재하면 **검사 자체를 건너뛴다**(없는 걸 0으로 보면 거짓 FAIL 이 난다).

허용오차 기본값은 1원(=1e-6 백만원). DART 금액은 원 단위 정수이므로 항등식은 원 단위로
정확히 성립해야 하고, 어긋나면 반올림이 아니라 실제 차이다.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .dart_fs import FsAccount, MultiYearFs
from .validators import Finding, Severity

#: 1원 = 1e-6 백만원. 표시 반올림이 아닌 실제 차이만 잡는 허용오차.
DEFAULT_TOL = Decimal("0.000001")

#: 손익은 IS(별도 손익계산서) 또는 CIS(단일 포괄손익계산서) 어느 쪽에나 실린다.
_PL_DIVS = ("IS", "CIS")


@dataclass(frozen=True)
class Anchor:
    """항등식 피연산자 — 표준계정코드 우선, 회사 확장계정은 명칭으로 폴백."""
    label: str
    divs: tuple[str, ...]
    ids: tuple[str, ...] = ()
    names: tuple[str, ...] = ()


# ── 재무상태표 ────────────────────────────────────────────────────────────────
A_ASSETS = Anchor("자산총계", ("BS",), ("ifrs-full_Assets",), ("자산총계", "총자산"))
A_CUR_ASSETS = Anchor("유동자산", ("BS",), ("ifrs-full_CurrentAssets",), ("유동자산",))
A_NONCUR_ASSETS = Anchor("비유동자산", ("BS",), ("ifrs-full_NoncurrentAssets",), ("비유동자산",))
A_LIAB = Anchor("부채총계", ("BS",), ("ifrs-full_Liabilities",), ("부채총계", "총부채"))
A_CUR_LIAB = Anchor("유동부채", ("BS",), ("ifrs-full_CurrentLiabilities",), ("유동부채",))
A_NONCUR_LIAB = Anchor("비유동부채", ("BS",), ("ifrs-full_NoncurrentLiabilities",), ("비유동부채",))
A_EQUITY = Anchor("자본총계", ("BS",), ("ifrs-full_Equity",), ("자본총계", "총자본", "자기자본총계"))
A_EQ_AND_LIAB = Anchor("자본과부채총계", ("BS",), ("ifrs-full_EquityAndLiabilities",),
                       ("자본과부채총계", "부채와자본총계", "부채및자본총계"))
A_BS_CASH = Anchor("현금및현금성자산(BS)", ("BS",), ("ifrs-full_CashAndCashEquivalents",),
                   ("현금및현금성자산",))

# ── 손익·포괄손익 ─────────────────────────────────────────────────────────────
A_REVENUE = Anchor("매출액", _PL_DIVS, ("ifrs-full_Revenue",), ("수익(매출액)", "매출액", "영업수익"))
A_COGS = Anchor("매출원가", _PL_DIVS, ("ifrs-full_CostOfSales",), ("매출원가",))
A_GROSS = Anchor("매출총이익", _PL_DIVS, ("ifrs-full_GrossProfit",), ("매출총이익",))
A_SGA = Anchor("판매비와관리비", _PL_DIVS,
               ("dart_TotalSellingGeneralAdministrativeExpenses",),
               ("판매비와관리비", "판매비와일반관리비"))
A_OP = Anchor("영업이익", _PL_DIVS, ("dart_OperatingIncomeLoss", "ifrs-full_ProfitLossFromOperatingActivities"),
              ("영업이익", "영업이익(손실)"))
A_NI = Anchor("당기순이익", _PL_DIVS, ("ifrs-full_ProfitLoss",), ("당기순이익", "당기순이익(손실)"))
A_OCI = Anchor("기타포괄손익", ("CIS",), ("ifrs-full_OtherComprehensiveIncome",),
               ("기타포괄손익", "세후기타포괄손익"))
A_CI = Anchor("총포괄손익", ("CIS",), ("ifrs-full_ComprehensiveIncome",),
              ("총포괄손익", "총포괄이익", "당기총포괄손익"))

# ── 현금흐름표 ────────────────────────────────────────────────────────────────
A_CFO = Anchor("영업활동현금흐름", ("CF",),
               ("ifrs-full_CashFlowsFromUsedInOperatingActivities",), ("영업활동현금흐름",))
A_CFI = Anchor("투자활동현금흐름", ("CF",),
               ("ifrs-full_CashFlowsFromUsedInInvestingActivities",), ("투자활동현금흐름",))
A_CFF = Anchor("재무활동현금흐름", ("CF",),
               ("ifrs-full_CashFlowsFromUsedInFinancingActivities",), ("재무활동현금흐름",))
#: 이름 변형이 특히 심한 항목 — API 는 '외화환산으로 인한 현금의 변동', 원문 공시는
#: '환율변동효과'·'외화표시 현금의 환율변동효과' 등. 좁게 잡으면 CF 3구간 합 검사가
#: 환율효과 금액만큼 통째로 WARN 이 된다(실측: 삼성전자 연결 2024 −4,821,010 백만원).
A_FX = Anchor("환율변동효과", ("CF",),
              ("ifrs-full_EffectOfExchangeRateChangesOnCashAndCashEquivalents",
               "dart_EffectOfExchangeRateChangesOnCashAndCashEquivalents"),
              ("환율변동효과", "외화표시현금", "외화환산", "환율변동", "환율효과"))
A_CF_NET = Anchor("현금및현금성자산의증가", ("CF",),
                  ("ifrs-full_IncreaseDecreaseInCashAndCashEquivalents",),
                  ("현금및현금성자산의순증가", "현금및현금성자산의증가", "현금및현금성자산의증가(감소)"))
A_CF_BEGIN = Anchor("기초현금", ("CF",),
                    ("dart_CashAndCashEquivalentsAtTheBeginningOfPeriod",
                     "ifrs-full_CashAndCashEquivalentsAtBeginningOfPeriod"),
                    ("기초현금및현금성자산", "기초의현금및현금성자산", "기초현금"))
A_CF_END = Anchor("기말현금", ("CF",),
                  ("dart_CashAndCashEquivalentsAtTheEndOfPeriod",
                   "ifrs-full_CashAndCashEquivalentsAtEndOfPeriod"),
                  ("기말현금및현금성자산", "기말의현금및현금성자산", "기말현금"))


# ── 계정 탐색 ─────────────────────────────────────────────────────────────────
def _norm(s: str) -> str:
    return s.replace(" ", "").replace("　", "").strip()


def find_account(fs: MultiYearFs, anchor: Anchor) -> FsAccount | None:
    """앵커에 해당하는 계정 1건 — ①표준코드 정확일치 ②명칭 정확일치 ③명칭 부분일치.

    부분일치 단계에서 후보가 여럿이면 **소계·총계로 판정된 계정(depth≤1)** 을 우선한다.
    ('유동자산' 부분일치에 '기타유동자산' 같은 세부계정이 걸리는 오탐을 막는다.)
    """
    pool = [a for a in fs.accounts if a.sj_div in anchor.divs]
    for aid in anchor.ids:
        for a in pool:
            if a.account_id == aid:
                return a
    wanted = {_norm(n) for n in anchor.names}
    for a in pool:
        if _norm(a.account_nm) in wanted:
            return a
    cands = [a for a in pool if any(w and w in _norm(a.account_nm) for w in wanted)]
    if not cands:
        return None
    cands.sort(key=lambda a: (a.depth, a.order))
    return cands[0]


def _v(acc: FsAccount | None, year: int) -> Decimal | None:
    return acc.value(year) if acc else None


# ── 항등식 ────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Identity:
    """`sum(lhs) == sum(rhs)` 형태의 항등식 한 건."""
    rule: str
    title: str
    lhs: tuple[Anchor, ...]
    rhs: tuple[Anchor, ...]
    severity: Severity
    note: str = ""
    #: 부재해도 0으로 간주해 검사를 진행할 앵커(환율효과처럼 없는 게 정상인 항목).
    optional: tuple[Anchor, ...] = ()


IDENTITIES: tuple[Identity, ...] = (
    Identity("bs_balance", "자산 = 부채 + 자본",
             (A_ASSETS,), (A_LIAB, A_EQUITY), Severity.FAIL,
             "대차는 공시상 반드시 성립 — 어긋나면 수집·환산 결함을 먼저 의심"),
    Identity("bs_eq_liab_total", "자본과부채총계 = 자산총계",
             (A_EQ_AND_LIAB,), (A_ASSETS,), Severity.FAIL),
    Identity("bs_asset_split", "유동자산 + 비유동자산 = 자산총계",
             (A_CUR_ASSETS, A_NONCUR_ASSETS), (A_ASSETS,), Severity.WARN,
             "유동/비유동 구분 미표시 기업은 앵커 부재로 자동 skip"),
    Identity("bs_liability_split", "유동부채 + 비유동부채 = 부채총계",
             (A_CUR_LIAB, A_NONCUR_LIAB), (A_LIAB,), Severity.WARN),
    Identity("pl_gross_profit", "매출액 − 매출원가 = 매출총이익",
             (A_REVENUE,), (A_GROSS, A_COGS), Severity.WARN,
             "성격별 표시(매출총이익 미표시) 기업은 앵커 부재로 skip"),
    Identity("pl_operating_income", "매출총이익 − 판관비 = 영업이익",
             (A_GROSS,), (A_OP, A_SGA), Severity.WARN),
    Identity("ci_total", "당기순이익 + 기타포괄손익 = 총포괄손익",
             (A_NI, A_OCI), (A_CI,), Severity.WARN),
    Identity("cf_sections", "영업 + 투자 + 재무 (+환율효과) = 현금 순증감",
             (A_CFO, A_CFI, A_CFF, A_FX), (A_CF_NET,), Severity.WARN,
             "환율변동효과는 없는 게 정상일 수 있어 0으로 간주", optional=(A_FX,)),
    Identity("cf_rollforward", "기초현금 + 순증감 = 기말현금",
             (A_CF_BEGIN, A_CF_NET), (A_CF_END,), Severity.WARN),
    Identity("cf_bs_cash_tie", "CF 기말현금 = BS 현금및현금성자산",
             (A_CF_END,), (A_BS_CASH,), Severity.WARN,
             "연결범위 차이·사용제한예금 재분류로 정당하게 어긋날 수 있음"),
)


def check_statements(fs: MultiYearFs, *, tol: Decimal | float = DEFAULT_TOL) -> list[Finding]:
    """다년도 표 → 연도별 항등식 검사 결과(Finding 목록).

    성립한 항등식도 PASS Finding 으로 남긴다 — H_FS 체크행이 TRUE 를 보여주는 것과
    같은 이유로, "검사가 돌았고 통과했다"와 "검사가 아예 안 돌았다"는 구분되어야 한다.
    앵커 부재로 건너뛴 항등식은 skipped 로 별도 표기한다.
    """
    tolerance = Decimal(str(tol))
    out: list[Finding] = []
    resolved = {id(a): find_account(fs, a) for ident in IDENTITIES
                for a in ident.lhs + ident.rhs}

    for ident in IDENTITIES:
        opt = {id(a) for a in ident.optional}
        missing = [a.label for a in ident.lhs + ident.rhs
                   if resolved[id(a)] is None and id(a) not in opt]
        if missing:
            out.append(Finding(
                rule=ident.rule, severity=Severity.PASS,
                message=f"[skip] {ident.title} — 앵커 부재: {', '.join(missing)}",
                detail={"skipped": True, "missing": missing, "title": ident.title}))
            continue
        for year in fs.years:
            lhs_terms = [(a.label, _v(resolved[id(a)], year), id(a) in opt) for a in ident.lhs]
            rhs_terms = [(a.label, _v(resolved[id(a)], year), id(a) in opt) for a in ident.rhs]
            gap = [lbl for lbl, v, is_opt in lhs_terms + rhs_terms if v is None and not is_opt]
            if gap:
                out.append(Finding(
                    rule=ident.rule, severity=Severity.PASS,
                    message=f"[skip] {year} {ident.title} — 값 부재: {', '.join(gap)}",
                    detail={"skipped": True, "year": year, "missing_values": gap,
                            "title": ident.title}))
                continue
            lhs = sum((v for _, v, _ in lhs_terms if v is not None), Decimal(0))
            rhs = sum((v for _, v, _ in rhs_terms if v is not None), Decimal(0))
            diff = lhs - rhs
            passed = abs(diff) <= tolerance
            detail = {
                "year": year, "title": ident.title,
                "lhs": str(lhs), "rhs": str(rhs), "diff": str(diff),
                "terms": {lbl: (None if v is None else str(v))
                          for lbl, v, _ in lhs_terms + rhs_terms},
            }
            if ident.note:
                detail["note"] = ident.note
            out.append(Finding(
                rule=ident.rule,
                severity=Severity.PASS if passed else ident.severity,
                message=(f"{year} {ident.title} — "
                         + ("일치" if passed
                            else f"불일치 {diff:,} 백만원 (좌 {lhs:,} vs 우 {rhs:,})"
                                 + (f" · {ident.note}" if ident.note else ""))),
                detail=detail))
    return out


def summarize(findings: list[Finding]) -> dict:
    """게이트 요약 — 연도별 FAIL/WARN 집계 + 통과 여부.

    ok=False 는 '엑셀로 내보내지 말라'가 아니라 '내보내기 전에 원인을 보라'는 신호다.
    (공시 원문 자체가 안 맞는 경우도 있어 사용자 판단으로 진행할 수 있어야 한다.)
    """
    fails = [f for f in findings if f.severity is Severity.FAIL]
    warns = [f for f in findings if f.severity is Severity.WARN]
    skipped = [f for f in findings if f.detail.get("skipped")]
    by_year: dict[int, dict[str, int]] = {}
    for f in fails + warns:
        y = f.detail.get("year")
        if y is None:
            continue
        b = by_year.setdefault(int(y), {"fail": 0, "warn": 0})
        b["fail" if f.severity is Severity.FAIL else "warn"] += 1
    return {
        "ok": not fails,
        "fail": len(fails), "warn": len(warns), "skipped": len(skipped),
        "checked": len(findings) - len(skipped),
        "by_year": {str(k): v for k, v in sorted(by_year.items())},
    }


def to_dicts(findings: list[Finding]) -> list[dict]:
    """API 응답용 직렬화(수제 dict 규약 — Pydantic 미사용)."""
    return [{"rule": f.rule, "severity": f.severity.value,
             "message": f.message, "detail": f.detail} for f in findings]
