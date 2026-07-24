"""수주산업 backlog 매출 모델 테스트 — 잔고 롤포워드·정상화 마진·스파인 배선.

근거: [[실전평가_상장사_사례집]] 한화오션(수주잔고→매출전환→정상마진). stdlib.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core.backlog import BacklogInputs, project_backlog, to_spine_lines  # noqa: E402
from calc_core.dcf import run as dcf_run  # noqa: E402
from calc_core.models import DcfSpineInput  # noqa: E402


def test_backlog_rollforward():
    # 기초 100, 전환율 40%, 신규수주 매년 40 → 정상상태(매출 40 유지)
    inp = BacklogInputs(opening_backlog=100.0, conversion_rate=0.4,
                        new_orders=[40.0] * 5, normalized_margin=0.12, years=5)
    r = project_backlog(inp)
    assert math.isclose(r.revenue[0], 40.0)          # 100 × 0.4
    # 1년차말 잔고 = 100 − 40 + 40 = 100 (정상상태)
    assert math.isclose(r.closing_backlog[0], 100.0)
    assert all(math.isclose(rev, 40.0) for rev in r.revenue)
    assert all(math.isclose(e, 40.0 * 0.12) for e in r.ebit)


def test_backlog_depletion_warning():
    # 신규수주 0 → 잔고 소진 → 매출 감소 + 경고
    inp = BacklogInputs(opening_backlog=1000.0, conversion_rate=0.5,
                        new_orders=[0.0] * 5, normalized_margin=0.1, years=5)
    r = project_backlog(inp)
    assert r.revenue[0] > r.revenue[-1]              # 매출 감소
    assert any("지속성" in w or "소진" in w for w in r.warnings)


def test_backlog_margin_applied():
    inp = BacklogInputs(opening_backlog=500.0, conversion_rate=0.3,
                        new_orders=[150.0] * 3, normalized_margin=0.15, years=3)
    r = project_backlog(inp)
    for i in range(3):
        assert math.isclose(r.ebit[i], r.revenue[i] * 0.15)


def test_to_spine_and_dcf_ebit_matches_margin():
    # backlog → 스파인 라인 → dcf: 스파인 EBIT == 정상화 마진 EBIT
    inp = BacklogInputs(opening_backlog=100_000.0, conversion_rate=0.35,
                        new_orders=[35_000.0] * 5, normalized_margin=0.12, years=5)
    r = project_backlog(inp)
    lines = to_spine_lines(r)
    spine = DcfSpineInput(
        wacc=0.078, terminal_growth=0.02,
        revenue=lines["revenue"], cogs=lines["cogs"], sga=lines["sga"],
        dep_amort=[0.0] * 5, capex=[0.0] * 5, delta_nwc_cash_adj=[0.0] * 5,
        non_operating_assets=0.0, net_debt=0.0, shares_outstanding=1_000_000,
        effective_tax_rate=0.22, terminal_from_last_fcff=True)
    res = dcf_run(spine)
    # 스파인 EBIT = revenue − cogs − sga = 정상화 마진 EBIT
    for i in range(5):
        assert math.isclose(res.ebit[i], r.ebit[i], rel_tol=1e-9)
    assert res.per_share > 0


def test_backlog_validation():
    for bad in (dict(conversion_rate=1.5), dict(new_orders=[1.0])):
        kw = dict(opening_backlog=100.0, conversion_rate=0.3,
                  new_orders=[10.0] * 3, normalized_margin=0.1, years=3)
        kw.update(bad)
        try:
            BacklogInputs(**kw)
            assert False, "ValueError 기대"
        except ValueError:
            pass


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
