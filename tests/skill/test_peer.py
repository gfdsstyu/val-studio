"""peer.py (W5 유사회사 4-step 퍼널) 검증 — 웹 /api/peer/select 미러.

벤더 ingest.peer_selection 소비이므로 subprocess 로 실행(_bootstrap 벤더 경로).
input= 로 UTF-8 전달(한글 안전). `python tests/skill/test_peer.py` 또는 pytest.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".claude" / "skills" / "excel-valuation-workbook" / "scripts"


def _run(payload: dict) -> dict:
    r = subprocess.run([sys.executable, str(SKILL / "peer.py")],
                       input=json.dumps(payload), capture_output=True, text=True,
                       encoding="utf-8", cwd=tempfile.gettempdir())
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _cands():
    return [
        {"ticker": "A", "name": "동종A", "industry_code": "2710", "revenue_share_related": 0.9, "listed_years": 5},
        {"ticker": "B", "name": "무관B", "industry_code": "5811", "revenue_share_related": 0.9, "listed_years": 5},
        {"ticker": "C", "name": "저비중C", "industry_code": "2710", "revenue_share_related": 0.4, "listed_years": 5},
        {"ticker": "D", "name": "신규D", "industry_code": "2710", "revenue_share_related": 0.9, "listed_years": 1},
        {"ticker": "E", "name": "정지E", "industry_code": "2710", "revenue_share_related": 0.9, "listed_years": 5, "suspended": True},
    ]


def _judg():
    return [
        {"ticker": "A", "similar": True, "reason": "동일 의료기기"},
        {"ticker": "C", "similar": True, "reason": "동일 산업 소모품"},
        {"ticker": "D", "similar": True, "reason": "동일 사업"},
        {"ticker": "E", "similar": True, "reason": "동일 사업"},
    ]


def test_full_funnel_matches_web():
    """5사 → Step1 코드(B 탈락)·Step3 비중(C)·Step4 상장/정지(D,E) → 확정 A 1사."""
    out = _run({"candidates": _cands(), "target_industry_codes": ["2710"], "judgments": _judg()})
    assert [c["ticker"] for c in out["selected"]] == ["A"]
    dropped = {d["ticker"]: d["dropped_at"] for d in out["dropped"]}
    assert dropped == {"B": "step1", "C": "step3", "D": "step4", "E": "step4"}
    # 퍼널 생존수 5→4→4→3→1
    assert list(out["funnel"].values()) == [5, 4, 4, 3, 1]
    assert out["size_note"] and "< 5" in out["size_note"]      # 1<5 통계취약


def test_uncertain_to_review_queue():
    """uncertain 판정(모든 결정론 게이트 통과)은 탈락 아닌 ⚖️ needs_review."""
    cands = [{"ticker": "U", "name": "애매U", "industry_code": "2710",
              "revenue_share_related": 0.9, "listed_years": 5}]
    out = _run({"candidates": cands, "target_industry_codes": ["2710"],
                "judgments": [{"ticker": "U", "similar": True, "uncertain": True, "reason": "사업 유사하나 경계"}]})
    assert out["selected"] == []                              # 확정 아님
    assert [t["ticker"] for t in out["needs_review"]] == ["U"]
    assert not out["dropped"]


def test_step2_missing_judgment_rejected():
    """생존 후보 판정 누락 → 게이트 거부(무근거 판정 금지)."""
    out = _run({"candidates": _cands(), "target_industry_codes": ["2710"],
                "judgments": [{"ticker": "A", "similar": True, "reason": "x"}]})  # C 판정 누락
    assert out.get("gate") == "step2_judgment"


def test_step2_no_reason_rejected():
    """사유 없는 판정 → 거부."""
    out = _run({"candidates": [{"ticker": "A", "name": "A", "industry_code": "2710",
                                "revenue_share_related": 0.9, "listed_years": 5}],
                "target_industry_codes": ["2710"],
                "judgments": [{"ticker": "A", "similar": True, "reason": "  "}]})
    assert out.get("gate") == "step2_judgment"


def test_deterministic_only_without_judgments():
    """judgments 없으면 Step2 no-op(결정론 1·3·4만) — 코드·비중·베타포인트 필터."""
    out = _run({"candidates": _cands(), "target_industry_codes": ["2710"]})
    # B(코드)·C(비중)·D,E(step4) 탈락, A 생존 (Step2 skip)
    assert [c["ticker"] for c in out["selected"]] == ["A"]


def test_seed_peers_ksic_reverse():
    """Step1a: target_industry_codes 없이 seed_peers 로 KSIC 역산(codes_used)."""
    out = _run({"candidates": [{"ticker": "A", "name": "A", "industry_code": "2710",
                                "revenue_share_related": 0.9, "listed_years": 5}],
                "seed_peers": [{"ticker": "S1", "industry_code": "2710"},
                               {"ticker": "S2", "industry_code": "2711"}]})
    assert set(out["codes_used"]) == {"2710", "2711"}


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed.")
