"""풀모델 템플릿(valstudio-full-v1) 되읽기 골든 — 셀맵·부호 규약 검증.

비올 골든 입력을 풀모델 좌표(M:Q 스파인·H37 가정·H46 음수 브리지)에 심은 합성
워크북을 만들어 import_fullmodel 로 복원 → 엔진 재계산이 8413.380552 를 재현하는지.
부호 번역(capex 음수 표시→양수, H46 음수 기입→양수 net_debt)이 핵심 검증 대상.
"""
import json
import tempfile
from math import isclose
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "backend"))

from calc_core import DcfSpineInput, run  # noqa: E402
from excel.fullmodel_layout import (  # noqa: E402
    FCOLS,
    FullModelImportError,
    detect_fullmodel,
    import_fullmodel,
)
from excel.xlsx_reader import read_workbook  # noqa: E402
from excel.xlsx_writer import Workbook  # noqa: E402

VIOL = ROOT / "fixtures" / "viol" / "inputs.json"
GOLDEN_PER_SHARE = 8413.380552312221


def _viol() -> DcfSpineInput:
    d = json.loads(VIOL.read_text(encoding="utf-8"))
    fields = set(DcfSpineInput.__dataclass_fields__)
    return DcfSpineInput(**{k: v for k, v in d.items() if k in fields})


def _build_fullmodel_xlsx(inp: DcfSpineInput, path: str,
                          claimed_per_share: float | None = None) -> None:
    """비올 입력을 풀모델 좌표에 기입한 합성 워크북(값 셀만 — Excel 저장본 등가).

    claimed_per_share 를 주면 H49(워크북 주장값)에 기입 — tie-out 게이트 검증용.
    """
    wb = Workbook()
    s = wb.add_sheet("DCF")
    if claimed_per_share is not None:
        s.num("H49", claimed_per_share)
    # 레이아웃 지문(라벨) — detect_fullmodel 이 보는 셀
    s.text("D37", "WACC")
    s.text("D48", "유통주식수")
    s.text("D49", "주당가치")
    s.text("C26", "FCFF")
    # 가정
    s.num("H37", inp.wacc)
    s.num("H38", inp.terminal_growth)
    s.num("H48", inp.shares_outstanding)
    s.num("H45", inp.non_operating_assets)
    s.num("H46", -inp.net_debt)                       # 음수 기입 규약(SUM 브리지)
    # 스파인 M..Q — capex 는 음수 표시 규약
    rows = {7: inp.revenue, 9: inp.cogs, 13: inp.sga, 18: None,
            22: inp.dep_amort, 23: [-v for v in inp.capex],
            24: inp.delta_nwc_cash_adj, 30: inp.mid_year_periods}
    for row, vals in rows.items():
        if vals is None:
            continue
        for c, v in zip(FCOLS, vals):
            s.num(f"{c}{row}", v)
    wb.save(path)


def test_fullmodel_import_golden():
    inp = _viol()
    with tempfile.TemporaryDirectory() as td:
        p = str(Path(td) / "full.xlsx")
        _build_fullmodel_xlsx(inp, p)

        assert detect_fullmodel(read_workbook(p)), "라벨 지문 판별 실패"
        rec, meta = import_fullmodel(p)

    assert meta.layout == "valstudio-full-v1"
    assert meta.warnings == []                        # 부호 규약 준수 → 경고 없음
    assert rec.wacc == pytest.approx(inp.wacc)
    assert rec.net_debt == pytest.approx(inp.net_debt)          # -H46 반전 복원
    assert rec.capex == pytest.approx(inp.capex)                # 음수 표시 → 양수 크기
    assert rec.mid_year_periods == pytest.approx(inp.mid_year_periods)
    assert rec.terminal_discount_period == pytest.approx(4.5)   # Q30

    res = run(rec)
    assert isclose(res.per_share, GOLDEN_PER_SHARE, rel_tol=1e-6)


def test_fullmodel_sign_warnings():
    """규약 위반 기입(H46 양수·CAPEX 양수)은 조용히 통과시키지 않고 경고 표면화."""
    inp = _viol()
    with tempfile.TemporaryDirectory() as td:
        p = str(Path(td) / "bad.xlsx")
        wb = Workbook()
        s = wb.add_sheet("DCF")
        s.text("D37", "WACC"); s.text("D48", "유통주식수"); s.text("D49", "주당가치")
        s.num("H37", inp.wacc); s.num("H38", inp.terminal_growth)
        s.num("H48", inp.shares_outstanding); s.num("H45", 0.0)
        s.num("H46", inp.net_debt)                    # 양수 기입 = 규약 위반
        for row, vals in {7: inp.revenue, 9: inp.cogs, 13: inp.sga,
                          22: inp.dep_amort, 23: inp.capex,          # 양수 = 위반
                          24: inp.delta_nwc_cash_adj, 30: inp.mid_year_periods}.items():
            for c, v in zip(FCOLS, vals):
                s.num(f"{c}{row}", v)
        wb.save(p)
        _, meta = import_fullmodel(p)
    assert any("H46" in w for w in meta.warnings)
    assert any("CAPEX" in w for w in meta.warnings)


def test_fullmodel_missing_cache_message():
    """수식만 있고 캐시 없는 셀(미저장 템플릿)은 '재계산 후 저장' 안내로 실패."""
    with tempfile.TemporaryDirectory() as td:
        p = str(Path(td) / "nocache.xlsx")
        wb = Workbook()
        s = wb.add_sheet("DCF")
        s.text("D37", "WACC"); s.text("D48", "유통주식수"); s.text("D49", "주당가치")
        s.formula("M7", "EBIT!M13")                   # 캐시 없는 수식(배선된 미저장 템플릿)
        wb.save(p)
        with pytest.raises(FullModelImportError, match="재계산"):
            import_fullmodel(p)
