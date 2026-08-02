"""추정치 간 교차 일관성(기준서 540 문단 24(c), A3) — 엔진 + API.

핵심: 개별 게이트가 전부 통과해도 **공유 가정이 추정치마다 다르면** 그 자체가 신호다
(손상검사 g 3% vs 평가모델 g 1% — 어느 한쪽이 목적에 맞춰 선택됐다는 뜻).
'비교 불가'(겹치는 키 없음)를 통과로 표시하지 않는 것도 계약이다.

stdlib: `python tests/test_cross_estimate.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core.checks import check_cross_estimate_consistency  # noqa: E402
from ingest.validators import Severity  # noqa: E402


def test_mismatch_warns_with_both_sources():
    fs = check_cross_estimate_consistency({
        "평가모델(DCF)": {"terminal_growth": 0.01, "risk_free": 0.032},
        "손상검사(VIU)": {"terminal_growth": 0.03, "risk_free": 0.032},
    })
    warns = [f for f in fs if f.severity is Severity.WARN]
    assert len(warns) == 1
    f = warns[0]
    assert f.detail["key"] == "terminal_growth"
    assert {f.detail["a"], f.detail["b"]} == {"평가모델(DCF)", "손상검사(VIU)"}
    assert "24(c)" in f.message                       # 근거 문단이 조서로 흘러간다


def test_rounding_noise_passes():
    """0.1%p 이내 차이(반올림·표기)는 잡지 않는다 — 경고 피로 방지."""
    fs = check_cross_estimate_consistency({
        "A": {"terminal_growth": 0.0100},
        "B": {"terminal_growth": 0.0105},
    })
    assert all(f.severity is Severity.PASS for f in fs)


def test_level_values_use_relative_tolerance():
    """환율 같은 레벨 값은 상대 비교 — 1,330 vs 1,336(0.45%) WARN, 1,330 vs 1,330.5 PASS."""
    warn = check_cross_estimate_consistency({
        "A": {"usd_krw": 1330.0}, "B": {"usd_krw": 1336.0}})
    assert any(f.severity is Severity.WARN for f in warn)
    ok = check_cross_estimate_consistency({
        "A": {"usd_krw": 1330.0}, "B": {"usd_krw": 1330.5}})
    assert all(f.severity is Severity.PASS for f in ok)


def test_no_overlap_is_not_a_pass():
    """겹치는 키가 없으면 '비교 불가' WARN — 침묵·통과로 위장하지 않는다."""
    fs = check_cross_estimate_consistency({
        "A": {"terminal_growth": 0.01}, "B": {"discount_rate": 0.11}})
    assert len(fs) == 1 and fs[0].severity is Severity.WARN
    assert fs[0].detail["compared"] == 0


def test_three_way_pairwise():
    """추정치 3개면 쌍별 전부 비교 — 하나만 어긋나도 그 쌍들이 각각 지목된다."""
    fs = check_cross_estimate_consistency({
        "DCF": {"terminal_growth": 0.01},
        "VIU": {"terminal_growth": 0.01},
        "PPA": {"terminal_growth": 0.03},
    })
    warns = [f for f in fs if f.severity is Severity.WARN]
    assert len(warns) == 2                            # DCF↔PPA, VIU↔PPA
    assert all(f.detail["b"] == "PPA" or f.detail["a"] == "PPA" for f in warns)


def test_api_endpoint():
    from fastapi.testclient import TestClient
    from api.main import app
    client = TestClient(app)
    r = client.post("/api/review/cross-estimate", json={"estimates": {
        "DCF": {"terminal_growth": 0.01}, "VIU": {"terminal_growth": 0.03}}})
    assert r.status_code == 200
    assert any(f["severity"] == "warn" for f in r.json()["findings"])
    bad = client.post("/api/review/cross-estimate", json={"estimates": {"DCF": {}}})
    assert bad.status_code == 422                     # 2개 미만 — 비교 자체가 성립 안 함


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
