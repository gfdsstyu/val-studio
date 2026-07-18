"""WACC 어셈블리 테스트 — 커넥터 3종 원천값 → 검증된 WaccInputs → build_wacc.

복붙 커넥터(paste_*)·BondYieldMatrix·price_client β 를 실제로 물려 통합 게이트를 검증.
stdlib: `python tests/test_wacc_assembly.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from assemble.wacc_inputs import (  # noqa: E402
    PeerBeta, WaccAssembly, assemble_wacc_inputs,
)
from ingest.manual_paste import (  # noqa: E402
    PasteParser, paste_mrp, paste_risk_free,
)
from ingest.validators import Severity  # noqa: E402


def _kd_matrix():
    text = "등급 3Y 5Y\nAAA 3.21 3.48\nBBB 5.40 5.80\n"
    p = PasteParser("KOFIABOND", pasted_at="2023-06-30", user="jjb")
    return p.parse_bond_matrix(text)


def _peers():
    # 유사기업 3사: 관측 레버드 β + 자본구조(무부채화 입력)
    return [
        PeerBeta("A", levered_beta=1.20, debt_to_equity=0.5, tax_rate=0.22),
        PeerBeta("B", levered_beta=1.05, debt_to_equity=0.3, tax_rate=0.22),
        PeerBeta("C", levered_beta=1.35, debt_to_equity=0.7, tax_rate=0.22),
    ]


def test_full_assembly_from_connectors():
    a = assemble_wacc_inputs(
        risk_free=paste_risk_free("3.45%", source_id="KOFIABOND", pasted_at="2023-06-30"),
        mrp=paste_mrp("8", source_id="한공회", pasted_at="2024-01-01"),
        peers=_peers(),
        target_debt_to_equity=0.4, tax_rate=0.22,
        kd_matrix=_kd_matrix(), kd_grade="BBB", kd_tenor="5Y",
        market_cap_musd=1500.0,                      # → Kroll decile size premium
        beta_source="bloomberg", beta_market="KOSPI",
        mrp_source="kicpa", mrp_market="KOSPI",
    )
    assert not a.blocked
    assert a.result is not None
    # Rf 3.45% + βL'·8% + size 가 Ke 에 반영 → WACC 는 Rf 초과·Ke 미만 사이 상식 범위
    assert 0.03 < a.result.wacc < 0.20
    assert a.inputs.market_risk_premium == 0.08
    assert abs(a.inputs.risk_free - 0.0345) < 1e-9
    assert a.inputs.pre_tax_cost_of_debt == 0.058   # BBB×5Y = 5.80%
    assert a.inputs.size_premium > 0                # 중형주 → decile 프리미엄 有
    # provenance: 각 원천이 감사 라벨 보유
    assert "risk_free" in a.provenance and "mrp" in a.provenance
    assert "pre_tax_cost_of_debt" in a.provenance and "BBB×5Y" in a.provenance["pre_tax_cost_of_debt"]


def test_unlevered_beta_from_peers():
    # peers 무부채화 평균이 unlevered_beta 로 조립됐는지(계산은 wacc.peer_unlevered_beta)
    a = assemble_wacc_inputs(
        risk_free=0.0345, mrp=0.08, peers=_peers(),
        target_debt_to_equity=0.4, tax_rate=0.22,
        pre_tax_cost_of_debt=0.058,
    )
    from calc_core.wacc import peer_unlevered_beta
    expected = peer_unlevered_beta([(1.20, 0.5, 0.22), (1.05, 0.3, 0.22), (1.35, 0.7, 0.22)])
    assert abs(a.inputs.unlevered_beta - expected) < 1e-12


def test_bad_paste_blocks_assembly():
    # Rf 복붙이 범위 밖(350%) → range FAIL 이 어셈블리로 전파돼 차단
    a = assemble_wacc_inputs(
        risk_free=paste_risk_free("350", source_id="KOFIABOND", pasted_at="2023-06-30"),
        mrp=0.08, peers=_peers(),
        target_debt_to_equity=0.4, tax_rate=0.22, pre_tax_cost_of_debt=0.058,
    )
    assert a.blocked
    assert a.result is None
    assert any(f.rule == "range" and f.severity is Severity.FAIL for f in a.report.findings)


def test_missing_kd_blocks():
    a = assemble_wacc_inputs(
        risk_free=0.0345, mrp=0.08, peers=_peers(),
        target_debt_to_equity=0.4, tax_rate=0.22,
        # Kd 미제공(매트릭스도 직접값도 없음)
    )
    assert a.blocked
    assert a.inputs is None
    assert any("Kd" in f.message for f in a.report.fails)


def test_kd_matrix_missing_cell_blocks():
    a = assemble_wacc_inputs(
        risk_free=0.0345, mrp=0.08, peers=_peers(),
        target_debt_to_equity=0.4, tax_rate=0.22,
        kd_matrix=_kd_matrix(), kd_grade="CCC", kd_tenor="5Y",   # CCC 등급 없음
    )
    assert a.blocked
    assert any("CCC" in f.message for f in a.report.fails)


def test_empty_peers_blocks():
    a = assemble_wacc_inputs(
        risk_free=0.0345, mrp=0.08, peers=[],
        target_debt_to_equity=0.4, tax_rate=0.22, pre_tax_cost_of_debt=0.058,
    )
    assert a.blocked
    assert any("peers" in f.message for f in a.report.fails)


def test_beta_mrp_market_mismatch_warns_not_blocks():
    # β 시장 ≠ MRP 시장 → WARN(감사 노출)이지 FAIL 아님 → 조립은 통과
    a = assemble_wacc_inputs(
        risk_free=0.0345, mrp=0.08, peers=_peers(),
        target_debt_to_equity=0.4, tax_rate=0.22, pre_tax_cost_of_debt=0.058,
        beta_source="bloomberg", beta_market="SP500",
        mrp_source="kicpa", mrp_market="KOSPI",
    )
    assert not a.blocked                             # WARN 은 게이트 안 막음
    assert any(f.rule == "beta_mrp_consistency" and f.severity is Severity.WARN
               for f in a.report.findings)


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
