"""편의 징후(기준서 540 문단 14·32, A5) — 소급 검토 + 방향성 집계.

계약 3가지를 고정한다:
  · 개별 항목의 옳고 그름은 판정하지 않는다 — **방향의 쏠림**만 집계(문단 32 의
    "개별적으로는 합리적일지라도").
  · 표본 부족(n<3)은 통과가 아니다 — 2건의 일치는 우연과 구분 불가.
  · 실제=0 인 항목은 오차를 만들지 않는다(무한대 방지) — None 으로 표기.

stdlib: `python tests/test_bias.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core.bias import (  # noqa: E402
    check_bias_directionality, check_retrospective,
)
from ingest.validators import Severity  # noqa: E402


def _rules(fs):
    return {f.rule: f.severity for f in fs}


def test_retrospective_all_same_direction_warns():
    """오차가 작아도 전부 같은 방향이면 WARN — 프로세스 편의 신호."""
    fs, rows = check_retrospective([
        {"label": "매출", "estimated": 103, "actual": 100},
        {"label": "영업이익", "estimated": 52, "actual": 50},
        {"label": "CAPEX", "estimated": 21, "actual": 20},
    ])
    assert _rules(fs).get("retrospective_direction") is Severity.WARN
    assert all(abs(r.error) < 0.10 for r in rows)     # 개별 오차는 전부 대형 임계 미만
    assert not any(f.rule == "retrospective_error" for f in fs)


def test_retrospective_mixed_direction_passes():
    fs, _ = check_retrospective([
        {"label": "a", "estimated": 103, "actual": 100},
        {"label": "b", "estimated": 48, "actual": 50},
        {"label": "c", "estimated": 21, "actual": 20},
    ])
    assert _rules(fs) == {"retrospective": Severity.PASS}


def test_retrospective_large_error_flagged_individually():
    fs, rows = check_retrospective([
        {"label": "매출", "estimated": 140, "actual": 100},   # +40% — J-1 급 오차
        {"label": "b", "estimated": 99, "actual": 100},
    ])
    errs = [f for f in fs if f.rule == "retrospective_error"]
    assert len(errs) == 1 and errs[0].detail["label"] == "매출"
    # 기준서 14 의 규율이 메시지에 남는다 — "당시 판단에 의문 제기가 아님"
    assert "의문" in errs[0].message


def test_retrospective_zero_actual_no_infinite():
    fs, rows = check_retrospective([
        {"label": "z", "estimated": 10, "actual": 0},
    ])
    assert rows[0].error is None                      # 무한대·0나눗셈 없음


def test_directionality_all_up_warns_and_mixed_passes():
    up = check_bias_directionality([
        {"label": "성장률 상단", "direction": 1},
        {"label": "할인율 하단", "direction": 1},
        {"label": "WC 낙관", "direction": 1},
    ])
    assert _rules(up)["bias_directionality"] is Severity.WARN
    mixed = check_bias_directionality([
        {"label": "a", "direction": 1}, {"label": "b", "direction": -1},
        {"label": "c", "direction": 1},
    ])
    assert _rules(mixed)["bias_directionality"] is Severity.PASS


def test_directionality_small_sample_is_not_a_pass():
    fs = check_bias_directionality([{"label": "a", "direction": 1},
                                    {"label": "b", "direction": 1}])
    assert fs[0].severity is Severity.WARN            # 표본 부족 — 통과 아님
    assert "표본" in fs[0].message or "최소" in fs[0].message


def test_directionality_strong_skew_warns():
    """전부 일치가 아니어도 75% 이상 쏠림(n>=4)은 WARN."""
    fs = check_bias_directionality([
        {"label": "a", "direction": 1}, {"label": "b", "direction": 1},
        {"label": "c", "direction": 1}, {"label": "d", "direction": -1},
    ])
    assert _rules(fs)["bias_directionality"] is Severity.WARN


def test_api_endpoint():
    from fastapi.testclient import TestClient
    from api.main import app
    client = TestClient(app)
    r = client.post("/api/review/bias", json={
        "prior": [{"label": "매출", "estimated": 103, "actual": 100},
                  {"label": "이익", "estimated": 52, "actual": 50},
                  {"label": "CAPEX", "estimated": 21, "actual": 20}],
        "judgments": [{"label": "g", "direction": 1}]})
    assert r.status_code == 200
    d = r.json()
    assert d["warn_count"] >= 2                       # 방향 쏠림 + 판단 표본 부족
    assert len(d["rows"]) == 3
    assert client.post("/api/review/bias", json={}).status_code == 422


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
