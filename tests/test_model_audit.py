"""외부 모델 정적 감사(model_audit.py) 테스트 — 비올 §7.1 결함 형태 재현.

R1C1 정규화·패턴 린트(행/열)·하드코딩 스캔·민감도 중심셀 검산.
균일 밀림(E-3형)은 **의도적 미검출**(L3 분석적 절차 소관)임을 테스트로 문서화.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from excel.model_audit import (  # noqa: E402
    audit_workbook, check_sensitivity_center, formula_pattern_lint, hardcode_scan,
    normalize_r1c1,
)
from excel.xlsx_reader import RCell  # noqa: E402
from ingest.validators import Severity  # noqa: E402


# ── R1C1 정규화 ──────────────────────────────────────────────────────────────
def test_normalize_absolute_and_relative():
    assert normalize_r1c1("$G$162", "M162") == "R162C7"
    assert normalize_r1c1("J162", "M162") == "R[+0]C[-3]"
    # 같은 패턴으로 복사된 수식은 호스트가 달라도 동일 정규형
    assert normalize_r1c1("N199*N200", "N198") == normalize_r1c1("Q199*Q200", "Q198")


def test_normalize_sheet_prefix_and_funcs():
    assert normalize_r1c1("상각비계산!H5/10^6", "M17") == "상각비계산!R[-12]C[-5]/10^6"
    # 함수명(LOG10 등) 중간의 숫자는 참조가 아니다
    assert normalize_r1c1("LOG10(5)", "A1") == "LOG10(5)"
    # 문자열 리터럴은 접어서 비교(내용 차이는 패턴 차이가 아님)
    assert normalize_r1c1('IF(A1>0,"양수",A2)', "C1") == 'IF(R[+0]C[-2]>0,"",R[+1]C[-2])'


# ── 패턴 린트: 행 방향 (E-6·E-10 형태) ──────────────────────────────────────
def test_row_lint_catches_e6_lone_reference():
    # E-6: M162 만 =J162(2021년 실적), 이웃 4개는 =$G$162(평균) — 3년 밀림
    cells = {"M162": RCell(None, "J162"),
             **{f"{c}162": RCell(None, "$G$162") for c in "NOPQ"}}
    fs = formula_pattern_lint(cells, sheet_name="EBIT")
    assert len(fs) == 1
    assert fs[0].detail["ref"] == "M162" and fs[0].detail["direction"] == "row"


def test_row_lint_catches_e10_operator_break():
    # E-10②: 합계가 곱(×)이어야 할 자리에 SUM — 실적/추정 열 구조 상이
    cells = {"M198": RCell(None, "SUM(M199:M202)"),
             **{f"{c}198": RCell(None, f"{c}199*{c}200") for c in "NOPQ"}}
    fs = formula_pattern_lint(cells, sheet_name="EBIT")
    assert [f.detail["ref"] for f in fs] == ["M198"]


# ── 패턴 린트: 열 방향 (E-5 형태) ────────────────────────────────────────────
def test_col_lint_catches_e5_column_shift():
    # 자산별 상각: M17~M22 는 H열(2024) 매칭, M23 만 G열(연상각액) — 1열 이름
    cells = {f"M{17 + i}": RCell(None, f"상각비계산!H{5 + i}/10^6") for i in range(6)}
    cells["M23"] = RCell(None, "상각비계산!G26/10^6")
    fs = formula_pattern_lint(cells, sheet_name="FA")
    assert [f.detail["ref"] for f in fs] == ["M23"]
    assert fs[0].detail["direction"] == "col"


def test_edge_and_inner_positions_are_labeled():
    """양끝/중간 위치 표기 — 소비자(UI)가 **끄지 않고 순서를 매길** 근거.

    실측(비올 워크북): 패턴 경고 80건 중 대부분이 구간 양끝이었고 양끝은 첫해 반년상각·
    터미널 외삽처럼 정상일 여지가 크다. 그렇다고 배제하면 안 된다 — E-6·E-10·E-5 가
    전부 양끝 결함이었다(이 파일 위쪽 테스트). 그래서 라벨만 붙이고 판정은 유지한다.
    """
    # 중간(inner) 이탈: 5칸 중 가운데가 다름
    mid = {f"{c}10": RCell(None, "$G$10") for c in "MNPQ"}
    mid["O10"] = RCell(None, "J10")
    fs = formula_pattern_lint(mid, sheet_name="X")
    assert [f.detail["position"] for f in fs] == ["inner"]
    # 양끝(edge) 이탈: E-6 형태(첫 칸)
    head = {"M162": RCell(None, "J162"),
            **{f"{c}162": RCell(None, "$G$162") for c in "NOPQ"}}
    fs2 = formula_pattern_lint(head, sheet_name="EBIT")
    assert [f.detail["position"] for f in fs2] == ["edge"]


def test_tax_bracket_and_check_row_are_not_hardcode():
    """규약이 요구하는 상수는 하드코딩이 아니다 — 자기 규약을 자기가 경고하지 않는다.

    ① CHECK 행 허용오차(template_schema.CHECK_TOL) ② 한국 법인세 계단식
    (dcf_export._tax_formula 가 생성하는 바로 그 수식). 실측에서 이 둘이 다수를 차지해
    진짜 신호(`T164=M165*32`)를 파묻었다.
    """
    cells = {
        "H16": RCell(None, 'IF(ABS((H14)-(H10-H13))<0.001,"TRUE",(H14)-(H10-H13))'),
        "M17": RCell(None, "IF(M15<0,0,IF(M15<200,M15*9%*1.1,IF(M15<20000,"
                           "(200*9%+(M15-200)*19%)*1.1,(200*9%+19800*19%+(M15-20000)*21%)*1.1)))"),
    }
    assert hardcode_scan(cells, sheet_name="DCF").severity is Severity.PASS
    # 반면 진짜 숨은 가정은 그대로 잡힌다(비올 J-1: 인건비 ×32 중복)
    real = {"T164": RCell(None, "M165*32")}
    f = hardcode_scan(real, sheet_name="EBIT")
    assert f.severity is Severity.WARN and f.detail["offenders"][0]["literals"] == [32.0]


def test_uniform_shift_is_blind_spot_by_design():
    # E-3(ΔNWC 5열 밀림)은 행 전체가 **균일하게** 밀려 이웃 대조로는 안 잡힌다
    # — L3 분석적 절차(성장-운전자본 정합)가 담당하는 계층 분담의 문서화.
    cells = {f"{c}24": RCell(None, f"-WC!{h}15")
             for c, h in zip("MNOPQ", "HIJKL")}
    assert formula_pattern_lint(cells, sheet_name="DCF") == []


def test_short_runs_ignored():
    cells = {"A1": RCell(None, "B1"), "B1": RCell(None, "$Z$1")}
    assert formula_pattern_lint(cells, sheet_name="S") == []


# ── 하드코딩 스캔 ────────────────────────────────────────────────────────────
def test_hardcode_scan_catches_t164():
    # J-1 진원지: `=M165*32` 의 32(인당급여 하드코딩)
    f = hardcode_scan({"T164": RCell(None, "M165*32")}, sheet_name="EBIT")
    assert f.severity is Severity.WARN
    assert f.detail["offenders"][0]["literals"] == [32.0]


def test_hardcode_scan_whitelists_conventions():
    cells = {"M16": RCell(None, "상각비계산!H5/10^6"),      # 단위환산
             "H49": RCell(None, "H22*365"),                  # 회전기일 관용
             "F23": RCell(None, "F20*(1+(1-F22)*F21)")}      # 구조 상수 0·1
    f = hardcode_scan(cells, sheet_name="FA")
    assert f.severity is Severity.PASS


# ── 민감도 중심셀 ────────────────────────────────────────────────────────────
def test_sensitivity_center_catches_e9():
    # E-9 실측: 표시 8,634.7 vs 실제 8,413.38 (+2.6% 과대 오독)
    f = check_sensitivity_center(8634.7, 8413.38)
    assert f.severity is Severity.WARN
    assert f.detail["diff"] == pytest.approx(221.32, abs=1e-2)


def test_sensitivity_center_pass():
    assert check_sensitivity_center(8413.38, 8413.38).severity is Severity.PASS


# ── 워크북 종합 ──────────────────────────────────────────────────────────────
def test_audit_workbook_aggregates():
    wb = {"EBIT": {"M162": RCell(None, "J162"),
                   **{f"{c}162": RCell(None, "$G$162") for c in "NOPQ"},
                   "T164": RCell(None, "M165*32")}}
    rep = audit_workbook(wb)
    rules = {f.rule for f in rep.warns}
    assert {"formula_pattern", "formula_hardcode"} <= rules
