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


def _classys() -> DcfSpineInput:
    d = json.loads((ROOT / "fixtures" / "classys" / "inputs.json").read_text(encoding="utf-8"))
    kw = {k: v for k, v in d.items() if not k.startswith("_")}
    return DcfSpineInput(**kw)


def test_roundtrip_overrides_preserved():
    # 클래시스: tax_override + terminal_fcff_override 완전 왕복 → 40,600원 재현
    inp = _classys()
    p = _path()
    export_dcf(inp, run(inp), p)
    back = import_dcf_model(p)
    assert back.tax_override is not None
    for a, b in zip(back.tax_override, inp.tax_override):
        assert _close(a, b)
    assert _close(back.terminal_fcff_override, inp.terminal_fcff_override)
    # 재계산 → 원본 주당가치 40,600 일치
    assert _close(run(back).per_share, run(inp).per_share)
    exp = json.loads((ROOT / "fixtures" / "classys" / "expected.json").read_text(encoding="utf-8"))
    assert _close(run(back).per_share, exp["per_share"], tol=1e-4)


def test_standard_model_no_false_override():
    # 비올(오버라이드·페이드 없음): 세금이 수식이라 tax_override 미검출, fade 도 미검출
    inp = _viol()
    p = _path()
    export_dcf(inp, run(inp), p)
    back = import_dcf_model(p)
    assert back.tax_override is None
    assert back.terminal_fcff_override is None
    assert back.fade_years is None and back.fade_growth is None


def test_nci_roundtrip_and_bridge():
    """비지배지분(NCI) 왕복 + 브리지 수식 반영(db6ffb1 배선). NCI 200 → 지분가치 정확히 200 차감."""
    import dataclasses
    base = _viol()
    inp = dataclasses.replace(base, non_controlling_interest=200.0)
    p = _path()
    export_dcf(inp, run(inp), p)
    cells = read_workbook(p)["DCF"]
    # C8 = NCI 입력셀, 지분 수식에 -C8 반영
    assert _close(cells["C8"].number, 200.0)
    assert "-C8" in cells["C32"].formula           # equity = ...+C6-C7-C8
    # 왕복: NCI 복원 + per_share 정확히 200 차감(주식수로 나눈 만큼)
    back = import_dcf_model(p)
    assert _close(back.non_controlling_interest, 200.0)
    assert _close(run(back).per_share, run(inp).per_share)
    delta = run(base).per_share - run(inp).per_share  # NCI 200 차감 효과
    assert _close(delta, 200.0 / inp.shares_outstanding * 1_000_000)


def test_old_workbook_without_nci_defaults_zero():
    """구 워크북(C8 없음) import → NCI 0 기본(브리지 무영향)."""
    inp = _viol()                                  # NCI 미설정
    p = _path()
    export_dcf(inp, run(inp), p)
    back = import_dcf_model(p)
    assert back.non_controlling_interest == 0.0


def test_fade_model_roundtrip():
    """fade 모델(R1) 왕복 — 페이드 열 실체화 + META C40/C41 파라메트릭 복원.

    갭 실측(2026-08-01, 수정 전): fade_years=3 이 왕복에서 소실돼 주당가치 −23.1%
    (10,946.89→8,413.38) 조용한 회귀 + C27 캐시(203,834)≠수식 SUM(127,002)으로
    recalc 순간 값이 바뀌는 워크북이었다. 수정: export 가 엔진의 입력확장을 재사용해
    페이드 열을 **실체화**(수식==캐시 복원, 모델러스 원본 관행과 동일)하고 META 에
    파라미터를 기록, import 가 뒤쪽 k열을 잘라 3단 파라메트릭 형태로 되돌린다.
    """
    import dataclasses
    from calc_core.dcf import resolve_fade_growth
    base = _viol()
    # 기준 케이스: 확장 시계 기준 자동 할인(terminal_discount_period 미선언).
    fade = dataclasses.replace(base, fade_years=3, terminal_discount_period=None)
    res_fade = run(fade)
    assert not _close(res_fade.per_share, run(base).per_share)   # sanity: fade 효과 존재
    n_total = base.n_years() + 3

    p = _path()
    export_dcf(fade, res_fade, p)
    cells = read_workbook(p)["DCF"]

    # 실체화: Year 행에 명시+페이드 전체 열, 명시 PV합 캐시 == 수식 SUM 범위(recalc 안정)
    year_cols = [c for c in ("C", "D", "E", "F", "G", "H", "I", "J")
                 if cells.get(f"{c}10") and cells[f"{c}10"].number is not None]
    assert len(year_cols) == n_total
    pv_sum = sum(cells[f"{c}24"].number for c in year_cols)
    assert _close(cells["C27"].number, pv_sum, tol=1e-9)
    # META 파라미터 기록(해석된 fade_growth)
    gf = resolve_fade_growth(fade, fade.terminal_growth)
    assert cells["C40"].number == 3
    assert _close(cells["C41"].number, gf)

    # 파라메트릭 복원: 명시 5년 + fade_years=3 + 재계산 등가
    back = import_dcf_model(p)
    assert back.fade_years == 3
    assert _close(back.fade_growth, gf)
    assert back.n_years() == base.n_years()
    for a, b in zip(back.revenue, base.revenue):
        assert _close(a, b)                                      # 명시 구간 원형 보존
    assert _close(run(back).per_share, res_fade.per_share)       # 왕복 등가(10,946.89)


def test_fade_export_exceeding_columns_raises():
    """열 한도 초과는 조용한 절단이 아니라 명시 에러(YEAR_COLS 12열, 5+8=13 > 12)."""
    import dataclasses
    fade = dataclasses.replace(_viol(), fade_years=8, terminal_discount_period=None)
    try:
        export_dcf(fade, run(fade), _path())
        assert False, "열 한도 초과가 조용히 통과"
    except ValueError as e:
        assert "YEAR_COLS" in str(e)


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
