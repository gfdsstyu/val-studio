"""골든 테스트 (Layer A) — calc_core 스파인 == 비올 DCF Model 최종본.

fixtures/viol/inputs.json → calc_core.run → fixtures/viol/expected.json 셀단위 대조.
부동소수 rel_tol 1e-9(원본 라이브 수식값과 동일 알고리즘이므로 사실상 완전일치 기대).

민감도표는 원본 캐시가 stale 이라 값 대조 대신 자기일관성(중심셀==base H49)만 검증.

의존 없이 stdlib 로 실행: `python tests/golden/test_viol_spine.py`
(pytest 설치 시 `pytest -q` 로도 동작.)
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core import DcfSpineInput, run  # noqa: E402

FX = ROOT / "fixtures" / "viol"
REL_TOL = 1e-9


def _load():
    inputs = json.loads((FX / "inputs.json").read_text(encoding="utf-8"))
    expected = json.loads((FX / "expected.json").read_text(encoding="utf-8"))
    inp = DcfSpineInput(
        wacc=inputs["wacc"],
        terminal_growth=inputs["terminal_growth"],
        revenue=inputs["revenue"],
        cogs=inputs["cogs"],
        sga=inputs["sga"],
        dep_amort=inputs["dep_amort"],
        capex=inputs["capex"],
        delta_nwc_cash_adj=inputs["delta_nwc_cash_adj"],
        non_operating_assets=inputs["non_operating_assets"],
        net_debt=inputs["net_debt"],
        shares_outstanding=inputs["shares_outstanding"],
        mid_year_periods=inputs.get("mid_year_periods"),
        terminal_discount_period=inputs.get("terminal_discount_period"),
    )
    return inp, expected


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=REL_TOL, abs_tol=1e-6)


def _check_list(name, got, exp, fails):
    for i, (x, y) in enumerate(zip(got, exp)):
        if not _close(x, y):
            fails.append(f"{name}[{i}]: got {x!r} != exp {y!r}")


def _check_scalar(name, got, exp, fails):
    if not _close(got, exp):
        fails.append(f"{name}: got {got!r} != exp {exp!r}")


def test_viol_spine():
    inp, exp = _load()
    res = run(inp)
    fails: list[str] = []

    _check_list("ebit", res.ebit, exp["ebit"], fails)
    _check_list("tax", res.tax, exp["tax"], fails)
    _check_list("noplat", res.noplat, exp["noplat"], fails)
    _check_list("fcff", res.fcff, exp["fcff"], fails)
    _check_list("pv_factor", res.pv_factor, exp["pv_factor"], fails)
    _check_list("pv_fcff", res.pv_fcff, exp["pv_fcff"], fails)
    _check_scalar("terminal_fcff", res.terminal_fcff, exp["terminal_fcff"], fails)
    _check_scalar("terminal_value_pv", res.terminal_value_pv, exp["terminal_value_pv"], fails)
    _check_scalar("pv_explicit_sum", res.pv_explicit_sum, exp["pv_explicit_sum"], fails)
    _check_scalar("enterprise_value", res.enterprise_value, exp["enterprise_value"], fails)
    _check_scalar("equity_value", res.equity_value, exp["equity_value"], fails)
    _check_scalar("per_share", res.per_share, exp["per_share"], fails)

    # 민감도 자기일관성: 중심 셀 == base 주당가치
    center = res.sensitivity["per_share"][1][1]
    _check_scalar("sensitivity_center==per_share", center, res.per_share, fails)

    assert not fails, "골든 불일치:\n  " + "\n  ".join(fails)


if __name__ == "__main__":
    # Windows 콘솔(cp949)에서도 한글/em-dash 출력이 깨지지 않도록.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    try:
        test_viol_spine()
    except AssertionError as e:
        print("FAIL\n" + str(e))
        raise SystemExit(1)
    print("PASS — calc_core 스파인이 비올 원본과 셀단위 일치 (rel_tol 1e-9)")
    # 요약 출력
    inp, exp = _load()
    res = run(inp)
    print(f"  EV        = {res.enterprise_value:,.2f} 백만원")
    print(f"  주식가치  = {res.equity_value:,.2f} 백만원")
    print(f"  주당가치  = {res.per_share:,.2f} 원  (원본 {exp['per_share']:,.2f})")
