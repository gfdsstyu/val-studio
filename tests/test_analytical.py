"""분석적 절차 계층(analytical.py) 골든 테스트 — 비올 리뷰노트 실측 픽스처.

원칙: "이 검사가 있었다면 잡혔다"를 테스트로 증명한다. 픽스처 수치는 전부
비올 DCF 리뷰 조서(§2 이상치 스캔·§3.5 마진 해부·§6.5 수정 실측)의 실측값.
소급 적발 대상: E-6(재료비율 3년 밀림)·E-10(상품매출원가)·J-1(인건비 중복)·
E-1/E-3(운전자본 누락)·§2-3(컨센서스 미대조).
stdlib: pytest.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core.analytical import (  # noqa: E402
    FinancialHistory, SegmentSeries, analytical_review, check_consensus_anchor,
    check_derived_continuity, check_mix_reconciliation, check_nwc_growth_consistency,
    check_ratio_seam, check_spike_revert, mix_decomposition, opm_bridge,
)
from calc_core.checks import audit_dcf  # noqa: E402
from calc_core.dcf import run  # noqa: E402
from calc_core.models import DcfSpineInput  # noqa: E402
from ingest.validators import Severity  # noqa: E402

# ── 비올 실측 픽스처 (리뷰노트 §2 표) ────────────────────────────────────────
COGS_RATIO_ACT = [0.256, 0.294, 0.331, 0.267, 0.222]   # 2019~2023 실적 원가율
COGS_RATIO_FC = [0.288, 0.245, 0.238, 0.235, 0.234]    # 2024E~2028E (E-6·J-1 오염)
SGA_RATIO_ACT = [0.402, 0.425, 0.375, 0.318, 0.253]
SGA_RATIO_FC = [0.241, 0.224, 0.234, 0.229, 0.228]
GPM_ACT = [0.744, 0.706, 0.669, 0.733, 0.778]
REV_ACT = [11087.0, 12151.0, 18372.0, 31104.0, 42520.0]
REV_FC = [56784.0, 70538.0, 85139.0, 97484.0, 109260.0]


def _by_rule(findings, rule):
    return [f for f in findings if f.rule == rule]


# ── 3.1 접합부 비율 연속성 ───────────────────────────────────────────────────
def test_seam_cogs_ratio_warns():
    # E-6·J-1 진입점: 원가율 22.2% → 28.8%, +6.6%p 계단 이탈
    f = check_ratio_seam(COGS_RATIO_ACT, COGS_RATIO_FC, name="매출원가율")
    assert f.severity is Severity.WARN
    assert f.detail["delta"] == pytest.approx(0.066, abs=1e-9)


def test_seam_corrected_cogs_passes():
    # E-6·J-1 제거 시 제품 원가율 20.9% — 실적 21.3%(2023 제품)와 자연 연결(§3.5)
    f = check_ratio_seam([0.276, 0.269, 0.217, 0.213], [0.209, 0.207],
                         name="제품 원가율")
    assert f.severity is Severity.PASS


def test_seam_merchandise_cogs_warns():
    # E-10: 상품 원가율 68.4% → 41.1%, 근거 없는 27%p 개선
    f = check_ratio_seam([0.699, 0.684], [0.411, 0.442, 0.462], name="상품 원가율")
    assert f.severity is Severity.WARN
    assert f.detail["delta"] == pytest.approx(-0.273, abs=1e-9)


def test_seam_relative_mode_for_days():
    # 회전기일: %p 개념 없음 → 상대 ±20%
    warn = check_ratio_seam([47.2, 39.0], [50.0], name="DSO", relative=True)
    assert warn.severity is Severity.WARN          # +28.2%
    ok = check_ratio_seam([47.2, 39.0], [42.0], name="DSO", relative=True)
    assert ok.severity is Severity.PASS            # +7.7%


def test_seam_no_actuals_degrades_to_pass():
    # 실적 부재 → 차단하지 않고 정보성 PASS (prior 원칙)
    f = check_ratio_seam([], COGS_RATIO_FC, name="매출원가율")
    assert f.severity is Severity.PASS


# ── 3.2 V자(스파이크-복귀) 시그니처 ─────────────────────────────────────────
def test_spike_revert_material_ratio():
    # E-6: 재료비율 2021~2023 실적 + 2024(2021값 오참조) + 2025~ 정상 평균.
    # 2024만 +2.99%p 이탈 후 복귀(이웃차 1.13%p) — 참조 밀림 시그니처.
    series = [0.1532, 0.1060, 0.1290, 0.1532, 0.1177, 0.1177, 0.1177]
    f = check_spike_revert(series, name="재료비율")
    assert f.severity is Severity.WARN
    assert len(f.detail["spikes"]) == 1
    assert f.detail["spikes"][0]["index"] == 3
    assert f.detail["spikes"][0]["deviation"] == pytest.approx(0.02985, abs=1e-5)


def test_spike_revert_ignores_level_shift():
    # 레벨 시프트(가정 변경 — 이웃끼리도 벌어짐)는 스파이크가 아니다
    f = check_spike_revert([0.12, 0.12, 0.17, 0.17, 0.17], name="비율")
    assert f.severity is Severity.PASS


# ── 3.3 마진 브리지 분해 ─────────────────────────────────────────────────────
def test_opm_bridge_reproduces_review_table():
    # §3.5(b): 연도별 OPM 변동의 GPM 기여·판관비율 기여 분해가 실측 표와 일치
    rows = opm_bridge(GPM_ACT, SGA_RATIO_ACT)
    assert rows[0]["gpm_contrib"] == pytest.approx(-0.038, abs=1e-9)   # 2020
    assert rows[0]["sga_contrib"] == pytest.approx(-0.023, abs=1e-9)
    assert rows[2]["gpm_contrib"] == pytest.approx(+0.064, abs=1e-9)   # 2022
    assert rows[2]["sga_contrib"] == pytest.approx(+0.057, abs=1e-9)
    assert rows[3]["gpm_contrib"] == pytest.approx(+0.045, abs=1e-9)   # 2023
    assert rows[3]["sga_contrib"] == pytest.approx(+0.065, abs=1e-9)
    # 항등: opm_to − opm_from = 두 기여의 합
    for r in rows:
        assert r["opm_to"] - r["opm_from"] == pytest.approx(r["d_opm"], abs=1e-12)


# 비올 §3.5(a) 근사 부문 레벨: 2021(상품 비중 13.0%) → 2023(2.5%)
_SEG_HIST = [
    SegmentSeries("제품", revenue=[87.0, 96.7], cogs=[23.403, 20.597]),   # 26.9%→21.3%
    SegmentSeries("상품", revenue=[13.0, 2.5], cogs=[9.854, 1.710]),      # 75.8%→68.4%
]


def test_mix_decomposition_identity_and_direction():
    out = mix_decomposition(_SEG_HIST)
    step = out["steps"][0]
    # midpoint 분해는 잔차가 항등적으로 0
    assert step["mix_effect"] + step["rate_effect"] == pytest.approx(
        step["total"], abs=1e-12)
    # 저마진(고원가율) 상품 비중 축소 → 믹스 효과는 원가율 하락(−) 방향
    assert step["mix_effect"] < 0
    # 가중평균 원가율 재현: 0.870×26.9% + 0.130×75.8% ≈ 33.3% (§3.5(a) ✓)
    assert out["ratio"][0] == pytest.approx(0.33257, abs=1e-4)


def test_mix_reconciliation_pass_and_warn():
    ok = check_mix_reconciliation(_SEG_HIST, [0.331, 0.222])
    assert ok.severity is Severity.PASS            # 재현 잔차 0.16%p·0.29%p
    bad = check_mix_reconciliation(_SEG_HIST, [0.331, 0.240])
    assert bad.severity is Severity.WARN           # −1.5%p → 부문표↔손익 불일치


# ── 3.4 단위경제 파생지표 ────────────────────────────────────────────────────
def test_per_capita_labor_catches_j1():
    # J-1: 전사 인당 인건비 58.2 → 46.0 → 64.5(+40%) — 인원·인건비 각각은
    # 자연스러워 보이나 나눗셈이 튄다("각 셀은 맞는데 결합하면 틀림")
    f = check_derived_continuity([5820.0, 4600.0, 6450.0], [100.0, 100.0, 100.0],
                                 name="인당 인건비")
    assert f.severity is Severity.WARN
    worst = max(f.detail["jumps"], key=lambda j: abs(j["yoy"]))
    assert worst["index"] == 2
    assert worst["yoy"] == pytest.approx(0.402, abs=1e-3)


def test_derived_continuity_stable_passes():
    f = check_derived_continuity([4600.0, 4800.0], [100.0, 102.0], name="인당 인건비")
    assert f.severity is Severity.PASS


# ── 3.5 컨센서스 앵커 ────────────────────────────────────────────────────────
def test_consensus_gap_warns():
    # §2-3: 자기 GPM 71.2% vs 이베스트 78% — 같은 파일에 있었는데 미대조
    f = check_consensus_anchor("GPM(2024E)", 0.712, 0.78, source="이베스트증권 2024E")
    assert f.rule == "consensus_anchor" and f.severity is Severity.WARN
    assert f.detail["delta"] == pytest.approx(-0.068, abs=1e-9)


def test_consensus_within_band_passes():
    f = check_consensus_anchor("GPM(2024E)", 0.775, 0.78, source="이베스트증권 2024E")
    assert f.severity is Severity.PASS


def test_consensus_requires_source():
    f = check_consensus_anchor("GPM(2024E)", 0.712, 0.78, source="")
    assert f.rule == "consensus_provenance" and f.severity is Severity.WARN


# ── 3.6 성장-운전자본 정합 ───────────────────────────────────────────────────
def test_nwc_zero_under_growth_warns():
    # E-1·E-3 현상: 매출 +33.5% 첫해 ΔNWC=0 — "성장의 대가 없는 밸류에이션"
    f = check_nwc_growth_consistency(REV_FC[:3], [0.0, -3000.0, -3500.0],
                                     prior_revenue=REV_ACT[-1])
    assert f.severity is Severity.WARN
    assert [x["index"] for x in f.detail["flags"]] == [0]


def test_nwc_restored_passes():
    # 수정 후 실측: 2024 ΔNWC 0 → −3,759백만 복원(§6.5(e))
    f = check_nwc_growth_consistency(REV_FC[:3], [-3759.0, -3000.0, -3500.0],
                                     prior_revenue=REV_ACT[-1])
    assert f.severity is Severity.PASS


# ── 종합: analytical_review + audit_dcf 배선 ────────────────────────────────
def _viol_like_input(delta_nwc0: float = 0.0) -> DcfSpineInput:
    return DcfSpineInput(
        wacc=0.113, terminal_growth=0.02,
        revenue=REV_FC,
        cogs=[r * x for r, x in zip(COGS_RATIO_FC, REV_FC)],
        sga=[r * x for r, x in zip(SGA_RATIO_FC, REV_FC)],
        dep_amort=[1500.0] * 5, capex=[1600.0] * 5,
        delta_nwc_cash_adj=[delta_nwc0, -3000.0, -3500.0, -3800.0, -4000.0],
        non_operating_assets=49463.0, net_debt=655.0,
        shares_outstanding=57_656_967,
    )


def _viol_history() -> FinancialHistory:
    return FinancialHistory(
        years=[2019, 2020, 2021, 2022, 2023],
        revenue=REV_ACT,
        cogs=[r * x for r, x in zip(COGS_RATIO_ACT, REV_ACT)],
        sga=[r * x for r, x in zip(SGA_RATIO_ACT, REV_ACT)],
    )


def test_analytical_review_composite():
    rep = analytical_review(_viol_history(), _viol_like_input())
    seams = _by_rule(rep.findings, "ratio_seam")
    warn_names = {f.detail["series_name"] for f in seams if f.severity is Severity.WARN}
    # 원가율 +6.6%p 와 영업마진(52.5→47.0, §2 OPM ⚠️) 둘 다 접합부 이탈
    assert "매출원가율" in warn_names
    assert "영업마진(감가비 반영 전)" in warn_names
    # 판관비율(25.3→24.1)은 연속
    sga = next(f for f in seams if f.detail["series_name"] == "판관비율")
    assert sga.severity is Severity.PASS
    # ΔNWC=0 첫해 → 성장-운전자본 WARN
    nwc = _by_rule(rep.findings, "nwc_growth_consistency")[0]
    assert nwc.severity is Severity.WARN


def test_analytical_review_segments():
    hist = FinancialHistory(
        years=[2021, 2023], revenue=[100.0, 99.2], cogs=[33.257, 22.307],
        sga=[37.5, 25.1], segments=_SEG_HIST)
    fc_segs = [
        SegmentSeries("제품", revenue=[98.0, 105.0], cogs=[28.224, 25.515]),
        SegmentSeries("상품", revenue=[2.0, 2.0], cogs=[0.822, 0.884]),  # 41.1%→44.2%
    ]
    rep = analytical_review(hist, None, forecast_segments=fc_segs)
    assert _by_rule(rep.findings, "mix_reconciliation")[0].severity is Severity.PASS
    seg_warns = {f.detail["series_name"] for f in _by_rule(rep.findings, "ratio_seam")
                 if f.severity is Severity.WARN}
    assert "부문 원가율(상품)" in seg_warns      # E-10
    assert "부문 원가율(제품)" in seg_warns      # E-6·J-1 (원가율 21.3→28.8 급등)


def test_analytical_review_sparse_history():
    # 있는 것만 검사: 매출만 있는 실적 → seam 생략, NWC 정합만 가동
    hist = FinancialHistory(years=[2023], revenue=[REV_ACT[-1]])
    rep = analytical_review(hist, _viol_like_input())
    assert not _by_rule(rep.findings, "ratio_seam")
    assert _by_rule(rep.findings, "nwc_growth_consistency")


def test_audit_dcf_history_wiring_and_backcompat():
    inp = _viol_like_input()
    res = run(inp)
    with_hist = audit_dcf(inp, res, history=_viol_history())
    assert any(f.rule == "ratio_seam" and f.severity is Severity.WARN
               for f in with_hist.findings)
    # 하위호환: history 미지정이면 L3 findings 자체가 없다
    without = audit_dcf(inp, res)
    assert not _by_rule(without.findings, "ratio_seam")
    assert not _by_rule(without.findings, "nwc_growth_consistency")


def test_history_length_validation():
    with pytest.raises(ValueError):
        FinancialHistory(years=[2022, 2023], revenue=[1.0])
