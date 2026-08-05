"""다년도 공시 재무제표 — 수집·병합·정합성·H_FS 시트 플랜 전량 mock 테스트.

네트워크·API 키 없이 canned fnlttSinglAcntAll 응답으로 전 경로를 검증한다.
stdlib: `python tests/test_dart_fs.py`
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from excel.fs_sheet import build_fs_sheets, col_letter, plan_to_json  # noqa: E402
from ingest.dart_client import DartClient  # noqa: E402
from ingest.dart_fs import build_multi_year, fetch_multi_year  # noqa: E402
from ingest.fs_integrity import check_statements, summarize  # noqa: E402
from ingest.validators import Severity  # noqa: E402

# ── 픽스처: 3개년이 정확히 맞물리는 가상 회사(원 단위) ────────────────────────
_BS = [
    # (account_id, 계정명, 2023, 2022, 2021, 2020)
    ("", "자산", None, None, None, None),
    ("ifrs-full_CurrentAssets", "유동자산", 5_000_000_000, 3_500_000_000, 2_000_000_000, 1_600_000_000),
    ("ifrs-full_CashAndCashEquivalents", "현금및현금성자산", 3_000_000_000, 2_000_000_000, 1_000_000_000, 700_000_000),
    ("dart_ShortTermTradeReceivable", "매출채권", 2_000_000_000, 1_500_000_000, 1_000_000_000, 900_000_000),
    ("ifrs-full_NoncurrentAssets", "비유동자산", 4_000_000_000, 3_500_000_000, 3_000_000_000, 2_900_000_000),
    ("ifrs-full_PropertyPlantAndEquipment", "유형자산", 4_000_000_000, 3_500_000_000, 3_000_000_000, 2_900_000_000),
    ("ifrs-full_Assets", "자산총계", 9_000_000_000, 7_000_000_000, 5_000_000_000, 4_500_000_000),
    ("", "부채", None, None, None, None),
    ("ifrs-full_CurrentLiabilities", "유동부채", 1_500_000_000, 1_500_000_000, 1_000_000_000, 900_000_000),
    ("dart_ShortTermTradePayables", "매입채무", 1_000_000_000, 800_000_000, 600_000_000, 500_000_000),
    ("dart_ShortTermBorrowings", "단기차입금", 500_000_000, 700_000_000, 400_000_000, 400_000_000),
    ("ifrs-full_NoncurrentLiabilities", "비유동부채", 1_000_000_000, 500_000_000, 500_000_000, 600_000_000),
    ("dart_LongTermBorrowings", "장기차입금", 1_000_000_000, 500_000_000, 500_000_000, 600_000_000),
    ("ifrs-full_Liabilities", "부채총계", 2_500_000_000, 2_000_000_000, 1_500_000_000, 1_500_000_000),
    ("", "자본", None, None, None, None),
    ("ifrs-full_IssuedCapital", "자본금", 1_000_000_000, 1_000_000_000, 1_000_000_000, 1_000_000_000),
    ("ifrs-full_RetainedEarnings", "이익잉여금", 5_500_000_000, 4_000_000_000, 2_500_000_000, 2_000_000_000),
    ("ifrs-full_Equity", "자본총계", 6_500_000_000, 5_000_000_000, 3_500_000_000, 3_000_000_000),
    ("ifrs-full_EquityAndLiabilities", "자본과부채총계", 9_000_000_000, 7_000_000_000, 5_000_000_000, 4_500_000_000),
]
_CIS = [
    ("ifrs-full_Revenue", "수익(매출액)", 10_000_000_000, 8_000_000_000, 6_000_000_000, 5_000_000_000),
    ("ifrs-full_CostOfSales", "매출원가", 6_000_000_000, 5_000_000_000, 4_000_000_000, 3_400_000_000),
    ("ifrs-full_GrossProfit", "매출총이익", 4_000_000_000, 3_000_000_000, 2_000_000_000, 1_600_000_000),
    ("dart_TotalSellingGeneralAdministrativeExpenses", "판매비와관리비",
     2_500_000_000, 2_000_000_000, 1_500_000_000, 1_300_000_000),
    ("dart_OperatingIncomeLoss", "영업이익", 1_500_000_000, 1_000_000_000, 500_000_000, 300_000_000),
    ("ifrs-full_ProfitLoss", "당기순이익", 1_500_000_000, 1_000_000_000, 500_000_000, 300_000_000),
]
_CF = [
    ("ifrs-full_CashFlowsFromUsedInOperatingActivities", "영업활동현금흐름",
     2_000_000_000, 1_800_000_000, 1_000_000_000, 800_000_000),
    ("ifrs-full_CashFlowsFromUsedInInvestingActivities", "투자활동현금흐름",
     -700_000_000, -600_000_000, -500_000_000, -400_000_000),
    ("ifrs-full_CashFlowsFromUsedInFinancingActivities", "재무활동현금흐름",
     -300_000_000, -200_000_000, -200_000_000, -100_000_000),
    ("ifrs-full_IncreaseDecreaseInCashAndCashEquivalents", "현금및현금성자산의순증가",
     1_000_000_000, 1_000_000_000, 300_000_000, 300_000_000),
    ("dart_CashAndCashEquivalentsAtTheBeginningOfPeriod", "기초현금및현금성자산",
     2_000_000_000, 1_000_000_000, 700_000_000, 400_000_000),
    ("dart_CashAndCashEquivalentsAtTheEndOfPeriod", "기말현금및현금성자산",
     3_000_000_000, 2_000_000_000, 1_000_000_000, 700_000_000),
]
_SPEC = [("BS", "재무상태표", _BS), ("CIS", "포괄손익계산서", _CIS), ("CF", "현금흐름표", _CF)]
#: 연도 → 픽스처 튜플의 인덱스(2=2023 … 5=2020)
_IDX = {2023: 2, 2022: 3, 2021: 4, 2020: 5}


def _amt(v):
    """None=결측('-' 관행 표기), 그 외는 콤마 포함 원문 문자열로."""
    return "-" if v is None else f"{v:,}"


def _report(bsns_year: int, *, overrides: dict | None = None,
            extra: list | None = None) -> dict:
    """한 사업연도 사업보고서 응답(당기·전기·전전기 3열)을 생성.

    overrides: {(sj_div, 계정명, 연도): 값} — 특정 보고서에서만 다른 값을 싣게 해
    전기 재작성 상황을 재현한다.
    extra: [(sj_div, account_id, 계정명, after_계정명)] — 그 보고서에만 존재하는 계정.
    """
    ov = overrides or {}
    rows: list[dict] = []
    for sj_div, sj_nm, spec in _SPEC:
        items = list(spec)
        for e_div, e_id, e_nm, after in (extra or []):
            if e_div != sj_div:
                continue
            pos = next(i for i, s in enumerate(items) if s[1] == after) + 1
            items.insert(pos, (e_id, e_nm, 111_000_000, 222_000_000, 333_000_000, 444_000_000))
        for i, (acc_id, nm, *vals) in enumerate(items, start=1):
            row = {
                "rcept_no": f"{bsns_year + 1}0315000001", "reprt_code": "11011",
                "bsns_year": str(bsns_year), "corp_code": "00126380",
                "sj_div": sj_div, "sj_nm": sj_nm,
                "account_id": acc_id or "-표준계정코드 미사용-",
                "account_nm": nm, "account_detail": "-",
                "ord": str(i), "currency": "KRW",
            }
            for col, offset in (("thstrm_amount", 0), ("frmtrm_amount", 1),
                                ("bfefrmtrm_amount", 2)):
                year = bsns_year - offset
                key = (sj_div, nm, year)
                if key in ov:
                    row[col] = _amt(ov[key])
                elif year in _IDX:
                    row[col] = _amt(vals[_IDX[year] - 2])
                else:
                    row[col] = "-"
            rows.append(row)
    return {"bsns_year": bsns_year, "rows": rows}


def _fs(years=(2021, 2022, 2023), *, old_overrides: dict | None = None, **kw):
    """2023·2022 두 보고서로 다년도 표 구성.

    kw(overrides/extra)는 **양쪽 보고서에 동일 적용** — 공시가 일관되게 그 값인 상황.
    old_overrides 는 **구 보고서(2022)에만** 적용 — 뒤에 재작성된 상황(교차 불일치)을 만든다.
    """
    reports = [_report(2023, **kw),
               _report(2022, **{**kw, "overrides": {**(kw.get("overrides") or {}),
                                                    **(old_overrides or {})}})]
    return build_multi_year(reports, corp_code="00126380", years=list(years))


# ── 병합 ─────────────────────────────────────────────────────────────────────
def test_three_years_from_two_reports():
    """보고서 2건(각 3개년)으로 요청 3개년이 전부 채워진다 — 콜 수 절감의 근거."""
    fs = _fs()
    assert fs.years == [2021, 2022, 2023]
    cash = next(a for a in fs.accounts if a.account_nm == "현금및현금성자산" and a.sj_div == "BS")
    assert cash.value(2023) == Decimal("3000")     # 원 → 백만원
    assert cash.value(2022) == Decimal("2000")
    assert cash.value(2021) == Decimal("1000")


def test_requested_years_only():
    """요청하지 않은 연도(2020)가 응답에 실려와도 열로 새어 들어오지 않는다."""
    fs = _fs()
    assert 2020 not in fs.years
    cash = next(a for a in fs.accounts if a.account_nm == "현금및현금성자산")
    assert 2020 not in cash.obs


def test_disclosure_order_and_depth_preserved():
    """계정 순서 = 공시 표시순서, 계층은 총계/제목 앵커로 복원된다."""
    fs = _fs()
    bs = [a.account_nm for a in fs.statement("BS")]
    assert bs[:4] == ["자산", "유동자산", "현금및현금성자산", "매출채권"]
    assert bs.index("자산총계") < bs.index("부채")
    by = {a.account_nm: a for a in fs.statement("BS")}
    assert by["자산"].depth == 0 and by["자산"].depth_basis == "anchor:title"
    assert by["유동자산"].depth == 1
    assert by["현금및현금성자산"].depth == 2
    assert by["현금및현금성자산"].label().startswith("　　")   # 전각공백 들여쓰기


def test_statements_split_bs_cis_cf():
    fs = _fs()
    assert set(fs.statements) == {"BS", "CIS", "CF"}
    assert list(fs.statements) == ["BS", "CIS", "CF"]          # 공시 표시 순서


def test_retired_account_inserted_in_place():
    """구 보고서에만 있는 계정은 표 끝이 아니라 원래 이웃 사이에 들어간다."""
    fs = build_multi_year(
        [_report(2023), _report(2022, extra=[("BS", "dart_Prepaid", "선급비용", "매출채권")])],
        years=[2021, 2022, 2023])
    bs = [a.account_nm for a in fs.statement("BS")]
    assert bs.index("매출채권") < bs.index("선급비용") < bs.index("비유동자산")


def test_restatement_detected_and_latest_adopted():
    """같은 연도가 두 보고서에서 다르면 WARN + 최신 공시 채택(재작성 반영본)."""
    fs = _fs(old_overrides={("BS", "매출채권", 2021): 1_100_000_000})
    ar = next(a for a in fs.statement("BS") if a.account_nm == "매출채권")
    assert ar.value(2021) == Decimal("1000")                   # 2023년 보고서 값 채택
    warns = [f for f in fs.report.warns if f.rule == "fs_restated"]
    assert len(warns) == 1
    d = warns[0].detail
    assert d["year"] == 2021 and d["adopted_source_year"] == 2023
    assert len(d["observations"]) == 2
    assert fs.ok                                               # 재작성은 FAIL 이 아니다


def test_account_id_change_across_years_does_not_split_row():
    """표준계정코드가 연도 사이에 바뀌어도 같은 계정은 한 줄 — 시계열이 끊기면 안 된다.

    실측 근거: 삼성전자 재무상태표만 2021→2025 사이 7건이 `-표준계정코드 미사용-`→
    `ifrs-full_*` 로 교체됐고, id 를 병합키에 넣었을 때 '미수금'·'선급비용' 등이 두 줄로
    쪼개져 각각 절반의 연도만 채워졌다.
    """
    old = _report(2022)
    for r in old["rows"]:
        if r["account_nm"] == "매출채권":
            r["account_id"] = "-표준계정코드 미사용-"
    fs = build_multi_year([_report(2023), old], years=[2021, 2022, 2023])
    ar = [a for a in fs.statement("BS") if a.account_nm == "매출채권"]
    assert len(ar) == 1, "account_id 변경으로 계정이 쪼개짐"
    assert all(ar[0].value(y) is not None for y in (2021, 2022, 2023))
    assert ar[0].account_id == "dart_ShortTermTradeReceivable"     # 최신 보고서 id 채택
    assert ar[0].id_history[2022] == "-표준계정코드 미사용-"          # 이력은 보존


def test_account_rename_across_years_does_not_split_row():
    """계정명이 바뀌어도 표준계정코드가 같으면 한 줄 — 안 그러면 자산이 이중계상된다.

    실측 근거: 삼성전자 '관계종속기업투자자산-지분법'→'관계기업 및 공동기업 투자'(8.93조),
    '기타포괄손익-공정가치 측정 비유동금융자산'→'기타포괄손익-공정가치금융자산'(13.97조).
    합쳐 2021 자산이 22.9조 과대였고 요약 대사가 깨졌다.
    """
    old = _report(2022)
    for r in old["rows"]:
        if r["account_nm"] == "유형자산":
            r["account_nm"] = "유형자산(구표시)"
    fs = build_multi_year([_report(2023), old], years=[2021, 2022, 2023])
    fa = [a for a in fs.statement("BS") if "유형자산" in a.account_nm]
    assert len(fa) == 1, [a.account_nm for a in fa]
    assert fa[0].account_nm == "유형자산"                       # 최신 표시명 채택
    assert fa[0].name_history[2022] == "유형자산(구표시)"          # 이력 보존
    assert all(fa[0].value(y) is not None for y in (2021, 2022, 2023))


def test_duplicate_suspect_when_both_name_and_id_change():
    """이름·코드가 함께 바뀌면 기계가 못 잇는다 — 병합하지 말고 짝을 지목한다."""
    old = _report(2022)
    for r in old["rows"]:
        if r["account_nm"] == "유형자산":
            r["account_nm"] = "설비자산"
            r["account_id"] = "-표준계정코드 미사용-"
    fs = build_multi_year([_report(2023), old], years=[2021, 2022, 2023])
    dups = [f for f in fs.report.warns if f.rule == "fs_duplicate_suspect"]
    assert len(dups) == 1
    names = {a["name"] for a in dups[0].detail["accounts"]}
    assert names == {"유형자산", "설비자산"}
    assert fs.ok            # 판단 대상이지 게이트 차단 사유는 아니다


def test_repeated_account_name_in_one_report_stays_separate():
    """한 보고서 안에서 같은 이름이 두 번 나오면(자본변동표 멤버 반복) 합치지 않는다."""
    rep = _report(2023)
    dup = dict(next(r for r in rep["rows"] if r["account_nm"] == "매출채권"))
    dup["thstrm_amount"] = "999,000,000"
    dup["ord"] = "99"
    rep["rows"].append(dup)
    fs = build_multi_year([rep], years=[2023])
    ar = [a for a in fs.statement("BS") if a.account_nm == "매출채권"]
    assert len(ar) == 2
    assert {a.occurrence for a in ar} == {0, 1}


def test_sign_flip_is_not_reported_as_restatement():
    """크기 같고 부호만 반대면 표시규약 차이 — 진짜 재작성과 분리해야 경보가 산다."""
    fs = _fs(old_overrides={("CF", "투자활동현금흐름", 2021): 500_000_000})  # 원래 −500,000,000
    rules = [f.rule for f in fs.report.warns]
    assert "fs_sign_convention" in rules
    assert "fs_restated" not in rules


def test_sce_excluded_by_default():
    """기본 수집 제표는 BS·IS·CIS·CF — 자본변동표는 멤버 반복으로 표를 압도한다."""
    rep = _report(2023)
    rep["rows"].append({**rep["rows"][0], "sj_div": "SCE", "sj_nm": "자본변동표",
                        "account_nm": "배당", "ord": "1"})
    assert "SCE" not in build_multi_year([rep], years=[2023]).statements
    assert "SCE" in build_multi_year([rep], years=[2023], statements=None).statements


def test_non_krw_currency_fails_gate():
    rep = _report(2023)
    for r in rep["rows"]:
        r["currency"] = "USD"
    fs = build_multi_year([rep], years=[2023])
    assert not fs.ok
    assert any(f.rule == "fs_currency_not_krw" for f in fs.report.fails)


def test_quarterly_report_does_not_expand_years():
    """분·반기는 thstrm_amount 가 3개월 값 — 전기열을 연도로 귀속하지 않는다."""
    fs = build_multi_year([_report(2023)], reprt_code="11013", years=[2021, 2022, 2023])
    assert fs.years == [2023]
    assert any("비 사업보고서" in n for n in fs.notes)


# ── 정합성 ────────────────────────────────────────────────────────────────────
def test_identities_all_pass_on_consistent_fixture():
    fs = _fs()
    findings = check_statements(fs)
    bad = [f for f in findings if f.severity is not Severity.PASS]
    assert not bad, [f.message for f in bad]
    s = summarize(findings)
    assert s["ok"] and s["fail"] == 0 and s["warn"] == 0 and s["checked"] > 0


def test_bs_imbalance_is_fail():
    """대차가 깨지면 FAIL — 공시상 성립할 수 없는 항등식이라 수집 결함을 의심해야 한다."""
    fs = _fs(overrides={("BS", "자산총계", 2023): 9_100_000_000})
    findings = check_statements(fs)
    fails = [f for f in findings if f.severity is Severity.FAIL and f.rule == "bs_balance"]
    assert len(fails) == 1
    assert fails[0].detail["year"] == 2023
    assert Decimal(fails[0].detail["diff"]) == Decimal(100)    # 백만원
    assert not summarize(findings)["ok"]


def test_pl_chain_mismatch_is_warn_only():
    fs = _fs(overrides={("CIS", "매출총이익", 2022): 3_100_000_000})
    findings = check_statements(fs)
    warns = [f for f in findings if f.severity is Severity.WARN]
    assert {f.rule for f in warns} == {"pl_gross_profit", "pl_operating_income"}
    assert summarize(findings)["ok"]                            # WARN 은 게이트를 막지 않는다


def test_missing_anchor_is_skipped_not_failed():
    """앵커가 없으면 검사를 건너뛴다 — 없는 값을 0으로 보면 거짓 FAIL 이 난다."""
    rep = _report(2023)
    rep["rows"] = [r for r in rep["rows"] if r["account_nm"] != "매출총이익"]
    fs = build_multi_year([rep], years=[2023])
    findings = check_statements(fs)
    skipped = [f for f in findings if f.detail.get("skipped") and f.rule == "pl_gross_profit"]
    assert skipped and all(f.severity is Severity.PASS for f in skipped)
    assert summarize(findings)["ok"]


def test_cf_to_bs_cash_tie():
    fs = _fs(overrides={("CF", "기말현금및현금성자산", 2023): 3_050_000_000})
    findings = check_statements(fs)
    rules = {f.rule for f in findings if f.severity is Severity.WARN}
    assert "cf_bs_cash_tie" in rules and "cf_rollforward" in rules


# ── H_FS 시트 플랜 ────────────────────────────────────────────────────────────
def _grid(plan, name):
    return next(s for s in plan.sheets if s.name == name).rows


def _find_row(grid, col: int, value: str):
    """빈 행(구분선)이 섞여 있으므로 길이를 확인한 뒤 찾는다."""
    return next(r for r in grid
                if len(r) > col and isinstance(r[col], str) and r[col].strip() == value)


def test_sheet_plan_two_sheets_and_raw_is_won():
    fs = _fs()
    plan = build_fs_sheets(fs, company="테스트㈜")
    assert [s.name for s in plan.sheets] == ["rFS", "H_FS"]
    raw = _grid(plan, "rFS")
    header = raw[3]
    assert header[:6] == ["구분", "제표명", "표준계정코드", "계정명(원문)", "계층", "공시순서"]
    assert header[6:9] == ["2021", "2022", "2023"]
    cash = _find_row(raw, 3, "현금및현금성자산")
    assert cash[6:9] == [1_000_000_000, 2_000_000_000, 3_000_000_000]   # 원 단위 정수


def test_hfs_is_reference_only_no_keyin():
    """H_FS 의 모든 숫자 셀은 rFS 참조 수식이어야 한다(key-in 금지 계약)."""
    plan = build_fs_sheets(_fs())
    hfs = _grid(plan, "H_FS")
    numeric = [c for row in hfs for c in row[2:]
               if isinstance(c, (int, float))]
    assert not numeric, f"H_FS 에 하드코딩 숫자 {numeric[:5]}"
    cash = _find_row(hfs, 1, "현금및현금성자산")
    assert cash[2] == "=rFS!G7/10^6"


def test_hfs_has_identity_check_rows():
    """서버 항등식이 엑셀 체크행으로 그대로 심긴다(같은 규칙, 두 표면)."""
    plan = build_fs_sheets(_fs())
    hfs = _grid(plan, "H_FS")
    titles = [r[1] for r in hfs if len(r) > 1 and isinstance(r[1], str)]
    assert "자산 = 부채 + 자본" in titles
    assert "기초현금 + 순증감 = 기말현금" in titles
    row = next(r for r in hfs if len(r) > 1 and r[1] == "자산 = 부채 + 자본")
    assert row[2].startswith("=ROUND(") and "=ROUND(" in row[2][7:]


def test_hfs_refer_check_per_block():
    plan = build_fs_sheets(_fs())
    hfs = _grid(plan, "H_FS")
    refers = [r for r in hfs if len(r) > 1 and r[1] == "원본자료 Refer Check(전 계정)"]
    assert len(refers) == 3                       # BS·CIS·CF 각 1행
    assert refers[0][2].startswith("=SUMPRODUCT(") and refers[0][2].endswith(")=0")
    assert "rFS!" in refers[0][2]


def test_summary_buckets_sumif_and_equity_tie():
    plan = build_fs_sheets(_fs())
    hfs = _grid(plan, "H_FS")
    noa = next(r for r in hfs if len(r) > 1 and r[1] == "NOA")
    assert noa[2].startswith("=SUMIF(") and "-SUMIF(" in noa[2]
    tie = next(r for r in hfs if len(r) > 1 and r[1] == "자본총계 대사")
    assert tie[2].startswith("=ROUND(")


def test_totals_are_not_bucket_tagged():
    """총계 행에 버킷 태그가 붙으면 SUMIF 가 두 배로 샌다(비올 H_FS 의 규약)."""
    plan = build_fs_sheets(_fs())
    hfs = _grid(plan, "H_FS")
    for r in hfs:
        if len(r) > 1 and isinstance(r[1], str) and r[1].strip() in (
                "자산총계", "부채총계", "자본총계", "유동자산", "비유동자산"):
            assert r[0] == "", f"{r[1]} 에 태그 {r[0]}"


def test_bucket_tags_bridge_fs_mapper():
    """fs_mapper 버킷 → 비올 H_FS 태그(자산측/부채측 접기)가 계정별로 고정된다."""
    plan = build_fs_sheets(_fs())
    hfs = _grid(plan, "H_FS")
    tag = {r[1].strip(): r[0] for r in hfs
           if len(r) > 1 and isinstance(r[1], str) and isinstance(r[0], str)}
    assert tag["현금및현금성자산"] == "NOA"
    assert tag["매출채권"] == "WC" and tag["매입채무"] == "WC"   # 같은 WC, 부호는 SUMIF 가 처리
    assert tag["유형자산"] == "FA"
    assert tag["단기차입금"] == "IBD" and tag["장기차입금"] == "IBD"
    assert tag["자본금"] == "" and tag["이익잉여금"] == ""        # 자본은 대사 상대편


def test_every_row_is_a_list_not_a_string():
    """행에 문자열을 그대로 넣으면 **글자 단위로 흩어진다** — 조용히 열 수가 폭발한다.

    실측: 상태 헤더를 `[...]` 로 감싸지 않아 rFS 2행이 ['삼','성','전','자',…] 가 되고
    시트 열 수가 8 → 102 로 부풀었다(배치 미리보기도 함께 거짓말을 했다).
    """
    plan = build_fs_sheets(_fs(), company="테스트㈜")
    for sp in plan.sheets:
        for i, row in enumerate(sp.rows, start=1):
            assert isinstance(row, list), f"{sp.name} {i}행이 리스트가 아님: {row!r}"


def test_layout_meta_matches_actual_grid():
    """배치 미리보기(행×열)는 실제 격자와 일치해야 한다 — 공간 예측의 근거."""
    plan = build_fs_sheets(_fs(), company="테스트㈜")
    by_name = {s.name: s for s in plan.sheets}
    for L in plan.meta["layout"]:
        sp = by_name[L["name"]]
        assert L["rows"] == len(sp.rows)
        assert L["cols"] == max(len(r) for r in sp.rows)
    assert plan.meta["layout"][1]["year_cols"] == "C:E"      # 3개년 → C,D,E
    titles = [b["title"] for b in plan.meta["blocks"]]
    assert titles == ["재무상태표", "포괄손익계산서", "현금흐름표"]


def test_status_header_states_years_and_unit():
    """모델러스 시트 헤더 규약 최소판 — 회사·연결여부·단위·연도범위가 2행에 확정된다."""
    plan = build_fs_sheets(_fs(), company="테스트㈜")
    hfs, raw = plan.sheets[1], plan.sheets[0]
    assert "2021~2023 3개년" in hfs.rows[1][0] and "단위: 백만원" in hfs.rows[1][0]
    assert "연결(CFS)" in hfs.rows[1][0] and "테스트㈜" in hfs.rows[1][0]
    assert "단위: 원(공시 원문)" in raw.rows[1][0]
    # 각 제표 블록에 연도 헤더가 반복된다(스크롤해도 어느 열이 몇 년인지 안다).
    year_headers = [r for r in hfs.rows if len(r) > 2 and r[2] == "2021"]
    assert len(year_headers) >= 4          # 요약 + BS·CIS·CF 블록


def test_plan_to_json_serializable():
    import json
    plan = build_fs_sheets(_fs(), company="테스트㈜")
    blob = json.dumps(plan_to_json(plan), ensure_ascii=False)
    assert '"H_FS"' in blob and "rFS!" in blob


def test_col_letter():
    assert [col_letter(i) for i in (0, 1, 25, 26, 27)] == ["A", "B", "Z", "AA", "AB"]


# ── 클라이언트 연동(네트워크 mock) ────────────────────────────────────────────
def test_fetch_multi_year_calls_per_year_newest_first():
    calls: list[dict] = []

    def http(url, params):
        calls.append(params)
        return {"status": "000", "list": _report(int(params["bsns_year"]))["rows"]}

    fs = fetch_multi_year(DartClient(api_key="K", http=http), "00126380", [2021, 2022, 2023])
    assert [p["bsns_year"] for p in calls] == ["2023", "2022", "2021"]
    assert all(p["crtfc_key"] == "K" and p["fs_div"] == "CFS" for p in calls)
    assert fs.years == [2021, 2022, 2023]


def test_fetch_multi_year_tolerates_missing_year():
    def http(url, params):
        if params["bsns_year"] == "2021":
            return {"status": "013", "message": "조회된 데이타가 없습니다."}
        return {"status": "000", "list": _report(int(params["bsns_year"]))["rows"]}

    fs = fetch_multi_year(DartClient(api_key="K", http=http), "c", [2021, 2022, 2023])
    # 2021 보고서는 못 받았지만 2022·2023 보고서의 비교열이 2021 을 채운다.
    assert fs.years == [2021, 2022, 2023]
    assert any("2021: 조회 실패" in n for n in fs.notes)


def test_total_failure_reports_per_year_reason_not_a_guess_list():
    """전량 실패 시 연도별 DART 상태코드를 버리지 않는다.

    회귀 대상: "corp_code·fs_div·연도 범위를 확인하세요"만 던지면, 사유를 이미 손에
    쥐고 있으면서 사용자에게 셋을 다 바꿔가며 재조회하라고 시키는 셈이 된다.
    """
    from ingest.dart_fs import MultiYearFsError

    def http(url, params):
        return {"status": "013", "message": "조회된 데이타가 없습니다."}

    try:
        fetch_multi_year(DartClient(api_key="K", http=http), "c", [2024, 2025])
    except MultiYearFsError as e:
        msg = str(e)
        assert "013" in msg and "조회된 데이타가 없습니다" in msg   # 본 사유가 실린다
        assert "2024" in msg and "2025" in msg                     # 어느 해가 왜인지
        assert "fs_div=CFS" in msg                                 # 무엇으로 물었는지
        assert "별도(OFS)" in msg                                  # 다음 수를 지목
    else:
        raise AssertionError("전량 실패는 MultiYearFsError 여야 한다")


def test_total_failure_without_no_data_does_not_suggest_ofs():
    """013 이 아닌 실패(키 오류 등)에 'OFS 로 바꾸세요'를 붙이면 오진을 유도한다."""
    from ingest.dart_fs import MultiYearFsError

    def http(url, params):
        return {"status": "020", "message": "사용한도를 초과하였습니다."}

    try:
        fetch_multi_year(DartClient(api_key="K", http=http), "c", [2024])
    except MultiYearFsError as e:
        assert "사용한도" in str(e) and "별도(OFS)" not in str(e)
    else:
        raise AssertionError("전량 실패는 MultiYearFsError 여야 한다")


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
