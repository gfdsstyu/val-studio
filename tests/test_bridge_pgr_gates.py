"""R2(PGR 출처 앵커링) · R3(교차방법 지분브리지 일치) 게이트 테스트.

근거: docs/reference/모델러스_통합모델_5.4.md §4 D3·D6, §5 R2·R3.
실측 결함을 그대로 재현해 게이트가 잡는지 확인한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core.checks import (  # noqa: E402
    check_bridge_consistency,
    check_pgr_provenance,
)
from ingest.macro_client import (  # noqa: E402
    CPI_INFLATION,
    MacroObservation,
    MacroSeries,
    suggest_pgr_from_inflation,
)


# ── R2: PGR 출처 ────────────────────────────────────────────────────────────
def test_pgr_without_source_warns():
    """무근거 하드코드 PGR = WARN (모델러스 D6 의 WACC 함정 재발 방지)."""
    f = check_pgr_provenance(0.0162, None)
    assert f.severity.name == "WARN"
    assert "출처 미기재" in f.message


def test_pgr_derived_requires_basis():
    """derived 인데 산출식 없으면 재현 불가 → WARN."""
    assert check_pgr_provenance(0.0162, "derived").severity.name == "WARN"
    ok = check_pgr_provenance(0.0162, "derived", basis="AVERAGE(cpi, 2013~2022)")
    assert ok.severity.name == "PASS"


def test_pgr_unknown_source_kind_warns():
    assert check_pgr_provenance(0.0162, "그냥감").severity.name == "WARN"


def _cpi_series(values, unit="%"):
    """⚠️ value 는 **비율**로 넣는다 — 이 모듈 규약(parse_paste_table 이 %→비율 변환하고
    unit 은 출처 라벨로만 남긴다). 픽스처를 %스케일로 만들면 실제 파서와 어긋난다."""
    obs = tuple(
        MacroObservation(CPI_INFLATION, f"{2013 + i}", v, vintage=f"{2014 + i}-03-31",
                         source="ECOS")
        for i, v in enumerate(values)
    )
    return MacroSeries(CPI_INFLATION, unit, obs)


def test_suggest_pgr_reproduces_modellers_anchor():
    """모델러스 F33 재현: 10년 물가 평균 → PGR.

    원본은 rInflation 10개년 평균 /100 = 1.62%. 동일 평균이 나오는 계열을 넣어
    단위환산(%→비율)과 평균 로직을 검증한다.
    """
    vals = [0.013, 0.013, 0.007, 0.010, 0.019, 0.015, 0.004, 0.005, 0.025, 0.051]  # 평균 1.62%
    s = _cpi_series(vals)
    # 기준일은 마지막 관측 vintage(2023-03-31) 이후여야 10개가 전부 usable
    sug = suggest_pgr_from_inflation(s, "2023-12-31", years=10)
    assert abs(sug.value - 0.0162) < 1e-12, sug.value
    assert sug.n_observations == 10
    assert "AVERAGE" in sug.basis
    assert all(f.severity.name == "PASS" for f in sug.findings)
    # 앵커 결과를 그대로 provenance 로 넘기면 R2 게이트 통과
    assert check_pgr_provenance(sug.value, "derived", basis=sug.basis).severity.name == "PASS"


def test_suggest_pgr_respects_vintage_guard():
    """평가기준일 이후 vintage 는 제외(look-ahead 방지)."""
    s = _cpi_series([0.01, 0.02, 0.03])       # vintage 2014·2015·2016-03-31
    sug = suggest_pgr_from_inflation(s, "2015-06-30", years=10)
    assert sug.n_observations == 2, sug.periods    # 2016 vintage 는 배제
    assert abs(sug.value - 0.015) < 1e-12


def test_suggest_pgr_no_data_fails_instead_of_guessing():
    """관측치 없으면 임의 기본값을 지어내지 않고 FAIL."""
    sug = suggest_pgr_from_inflation(_cpi_series([]), "2023-01-01")
    assert sug.value == 0.0
    assert any(f.severity.name == "FAIL" for f in sug.findings)


def test_suggest_pgr_unit_label_does_not_rescale():
    """unit 라벨('%' vs 'ratio')이 값을 다시 나누면 안 된다 — value 는 항상 비율.

    회귀: 초기 구현이 unit=='%' 를 보고 /100 해서 라이브에서 1.62% → 0.0162% 로
    100배 축소됐다(단위 테스트는 잘못된 픽스처라 통과).
    """
    for unit in ("%", "ratio"):
        s = _cpi_series([0.02, 0.02], unit=unit)
        assert abs(suggest_pgr_from_inflation(s, "2023-01-01").value - 0.02) < 1e-12, unit


def test_suggest_pgr_percent_scale_input_warns():
    """% 스케일로 잘못 들어오면 조용히 100배 틀리지 않고 WARN 한다."""
    s = _cpi_series([1.3, 1.9, 2.5])          # 비율이어야 하는데 % 스케일
    sug = suggest_pgr_from_inflation(s, "2023-12-31")
    assert any("비현실적" in f.message for f in sug.findings), sug.findings


# ── R3: 교차방법 브리지 ──────────────────────────────────────────────────────
def test_bridge_consistent_passes():
    b = {"cash": 133_510.0, "interest_bearing_debt": 101_374.0,
         "non_controlling_interest": 58_654.0}
    assert check_bridge_consistency(b, dict(b)).severity.name == "PASS"


def test_bridge_reproduces_modellers_d3_defect():
    """모델러스 D3 실측 재현: 단기금융자산 포함여부 + NCI 처리 차이.

    DCF 는 단기금융자산 392,202 을 이자부자산에 넣고 NCI 를 0 으로 두었고,
    Trading 은 vendor CASH_LTM(단기금융자산 제외)에 NCI 58,654 를 가산했다.
    """
    dcf = {"cash": 131_785.0, "short_term_investments": 392_202.0,
           "interest_bearing_debt": 97_796.0, "non_controlling_interest": 0.0}
    rel = {"cash": 133_510.0, "short_term_investments": 0.0,
           "interest_bearing_debt": 101_374.0, "non_controlling_interest": 58_654.0}
    f = check_bridge_consistency(dcf, rel)
    assert f.severity.name == "WARN"
    m = f.detail["mismatches"]
    # 세 항목 모두 잡혀야 한다(단기금융자산이 가장 큰 델타)
    assert "short_term_investments" in m
    assert "non_controlling_interest" in m
    assert abs(m["short_term_investments"]["delta"] - 392_202.0) < 1e-9


def test_bridge_missing_key_is_not_treated_as_zero():
    """한쪽에만 있는 키 = 누락(0 으로 간주 금지 — 0 과 미정의는 다르다)."""
    f = check_bridge_consistency({"cash": 100.0, "preferred_stock": 0.0},
                                 {"cash": 100.0})
    assert f.severity.name == "WARN"
    assert f.detail["missing_in"]["preferred_stock"] == "relative"


def test_bridge_tolerance_absorbs_rounding():
    f = check_bridge_consistency({"cash": 1_000_000.0}, {"cash": 1_000_050.0})
    assert f.severity.name == "PASS"      # 0.005% < 1% 허용


# ── R15: 터미널 할인기간 컨벤션 ──────────────────────────────────────────────
def _spine(**kw):
    from calc_core.models import DcfSpineInput
    base = dict(
        wacc=0.10, terminal_growth=0.02,
        revenue=[1000.0, 1100.0, 1200.0], cogs=[600.0, 660.0, 720.0],
        sga=[200.0, 220.0, 240.0], dep_amort=[50.0, 55.0, 60.0],
        capex=[50.0, 55.0, 60.0], delta_nwc_cash_adj=[0.0, 0.0, 0.0],
        non_operating_assets=0.0, net_debt=0.0, shares_outstanding=1_000_000,
    )
    base.update(kw)
    return DcfSpineInput(**base)


def test_terminal_period_implicit_warns_with_impact():
    """미선언이면 WARN 하되 대안 컨벤션의 주당 영향을 함께 제시(행동 가능한 경고)."""
    from calc_core.checks import check_terminal_discount_convention
    from calc_core.dcf import run
    inp = _spine()
    f = check_terminal_discount_convention(inp, run(inp))
    assert f.severity.name == "WARN"
    assert f.detail["explicit"] is False
    assert abs(f.detail["terminal_discount_period"] - 2.5) < 1e-6   # mid-year 기본
    assert f.detail["alternative_period"] == 3.0            # 기말 대안
    # 기말 할인은 한 반기 더 할인 → 주당가치 하락. 값도 해석적으로 고정한다
    # (PV(TV) 만 1/(1+w)^0.5 배로 줄고 명시구간 PV 는 불변).
    res = run(inp)
    expected_alt = res.pv_explicit_sum + res.terminal_value_pv / (1.0 + inp.wacc) ** 0.5
    expected_delta = expected_alt / res.enterprise_value - 1.0     # 브리지 0 이라 EV 비 = 주당 비
    assert f.detail["delta_pct"] < 0
    assert abs(f.detail["delta_pct"] - expected_delta) < 1e-9, (
        f.detail["delta_pct"], expected_delta)


def test_terminal_period_explicit_passes():
    from calc_core.checks import check_terminal_discount_convention
    from calc_core.dcf import run
    inp = _spine(terminal_discount_period=3.0)
    f = check_terminal_discount_convention(inp, run(inp))
    assert f.severity.name == "PASS"
    assert f.detail["explicit"] is True
    assert f.detail["alternative_period"] == 2.5            # 반대편 제시


def test_terminal_period_impact_matches_manual_ratio():
    """정량치 검증: 대안 주당 / 현재 주당 이 PV 계수비와 정합."""
    from calc_core.checks import check_terminal_discount_convention
    from calc_core.dcf import run
    inp = _spine()
    res = run(inp)
    f = check_terminal_discount_convention(inp, res)
    pv_tv_alt = res.terminal_value / (1.0 + inp.wacc) ** 3.0
    ev_alt = res.pv_explicit_sum + pv_tv_alt
    expected = ev_alt / inp.shares_outstanding * 1_000_000
    assert abs(f.detail["per_share_alternative"] - expected) < 1e-6


def test_terminal_period_alternative_accounts_for_fade():
    """회귀: 페이드가 있으면 대안 기간은 **확장된 시계**(명시+페이드) 기준이어야 한다.

    inp.n_years() 는 페이드 확장 **전** 길이라 그대로 쓰면 명시 3 + 페이드 7 인 모델에서
    대안이 t=3 으로 잡히는 버그가 났었다(실측 '대안 t=5 이면 +23.6%' 오표기).
    """
    from calc_core.checks import check_terminal_discount_convention
    from calc_core.dcf import run
    inp = _spine(fade_years=7)                 # 명시 3 + 페이드 7 = 시계 10년
    res = run(inp)
    assert len(res.pv_fcff) == 10
    f = check_terminal_discount_convention(inp, res)
    assert abs(f.detail["terminal_discount_period"] - 9.5) < 1e-9, f.detail
    assert f.detail["alternative_period"] == 10.0, f.detail
    # 기말 할인이 반기 더 할인 → 대안 주당가치는 낮아야 한다
    assert f.detail["delta_pct"] < 0


# ── R3 실배선: 교차방법 브리지(순포지션 + 주식수) ────────────────────────────
def test_net_position_formula():
    """순포지션 = 순차입부채 − 비영업자산 + 비지배지분 (EV 에서 빼는 총액)."""
    from calc_core.checks import bridge_net_position
    assert bridge_net_position({"net_debt": 100.0}) == 100.0
    assert bridge_net_position({"net_debt": 100.0, "non_operating_assets": 30.0}) == 70.0
    assert bridge_net_position(
        {"net_debt": 100.0, "non_operating_assets": 30.0,
         "non_controlling_interest": 20.0}) == 90.0
    assert bridge_net_position({}) == 0.0


def test_scalar_relative_bridge_no_false_positive():
    """상대가치가 net_debt 스칼라로만 선언해도, 순포지션이 같으면 PASS(오탐 방지).

    DCF: 순차입 100 − 비영업 30 = 순포지션 70
    상대: net_debt 70 (비영업자산을 이미 접어 넣은 실무 관행)
    """
    from calc_core.checks import check_cross_method_bridge
    fs = check_cross_method_bridge(
        {"net_debt": 100.0, "non_operating_assets": 30.0},
        {"net_debt": 70.0})
    bridge = next(f for f in fs if f.rule == "cross_method_bridge")
    assert bridge.severity.name == "PASS", bridge.message
    # 항목 미선언 → 항목별 엄격 대조는 돌지 않는다(오탐 방지)
    assert not any(f.rule == "bridge_consistency" for f in fs)


def test_cross_method_reproduces_modellers_d3():
    """모델러스 D3: DCF 순현금 426,191 vs Trading 순부채 26,518 → WARN."""
    from calc_core.checks import check_cross_method_bridge
    fs = check_cross_method_bridge(
        {"net_debt": 97_796.0, "non_operating_assets": 523_987.0,
         "non_controlling_interest": 0.0},
        {"net_debt": 26_518.0})
    bridge = next(f for f in fs if f.rule == "cross_method_bridge")
    assert bridge.severity.name == "WARN"
    assert bridge.detail["dcf_net_position"] == -426_191.0     # 순현금
    assert bridge.detail["relative_net_position"] == 26_518.0  # 순부채
    assert "무의미" in bridge.message


def test_declared_components_trigger_strict_compare():
    """상대가치가 항목을 명시 선언하면 항목별 엄격 대조가 추가로 돈다."""
    from calc_core.checks import check_cross_method_bridge
    fs = check_cross_method_bridge(
        {"net_debt": 100.0, "non_operating_assets": 30.0, "non_controlling_interest": 0.0},
        {"net_debt": 100.0, "non_operating_assets": 30.0, "non_controlling_interest": 20.0})
    assert any(f.rule == "bridge_consistency" for f in fs)
    # NCI 20 차이 → 순포지션도 어긋남
    assert next(f for f in fs if f.rule == "cross_method_bridge").severity.name == "WARN"


def test_shares_mismatch_flagged():
    """브리지가 같아도 주식수가 다르면 주당가치가 어긋난다(자기주식·희석)."""
    from calc_core.checks import check_cross_method_bridge
    fs = check_cross_method_bridge(
        {"net_debt": 100.0, "shares_outstanding": 10_000_000},
        {"net_debt": 100.0, "shares_outstanding": 9_500_000})
    sh = next(f for f in fs if f.rule == "cross_method_shares")
    assert sh.severity.name == "WARN"
    assert "자기주식" in sh.message


def test_shares_absent_is_skipped():
    """한쪽이라도 주식수가 없으면 판정하지 않는다(추측 금지)."""
    from calc_core.checks import check_cross_method_bridge
    fs = check_cross_method_bridge({"net_debt": 100.0}, {"net_debt": 100.0})
    assert not any(f.rule == "cross_method_shares" for f in fs)


def test_d7_share_count_discrepancy_reproduced():
    """D7 실측: DCF 발행주식수 12,385,455 vs Trading 시총/주가 역산 11,214,141.

    자기주식 약 1.17M주(9.5%) 차이 → 주당가치 10.4% 괴리. 게이트가 문서 초안에
    없던 이 결함을 사후 발견했다.
    """
    from calc_core.checks import check_cross_method_bridge
    fs = check_cross_method_bridge(
        {"net_debt": 97_796.0, "non_operating_assets": 523_987.0,
         "shares_outstanding": 12_385_455},
        {"net_debt": 26_518.0, "shares_outstanding": 11_214_141})
    rules = {f.rule: f for f in fs}
    assert rules["cross_method_bridge"].severity.name == "WARN"
    assert rules["cross_method_shares"].severity.name == "WARN"
    # 두 오차는 방향이 반대라 서로를 가릴 수 있다 — 별개 finding 으로 분리 보고되어야
    assert rules["cross_method_shares"].detail["dcf_shares"] == 12_385_455
    assert rules["cross_method_shares"].detail["relative_shares"] == 11_214_141


# ══ 코드리뷰 회귀 (2026-07-20 독립검토 지적사항) ══════════════════════════════
def _fade_base(**kw):
    from calc_core.models import DcfSpineInput
    base = dict(wacc=0.10, terminal_growth=0.02,
                revenue=[1000., 1150., 1300., 1450., 1600.],
                cogs=[600., 690., 780., 870., 960.],
                sga=[200., 230., 260., 290., 320.],
                dep_amort=[50., 57., 65., 72., 80.],
                capex=[60., 69., 78., 87., 96.],
                delta_nwc_cash_adj=[-20., -23., -26., -29., -32.],
                non_operating_assets=100., net_debt=200., shares_outstanding=1_000_000)
    base.update(kw)
    return DcfSpineInput(**base)


def test_terminal_period_stale_declaration_caught():
    """페이드를 켜기 전 시계로 선언한 terminal_discount_period 를 잡는다.

    실측 결함: 명시 5년 기준 t=4.5 선언 + 페이드 5년 → TV 를 t=4.5 로 할인해
    **주당 +36% 과대**인데 게이트가 PASS 를 줬다(explicit 분기가 시계 검사를 우회).
    """
    from calc_core.checks import check_terminal_discount_convention
    from calc_core.dcf import run
    stale = _fade_base(fade_years=5, terminal_discount_period=4.5)
    ok = _fade_base(fade_years=5, terminal_discount_period=9.5)
    r_stale, r_ok = run(stale), run(ok)
    assert r_stale.per_share / r_ok.per_share - 1 > 0.30          # 실제로 크게 과대
    f = check_terminal_discount_convention(stale, r_stale)
    assert f.severity.name == "WARN", f.message
    assert f.detail["horizon"] == 10 and f.detail["consistent_with_horizon"] is False
    # 정합 선언은 PASS
    assert check_terminal_discount_convention(ok, r_ok).severity.name == "PASS"


def test_terminal_period_wacc_le_minus_one_returns_finding_not_exception():
    """검증 게이트는 잘못된 입력에 **예외가 아니라 finding** 을 내야 한다.

    WACC=-1 → 0 나눗셈, WACC<-1 → (음수)^소수 = complex. 예외면 audit 전체가 중단된다.
    """
    from calc_core.checks import check_terminal_discount_convention
    from calc_core.dcf import run
    res = run(_fade_base())
    for w in (-1.0, -1.5):
        f = check_terminal_discount_convention(_fade_base(wacc=w), res)
        assert f.severity.name == "FAIL", (w, f.message)


def test_diagnose_gap_uses_expanded_horizon_and_per_share_scale():
    """가설값이 실제 per_share 와 같은 스케일·시계여야 매칭이 가능하다.

    선행 결함(8fbd8b8): ps() 가 ×1e6 환산과 NCI 차감을 빠뜨려 모든 가설이 100만배
    작았다 → 어떤 가설도 영원히 매칭 불가. 여기에 페이드 미확장 시계까지 겹쳤다.
    """
    from calc_core.checks import diagnose_dcf_gap
    from calc_core.dcf import run
    inp = _fade_base(fade_years=5)
    res = run(inp)
    f = diagnose_dcf_gap(inp, res, claimed_per_share=res.per_share)
    assert f.severity.name == "PASS"                      # 자기 자신은 일치
    h = f.detail["hypotheses"]
    # 모든 가설이 per_share 와 같은 자릿수(0.1~10배)여야 한다
    for k, v in h.items():
        assert 0.1 < v / res.per_share < 10.0, (k, v, res.per_share)
    # tv_missing 가설 = 명시구간만 → 실제보다 작아야
    assert h["tv_missing"] < res.per_share


def test_from_last_fcff_not_credited_when_underinvesting():
    """마지막 해 CAPEX < D&A 면 재투자 부족을 영구 승계 → 재투자 반영으로 인정 금지.

    실측: 무조건 인정하면 기본(WARN) 대비 EV 가 23% 큰 결과에 PASS 가 붙어 게이트
    방향이 뒤집힌다.
    """
    from calc_core.checks import audit_dcf
    from calc_core.dcf import run
    kw = dict(wacc=0.10, terminal_growth=0.04, revenue=[100., 110., 120.],
              cogs=[50., 55., 60.], sga=[20., 22., 24.], dep_amort=[10., 10., 10.],
              delta_nwc_cash_adj=[0., 0., 0.], non_operating_assets=0., net_debt=0.,
              shares_outstanding=1000)
    from calc_core.models import DcfSpineInput
    under = DcfSpineInput(**kw, capex=[10., 10., 1.], terminal_from_last_fcff=True)
    rep = audit_dcf(under, run(under))
    rules = {f.rule: f.severity.name for f in rep.findings}
    assert rules["terminal_reinvestment"] == "WARN"          # 승격되지 않아야
    assert rules["terminal_from_last_fcff"] == "WARN"        # 별도 경고도 나와야

    healthy = DcfSpineInput(**kw, capex=[10., 10., 15.], terminal_from_last_fcff=True)
    rep2 = audit_dcf(healthy, run(healthy))
    rules2 = {f.rule: f.severity.name for f in rep2.findings}
    assert rules2["terminal_reinvestment"] == "PASS"         # 충분하면 인정
    assert "terminal_from_last_fcff" not in rules2


def test_shares_zero_is_not_silently_skipped():
    """`if ds and rs` truthiness 로 쓰면 0 주가 조용히 통과한다 — 가장 흔한 불량 입력."""
    from calc_core.checks import check_cross_method_bridge
    fs = check_cross_method_bridge({"net_debt": 0.0, "shares_outstanding": 0},
                                   {"net_debt": 0.0, "shares_outstanding": 5000})
    sh = [f for f in fs if f.rule == "cross_method_shares"]
    assert sh and sh[0].severity.name == "WARN", [f.rule for f in fs]
    # None(미선언)은 판정보류 — 추측 금지
    fs2 = check_cross_method_bridge({"net_debt": 0.0}, {"net_debt": 0.0})
    assert not any(f.rule == "cross_method_shares" for f in fs2)


def test_suggest_pgr_rejects_nonpositive_years():
    """파이썬 슬라이싱 함정: lst[-0:] 는 빈 리스트가 아니라 **전체 리스트**.

    years=0 을 흘리면 요청하지 않은 전체 평균이 나오면서 basis 는 그럴듯하게 찍히고
    finding 은 PASS — 감사추적이 거짓이 된다.
    """
    s = _cpi_series([0.01] * 12)
    for bad in (0, -3):
        try:
            suggest_pgr_from_inflation(s, "2030-01-01", years=bad)
            raise AssertionError(f"years={bad} 가 통과됨")
        except ValueError:
            pass
    assert suggest_pgr_from_inflation(s, "2030-01-01", years=10).n_observations == 10


def test_fade_years_invalid_rejected():
    """음수는 조용히 '페이드 없음'으로 흡수되면 안 되고, 실수는 raw TypeError 금지."""
    from calc_core.dcf import run
    for bad in (-3, 3.0, True):
        try:
            run(_fade_base(fade_years=bad))
            raise AssertionError(f"fade_years={bad!r} 가 통과됨")
        except ValueError:
            pass
    # None/0 은 정상(페이드 없음)
    assert len(run(_fade_base(fade_years=0)).fcff) == 5


# ══ 코드리뷰 회귀 (2026-07-20 독립검토 지적사항) ══════════════════════════════
def _fade_base(**kw):
    from calc_core.models import DcfSpineInput
    base = dict(wacc=0.10, terminal_growth=0.02,
                revenue=[1000., 1150., 1300., 1450., 1600.],
                cogs=[600., 690., 780., 870., 960.],
                sga=[200., 230., 260., 290., 320.],
                dep_amort=[50., 57., 65., 72., 80.],
                capex=[60., 69., 78., 87., 96.],
                delta_nwc_cash_adj=[-20., -23., -26., -29., -32.],
                non_operating_assets=100., net_debt=200., shares_outstanding=1_000_000)
    base.update(kw)
    return DcfSpineInput(**base)


def test_terminal_period_stale_declaration_caught():
    """페이드를 켜기 전 시계로 선언한 terminal_discount_period 를 잡는다.

    실측 결함: 명시 5년 기준 t=4.5 선언 + 페이드 5년 → TV 를 t=4.5 로 할인해
    **주당 +36% 과대**인데 게이트가 PASS 를 줬다(explicit 분기가 시계 검사를 우회).
    """
    from calc_core.checks import check_terminal_discount_convention
    from calc_core.dcf import run
    stale = _fade_base(fade_years=5, terminal_discount_period=4.5)
    ok = _fade_base(fade_years=5, terminal_discount_period=9.5)
    r_stale, r_ok = run(stale), run(ok)
    assert r_stale.per_share / r_ok.per_share - 1 > 0.30          # 실제로 크게 과대
    f = check_terminal_discount_convention(stale, r_stale)
    assert f.severity.name == "WARN", f.message
    assert f.detail["horizon"] == 10 and f.detail["consistent_with_horizon"] is False
    # 정합 선언은 PASS
    assert check_terminal_discount_convention(ok, r_ok).severity.name == "PASS"


def test_terminal_period_wacc_le_minus_one_returns_finding_not_exception():
    """검증 게이트는 잘못된 입력에 **예외가 아니라 finding** 을 내야 한다.

    WACC=-1 → 0 나눗셈, WACC<-1 → (음수)^소수 = complex. 예외면 audit 전체가 중단된다.
    """
    from calc_core.checks import check_terminal_discount_convention
    from calc_core.dcf import run
    res = run(_fade_base())
    for w in (-1.0, -1.5):
        f = check_terminal_discount_convention(_fade_base(wacc=w), res)
        assert f.severity.name == "FAIL", (w, f.message)


def test_diagnose_gap_uses_expanded_horizon_and_per_share_scale():
    """가설값이 실제 per_share 와 같은 스케일·시계여야 매칭이 가능하다.

    선행 결함(8fbd8b8): ps() 가 ×1e6 환산과 NCI 차감을 빠뜨려 모든 가설이 100만배
    작았다 → 어떤 가설도 영원히 매칭 불가. 여기에 페이드 미확장 시계까지 겹쳤다.
    """
    from calc_core.checks import diagnose_dcf_gap
    from calc_core.dcf import run
    inp = _fade_base(fade_years=5)
    res = run(inp)
    f = diagnose_dcf_gap(inp, res, claimed_per_share=res.per_share)
    assert f.severity.name == "PASS"                      # 자기 자신은 일치
    h = f.detail["hypotheses"]
    # 모든 가설이 per_share 와 같은 자릿수(0.1~10배)여야 한다
    for k, v in h.items():
        assert 0.1 < v / res.per_share < 10.0, (k, v, res.per_share)
    # tv_missing 가설 = 명시구간만 → 실제보다 작아야
    assert h["tv_missing"] < res.per_share


def test_from_last_fcff_not_credited_when_underinvesting():
    """마지막 해 CAPEX < D&A 면 재투자 부족을 영구 승계 → 재투자 반영으로 인정 금지.

    실측: 무조건 인정하면 기본(WARN) 대비 EV 가 23% 큰 결과에 PASS 가 붙어 게이트
    방향이 뒤집힌다.
    """
    from calc_core.checks import audit_dcf
    from calc_core.dcf import run
    kw = dict(wacc=0.10, terminal_growth=0.04, revenue=[100., 110., 120.],
              cogs=[50., 55., 60.], sga=[20., 22., 24.], dep_amort=[10., 10., 10.],
              delta_nwc_cash_adj=[0., 0., 0.], non_operating_assets=0., net_debt=0.,
              shares_outstanding=1000)
    from calc_core.models import DcfSpineInput
    under = DcfSpineInput(**kw, capex=[10., 10., 1.], terminal_from_last_fcff=True)
    rep = audit_dcf(under, run(under))
    rules = {f.rule: f.severity.name for f in rep.findings}
    assert rules["terminal_reinvestment"] == "WARN"          # 승격되지 않아야
    assert rules["terminal_from_last_fcff"] == "WARN"        # 별도 경고도 나와야

    healthy = DcfSpineInput(**kw, capex=[10., 10., 15.], terminal_from_last_fcff=True)
    rep2 = audit_dcf(healthy, run(healthy))
    rules2 = {f.rule: f.severity.name for f in rep2.findings}
    assert rules2["terminal_reinvestment"] == "PASS"         # 충분하면 인정
    assert "terminal_from_last_fcff" not in rules2


def test_shares_zero_is_not_silently_skipped():
    """`if ds and rs` truthiness 로 쓰면 0 주가 조용히 통과한다 — 가장 흔한 불량 입력."""
    from calc_core.checks import check_cross_method_bridge
    fs = check_cross_method_bridge({"net_debt": 0.0, "shares_outstanding": 0},
                                   {"net_debt": 0.0, "shares_outstanding": 5000})
    sh = [f for f in fs if f.rule == "cross_method_shares"]
    assert sh and sh[0].severity.name == "WARN", [f.rule for f in fs]
    # None(미선언)은 판정보류 — 추측 금지
    fs2 = check_cross_method_bridge({"net_debt": 0.0}, {"net_debt": 0.0})
    assert not any(f.rule == "cross_method_shares" for f in fs2)


def test_suggest_pgr_rejects_nonpositive_years():
    """파이썬 슬라이싱 함정: lst[-0:] 는 빈 리스트가 아니라 **전체 리스트**.

    years=0 을 흘리면 요청하지 않은 전체 평균이 나오면서 basis 는 그럴듯하게 찍히고
    finding 은 PASS — 감사추적이 거짓이 된다.
    """
    s = _cpi_series([0.01] * 12)
    for bad in (0, -3):
        try:
            suggest_pgr_from_inflation(s, "2030-01-01", years=bad)
            raise AssertionError(f"years={bad} 가 통과됨")
        except ValueError:
            pass
    assert suggest_pgr_from_inflation(s, "2030-01-01", years=10).n_observations == 10


def test_fade_years_invalid_rejected():
    """음수는 조용히 '페이드 없음'으로 흡수되면 안 되고, 실수는 raw TypeError 금지."""
    from calc_core.dcf import run
    for bad in (-3, 3.0, True):
        try:
            run(_fade_base(fade_years=bad))
            raise AssertionError(f"fade_years={bad!r} 가 통과됨")
        except ValueError:
            pass
    # None/0 은 정상(페이드 없음)
    assert len(run(_fade_base(fade_years=0)).fcff) == 5


def test_bridge_unit_contract_prevents_structural_false_positive():
    """DCF(백만원)와 상대가치(원)를 단위 선언 없이 비교하면 무조건 오탐이 난다.

    실측 근거: multiples.py 의 EV/EBITDA 경로는 `(EV−net_debt)/shares` 에 ×1e6 환산이
    없어 **원**을 전제하는데, DCF 스파인은 백만원이다(per_share 에 ×1e6).
    경제적으로 동일한 순부채 100억을 각 시트 규약대로 넣으면 일치해야 한다.
    """
    from calc_core.checks import bridge_unit_scale, check_cross_method_bridge
    dcf = {"net_debt": 10_000.0, "unit": "KRW_mn"}                 # 100억 = 10,000 백만원
    rel = {"net_debt": 10_000_000_000.0, "unit": "KRW"}            # 100억 = 1e10 원
    f = next(x for x in check_cross_method_bridge(dcf, rel)
             if x.rule == "cross_method_bridge")
    assert f.severity.name == "PASS", f.message
    assert f.detail["dcf_unit"] == "KRW_mn" and f.detail["relative_unit"] == "KRW"
    # 단위 미선언은 백만원(엔진 기본)으로 본다 → 같은 숫자면 일치
    assert bridge_unit_scale(None) == 1.0
    try:
        bridge_unit_scale("USD")
        raise AssertionError("알 수 없는 단위가 통과됨")
    except ValueError:
        pass


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("R2·R3 게이트 통과")
