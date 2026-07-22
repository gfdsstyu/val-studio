"""상대가치 실적 정규화(LTM·계절성) 테스트 — 북 골든 예시 재현.

stdlib: `python tests/test_relative.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core.checks import check_peer_seasonality  # noqa: E402
from calc_core.relative import annualize_naive, ltm, max_quarter_share  # noqa: E402
from ingest.validators import Severity  # noqa: E402

# 북 골든(상대가치_계절성_LTM): X1 분기 100/120/130/350(연 700) + X2Q1 120
BOOK = [100.0, 120.0, 130.0, 350.0, 120.0]


def test_ltm_book_golden():
    assert ltm(BOOK) == 720.0                       # 120+130+350+120


def test_ltm_requires_four_quarters():
    try:
        ltm([100.0, 120.0, 130.0])
        raise AssertionError("3개 분기로 LTM 이 통과됨")
    except ValueError as e:
        assert "4개 분기" in str(e)


def test_annualize_naive_distortion_book_example():
    # 북 왜곡 실측: 1분기×4=400(과소) vs 4분기×4=1400(과대) vs 실제 700
    assert annualize_naive(100.0) == 400.0
    assert annualize_naive(350.0) == 1400.0


def test_max_quarter_share_book():
    assert abs(max_quarter_share([100.0, 120.0, 130.0, 350.0]) - 0.50) < 1e-12
    assert abs(max_quarter_share([100.0] * 4) - 0.25) < 1e-12


def test_seasonality_check_warns_at_40pct():
    f = check_peer_seasonality([100.0, 120.0, 130.0, 350.0], name="A사")
    assert f.severity is Severity.WARN and "LTM" in f.message
    f2 = check_peer_seasonality([100.0, 110.0, 105.0, 120.0], name="B사")
    assert f2.severity is Severity.PASS


def test_seasonality_undecidable_warns_not_passes():
    # 합≤0(적자) → 자동 통과 금지, 유저 확인 WARN (LLM 판단보조 원칙)
    f = check_peer_seasonality([-50.0, 30.0, 10.0, 5.0], name="적자사")
    assert f.severity is Severity.WARN and "판정 불가" in f.message


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
