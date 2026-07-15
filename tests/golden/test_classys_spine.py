"""골든 테스트 (Layer A, 3차 실사례) — calc_core 스파인 == 클래시스 DCF.

비올(1차)이 구간세율+순진 터미널의 순수 스파인이라면, 클래시스(3차)는 개선 A·B를 실증한다:
  - 세금 주입(tax_override): 분석가 명시세금(유효세율 23%→15.6%) — 구간세율 미사용.
  - 터미널 정규화(terminal_fcff_override=31,557): WACC(6.24%)≈g(5%) 폭발을 정규화로 길들임.

원본 시트는 표기값이 4~5 유효숫자 반올림이라 rel_tol 2e-3(소스 반올림 수용).
단, 주당가치는 정확히 40,600원 일치(abs_tol 5원).

stdlib: `python tests/golden/test_classys_spine.py`
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core import DcfSpineInput, run  # noqa: E402

FX = ROOT / "fixtures" / "classys"
REL_TOL = 2e-3  # 소스 표기값 반올림 허용


def _load():
    inputs = json.loads((FX / "inputs.json").read_text(encoding="utf-8"))
    expected = json.loads((FX / "expected.json").read_text(encoding="utf-8"))
    kw = {k: v for k, v in inputs.items() if not k.startswith("_")}
    return DcfSpineInput(**kw), expected


def _close(a: float, b: float, rel: float = REL_TOL, ab: float = 1.0) -> bool:
    return math.isclose(a, b, rel_tol=rel, abs_tol=ab)


def test_classys_spine():
    inp, exp = _load()
    res = run(inp)
    fails: list[str] = []

    for i, (x, y) in enumerate(zip(res.fcff, exp["fcff"])):
        if not _close(x, y, ab=10.0):  # 표시 FCF 는 정수 반올림
            fails.append(f"fcff[{i}]: got {x:.1f} != exp {y}")
    for name, key in [("pv_explicit_sum", "pv_explicit_sum"),
                      ("terminal_value_pv", "terminal_value_pv"),
                      ("enterprise_value", "enterprise_value"),
                      ("equity_value", "equity_value")]:
        got = getattr(res, name)
        if not _close(got, exp[key]):
            fails.append(f"{name}: got {got:,.0f} != exp {exp[key]:,} (rel>2e-3)")

    # 주당가치는 정확 일치(핵심 헤드라인)
    if not _close(res.per_share, exp["per_share"], rel=0, ab=5.0):
        fails.append(f"per_share: got {res.per_share:,.1f} != exp {exp['per_share']:,} (>5원)")

    assert not fails, "골든 불일치:\n  " + "\n  ".join(fails)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    try:
        test_classys_spine()
    except AssertionError as e:
        print("FAIL\n" + str(e))
        raise SystemExit(1)
    inp, exp = _load()
    res = run(inp)
    print("PASS — calc_core 스파인이 클래시스 원본 재현 (개선 A 세금주입 + B 터미널정규화)")
    print(f"  EV        = {res.enterprise_value:,.0f} 백만원 (원본 {exp['enterprise_value']:,})")
    print(f"  주당가치  = {res.per_share:,.0f} 원  (원본 {exp['per_share']:,})")
    print(f"  TV 비중   = {res.terminal_value_pv / res.enterprise_value:.1%}")
