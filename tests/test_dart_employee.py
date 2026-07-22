"""DART 직원현황 커넥터 테스트 — 집계·인당급여·cross-source tie-out·headcount 배선.

canned empSttus JSON 주입(네트워크/키 불요). stdlib: `python tests/test_dart_employee.py`.
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ingest.dart_client import DartClient  # noqa: E402
from ingest.dart_employee import (  # noqa: E402
    aggregate_employee_status, tieout_labor_cost, to_headcount_costline,
)
from ingest.validators import Severity  # noqa: E402

# 사업부문×성별 4행. sm=인원, fyer_salary_totamt=연간급여총액(원).
_ROWS = [
    {"fo_bbm": "제조", "sexdstn": "남", "sm": "200",
     "fyer_salary_totamt": "12,000,000,000", "rcept_no": "R1"},
    {"fo_bbm": "제조", "sexdstn": "여", "sm": "100",
     "fyer_salary_totamt": "5,000,000,000", "rcept_no": "R1"},
    {"fo_bbm": "관리", "sexdstn": "남", "sm": "50",
     "fyer_salary_totamt": "4,000,000,000", "rcept_no": "R1"},
    {"fo_bbm": "관리", "sexdstn": "여", "sm": "50",
     "fyer_salary_totamt": "3,000,000,000", "rcept_no": "R1"},
]
# 총원 400명, 급여총액 24,000백만원(원→백만원), 인당 60백만원


def test_aggregate_headcount_and_wage():
    snap = aggregate_employee_status(_ROWS, source_id="T", year="2024")
    assert snap.headcount == Decimal("400")
    assert snap.total_salary == Decimal("24000")          # 240억원 → 24,000백만원
    assert snap.avg_wage == Decimal("60.0000")            # 24000/400
    assert snap.report.ok
    # 부문별 세부
    assert snap.by_division["제조"]["인원"] == Decimal("300")
    assert snap.by_division["관리"]["급여총액"] == Decimal("7000")


def test_provenance_is_dart_structured():
    snap = aggregate_employee_status(_ROWS, source_id="T", year="2024")
    pv = snap.values[0]
    assert pv.provenance.source_kind.value == "dart"
    assert pv.provenance.method.value == "structured"
    assert pv.provenance.locator.rcept_no == "R1"


def test_zero_headcount_warns():
    rows = [{"fo_bbm": "휴면", "sexdstn": "남", "sm": "-",
             "fyer_salary_totamt": "-", "rcept_no": "R9"}]
    snap = aggregate_employee_status(rows, source_id="T", year="2024")
    assert snap.headcount == Decimal("0") and snap.avg_wage is None
    assert any(f.rule == "employee" and f.severity is Severity.WARN
               for f in snap.report.findings)


def test_to_headcount_costline_projects():
    snap = aggregate_employee_status(_ROWS, source_id="T", year="2024")
    line = to_headcount_costline(snap, name="노무비", category="cogs", years=3,
                                 headcount_growth=0.05, wage_growth=0.03,
                                 severance_rate=0.1)
    assert line["method"] == "headcount" and line["category"] == "cogs"
    # 인원 400×1.05=420, 인당 60×1.03=61.8 (1차년)
    assert abs(line["headcount"][0] - 420.0) < 1e-6
    assert abs(line["wage_per_head"][0] - 61.8) < 1e-6
    assert line["severance_rate"] == 0.1
    # cost_build 로 실제 투영되는지(왕복) — 인원×인당×(1+퇴직)
    from calc_core.cost_build import CostLine, project_costs
    cl = CostLine(name="노무비", category="cogs", method="headcount",
                  headcount=line["headcount"], wage_per_head=line["wage_per_head"],
                  severance_rate=line["severance_rate"])
    res = project_costs([cl], 3)
    assert abs(res.cogs[0] - 420.0 * 61.8 * 1.1) < 1e-3


def test_headcount_costline_none_when_no_wage():
    rows = [{"fo_bbm": "x", "sexdstn": "", "sm": "0", "fyer_salary_totamt": "0"}]
    snap = aggregate_employee_status(rows, source_id="T", year="2024")
    line = to_headcount_costline(snap, years=3)
    assert line["headcount"] is None                       # 산출 불가 → 수기 필요


def test_cross_source_tieout_pass_and_fail():
    snap = aggregate_employee_status(_ROWS, source_id="T", year="2024")
    # 주석 성격별 '급여' 23,500백만원 ≈ DART 24,000 (2.1% 차 < 5% tol) → PASS
    f_ok = tieout_labor_cost(Decimal("23500"), snap)
    assert f_ok.severity is Severity.PASS
    # 주석 급여 18,000 → 25% 차 > tol → FAIL(발견사항)
    f_bad = tieout_labor_cost(Decimal("18000"), snap)
    assert f_bad.severity is Severity.FAIL


def test_client_employee_status_via_injected_http():
    # DartClient.employee_status 가 empSttus 를 호출해 snapshot 을 만드는지(http 주입)
    calls = {}

    def fake_http(url, params):
        calls["url"] = url
        return {"status": "000", "list": _ROWS}

    client = DartClient(api_key="k", http=fake_http)
    snap = client.employee_status("00126380", 2024)
    assert "empSttus.json" in calls["url"]
    assert snap.headcount == Decimal("400") and snap.avg_wage == Decimal("60.0000")


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
