"""값-only 복원(P2) 테스트 — 골든 3종의 값-only 사본에서 원값 재현.

검증 설계(계획 §4): 정답을 아는 워크북(표준 export)에서 **수식을 전부 제거**한 사본을
만들어 복원기에 넣는다 — 복원이 맞다면 골든 주당가치가 그대로 나와야 한다.
  · 비올(구간세율 표준) → 8,413.38 · 세금정책 'bracket' 판정(override 오검출 방지)
  · 클래시스(tax_override + terminal_fcff_override) → 40,600 · 'override' 판정
  · 페이드(META 파라미터) → 3단 파라메트릭 복원 등가
자동 탐지(detected)는 합성 값 행렬로 암묵 WACC 역산 정확도를 검증한다.

stdlib: `python tests/test_value_recovery.py`
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
from excel import export_dcf  # noqa: E402
from excel.value_recovery import (  # noqa: E402
    detect_discount_pairs, recover, recover_standard,
)
from excel.xlsx_reader import RCell, read_workbook  # noqa: E402


def _values_only(wb: dict) -> dict:
    """워크북 → 값-only 사본(수식 전부 제거, 캐시값만 유지) — '값 붙여넣기' 재현."""
    return {sheet: {ref: RCell(getattr(c, "number", None), None)
                    for ref, c in cells.items()
                    if getattr(c, "number", None) is not None}
            for sheet, cells in wb.items()}


def _export_values_only(inp: DcfSpineInput) -> dict:
    p = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False).name
    export_dcf(inp, run(inp), p)
    return _values_only(read_workbook(p))


def _load(fixture: str) -> DcfSpineInput:
    """픽스처에는 엔진 필드가 아닌 메타 키(explicit_years 등)가 있다 — 필드만 취한다."""
    from dataclasses import fields
    allowed = {f.name for f in fields(DcfSpineInput)}
    d = json.loads((ROOT / "fixtures" / fixture / "inputs.json").read_text(encoding="utf-8"))
    return DcfSpineInput(**{k: v for k, v in d.items() if k in allowed})


def _close(a, b, tol=1e-6):
    return math.isclose(a, b, rel_tol=tol, abs_tol=1e-6)


def test_viol_values_only_recovers_golden():
    """비올: 값-only 에서 8,413.38 재현 + 세금 'bracket' 판정(override 오검출 방지)."""
    inp = _load("viol")
    r = recover_standard(_export_values_only(inp))
    assert r.mode == "standard"
    assert _close(r.recomputed_per_share, run(inp).per_share)
    assert r.input.tax_override is None            # 값이 전부 하드여도 산술 지문으로 구분
    assert r.input.effective_tax_rate is None
    tie = next(f for f in r.findings if f.rule == "recovery_tieout")
    assert tie.severity.value == "pass"            # 재계산 == 워크북 표기
    assert r.unresolved                            # 원천·근거는 복원 불가 — 항상 질의 목록


def test_classys_values_only_recovers_overrides():
    """클래시스: 세금 override + 터미널 override 가 값-only 에서도 복원 → 40,600."""
    inp = _load("classys")
    r = recover_standard(_export_values_only(inp))
    assert r.mode == "standard"
    assert r.input.tax_override is not None        # 구간세율과 불일치 → override 판정
    assert _close(r.input.terminal_fcff_override, inp.terminal_fcff_override)
    assert _close(r.recomputed_per_share, run(inp).per_share, tol=1e-6)
    # override 판정은 WARN(원천 확인 필요) — 조용히 정상으로 넘기지 않는다
    pol = next(f for f in r.findings if f.rule == "recovery_tax_policy")
    assert pol.severity.value == "warn"


def test_fade_values_only_recovers_parametric():
    """페이드: META(C40/C41)가 값 셀이라 값-only 에서도 3단 파라메트릭 복원."""
    import dataclasses
    base = _load("viol")
    fade = dataclasses.replace(base, fade_years=3, terminal_discount_period=None)
    r = recover_standard(_export_values_only(fade))
    assert r.mode == "standard"
    assert r.input.fade_years == 3
    assert _close(r.recomputed_per_share, run(fade).per_share)


def test_nonstandard_falls_back_to_detection():
    """비표준 값-only → 자동 탐지 모드: FCFF↔PV 행 쌍에서 암묵 WACC 역산."""
    w, n = 0.113, 5
    fcff = [1000.0 * (1.1 ** i) for i in range(n)]
    pv = [fcff[i] / (1 + w) ** (i + 0.5) for i in range(n)]    # mid-year
    cells = {}
    for i, (f, p) in enumerate(zip(fcff, pv)):
        col = chr(ord("C") + i)
        cells[f"{col}10"] = RCell(f, None)
        cells[f"{col}11"] = RCell(p, None)
    cells["C3"] = RCell(123.0, None)                            # 노이즈 스칼라
    r = recover({"모델": cells})
    assert r.mode == "detected"
    assert _close(r.implied["wacc"], w, tol=1e-6)
    assert r.implied["mid_year"] is True
    assert any(f.rule == "recovery_implied_wacc" for f in r.findings)
    assert r.unresolved                                        # g·브리지는 미해결로 명시


def test_detection_rejects_proportional_noise():
    """단순 비례 행(매출 vs 원가율 60%)은 할인 구조로 오인하지 않는다 — q>1/대역 밖."""
    rev = [100.0, 110.0, 121.0, 133.1, 146.4]
    cogs = [v * 0.6 for v in rev]                              # 비율 일정하지만 감쇠 없음
    cells = {}
    for i, (a, b) in enumerate(zip(rev, cogs)):
        col = chr(ord("C") + i)
        cells[f"{col}5"] = RCell(a, None)
        cells[f"{col}6"] = RCell(b, None)
    assert detect_discount_pairs(cells) == []


def test_failed_mode_is_honest():
    """표준도 아니고 할인 구조도 없으면 failed — 원본 요청 권고를 명시."""
    r = recover({"Sheet1": {"A1": RCell(1.0, None), "B2": RCell(2.0, None)}})
    assert r.mode == "failed"
    assert any("원본" in u for u in r.unresolved)


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
