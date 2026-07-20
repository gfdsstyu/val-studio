"""3표 완전연결 — 정합성 검증기 + 순환참조 3층 해법 테스트.

핵심은 **결함 주입**이다. 항등식이 0으로 맞는 것만 확인하면 "검증기가 작동한다"는
증거가 못 된다 — 일부러 배관을 어긋나게 했을 때 **그만큼의 잔차가 뜨는지**가 증거다.

근거: docs/reference/앤트로픽_금융스킬_벤치마크.md §2 audit-xls(모델 스코프 무결성),
docs/reference/모델러스_통합모델_5.4.md §2.2(Circuit Switch).

실행: `py -3.12 -m pytest tests/test_three_statement.py` 또는 `py -3.12 tests/...`
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core.checks import (  # noqa: E402
    THREE_STATEMENT_TOL,
    check_fcff_vs_cashflow,
    check_three_statement_integrity,
)
from calc_core.three_statement import (  # noqa: E402
    FinancingPlan,
    OpeningBalanceSheet,
    ThreeStatementInput,
    project_three_statements,
)

TAX = 0.242            # 정률(구간세율 비선형성을 배제해 대사를 정확히 성립시킴)


def _opening(**over) -> OpeningBalanceSheet:
    base = dict(cash=500.0, short_term_investments=200.0, net_working_capital=300.0,
                net_fixed_assets=1000.0, other_assets=50.0,
                interest_bearing_debt=800.0, other_liabilities=100.0,
                paid_in_capital=600.0, retained_earnings=550.0, other_equity=0.0)
    base.update(over)
    return OpeningBalanceSheet(**base)


def _input(**over) -> ThreeStatementInput:
    base = dict(
        ebit=[300.0, 330.0, 360.0],
        dep_amort=[100.0, 110.0, 120.0],
        capex=[120.0, 130.0, 140.0],
        net_working_capital=[320.0, 345.0, 370.0],
        opening=_opening(),
        financing=FinancingPlan(
            debt_issuance=[0.0, 0.0, 0.0], debt_repayment=[100.0, 100.0, 100.0],
            interest_rate_debt=0.04, interest_rate_cash=0.03,
            dividend_payout_ratio=0.3),
        effective_tax_rate=TAX,
    )
    base.update(over)
    return ThreeStatementInput(**base)


def _sev(findings, rule):
    return next(f.severity.name for f in findings if f.rule == rule)


def _find(findings, rule):
    return next(f for f in findings if f.rule == rule)


# ══ ① 항등식: 정합 입력이면 잔차 0 ═══════════════════════════════════════════
def test_opening_balance_sheet_must_balance():
    assert abs(_opening().balance_residual()) < 1e-12


def test_identities_hold_for_consistent_input():
    """조립이 정합하면 대차·현금연결·RE 롤이 **저절로** 맞는다(플러그 없이)."""
    r = project_three_statements(_input())
    for name, seq in (("대차", r.balance_residual),
                      ("현금연결", r.cash_tie_residual),
                      ("RE롤", r.re_rollforward_residual)):
        assert max(abs(x) for x in seq) < 1e-9, (name, seq)
    f = check_three_statement_integrity(r)
    for rule in ("ts_opening_balance", "ts_balance_sheet", "ts_cash_tie",
                 "ts_re_rollforward", "ts_circularity"):
        assert _sev(f, rule) == "PASS", (rule, _find(f, rule).message)


def test_statements_are_internally_coherent():
    """IS→CF→BS 연결이 실제 값으로도 성립하는지(항등식 외 스팟 체크)."""
    r = project_three_statements(_input())
    # 기말현금 = 기초현금 + 순증감
    assert abs(r.cash[0] - (500.0 + r.net_change_in_cash[0])) < 1e-9
    # FA 롤포워드 = 기초 + CAPEX − D&A
    assert abs(r.net_fixed_assets[0] - (1000.0 + 120.0 - 100.0)) < 1e-9
    # 부채 = 기초 + 발행 − 상환
    assert abs(r.interest_bearing_debt[0] - (800.0 - 100.0)) < 1e-9
    # EBT = EBIT + 이자수익 − 이자비용
    assert abs(r.ebt[0] - (300.0 + r.interest_income[0] - r.interest_expense[0])) < 1e-9
    # 세금 = 세전 × 정률
    assert abs(r.tax[0] - r.ebt[0] * TAX) < 1e-9


# ══ ② 결함 주입 — 검증기가 실제로 잡는가 (가장 중요) ═════════════════════════
def test_unbalanced_opening_persists_as_constant_residual():
    """기초 BS 불균형은 **누적되지 않고 상수로 지속** — 진단이 쉬워야 한다."""
    bad = _input(opening=_opening(other_assets=50.0 + 100.0))   # 자산만 +100
    r = project_three_statements(bad)
    assert abs(r.opening_balance_residual - 100.0) < 1e-9
    for t, resid in enumerate(r.balance_residual):
        assert abs(resid - 100.0) < 1e-9, (t, resid)            # 100 이 계속 남는다
    f = check_three_statement_integrity(r)
    assert _sev(f, "ts_opening_balance") == "FAIL"
    assert _sev(f, "ts_balance_sheet") == "FAIL"


def test_dep_amort_divergence_is_absorbed_by_balance_identity():
    """⚠️ **대차는 D&A 오류를 흡수한다** — 이 검증기의 한계를 명시적으로 고정한다.

    D&A 는 CFO(+비현금 가산)와 FA 롤(−상각)에 **같은 크기로** 들어가 ΔAssets 유도에서
    상쇄된다. 따라서 D&A 를 틀리게 넣어도 대차 잔차는 0 이다. 대차만 보고 "모델이
    맞다"고 결론내면 안 된다는 뜻 — audit-xls 가 'D&A(CF=IS)' 를 별도 항목으로 둔 이유다.
    실제 탐지는 `check_three_statement_vs_spine` 이 담당한다(아래 ⑥).
    """
    base = _input()
    bad = _input(dep_amort=[100.0 + 50.0, 110.0, 120.0])
    rb, rr = project_three_statements(base), project_three_statements(bad)
    assert max(abs(x) for x in rb.balance_residual) < 1e-9
    # 대차는 여전히 맞는다(항등식이라) — 대신 FA 잔액이 50 줄고 현금이 그만큼 늘어난다.
    # 즉 이 결함은 '대차'가 아니라 **FA 롤 대사**로 잡아야 한다는 사실을 고정한다.
    assert abs((rb.net_fixed_assets[0] - rr.net_fixed_assets[0]) - 50.0) < 1e-9
    assert rr.cash[0] > rb.cash[0]      # D&A 는 비현금이라 CFO 를 늘린다


def test_nwc_balance_vs_cfo_delta_are_tied():
    """CFO 의 ΔNWC 는 NWC **잔액 차분**에서 파생 — 둘이 갈라질 수 없게 묶여 있다."""
    r = project_three_statements(_input())
    assert abs(r.delta_nwc[0] - (320.0 - 300.0)) < 1e-9
    assert abs(r.delta_nwc[1] - (345.0 - 320.0)) < 1e-9


def test_severity_ordering_marks_downstream_unreliable():
    """audit-xls 원칙: BS 안 맞으면 그것부터 — 하위 finding 은 신뢰불가 표시."""
    r = project_three_statements(_input(opening=_opening(other_assets=150.0)))
    f = check_three_statement_integrity(r)
    assert _sev(f, "ts_balance_sheet") == "FAIL"
    # 현금연결은 수치상 PASS 여도 신뢰불가 플래그가 붙어야 한다
    cash = _find(f, "ts_cash_tie")
    assert cash.detail.get("bs_unreliable") is True, cash.detail
    # 대차가 맞으면 플래그가 없어야(오탐 방지)
    ok = check_three_statement_integrity(project_three_statements(_input()))
    assert "bs_unreliable" not in _find(ok, "ts_cash_tie").detail


# ══ ③ 순환참조 3층 ══════════════════════════════════════════════════════════
def test_layer1_opening_basis_has_no_circularity():
    """기초잔액 기준 → 반복 없이 1패스. 순환이 원천적으로 발생하지 않는다."""
    r = project_three_statements(_input(interest_basis="opening"))
    assert r.iterations == [1, 1, 1]
    assert r.converged
    # 이자수익 = 이자율 × 기초 이자부자산(현금+단기금융)
    assert abs(r.interest_income[0] - 0.03 * (500.0 + 200.0)) < 1e-12
    assert _sev(check_three_statement_integrity(r), "ts_circularity") == "PASS"


def test_layer2_average_basis_converges_and_satisfies_fixed_point():
    """평균잔액 기준 → 고정점 반복이 수렴하고, 수렴값이 이자 항등식을 만족한다."""
    r = project_three_statements(_input(interest_basis="average"))
    assert r.converged
    assert max(r.iterations) <= 10, r.iterations       # 압축사상이라 한 자릿수
    # 수렴 검증: II = r × (기초IBA + 기말IBA)/2
    iba_prev = 500.0 + 200.0
    iba_end = r.cash[0] + r.short_term_investments[0]
    assert abs(r.interest_income[0] - 0.03 * (iba_prev + iba_end) / 2.0) < 1e-8
    assert _sev(check_three_statement_integrity(r), "ts_circularity") == "PASS"


def test_average_basis_yields_more_interest_than_opening():
    """현금이 쌓이는 모델이면 평균잔액 이자수익 > 기초잔액 이자수익(방향 확인)."""
    o = project_three_statements(_input(interest_basis="opening"))
    a = project_three_statements(_input(interest_basis="average"))
    assert a.interest_income[0] > o.interest_income[0]
    assert a.net_income[0] > o.net_income[0]


def test_contraction_holds_even_at_absurd_rates_or_reports_failure():
    """비현실적 이자율에서도 무한루프 금지 — 수렴하거나 converged=False 로 노출."""
    wild = _input(interest_basis="average",
                  financing=FinancingPlan(
                      debt_issuance=[0.0] * 3, debt_repayment=[0.0] * 3,
                      interest_rate_debt=0.5, interest_rate_cash=0.5,
                      dividend_payout_ratio=0.0))
    r = project_three_statements(wild)       # 반드시 되돌아온다(행 걸림 없음)
    assert isinstance(r.converged, bool)
    if not r.converged:
        assert _sev(check_three_statement_integrity(r), "ts_circularity") == "FAIL"


def test_max_iterations_exhausted_reports_not_converged():
    """반복 상한을 1로 조이면 수렴 실패가 **조용히 넘어가지 않고** 노출된다."""
    r = project_three_statements(_input(interest_basis="average", max_iterations=1))
    assert r.converged is False
    f = check_three_statement_integrity(r)
    assert _sev(f, "ts_circularity") == "FAIL"
    assert "미수렴" in _find(f, "ts_circularity").message


def test_layer3_circuit_switch_off_zeroes_interest_and_warns():
    """R14 Circuit Switch — 고리를 끊되 **조용히 지나가지 않는다**(NI 과소)."""
    on = project_three_statements(_input())
    off = project_three_statements(_input(circularity_enabled=False))
    assert off.interest_income == [0.0, 0.0, 0.0]
    assert off.net_income[0] < on.net_income[0]        # 이자수익이 빠져 과소
    assert off.iterations == [1, 1, 1]
    f = check_three_statement_integrity(off)
    assert _sev(f, "ts_circularity") == "WARN"
    assert "과소" in _find(f, "ts_circularity").message
    # 스위치를 꺼도 회계 항등식 자체는 유지돼야 한다
    assert max(abs(x) for x in off.balance_residual) < 1e-9


def test_invalid_interest_basis_rejected():
    try:
        project_three_statements(_input(interest_basis="ending"))
        raise AssertionError("잘못된 basis 가 통과됨")
    except ValueError as e:
        assert "interest_basis" in str(e)


def test_length_mismatch_rejected():
    try:
        project_three_statements(_input(dep_amort=[100.0, 110.0]))
        raise AssertionError("길이 불일치가 통과됨")
    except ValueError as e:
        assert "길이" in str(e)


# ══ ④ FCFF ↔ CF표 대사 (unlevered 위반 탐지) ═════════════════════════════════
def _spine_fcff(inp, r) -> list[float]:
    """무차입 FCFF = EBIT×(1−τ) + D&A − CAPEX − ΔNWC (DCF 스파인과 같은 정의)."""
    return [inp.ebit[t] * (1 - TAX) + inp.dep_amort[t] - inp.capex[t] - r.delta_nwc[t]
            for t in range(len(inp.ebit))]


def test_fcff_reconciles_to_cashflow_statement():
    """정률 세제에서는 CF표 역산 FCFF 가 스파인 FCFF 와 **정확히** 대사된다."""
    inp = _input()
    r = project_three_statements(inp)
    spine = _spine_fcff(inp, r)
    cf = r.fcff_from_cashflow(TAX)
    assert max(abs(cf[t] - spine[t]) for t in range(len(spine))) < 1e-9, (spine, cf)
    assert _sev([check_fcff_vs_cashflow(spine, r, tax_rate=TAX)],
                "fcff_vs_cashflow") == "PASS"


def test_fcff_gate_detects_interest_leaking_into_fcf():
    """FCF 에 이자가 섞이면(unlevered 위반) 게이트가 잡는다.

    audit-xls 'DCF 특화 버그 5종' 중 하나를 자동 검사로 승격한 것.
    """
    inp = _input()
    r = project_three_statements(inp)
    leaked = [x + r.interest_income[t] for t, x in enumerate(_spine_fcff(inp, r))]
    f = check_fcff_vs_cashflow(leaked, r, tax_rate=TAX, tol=0.001)
    assert f.severity.name == "WARN"
    assert "unlevered" in f.message


def test_fcff_gate_flags_bracket_tax_caveat():
    """구간세율이면 과세표준(EBIT vs EBT) 차이로 잔차가 정상 — 메시지에 명시."""
    inp = _input(effective_tax_rate=None)          # 구간세율 경로
    r = project_three_statements(inp)
    spine = [inp.ebit[t] * 0.8 + inp.dep_amort[t] - inp.capex[t] - r.delta_nwc[t]
             for t in range(len(inp.ebit))]
    f = check_fcff_vs_cashflow(spine, r, tax_rate=None, tol=0.0001)
    assert f.detail["bracket_tax"] is True
    if f.severity.name == "WARN":
        assert "구간세율" in f.message


# ══ ⑤ 허용오차 SSOT ══════════════════════════════════════════════════════════
def test_tolerance_matches_workbook_check_rows():
    """엔진 허용오차와 워크북 CHECK 행 허용오차는 같은 개념 — 값이 갈라지면 안 된다.

    (import 로 묶지 않은 이유는 checks.py 주석 참조: excel→calc_core 의존 방향 보존)
    """
    from excel.template_schema import CHECK_TOL
    assert THREE_STATEMENT_TOL == CHECK_TOL


# ══ ⑥ 3표 ↔ 스파인 영업벡터 대사 (대차가 흡수하는 결함을 잡는 자리) ═══════════
def _spine_from(inp, cogs_ratio=0.6):
    """3표 입력과 **같은 영업 벡터**를 갖는 DcfSpineInput 을 만든다."""
    from calc_core.models import DcfSpineInput
    rev = [e / 0.2 for e in inp.ebit]                    # EBIT 마진 20% 로 역산
    cogs = [r * cogs_ratio for r in rev]
    sga = [rev[t] - cogs[t] - inp.ebit[t] for t in range(len(rev))]
    r = project_three_statements(inp)
    return DcfSpineInput(
        wacc=0.10, terminal_growth=0.02, revenue=rev, cogs=cogs, sga=sga,
        dep_amort=list(inp.dep_amort), capex=list(inp.capex),
        delta_nwc_cash_adj=[-d for d in r.delta_nwc],     # 스파인은 현금조정 부호
        non_operating_assets=0.0, net_debt=0.0, shares_outstanding=1_000_000)


def test_three_statement_matches_spine_vectors():
    from calc_core.checks import check_three_statement_vs_spine
    inp = _input()
    r = project_three_statements(inp)
    f = check_three_statement_vs_spine(_spine_from(inp), r)
    assert f.severity.name == "PASS", f.message


def test_dep_amort_divergence_caught_here_not_by_balance():
    """⭐ 대차가 흡수하는 D&A 불일치를 이 게이트가 잡는다.

    D&A 는 CFO(+)와 FA 롤(−)에 같은 크기로 들어가 ΔAssets 유도에서 상쇄된다 →
    대차 잔차는 0 인 채로 D&A 만 틀릴 수 있다. audit-xls 가 'D&A(CF=IS)' 를 별도
    항목으로 둔 이유이며, 스파인 대사가 그 자리를 채운다.
    """
    from calc_core.checks import check_three_statement_vs_spine
    inp = _input()
    spine = _spine_from(inp)                              # 스파인은 원래 D&A
    bad = project_three_statements(_input(dep_amort=[150.0, 110.0, 120.0]))
    assert max(abs(x) for x in bad.balance_residual) < 1e-9   # 대차는 여전히 0
    f = check_three_statement_vs_spine(spine, bad)
    assert f.severity.name == "FAIL", f.message
    assert "dep_amort" in f.detail["mismatches"]
    assert abs(f.detail["mismatches"]["dep_amort"]["delta"] - 50.0) < 1e-9


def test_capex_and_nwc_divergence_caught():
    from calc_core.checks import check_three_statement_vs_spine
    inp = _input()
    spine = _spine_from(inp)
    bad = project_three_statements(_input(capex=[120.0, 130.0, 999.0],
                                          net_working_capital=[320.0, 345.0, 500.0]))
    f = check_three_statement_vs_spine(spine, bad)
    assert f.severity.name == "FAIL"
    assert {"capex", "delta_nwc"} <= set(f.detail["mismatches"])


# ══ ⑦ 기본값 = 평균잔액 (정확도 우선) ════════════════════════════════════════
def test_default_basis_is_average_for_accuracy():
    """⭐ 기본은 **정확도**(평균잔액)다 — 순환 회피는 구현 편의이지 정확성 논거가 아니다.

    솔버를 만들어 놓고 편의를 위해 정확도를 포기하면 앞뒤가 안 맞는다.
    """
    from calc_core.three_statement import DEFAULT_INTEREST_BASIS
    assert DEFAULT_INTEREST_BASIS == "average"
    assert _input().interest_basis == "average"
    assert project_three_statements(_input()).interest_basis == "average"


def test_average_is_the_better_approximation_of_accrued_interest():
    """평균잔액이 왜 더 정확한지 수치로 고정한다.

    이자는 연중 잔액에 붙는다. 기초잔액만 쓰면 **좌단점 직사각형 근사**라 연중 변화를
    통째로 무시하고, 평균잔액은 **사다리꼴 근사**라 선형 변화를 정확히 담는다.
    잔액이 선형으로 변하면 사다리꼴이 참값과 일치한다 → 그 성질로 검증한다.
    """
    o = project_three_statements(_input(interest_basis="opening"))
    a = project_three_statements(_input(interest_basis="average"))
    r_cash = 0.03
    iba0 = 500.0 + 200.0
    iba1_avg = a.cash[0] + a.short_term_investments[0]

    # 사다리꼴: 잔액이 iba0 → iba1 로 균등 변화할 때의 정확한 연간 이자
    trapezoid = r_cash * (iba0 + iba1_avg) / 2.0
    assert abs(a.interest_income[0] - trapezoid) < 1e-8          # 평균 = 사다리꼴 ✓
    # 좌단점: 연중 증가분을 전부 누락 → 과소
    assert o.interest_income[0] < trapezoid
    # 누락분 = r × (기말−기초)/2 (기하학적으로 삼각형 넓이)
    missed = r_cash * (iba1_avg - iba0) / 2.0
    assert abs((trapezoid - o.interest_income[0]) - missed) < 1e-8


def test_opening_basis_remains_available_as_baseline():
    """기초잔액도 유효한 선택지로 남는다 — 반복의 초기값이자 대조용 기준선."""
    r = project_three_statements(_input(interest_basis="opening"))
    assert r.iterations == [1, 1, 1]
    assert _sev(check_three_statement_integrity(r), "ts_circularity") == "PASS"


# ══ ⑦ 기본값 = 평균잔액 (정확도 우선) ════════════════════════════════════════
def test_default_basis_is_average_for_accuracy():
    """⭐ 기본은 **정확도**(평균잔액)다 — 순환 회피는 구현 편의이지 정확성 논거가 아니다.

    솔버를 만들어 놓고 편의를 위해 정확도를 포기하면 앞뒤가 안 맞는다.
    """
    from calc_core.three_statement import DEFAULT_INTEREST_BASIS
    assert DEFAULT_INTEREST_BASIS == "average"
    assert _input().interest_basis == "average"
    assert project_three_statements(_input()).interest_basis == "average"


def test_average_is_the_better_approximation_of_accrued_interest():
    """평균잔액이 왜 더 정확한지 수치로 고정한다.

    이자는 연중 잔액에 붙는다. 기초잔액만 쓰면 **좌단점 직사각형 근사**라 연중 변화를
    통째로 무시하고, 평균잔액은 **사다리꼴 근사**라 선형 변화를 정확히 담는다.
    잔액이 선형으로 변하면 사다리꼴이 참값과 일치한다 → 그 성질로 검증한다.
    """
    o = project_three_statements(_input(interest_basis="opening"))
    a = project_three_statements(_input(interest_basis="average"))
    r_cash = 0.03
    iba0 = 500.0 + 200.0
    iba1_avg = a.cash[0] + a.short_term_investments[0]

    # 사다리꼴: 잔액이 iba0 → iba1 로 균등 변화할 때의 정확한 연간 이자
    trapezoid = r_cash * (iba0 + iba1_avg) / 2.0
    assert abs(a.interest_income[0] - trapezoid) < 1e-8          # 평균 = 사다리꼴 ✓
    # 좌단점: 연중 증가분을 전부 누락 → 과소
    assert o.interest_income[0] < trapezoid
    # 누락분 = r × (기말−기초)/2 (기하학적으로 삼각형 넓이)
    missed = r_cash * (iba1_avg - iba0) / 2.0
    assert abs((trapezoid - o.interest_income[0]) - missed) < 1e-8


def test_opening_basis_remains_available_as_baseline():
    """기초잔액도 유효한 선택지로 남는다 — 반복의 초기값이자 대조용 기준선."""
    r = project_three_statements(_input(interest_basis="opening"))
    assert r.iterations == [1, 1, 1]
    assert _sev(check_three_statement_integrity(r), "ts_circularity") == "PASS"


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



