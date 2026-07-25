"""산업 벤치마크 공유 로더·매칭 — 세 표면(엔진·API·카드) 단일 정본 계약.

회귀 대상:
  #4 부분일치가 dict 순회 첫 겹침이라 JSON 키 순서에 따라 엉뚱한 코호트 매칭.
  #5 _BENCH_CACHE 영구 캐시 → 장수 서버가 재생성된 JSON 을 반영 못 함.
  #6 경로/매칭 규칙이 API·엔진에 중복 → 조용한 drift.

`py -3.12 tests/test_benchmarks_shared.py` 또는 pytest.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core import checks  # noqa: E402
from calc_core.checks import load_benchmarks, match_industry  # noqa: E402


# ── #4 결정적 부분일치 ────────────────────────────────────────────────
def test_partial_match_is_deterministic_across_dict_order():
    """같은 후보 집합이면 dict 삽입 순서와 무관하게 동일 산업을 고른다."""
    a = {"반도체 장비": {"opm": 1}, "반도체 소재": {"opm": 2}}
    b = {"반도체 소재": {"opm": 2}, "반도체 장비": {"opm": 1}}   # 순서 반전
    assert match_industry(a, "반도체")[0] == match_industry(b, "반도체")[0]


def test_partial_match_prefers_closest_length():
    """길이가 입력에 가장 가까운(가장 구체적인) 후보를 택한다."""
    inds = {"화장품": {"opm": 1}, "화장품 ODM 제조": {"opm": 2}}
    # 입력 '화장품 ODM' → 길이차 최소인 '화장품 ODM 제조' 쪽
    name, dist = match_industry(inds, "화장품 ODM")
    assert name == "화장품 ODM 제조" and dist == {"opm": 2}


def test_exact_match_wins_over_partial():
    inds = {"반도체": {"opm": 9}, "반도체 장비": {"opm": 1}}
    assert match_industry(inds, "반도체") == ("반도체", {"opm": 9})


def test_no_match_returns_none():
    assert match_industry({"조선": {}}, "바이오") == ("바이오", None)
    assert match_industry({"조선": {}}, "") == ("", None)


# ── #5 mtime 무효화 ──────────────────────────────────────────────────
def test_cache_invalidates_on_mtime_change(tmp_path, monkeypatch):
    """파일이 재생성(mtime 변화)되면 캐시가 새 내용을 반영한다."""
    f = tmp_path / "bench.json"
    f.write_text(json.dumps({"industries": {"조선": {"opm": {"p50": 5}}}}),
                 encoding="utf-8")
    import os
    os.utime(f, (1_000_000, 1_000_000))
    monkeypatch.setattr(checks, "_BENCH_PATH", f)
    monkeypatch.setattr(checks, "_BENCH_CACHE", None)
    monkeypatch.setattr(checks, "_BENCH_MTIME", None)

    assert load_benchmarks()["industries"]["조선"]["opm"]["p50"] == 5
    # 재생성 — 내용 변경 + 더 늦은 mtime
    f.write_text(json.dumps({"industries": {"조선": {"opm": {"p50": 99}}}}),
                 encoding="utf-8")
    os.utime(f, (2_000_000, 2_000_000))
    assert load_benchmarks()["industries"]["조선"]["opm"]["p50"] == 99  # stale 아님


def test_missing_file_degrades_without_raising(tmp_path, monkeypatch):
    monkeypatch.setattr(checks, "_BENCH_PATH", tmp_path / "nope.json")
    monkeypatch.setattr(checks, "_BENCH_CACHE", None)
    monkeypatch.setattr(checks, "_BENCH_MTIME", None)
    assert load_benchmarks() == {"industries": {}}


# ── #6 엔진과 API 가 같은 규칙을 쓰는가 ────────────────────────────────
def test_engine_and_endpoint_agree_on_match():
    """check_metric_vs_industry 와 /api/benchmarks/industry 가 동일 산업으로 매칭."""
    try:
        from fastapi.testclient import TestClient

        from backend.api.main import app
    except ImportError:
        return  # fastapi 미설치 환경 skip
    sys.path.insert(0, str(ROOT))
    client = TestClient(app)
    inds = load_benchmarks().get("industries", {})
    if not inds:
        return
    name = next(iter(inds))
    endpoint_ind = client.get("/api/benchmarks/industry", params={"name": name}).json()["industry"]
    engine_ind = match_industry(inds, name)[0]
    assert endpoint_ind == engine_ind == name


if __name__ == "__main__":
    for fn in [test_partial_match_is_deterministic_across_dict_order,
               test_partial_match_prefers_closest_length,
               test_exact_match_wins_over_partial, test_no_match_returns_none]:
        fn()
    print("match_industry tests passed (mtime/endpoint 테스트는 pytest 로).")
