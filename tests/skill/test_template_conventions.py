"""W2.5·W4·W5 뼈대 규약 회귀 (P2: R4·R6·R8·R10·R12).

근거: docs/reference/모델러스_통합모델_5.4.md §2.1(b)(c)·§2.2(b)(c)·§2.4(a)·§1.2.
생성물(뼈대 시트)은 사람이 눈으로만 확인하기 쉬워 회귀가 조용히 난다 — 수식 형태를
문자열로 고정한다.

실행: `py -3.12 -m pytest tests/skill/test_template_conventions.py`
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / ".claude" / "skills" / "excel-valuation-workbook" / "scripts"))

from excel.template_schema import CHECK_TOL, LABOR_ROLES  # noqa: E402
from excel.xlsx_writer import Workbook  # noqa: E402

import stage_sheets  # noqa: E402


def _cells(builder, n: int = 5) -> dict:
    """뼈대 생성 → {ref: 수식 or 값} 평면 dict."""
    wb = Workbook()
    s = builder(wb, n)
    out = {}
    for ref, c in s.cells.items():
        out[ref] = ("=" + c.formula) if c.formula is not None else c.value
    return out


def _find_row(cells: dict, needle: str) -> int:
    """B열 라벨로 행 찾기(뼈대 행번호를 테스트에 하드코딩하지 않기 위함)."""
    for ref, v in cells.items():
        if ref.startswith("B") and isinstance(v, str) and needle in v:
            return int(re.sub(r"\D", "", ref))
    raise AssertionError(f"라벨 '{needle}' 없음")


# ── R8 가시 상태 헤더 ────────────────────────────────────────────────────────
def test_status_header_on_every_stage_sheet():
    """전 시트 상단에 Scenario/Target Price/Stage 노출 — _VS_STATE 는 숨김이라 안 보인다."""
    for builder in (stage_sheets.build_fcst_cost, stage_sheets.build_wc,
                    stage_sheets.build_peer, stage_sheets.build_fs_disagg):
        c = _cells(builder)
        assert c.get("I1") == "Scenario :", builder.__name__
        assert c.get("I2") == "Target Price :", builder.__name__
        assert c.get("I3") == "Stage :", builder.__name__


# ── R6 CHECK 행(허용오차) ────────────────────────────────────────────────────
def test_check_rows_use_tolerance_not_exact_equality():
    """정확일치 비교는 부동소수 노이즈로 오작동한다(모델러스 D1) — ABS(차이)<tol 이어야."""
    for builder in (stage_sheets.build_fs_disagg, stage_sheets.build_fcst_cost):
        c = _cells(builder)
        checks = [v for v in c.values()
                  if isinstance(v, str) and v.startswith("=IF(") and "TRUE" in v]
        assert checks, builder.__name__
        for f in checks:
            assert f"ABS(" in f and f"<{CHECK_TOL}" in f, (builder.__name__, f)
            # 잔차를 표시해야 한다 — TRUE/FALSE 만으로는 어디가 얼마나 틀렸는지 모른다
            assert not f.endswith('"FALSE")'), f


def test_fs_disagg_sum_preservation_check():
    """세분합 = 원계정 CHECK 가 블록마다 있어야."""
    c = _cells(stage_sheets.build_fs_disagg)
    rows = [r for r, v in c.items()
            if r.startswith("B") and isinstance(v, str) and "CHECK 세분합" in v]
    assert len(rows) == 4, rows        # 매출·원가·판관비·영업외 4블록


# ── R4 인건비 bottom-up + 배분 ───────────────────────────────────────────────
def test_labor_buildup_is_live_formula():
    """총인건비 = 총인원 × (연근무일 × 일근무시간 × 시급) — 전부 살아있는 수식."""
    c = _cells(stage_sheets.build_fcst_cost)
    head_tot = _find_row(c, "총인원 (= Σ직군)")
    per_head = _find_row(c, "1인 인건비")
    total = _find_row(c, "총인건비")
    assert c[f"C{head_tot}"].startswith("=SUM(")
    days, hours, wage = per_head - 3, per_head - 2, per_head - 1
    assert c[f"C{per_head}"] == f"=C{days}*C{hours}*C{wage}"
    assert c[f"C{total}"] == f"=C{head_tot}*C{per_head}"
    # 직군 행이 스키마 SSOT 와 동수
    assert sum(1 for v in c.values()
               if isinstance(v, str) and v.startswith("인원 · ")) == len(LABOR_ROLES)


def test_allocation_is_residual_so_sum_is_preserved():
    """배분은 `판관비=총액×%`, `원가=총액−판관비` 잔차 방식 — 합보존이 수식으로 강제된다."""
    c = _cells(stage_sheets.build_fcst_cost)
    sga_r = _find_row(c, "→ 판관비 (급여)")
    cogs_r = _find_row(c, "→ 매출원가 (노무비)")
    tot_r, pct_r = sga_r - 2, sga_r - 1
    assert c[f"C{sga_r}"] == f"=C{tot_r}*C{pct_r}"
    assert c[f"C{cogs_r}"] == f"=C{tot_r}-C{sga_r}"      # 잔차 — 두 % 를 따로 입력하지 않는다
    chk = _find_row(c, "CHECK 배분합 = 인건비 총액")
    assert "ABS(" in c[f"C{chk}"] and f"C{cogs_r}+C{sga_r}" in c[f"C{chk}"]


# ── R10 2차원 INDEX/MATCH ────────────────────────────────────────────────────
def test_peer_lookup_is_two_dimensional_index_match():
    """②는 ①을 행=티커·열=필드명 이중 MATCH 로 조회 — 손으로 옮겨적지 않는다."""
    c = _cells(stage_sheets.build_peer)
    f = c["C17"]
    assert f.startswith("=INDEX(") and f.count("MATCH(") == 2, f
    assert "$C$6:$C$11" in f          # 행 키 = ① Ticker 열
    assert "$B$6:$J$6" in f           # 열 키 = ① 헤더행


def test_peer_lookup_header_string_matches_source():
    """헤더 문자열이 곧 조회 키 — 장식을 붙이면 #N/A 가 된다(실제로 한 번 냈던 실수)."""
    c = _cells(stage_sheets.build_peer)
    src_headers = {c.get(col + "6") for col in "BCDEFGHIJ"}
    assert c["C16"] in src_headers, (c["C16"], src_headers)


# ── R12 lookback provenance ──────────────────────────────────────────────────
def test_wc_requires_lookback_window_and_reason():
    """회전일은 대개 과거 N년 평균인데 N 자체가 판단 — 창과 사유 칸이 있어야."""
    c = _cells(stage_sheets.build_wc)
    assert c.get("K5") == "lookback(년)"
    assert c.get("L5") == "lookback 사유"
    for rr in (8, 9, 10):                      # DSO·DIO·DPO
        assert c.get(f"K{rr}") == "[입력]"
        assert "[입력" in c.get(f"L{rr}", "")


# ── W6b Model 3표 뼈대 ───────────────────────────────────────────────────────
def test_model_sheet_has_opening_column_so_rollforward_is_uniform():
    """기초(실적) 열이 있어야 롤포워드가 **첫 해부터 같은 수식**으로 떨어진다."""
    c = _cells(stage_sheets.build_model_3s)
    assert c.get("C8") == "기초/실적" and c.get("D8") == "1년차"
    fa = _find_row(c, "순유형자산")
    da = _find_row(c, "(+) 감가상각비")
    capex = _find_row(c, "(−) CAPEX")
    # 1년차 FA = 기초(C) + CAPEX − D&A  ← 기초 열을 참조
    assert c[f"D{fa}"] == f"=C{fa}+D{capex}-D{da}"


def test_model_sheet_circuit_switch_gates_interest_income():
    """R14 Circuit Switch — OFF 면 이자수익 0(모델러스 IF($L$5=\"ON\",…) 재현)."""
    c = _cells(stage_sheets.build_model_3s)
    assert c.get("C5") == "ON"
    ii = _find_row(c, "(+) 이자수익")
    f = c[f"D{ii}"]
    assert f.startswith('=IF($C$5="ON",') and f.endswith(",0)"), f
    # 평균잔액 기준(기본·더 정확)이어야 한다
    avg = _find_row(c, "이자부자산 평균잔액")
    assert c[f"D{avg}"].startswith("=AVERAGE("), c[f"D{avg}"]


def test_check_rows_parenthesize_both_sides():
    """⚠️ 회귀: 우변이 다항식이면 괄호 없이는 **부호가 뒤집힌다**.

    `자산-부채+자본` 이 되어버려 대차 CHECK 가 완전히 틀린 값을 낸다
    (연산자 우선순위 함정 — 실제로 W6b 생성물에서 발견).
    """
    c = _cells(stage_sheets.build_model_3s)
    bs = _find_row(c, "CHECK 대차")
    ta, tl, te = _find_row(c, "자산 계"), _find_row(c, "부채 계"), _find_row(c, "자본 계")
    assert c[f"D{bs}"] == (
        f'=IF(ABS((D{ta})-(D{tl}+D{te}))<{CHECK_TOL},"TRUE",(D{ta})-(D{tl}+D{te}))'
    ), c[f"D{bs}"]
    # 현금연결도 3항 우변
    cf = _find_row(c, "CHECK 현금연결")
    assert "-(D" in c[f"D{cf}"] and c[f"D{cf}"].count("+") >= 2, c[f"D{cf}"]


def test_model_sheet_registered_as_w6b_stage():
    from excel.xlsx_writer import Workbook
    wb = Workbook()
    assert stage_sheets.build_stage(wb, "W6b") == ["Model"]


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"{len(fns)}/{len(fns)} passed")



