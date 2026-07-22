"""fs_clean.py 단위 검증 — 정규화·교차검증·재분류 추적.

순수 stdlib(calc_core 미의존)라 스킬 스크립트를 직접 import 해 검증.
`python tests/skill/test_fs_clean.py` 또는 `pytest tests/skill/test_fs_clean.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SKILL = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "excel-valuation-workbook" / "scripts"
sys.path.insert(0, str(_SKILL))

import fs_clean  # noqa: E402


def test_normalize_value():
    assert fs_clean.normalize_value("1,234") == 1234.0
    assert fs_clean.normalize_value("(567)") == -567.0
    assert fs_clean.normalize_value("₩ 1,000") == 1000.0
    assert fs_clean.normalize_value("△500") == -500.0
    assert fs_clean.normalize_value("-") == 0.0          # 대시 = 명시적 0
    assert fs_clean.normalize_value("") is None           # 공백 = 결측
    assert fs_clean.normalize_value("N/A") is None
    assert fs_clean.normalize_value(1234) == 1234.0
    assert fs_clean.normalize_value("1,234백만원") == 1234.0


def test_unit_scaling():
    payload = {"sources": [{"label": "F", "unit": "천원",
                            "periods": {"2024": {"매출액": "1,000,000"}}}]}
    out = fs_clean.run_clean(payload)
    # 천원 → 백만원: 1,000,000 천원 = 1,000 백만원
    assert out["normalized"]["2024"]["매출액"] == 1000.0


def test_bs_balance_pass():
    payload = {"sources": [{"label": "F", "unit": "백만원", "periods": {"2024": {
        "자산총계": "5000", "부채총계": "3000", "자본총계": "2000"}}}]}
    out = fs_clean.run_clean(payload)
    assert not any(i["code"] == "bs_imbalance" for i in out["issues"])


def test_bs_balance_fail():
    payload = {"sources": [{"label": "F", "unit": "백만원", "periods": {"2024": {
        "자산총계": "5000", "부채총계": "3000", "자본총계": "1900"}}}]}
    out = fs_clean.run_clean(payload)
    assert any(i["code"] == "bs_imbalance" and i["severity"] == "FAIL" for i in out["issues"])
    assert out["gate_ok"] is False


def test_cross_period_reclass_1to1():
    """FY2024는 '기타유동자산' 300, FY2025의 전기(2024)에선 '기타유동자산' 0 + '단기금융상품' 300.
    → 재분류 1:1 추적 후보 (300 이관)."""
    payload = {"sources": [
        {"label": "FY2024", "unit": "백만원",
         "periods": {"2024": {"현금": "100", "기타유동자산": "300", "단기금융상품": "0"}}},
        {"label": "FY2025", "unit": "백만원",
         "periods": {"2024": {"현금": "100", "기타유동자산": "0", "단기금융상품": "300"}}},
    ]}
    out = fs_clean.run_clean(payload)
    assert len(out["cross_period"]) == 2  # 기타유동자산↓, 단기금융상품↑
    cands = out["reclass_candidates"]
    assert len(cands) == 1
    assert cands[0]["from"] == "기타유동자산"
    assert cands[0]["to"] == "단기금융상품"
    assert cands[0]["amount"] == 300.0
    assert cands[0]["confidence"] == "high"
    assert out["unresolved"] == []


def test_cross_period_reclass_1tomany():
    """기타유동자산 500 → 단기금융상품 300 + 미수금 200 (1:2 분할)."""
    payload = {"sources": [
        {"label": "FY2024", "unit": "백만원",
         "periods": {"2024": {"기타유동자산": "500", "단기금융상품": "0", "미수금": "0"}}},
        {"label": "FY2025", "unit": "백만원",
         "periods": {"2024": {"기타유동자산": "0", "단기금융상품": "300", "미수금": "200"}}},
    ]}
    out = fs_clean.run_clean(payload)
    cands = out["reclass_candidates"]
    assert len(cands) == 1
    assert cands[0]["from"] == "기타유동자산"
    assert sorted(cands[0]["to"]) == ["단기금융상품", "미수금"]
    assert cands[0]["amount"] == 500.0
    assert out["unresolved"] == []


def test_net_nonzero_surfaced():
    """감소 300, 증가 250 → net≠0(수치 재작성) → unresolved 표면화, gate 차단."""
    payload = {"sources": [
        {"label": "FY2024", "unit": "백만원", "periods": {"2024": {"A": "300", "B": "0"}}},
        {"label": "FY2025", "unit": "백만원", "periods": {"2024": {"A": "0", "B": "250"}}},
    ]}
    out = fs_clean.run_clean(payload)
    assert len(out["unresolved"]) > 0
    assert out["gate_ok"] is False


def test_reclass_hint_on_unresolved():
    """미해결(net≠0) 시 account_dictionary 관계로 이관 힌트 제공(매칭 로직 불변)."""
    payload = {"sources": [
        {"label": "FY2024", "unit": "백만원",
         "periods": {"2024": {"기타유동자산": "300", "단기금융상품": "0"}}},
        {"label": "FY2025", "unit": "백만원",
         "periods": {"2024": {"기타유동자산": "0", "단기금융상품": "250"}}},  # net −50
    ]}
    out = fs_clean.run_clean(payload)
    assert out["gate_ok"] is False
    assert len(out["unresolved"]) == 2
    # 기타유동자산(from) → 단기금융상품 힌트, 단기금융상품(to) → 출처 힌트
    hints = {u["account"]: u.get("hint") for u in out["unresolved"]}
    assert hints["기타유동자산"] and "단기금융상품" in hints["기타유동자산"]
    assert hints["단기금융상품"] and "기타유동자산" in hints["단기금융상품"]


def test_unknown_account_no_hint():
    """사전에 없는 계정은 힌트 None(오탐 없음)."""
    payload = {"sources": [
        {"label": "FY2024", "unit": "백만원", "periods": {"2024": {"임의계정X": "300", "임의계정Y": "0"}}},
        {"label": "FY2025", "unit": "백만원", "periods": {"2024": {"임의계정X": "0", "임의계정Y": "250"}}},
    ]}
    out = fs_clean.run_clean(payload)
    assert all(u.get("hint") is None for u in out["unresolved"])


def test_clean_single_source_gate_ok():
    """재분류 없는 단일 source + 대차 일치 → gate_ok."""
    payload = {"sources": [{"label": "F", "unit": "백만원", "periods": {"2024": {
        "자산총계": "5000", "부채총계": "3000", "자본총계": "2000", "매출액": "8000"}}}]}
    out = fs_clean.run_clean(payload)
    assert out["gate_ok"] is True
    assert out["reclass_candidates"] == []
    assert out["unresolved"] == []


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed.")
