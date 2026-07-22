"""DCF 전체 어셈블리 테스트 — WACC 서브어셈블리 + 운영가정 → DcfResult, 게이트 순서.

커넥터(복붙)→WACC→DCF 엔드투엔드 + 실행 전/후 게이트 차단 시나리오.
stdlib: `python tests/test_dcf_assembly.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from assemble.dcf_inputs import assemble_dcf_inputs  # noqa: E402
from assemble.wacc_inputs import PeerBeta, assemble_wacc_inputs  # noqa: E402
from calc_core import fa, wc  # noqa: E402
from ingest.manual_paste import PasteParser, paste_mrp, paste_risk_free  # noqa: E402
from ingest.validators import Severity  # noqa: E402


def _wacc(**over):
    """커넥터 원천값으로 조립한 WaccAssembly(BBB 5Y Kd·peer βu·Rf/MRP 복붙)."""
    p = PasteParser("KOFIABOND", pasted_at="2023-06-30")
    kd = p.parse_bond_matrix("등급 3Y 5Y\nAAA 3.21 3.48\nBBB 5.40 5.80\n")
    kw = dict(
        risk_free=paste_risk_free("3.45%", source_id="KOFIABOND", pasted_at="2023-06-30"),
        mrp=paste_mrp("8", source_id="한공회", pasted_at="2024-01-01"),
        peers=[PeerBeta("A", 1.20, 0.5, 0.22), PeerBeta("B", 1.05, 0.3, 0.22)],
        target_debt_to_equity=0.4, tax_rate=0.22,
        kd_matrix=kd, kd_grade="BBB", kd_tenor="5Y", market_cap_musd=1500.0,
        beta_source="bloomberg", beta_market="KOSPI",
        mrp_source="kicpa", mrp_market="KOSPI",
    )
    kw.update(over)
    return assemble_wacc_inputs(**kw)


def _ops(**over):
    """운영가정(매출·원가·FA·WC·브리지) 기본 묶음."""
    kw = dict(
        revenue=[1000, 1100, 1210],
        cogs_pct=[0.6, 0.6, 0.6], sga_pct=[0.2, 0.2, 0.2],
        asset_classes=[fa.AssetClass("설비", opening_net_book=300, remaining_life=3, useful_life=10)],
        new_capex_by_class={"설비": [50, 50, 50]},
        wc_items=[wc.WcItem("AR", base_balance=100, base_driver=1000, is_asset=True)],
        wc_driver_by_item={"AR": [1000, 1100, 1210]},
        base_net_working_capital=100.0,
        terminal_growth=0.02, non_operating_assets=100.0, net_debt=50.0,
        shares_outstanding=1_000_000,
    )
    kw.update(over)
    return kw


def test_end_to_end_from_connectors():
    a = assemble_dcf_inputs(wacc=_wacc(), **_ops())
    assert not a.blocked
    assert a.result is not None and a.spine is not None
    assert a.result.enterprise_value > 0 and a.result.per_share > 0
    # spine WACC = 어셈블리 WACC(≈11%대) 가 흘러들어감
    assert 0.08 < a.spine.wacc < 0.16
    # EBIT = 매출·0.2
    assert abs(a.result.ebit[0] - 200.0) < 1e-6
    # provenance 가 WACC 어셈블리에서 승계됨
    assert "risk_free" in a.provenance and "pre_tax_cost_of_debt" in a.provenance


def test_wacc_blocked_short_circuits():
    # WACC 어셈블리가 막히면(복붙 Rf 350%) DCF 즉시 차단 — dcf_run 도달 안 함
    bad_wacc = _wacc(risk_free=paste_risk_free("350", source_id="X", pasted_at="2023-06-30"))
    a = assemble_dcf_inputs(wacc=bad_wacc, **_ops())
    assert a.blocked
    assert a.config is None and a.spine is None and a.result is None
    assert any(f.rule == "range" and f.severity is Severity.FAIL for f in a.report.findings)


def test_pgr_ge_wacc_blocks_before_run():
    # PGR(20%) ≥ WACC → 실행 전 게이트 FAIL, spine/result 생성 안 함(Gordon 발산 방지)
    a = assemble_dcf_inputs(wacc=_wacc(), **_ops(terminal_growth=0.20))
    assert a.blocked
    assert a.config is not None            # 참고용 config 는 있음
    assert a.spine is None and a.result is None
    assert any(f.rule == "pgr_vs_wacc" and f.severity is Severity.FAIL
               for f in a.report.findings)


def test_revenue_jump_warns_not_blocks():
    # 매출 YoY 급변(+150%)은 WARN(사업근거 기재 신호) — 차단 아님, 결과는 나옴
    a = assemble_dcf_inputs(wacc=_wacc(), **_ops(revenue=[1000, 2500, 2700],
                                                 wc_driver_by_item={"AR": [1000, 2500, 2700]}))
    assert not a.blocked
    assert a.result is not None
    assert any(f.rule == "projection_smoothness" and f.severity is Severity.WARN
               for f in a.report.findings)


def test_post_run_tv_weight_recorded():
    # 실행 후 게이트(TV 비중)가 리포트에 남는지 — 통과/경고 무관 항상 기록
    a = assemble_dcf_inputs(wacc=_wacc(), **_ops())
    assert any(f.rule == "tv_weight" for f in a.report.findings)
    assert any(f.rule == "working_capital_burn" for f in a.report.findings)


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
