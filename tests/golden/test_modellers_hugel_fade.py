"""골든 테스트 (R1 페이드) — calc_core 3단 DCF == 모델러스 통합모델 5.4 (Hugel).

**3번째 독립 레퍼런스 재현.** 비올(1차)·클래시스(2차)는 한국 실무 평가서 계열이고,
이것은 IB 트레이닝 표준모델(The Modellers `5.4(COMPLETED).xlsx`, Hugel 145020.KQ)이다.
핵심 검증 대상은 **페이드 구간**(명시 5년 + 페이드 5년 + Gordon) — 우리 엔진에 없던
구조를 이식한 뒤 원본 주당가치 144,000원이 재현되는지 본다.

지식 문서: docs/reference/모델러스_통합모델_5.4.md §2.3, §3.

원본 단위는 KRW B(십억)이고 우리 엔진은 백만원이므로 **×1000** 으로 환산해 투입한다
(주식수는 실주식수 12,385,455주 → per_share 가 원 단위로 떨어진다).

원본은 EBIT 를 매출×OPM 으로 직접 잡으므로 cogs=0, sga=매출−EBIT 로 넣어
`EBIT = 매출 − cogs − sga` 항등식을 만족시킨다(스파인 계약 유지).

의존 없이 stdlib 로 실행: `python tests/golden/test_modellers_hugel_fade.py`
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core import DcfSpineInput, run  # noqa: E402
from calc_core.dcf import resolve_fade_growth  # noqa: E402

B = 1000.0          # KRW B → 백만원
REL_TOL = 1e-6      # 원본 캐시값 유효자릿수 한계

# ── 원본 DCF 시트 명시추정 2023E~2027E (열 O~S), 단위 KRW B ──────────────────
REVENUE = [317.02377041557327, 357.27508738340475, 403.1410812741238,
           455.43920025515956, 515.1080961754689]
EBIT = [126.00104583279465, 145.32060815233305, 164.9877965012101,
        188.07642543513606, 217.4057988396623]
TAX = [32.570164225027526, 37.213844186460975, 41.719966059352465,
       47.28361298553076, 54.506707751004576]
DEP = [14.102049814839491, 15.452191265015173, 22.885425214368027,
       29.88006605297354, 30.693575707112764]
AMORT = [3.804431017134523, 4.211232485268884, 4.6711335532985565,
         5.191610426974835, 5.781232624440801]
CAPEX_PPE = [25.63694130029326, 78.95779431173246, 82.64392166119538,
             36.830260480115925, 41.655538976289954]
CAPEX_INTAN = [25.198462871844946, 28.397817023829187, 32.04345073331577,
               36.200338425628146, 40.943088335141034]
DELTA_NWC = [9.963502939771132, 2.9263837378578614, 3.32468998686862,
             3.7796545547600147, 4.29941533291958]

WACC = 0.10                     # DCF!F34 (원본 유일 하드코드)
PGR = 0.0162                    # DCF!F33 = AVERAGE(rInflation 10년)/100
FADE_YEARS = 5                  # 2028E~2032E

# ── 원본 산출(DCF!F37~F45, X26) ─────────────────────────────────────────────
EXP_FADE_GROWTH = 0.07360698302526425   # F30 = AVERAGE(S15, F33)
EXP_LAST_FCFF = 160.4301346690072       # X26 (2032E FCFF)
EXP_TERMINAL_VALUE = 1945.4546879551922  # F40
EXP_PV_TV = 786.6664180540264           # F39
EXP_PV_EXPLICIT = 574.108868847236      # F38 = SUM(O27:X27)
EXP_EV = 1360.7752869012625             # F37
EXP_EQUITY = 1786.9666348812625         # F41
EXP_PER_SHARE_ROUNDED = 144000          # F44 = ROUND(F41/F45*10^3, -3)

IBD = 97.796128165                      # F42 Model!N146 이자부부채
IB_ASSETS = 523.987476145               # F43 Model!N163 현금+단기금융자산
SHARES = 12_385_455                     # F45 = rFS!K229 (실주식수)


def _build() -> DcfSpineInput:
    return DcfSpineInput(
        wacc=WACC,
        terminal_growth=PGR,
        revenue=[r * B for r in REVENUE],
        cogs=[0.0] * len(REVENUE),
        # EBIT = 매출 − 0 − sga  ⇒  sga = 매출 − EBIT
        sga=[(REVENUE[i] - EBIT[i]) * B for i in range(len(REVENUE))],
        dep_amort=[(DEP[i] + AMORT[i]) * B for i in range(len(REVENUE))],
        capex=[(CAPEX_PPE[i] + CAPEX_INTAN[i]) * B for i in range(len(REVENUE))],
        # 원본 FCFF = NOPLAT + D&A − CAPEX − ΔNWC, 우리 규약은 (+)현금조정 ⇒ 부호 반전
        delta_nwc_cash_adj=[-d * B for d in DELTA_NWC],
        tax_override=[t * B for t in TAX],
        non_operating_assets=IB_ASSETS * B,
        net_debt=IBD * B,
        shares_outstanding=SHARES,
        fade_years=FADE_YEARS,
        terminal_from_last_fcff=True,   # 원본 TV = X26×(1+g)/(WACC−g)
    )


def _close(a: float, b: float, tol: float = REL_TOL) -> bool:
    return math.isclose(a, b, rel_tol=tol)


def test_fade_growth_matches_source():
    """페이드 성장률 = AVERAGE(마지막 명시 성장률 13.101%, PGR 1.62%) = 7.361%."""
    gf = resolve_fade_growth(_build(), PGR)
    assert _close(gf, EXP_FADE_GROWTH), f"{gf} != {EXP_FADE_GROWTH}"


def test_horizon_is_ten_years():
    """명시 5 + 페이드 5 = 10년이 PV 대상, 할인기간은 0.5…9.5 (mid-year)."""
    res = run(_build())
    assert len(res.fcff) == 10, len(res.fcff)
    assert _close(res.pv_factor[0], 1.0 / (1.0 + WACC) ** 0.5)
    assert _close(res.pv_factor[-1], 1.0 / (1.0 + WACC) ** 9.5)


def test_last_fade_year_fcff():
    """페이드 최종연도(2032E) FCFF == 원본 X26."""
    res = run(_build())
    assert _close(res.fcff[-1], EXP_LAST_FCFF * B), f"{res.fcff[-1] / B}"


def test_terminal_and_ev():
    """TV·PV(TV)·PV(명시+페이드)·EV 가 원본과 일치."""
    res = run(_build())
    assert _close(res.terminal_value, EXP_TERMINAL_VALUE * B), res.terminal_value / B
    assert _close(res.terminal_value_pv, EXP_PV_TV * B), res.terminal_value_pv / B
    assert _close(res.pv_explicit_sum, EXP_PV_EXPLICIT * B), res.pv_explicit_sum / B
    assert _close(res.enterprise_value, EXP_EV * B), res.enterprise_value / B


def test_equity_bridge_and_per_share():
    """지분 브리지(EV −이자부부채 +이자부자산)와 주당가치 144,000원 재현."""
    res = run(_build())
    assert _close(res.equity_value, EXP_EQUITY * B), res.equity_value / B
    rounded = round(res.per_share, -3)
    assert rounded == EXP_PER_SHARE_ROUNDED, f"{res.per_share} → {rounded}"


def test_tv_weight_passes_gate():
    """페이드 효과 실증: TV 비중 57.8% < 75% 게이트.

    페이드 없이 명시 5년만 하면 TV 비중이 치솟는다(대조군으로 확인).
    """
    from calc_core.checks import TV_WEIGHT_WARN, check_terminal_value_weight
    from dataclasses import replace

    faded = run(_build())
    w_faded = faded.terminal_value_pv / faded.enterprise_value
    assert _close(w_faded, 0.578, tol=1e-2), w_faded
    assert check_terminal_value_weight(faded).severity.name == "PASS"

    no_fade = run(replace(_build(), fade_years=None))
    w_plain = no_fade.terminal_value_pv / no_fade.enterprise_value
    # 페이드가 TV 편중을 실제로 낮춘다 — 구조적 방어장치임의 정량 근거
    assert w_plain > w_faded, f"페이드 {w_faded:.3f} vs 무페이드 {w_plain:.3f}"
    assert w_plain > TV_WEIGHT_WARN, w_plain


def test_fade_none_is_identity():
    """fade_years=None 이면 기존 2단 동작과 완전 동일(골든 회귀 방어)."""
    from dataclasses import replace
    base = _build()
    a = run(replace(base, fade_years=None))
    b = run(replace(base, fade_years=0))
    assert a.per_share == b.per_share
    assert len(a.fcff) == len(REVENUE)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("모델러스 Hugel 페이드 골든 통과")
