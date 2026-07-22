"""4종 검증 엔진 단위테스트 — 숫자형·공백·합계·정합성.

실제 DART/복붙 데이터의 지저분한 형태(콤마·괄호음수·단위·대시)를 커버.
stdlib: `python tests/test_validators.py`.
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ingest import (  # noqa: E402
    CellKind, Severity, ValidationReport,
    classify_cell, parse_number, reconcile_sum, tie_out,
)

D = Decimal


# ── ① 숫자형 ────────────────────────────────────────────────────────────────
def test_parse_basic_and_commas():
    assert parse_number("1,234,567") == D("1234567")
    assert parse_number("  42.5 ") == D("42.5")


def test_parse_parenthesis_negative():
    assert parse_number("(1,234)") == D("-1234")
    assert parse_number("△500") == D("-500")


def test_parse_percent():
    assert parse_number("12.5%") == D("0.125")


def test_parse_units_to_million():
    # 백만원 기준 정규화
    assert parse_number("5", unit="억원") == D("500")      # 5억 = 500백만
    assert parse_number("3,000", unit="천원") == D("3")     # 3,000천원 = 3백만
    assert parse_number("2,000,000원") == D("2")            # 인라인 단위 우선: 2백만
    assert parse_number("1조") == D("1000000")             # 1조 = 1,000,000백만


def test_parse_useful_life_years():
    assert parse_number("5년") == D("5")
    assert parse_number("40년") == D("40")


def test_parse_invalid_records_fail():
    rep = ValidationReport()
    assert parse_number("N/A", report=rep, field_name="내용연수") is None
    assert not rep.ok  # fail 기록
    assert rep.fails[0].rule == "numeric"


def test_parse_blank_and_dash_are_none_not_fail():
    rep = ValidationReport()
    assert parse_number("", report=rep) is None
    assert parse_number("-", report=rep) is None
    assert parse_number(None, report=rep) is None
    assert rep.ok  # 공백/대시/결측은 fail 아님


# ── ② 공백유무 ──────────────────────────────────────────────────────────────
def test_classify_cell():
    assert classify_cell(None) is CellKind.MISSING
    assert classify_cell("   ") is CellKind.BLANK
    assert classify_cell("-") is CellKind.DASH
    assert classify_cell("0") is CellKind.ZERO
    assert classify_cell("123") is CellKind.VALUE


# ── ③ 합계검증 ──────────────────────────────────────────────────────────────
def test_reconcile_sum_pass_and_fail():
    ok = reconcile_sum("판관비성격별", [D(100), D(200), D(300)], D(600))
    assert ok.severity is Severity.PASS
    bad = reconcile_sum("판관비성격별", [D(100), D(200), D(300)], D(650))
    assert bad.severity is Severity.FAIL and "불일치" in bad.message


def test_reconcile_sum_missing_component_warns():
    w = reconcile_sum("유형자산", [D(100), None, D(300)], D(400))
    assert w.severity is Severity.WARN


def test_reconcile_within_tolerance():
    # 반올림 오차 허용
    r = reconcile_sum("합", [D("100.0001")], D("100.0"))
    assert r.severity is Severity.PASS


# ── ④ 정합성(tie-out) ───────────────────────────────────────────────────────
def test_tie_out_pass_and_fail():
    # 주석 감가상각비 = CF D&A
    assert tie_out("감가상각 tie-out", D("1500.09"), D("1500.09")).severity is Severity.PASS
    bad = tie_out("감가상각 tie-out", D("1500"), D("1800"))
    assert bad.severity is Severity.FAIL


def test_report_gate():
    rep = ValidationReport()
    reconcile_sum("a", [D(1), D(2)], D(3), report=rep)      # pass
    tie_out("b", D(10), D(10), report=rep)                  # pass
    assert rep.ok
    reconcile_sum("c", [D(1)], D(99), report=rep)           # fail
    assert not rep.ok and len(rep.fails) == 1


ALL = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    for fn in ALL:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"PASS — 4종 검증 엔진 {len(ALL)}건 전부 통과")
