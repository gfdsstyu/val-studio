"""fs_disagg.py 단위 검증 — 손익 세분 합보존 + 구성비 추이 (W2.5).

순수 stdlib(calc_core 미의존). fs_disagg 는 fs_clean 의 정규화를 재사용하므로
같은 scripts/ 디렉터리를 path 에 넣으면 둘 다 import 된다.
`python tests/skill/test_fs_disagg.py` 또는 `pytest tests/skill/test_fs_disagg.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SKILL = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "excel-valuation-workbook" / "scripts"
sys.path.insert(0, str(_SKILL))

import fs_disagg  # noqa: E402


def test_sum_preservation_pass():
    """제품 800 + 상품 434 = 매출액 1,234 → 합보존, gate_ok."""
    payload = {"blocks": [{"parent": "매출액", "unit": "백만원", "periods": {
        "2024": {"total": "1,234", "children": {"제품매출": "800", "상품매출": "434"}}}}]}
    out = fs_disagg.run_disagg(payload)
    assert out["gate_ok"] is True
    row = out["disaggregated"]["매출액"]["2024"]
    assert row["_total"] == 1234.0
    assert row["_residual"] == 0.0
    assert not any(i["code"] == "disagg_imbalance" for i in out["issues"])


def test_sum_preservation_fail():
    """세분합 700+434=1134 ≠ 원계정 1234 (잔차 100) → FAIL, gate 차단."""
    payload = {"blocks": [{"parent": "매출액", "unit": "백만원", "periods": {
        "2024": {"total": "1,234", "children": {"제품매출": "700", "상품매출": "434"}}}}]}
    out = fs_disagg.run_disagg(payload)
    assert out["gate_ok"] is False
    fails = [i for i in out["issues"] if i["code"] == "disagg_imbalance"]
    assert len(fails) == 1 and fails[0]["severity"] == "FAIL"
    assert fails[0]["detail"]["residual"] == 100.0


def test_normalization_reuse():
    """fs_clean 정규화 재사용 — 콤마·괄호음수. 매출원가는 음수 표기(괄호)로 세분."""
    payload = {"blocks": [{"parent": "매출원가", "unit": "백만원", "periods": {
        "2024": {"total": "(1,000)", "children": {"재료비": "(600)", "노무비": "(400)"}}}}]}
    out = fs_disagg.run_disagg(payload)
    assert out["gate_ok"] is True
    row = out["disaggregated"]["매출원가"]["2024"]
    assert row["_total"] == -1000.0
    assert row["_residual"] == 0.0


def test_unit_scaling():
    """천원 → 백만원 스케일 후 합보존."""
    payload = {"blocks": [{"parent": "매출액", "unit": "천원", "periods": {
        "2024": {"total": "1,000,000", "children": {"제품매출": "600,000", "상품매출": "400,000"}}}}]}
    out = fs_disagg.run_disagg(payload)
    row = out["disaggregated"]["매출액"]["2024"]
    assert row["_total"] == 1000.0          # 1,000,000 천원 = 1,000 백만원
    assert row["_residual"] == 0.0
    assert out["gate_ok"] is True


def test_mix_ratio_computed():
    """구성비 = child/total."""
    payload = {"blocks": [{"parent": "매출액", "unit": "백만원", "periods": {
        "2024": {"total": "1000", "children": {"제품매출": "750", "상품매출": "250"}}}}]}
    out = fs_disagg.run_disagg(payload)
    mix = out["mix"]["매출액"]["2024"]
    assert mix["제품매출"] == 0.75
    assert mix["상품매출"] == 0.25


def test_mix_swing_warns_but_not_blocks():
    """구성비 급변(제품 90%→60%, Δ30%p>15%p) → WARN, 그러나 합보존이면 gate_ok 유지."""
    payload = {"blocks": [{"parent": "매출액", "unit": "백만원", "periods": {
        "2023": {"total": "1000", "children": {"제품매출": "900", "상품매출": "100"}},
        "2024": {"total": "1000", "children": {"제품매출": "600", "상품매출": "400"}}}}]}
    out = fs_disagg.run_disagg(payload)
    swings = [i for i in out["issues"] if i["code"] == "mix_swing"]
    assert any(i["severity"] == "WARN" for i in swings)
    assert out["gate_ok"] is True           # 급변은 표면화만, 차단 안 함(합보존 OK)


def test_mix_stable_no_warn():
    """구성비 안정(Δ<15%p) → mix_swing 없음."""
    payload = {"blocks": [{"parent": "매출액", "unit": "백만원", "periods": {
        "2023": {"total": "1000", "children": {"제품매출": "700", "상품매출": "300"}},
        "2024": {"total": "1000", "children": {"제품매출": "720", "상품매출": "280"}}}}]}
    out = fs_disagg.run_disagg(payload)
    assert not any(i["code"] == "mix_swing" for i in out["issues"])


def test_child_missing_surfaced():
    """결측 자식(None) → WARN child_missing + 잔차에 반영(합보존 FAIL 가능)."""
    payload = {"blocks": [{"parent": "판매관리비", "unit": "백만원", "periods": {
        "2024": {"total": "500", "children": {"급여": "300", "감가상각비": None, "기타판관비": "50"}}}}]}
    out = fs_disagg.run_disagg(payload)
    assert any(i["code"] == "child_missing" and i["severity"] == "WARN" for i in out["issues"])
    row = out["disaggregated"]["판매관리비"]["2024"]
    assert row["_residual"] == 150.0        # 500 - (300+50) = 150 (감가상각비 누락분)


def test_no_total_warns():
    """원계정 결측 → 합보존 검증 불가 WARN(FAIL 아님 — gate 유지)."""
    payload = {"blocks": [{"parent": "영업외손익", "unit": "백만원", "periods": {
        "2024": {"children": {"경상항목": "10", "일회성항목": "5"}}}}]}
    out = fs_disagg.run_disagg(payload)
    assert any(i["code"] == "no_total" and i["severity"] == "WARN" for i in out["issues"])
    assert out["gate_ok"] is True


def test_empty_blocks_gate_false():
    out = fs_disagg.run_disagg({"blocks": []})
    assert out["gate_ok"] is False
    assert any(i["code"] == "no_input" for i in out["issues"])


def test_multi_block_independent():
    """여러 원계정 블록 독립 검증 — 하나 FAIL 이면 전체 gate 차단."""
    payload = {"blocks": [
        {"parent": "매출액", "unit": "백만원", "periods": {
            "2024": {"total": "1000", "children": {"제품매출": "1000"}}}},           # OK
        {"parent": "매출원가", "unit": "백만원", "periods": {
            "2024": {"total": "600", "children": {"재료비": "500"}}}},               # 잔차 100 FAIL
    ]}
    out = fs_disagg.run_disagg(payload)
    assert out["gate_ok"] is False
    assert set(out["disaggregated"].keys()) == {"매출액", "매출원가"}


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed.")
