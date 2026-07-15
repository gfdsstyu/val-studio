"""상류 엔진 단위테스트 — wacc·wc·fa·revenue·ebit·tax·model.

표준 방법론 검증 + 비올 골든과 연결되는 부분(법인세)은 픽스처로 앵커.
stdlib 로 실행: `python tests/test_upstream.py` (pytest 도 가능).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core import (  # noqa: E402
    ModelConfig, WaccInputs, build_wacc, corporate_tax, ebit, fa,
    relever_beta, revenue, run_model, unlever_beta, wc,
)

FX = ROOT / "fixtures" / "viol"


def close(a, b, rel=1e-9, ab=1e-6):
    return math.isclose(a, b, rel_tol=rel, abs_tol=ab)


# ── 법인세: 비올 골든과 일치 ───────────────────────────────────────────────
def test_tax_matches_viol():
    inp = json.loads((FX / "inputs.json").read_text(encoding="utf-8"))
    exp = json.loads((FX / "expected.json").read_text(encoding="utf-8"))
    ebit_vec = [inp["revenue"][t] - inp["cogs"][t] - inp["sga"][t] for t in range(5)]
    for t in range(5):
        got = corporate_tax(ebit_vec[t])
        assert close(got, exp["tax"][t]), f"tax[{t}] {got} != {exp['tax'][t]}"


def test_tax_brackets():
    # 구간 경계 검증(백만원 단위, ×1.1 지방소득세 포함)
    assert corporate_tax(0) == 0.0
    assert corporate_tax(-100) == 0.0
    assert close(corporate_tax(100), 100 * 0.09 * 1.1)                 # 1구간
    assert close(corporate_tax(200), 200 * 0.09 * 1.1)                 # 경계
    assert close(corporate_tax(1000), (200 * 0.09 + 800 * 0.19) * 1.1)  # 2구간


# ── WACC 빌드업 ────────────────────────────────────────────────────────────
def test_beta_unlever_relever_roundtrip():
    bl, de, t = 1.2, 0.5, 0.22
    bu = unlever_beta(bl, de, t)
    assert close(relever_beta(bu, de, t), bl)  # 같은 D/E·t 로 되돌리면 원복


def test_wacc_buildup():
    # 깨끗한 예: Rf 3.5%, ERP 8%(한공회 범위), βu 0.9, D/E 0.25, t 22%, Kd 5%
    r = build_wacc(WaccInputs(
        risk_free=0.035, equity_risk_premium=0.08, unlevered_beta=0.9,
        target_debt_to_equity=0.25, tax_rate=0.22, pre_tax_cost_of_debt=0.05,
        size_premium=0.01,
    ))
    # 수동 검증
    beta_l = 0.9 * (1 + (1 - 0.22) * 0.25)
    ke = 0.035 + beta_l * 0.08 + 0.01
    kd_at = 0.05 * (1 - 0.22)
    we, wd = 1 / 1.25, 0.25 / 1.25
    assert close(r.relevered_beta, beta_l)
    assert close(r.cost_of_equity, ke)
    assert close(r.after_tax_cost_of_debt, kd_at)
    assert close(r.wacc, we * ke + wd * kd_at)
    assert 0.08 < r.wacc < 0.14  # 상식 범위


# ── 운전자본 회전율 ────────────────────────────────────────────────────────
def test_wc_turnover_and_delta():
    # 매출채권: 기초 잔액 100, driver(매출) 1000 → 회전율10, 회전기간36.5일
    item = wc.WcItem(name="AR", base_balance=100, base_driver=1000, is_asset=True)
    assert close(item.turnover_days(), 36.5)
    # 매출 2000 투영 → 잔액 200 (회전기간 고정)
    assert close(wc.project_balance(item, 2000), 200.0)
    res = wc.project_working_capital(
        [item], {"AR": [2000, 3000]}, base_net_working_capital=100.0
    )
    assert close(res.net_working_capital[0], 200.0)
    assert close(res.net_working_capital[1], 300.0)
    # ΔNWC 현금조정: 자산 증가 → 현금유출(−)
    assert close(res.delta_nwc_cash_adj[0], -(200 - 100))
    assert close(res.delta_nwc_cash_adj[1], -(300 - 200))


# ── 감가상각 스케줄 ────────────────────────────────────────────────────────
def test_fa_depreciation():
    # 기존자산 순장부 100, 잔여 5년 → 연 20 상각(5년간)
    ac = fa.AssetClass(name="기계", opening_net_book=100, remaining_life=5, useful_life=10)
    # 신규 CAPEX: 1년차 200 투자, 내용연수 10 → 연 20 상각
    res = fa.project_fixed_assets([ac], {"기계": [200, 0, 0]})
    # t0: 기존20 + 신규(200/10=20) = 40 ; t1,t2 동일(둘 다 상각 지속)
    assert close(res.dep_amort[0], 40.0)
    assert close(res.dep_amort[1], 40.0)
    assert close(res.capex[0], 200.0)
    assert close(res.capex[1], 0.0)


# ── 매출 전략 ──────────────────────────────────────────────────────────────
def test_revenue_top_down():
    # TAM 1000, 점유율 10%, CAGR 20%, 3년 → 120, 144, 172.8
    out = revenue.top_down(market_size=1000, share=0.1, cagr=0.2, years=3)
    assert close(out[0], 120.0) and close(out[1], 144.0) and close(out[2], 172.8)


def test_revenue_bottom_up_tree_and_sums():
    # 장비/소모품 트리 (razor-and-blades)
    equip = revenue.RevenueNode("장비", price=[10, 10], qty=[5, 6])       # 50, 60
    consum = revenue.RevenueNode("소모품", base=30, growth=[0.1, 0.1])     # 33, 36.3
    root = revenue.RevenueNode("총매출", children=[equip, consum])
    out = revenue.bottom_up(root, years=2)
    assert close(out[0], 50 + 33) and close(out[1], 60 + 36.3)
    assert revenue.validate_tree_sums(root, years=2) == []  # 합계검증 통과


# ── 엔드투엔드 통합 ────────────────────────────────────────────────────────
def test_run_model_end_to_end():
    cfg = ModelConfig(
        revenue=[1000, 1100, 1210],
        cogs_pct=[0.6, 0.6, 0.6],
        sga_pct=[0.2, 0.2, 0.2],
        asset_classes=[fa.AssetClass("설비", opening_net_book=300, remaining_life=3, useful_life=10)],
        new_capex_by_class={"설비": [50, 50, 50]},
        wc_items=[wc.WcItem("AR", base_balance=100, base_driver=1000, is_asset=True)],
        wc_driver_by_item={"AR": [1000, 1100, 1210]},
        base_net_working_capital=100.0,
        wacc_inputs=WaccInputs(
            risk_free=0.035, equity_risk_premium=0.08, unlevered_beta=0.9,
            target_debt_to_equity=0.25, tax_rate=0.22, pre_tax_cost_of_debt=0.05,
        ),
        terminal_growth=0.02,
        non_operating_assets=100.0,
        net_debt=50.0,
        shares_outstanding=1_000_000,
    )
    res = run_model(cfg)
    # EBIT = 매출·(1−0.6−0.2) = 매출·0.2
    assert close(res.ebit[0], 200.0)
    assert res.enterprise_value > 0 and res.per_share > 0
    # 민감도 중심 == base
    assert close(res.sensitivity["per_share"][1][1], res.per_share)


ALL = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    passed = 0
    for fn in ALL:
        fn()
        passed += 1
        print(f"  ok  {fn.__name__}")
    print(f"PASS — 상류 엔진 단위테스트 {passed}건 전부 통과")
