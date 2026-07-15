"""DCF 모델 import/export 왕복 테스트 — 우리 xlsx 포맷 무손실 왕복.

export(DcfSpineInput→xlsx) → import(xlsx→DcfSpineInput) → 동일 입력 + 재계산 일치.
비올 골든(오버라이드 없는 표준 모델)로 왕복. stdlib: `python tests/test_dcf_roundtrip.py`
"""
from __future__ import annotations

import json
import math
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core import DcfSpineInput, run  # noqa: E402
from excel import export_dcf, import_dcf_model, read_workbook  # noqa: E402

FX = ROOT / "fixtures" / "viol"


def _viol() -> DcfSpineInput:
    d = json.loads((FX / "inputs.json").read_text(encoding="utf-8"))
    return DcfSpineInput(
        wacc=d["wacc"], terminal_growth=d["terminal_growth"],
        revenue=d["revenue"], cogs=d["cogs"], sga=d["sga"],
        dep_amort=d["dep_amort"], capex=d["capex"],
        delta_nwc_cash_adj=d["delta_nwc_cash_adj"],
        non_operating_assets=d["non_operating_assets"], net_debt=d["net_debt"],
        shares_outstanding=d["shares_outstanding"],
        mid_year_periods=d.get("mid_year_periods"),
        terminal_discount_period=d.get("terminal_discount_period"),
    )


def _close(a, b, tol=1e-6):
    return math.isclose(a, b, rel_tol=tol, abs_tol=1e-6)


def _path() -> str:
    return tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False).name


def test_roundtrip_inputs_preserved():
    inp = _viol()
    p = _path()
    export_dcf(inp, run(inp), p)
    back = import_dcf_model(p)
    # 스칼라
    assert _close(back.wacc, inp.wacc)
    assert _close(back.terminal_growth, inp.terminal_growth)
    assert back.shares_outstanding == inp.shares_outstanding
    assert _close(back.non_operating_assets, inp.non_operating_assets)
    assert _close(back.net_debt, inp.net_debt)
    # 벡터
    for a, b in zip(back.revenue, inp.revenue):
        assert _close(a, b)
    for a, b in zip(back.cogs, inp.cogs):
        assert _close(a, b)
    for a, b in zip(back.delta_nwc_cash_adj, inp.delta_nwc_cash_adj):
        assert _close(a, b)
    assert back.n_years() == inp.n_years()


def test_roundtrip_recompute_matches_golden():
    # import 한 입력으로 재계산 → 원본 주당가치(8,413.38) 일치
    inp = _viol()
    p = _path()
    export_dcf(inp, run(inp), p)
    back = import_dcf_model(p)
    assert _close(run(back).per_share, run(inp).per_share)
    exp = json.loads((FX / "expected.json").read_text(encoding="utf-8"))
    assert _close(run(back).per_share, exp["per_share"])


def test_reader_reads_formulas_and_values():
    inp = _viol()
    p = _path()
    export_dcf(inp, run(inp), p)
    cells = read_workbook(p)["DCF"]
    # 가정 셀은 값
    assert _close(cells["C3"].number, inp.wacc)
    # 결과 셀은 수식 + 캐시값(감사추적)
    assert cells["C33"].formula is not None and "C32/C5" in cells["C33"].formula
    assert cells["C33"].number is not None            # 캐시된 주당가치


def test_missing_sheet_raises():
    from excel import DcfModelImportError
    inp = _viol()
    p = _path()
    export_dcf(inp, run(inp), p)
    try:
        import_dcf_model(p, sheet="없는시트")
        assert False
    except DcfModelImportError:
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
