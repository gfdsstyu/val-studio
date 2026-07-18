"""Damodaran CRP 테스트 — 국가 룩업·목록·ctryprem 파싱.

stdlib: `python tests/test_damodaran.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ingest.damodaran import (  # noqa: E402
    country_detail, country_risk_premium, list_countries, parse_ctryprem,
)


def test_lookup_korea_hangul_and_english():
    assert country_risk_premium("한국") == country_risk_premium("Korea") == 0.0055
    assert country_risk_premium("미국") == 0.0                 # 성숙시장 CRP 0


def test_whitespace_case_insensitive():
    assert country_risk_premium(" KOREA ") == 0.0055


def test_unknown_country_none():
    assert country_risk_premium("아무국가") is None            # 미등록 → None(유저 확인)


def test_country_detail():
    d = country_detail("베트남")
    assert d["crp"] == 0.0281 and d["rating"] == "Ba2" and "예시" in d["vintage"]


def test_list_countries_sorted():
    rows = list_countries()
    crps = [r["crp"] for r in rows]
    assert crps == sorted(crps)                                # CRP 오름차순
    assert any(r["country"] == "한국" for r in rows)           # 한글명 우선


def test_parse_ctryprem():
    rows = [["Country", "CRP"],                                # 헤더(자동 스킵)
            ["Korea", "0.55%"], ["Vietnam", "2.81"], ["", "1.0"]]
    out = parse_ctryprem(rows)
    assert abs(out["Korea"] - 0.0055) < 1e-9
    assert abs(out["Vietnam"] - 0.0281) < 1e-9
    assert "Country" not in out and "" not in out


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
