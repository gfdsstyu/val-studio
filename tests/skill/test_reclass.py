"""reclass.py (W3 평가재분류) 검증 — 파티션 보존(분류합=원본·중복·누락·유형).

순수 stdlib. `python tests/skill/test_reclass.py` 또는 pytest.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SKILL = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "excel-valuation-workbook" / "scripts"
sys.path.insert(0, str(_SKILL))

import reclass  # noqa: E402


def test_clean_partition_gate_ok():
    out = reclass.run_reclass({"items": [
        {"account": "매출채권", "amount": 100, "type": "WC"},
        {"account": "재고자산", "amount": 200, "type": "WC"},
        {"account": "유형자산", "amount": 700, "type": "FA"},
    ], "original_total": 1000})
    assert out["gate_ok"] is True
    assert out["by_type"] == {"WC": 300.0, "FA": 700.0}
    assert out["total"] == 1000.0


def test_total_defaults_to_sum():
    """original_total 생략 → sum(items) 자기일관(다른 이슈 없으면 gate_ok)."""
    out = reclass.run_reclass({"items": [
        {"account": "현금", "amount": 50, "type": "NOA"},
        {"account": "차입금", "amount": 300, "type": "IBD"},
    ]})
    assert out["gate_ok"] is True
    assert out["total"] == 350.0


def test_total_mismatch_fails():
    out = reclass.run_reclass({"items": [
        {"account": "매출채권", "amount": 100, "type": "WC"},
    ], "original_total": 5000})
    assert out["gate_ok"] is False
    assert any(i["code"] == "total_mismatch" and i["severity"] == "FAIL" for i in out["issues"])


def test_duplicate_account_fails():
    out = reclass.run_reclass({"items": [
        {"account": "매출채권", "amount": 100, "type": "WC"},
        {"account": "매출채권", "amount": 100, "type": "NOA"},   # 중복 분류
    ]})
    assert out["gate_ok"] is False
    assert "매출채권" in out["duplicates"]
    assert any(i["code"] == "duplicate_account" for i in out["issues"])


def test_unclassified_fails():
    out = reclass.run_reclass({"items": [
        {"account": "매출채권", "amount": 100, "type": "WC"},
        {"account": "이연법인세자산", "amount": 50, "type": ""},   # 미분류
    ]})
    assert out["gate_ok"] is False
    assert "이연법인세자산" in out["unclassified"]


def test_invalid_type_fails():
    out = reclass.run_reclass({"items": [
        {"account": "매출채권", "amount": 100, "type": "운전자본"},   # 한글 유형(허용 아님)
    ]})
    assert out["gate_ok"] is False
    assert any(i["code"] == "invalid_type" for i in out["issues"])


def test_valid_types_restriction():
    """BS 전용 valid_types 지정 시 PL 유형(Sales) 거부."""
    out = reclass.run_reclass({"items": [
        {"account": "매출", "amount": 100, "type": "Sales"},
    ], "valid_types": ["WC", "FA", "NOA", "IBD", "OAL", "EQU"]})
    assert out["gate_ok"] is False
    assert any(i["account"] == "매출" for i in out["invalid_types"])


def test_pl_partition():
    """PL 4유형 파티션 — 기본 valid 에 포함."""
    out = reclass.run_reclass({"items": [
        {"account": "제품매출", "amount": 1000, "type": "Sales"},
        {"account": "매출원가", "amount": 600, "type": "COGS"},
        {"account": "판관비", "amount": 200, "type": "SGA"},
        {"account": "이자수익", "amount": 20, "type": "NO"},
    ], "original_total": 1820})
    assert out["gate_ok"] is True
    assert out["by_type"]["Sales"] == 1000.0 and out["by_type"]["NO"] == 20.0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed.")
