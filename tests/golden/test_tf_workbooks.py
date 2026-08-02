"""골든 테스트 (Layer A) — T-F 전환사채 워크북 3종 채록 재현 + convertible.py 교차검증.

원본: D:\\칼럼\\ifrs 의 엑셀 3종(레포 밖·비공개 코퍼스 원자료). 캐시값을 상수로 채록해
픽스처 파일 없이 검증한다. 채록 SSOT:
d:\\gfdsstyu.github.io\\docs\\book\\research\\corpus\\ifrs\\ifrs-tf-model-excels.md

재현 검증으로 확정한 각 파일의 실제 모델(채록 결과 요지):

파일 B `TF_Model_CB_Valuation_Detailed_Steps.xlsx` (12스텝 CRR):
  · 트리 = **단일 위험할인율(rf+spread=5%)** + 전 노드 **액면 floor** + 쿠폰 미반영.
    'TF' 명명과 달리 성분 분리할인이 아님(정식 TF는 주식성분을 rf로 할인 → 본 엔진이 정식).
  · 'Bond Value' 119.669 = 액면100 + **분기 쿠폰 3.0(연 3%의 4배)** 을 이산 1.05^t 로 할인.
    트리(연속할인·쿠폰無)와 이종 가정 → 'Residual(내재옵션) 1.35' 는 정합 분해가 아님(반면교사).

파일 A `CB_TF_Model_B2Formula.xlsx` (12스텝, u=1.1·d=0.9 임의격자):
  · 격자 본체 = p=(e^{rΔt}−d)/(u−d)≈0.53764 위험중립, disc=e^{−0.03·0.25}, max(보유·전환·1000).
  · **루트 B2 만 예시 수식으로 덮어씀**: 0.5/0.5 동일가중 + 비자식 셀(C3=step1노드1, D3=step2노드1)
    참조 → 자기 격자 루트(1022.72)와 모순되는 1001.58 표시(반면교사: 표시수식≠생성로직).

파일 C `TF_Model_Convertible_Bond_With_Put.xlsx` (Black-Scholes 폐형식 + 풋):
  · d2 셀이 `r_adj − σ√T` (정상식 d1−σ√T 아님 — 수식 결함).
  · 채권가치 쿠폰항이 이율 0.05를 '금액'으로 사용(연 5 지급이어야 → 86.21 과소, 결함).
  · 골든은 as-written(SSOT) 재현 + 교정판 방향성 검증 병행.

stdlib: `python tests/golden/test_tf_workbooks.py` (pytest 도 동작)
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core.convertible import (  # noqa: E402
    ConvertibleInputs, price_convertible,
)

REL = 1e-12  # 캐시 double 을 동일 산식으로 재현 → 사실상 완전일치 기대


# ═══════════════ 파일 B — 골든 상수 (워크북 캐시값 채록) ═══════════════
B_FINAL_CB = 121.0199893394989          # Final Results!B2
B_BOND = 119.66923910043                # Final Results!B3
B_RESIDUAL = 1.350750239068901          # Final Results!B4
B_NODE = {                              # Valuation Steps (하향횟수 k, 스텝 i): (보유, 최종)
    (0, 0): (121.0199893394989, 121.0199893394989),
    (0, 1): (132.4099135049246, 132.6205101690777),   # 전환 선택
    (1, 1): (111.9429173804037, 111.9429173804037),
    (2, 2): (105.3731533979352, 105.3731533979352),
    (5, 5): (98.75778004938815, 100.0),               # 액면 floor 발동
}


def _file_b_tree(disc_rate: float = 0.05):
    """파일 B 재현: CRR 12스텝, 단일할인율, 쿠폰無, 노드=max(보유·전환·액면).

    반환: (루트값, {(k하향,i스텝): (보유, 최종)}) — 채록 스팟 노드 대조용.
    """
    face, s0, strike = 100.0, 60.0, 50.0
    rf, vol, tt, n = 0.03, 0.2, 3.0, 12
    dt = tt / n
    cr = face / strike
    u = math.exp(vol * math.sqrt(dt))
    d = 1.0 / u
    p = (math.exp(rf * dt) - d) / (u - d)
    df = math.exp(-disc_rate * dt)

    nodes: dict[tuple[int, int], tuple[float, float]] = {}
    v = [max(cr * s0 * u ** j * d ** (n - j), face) for j in range(n + 1)]
    for i in range(n - 1, -1, -1):
        nv = []
        for j in range(i + 1):          # j = 상승횟수, 하향 k = i − j
            hold = df * (p * v[j + 1] + (1 - p) * v[j])
            conv = cr * s0 * u ** j * d ** (i - j)
            final = max(hold, conv, face)
            nodes[(i - j, i)] = (hold, final)
            nv.append(final)
        v = nv
    return v[0], nodes


def test_file_b_root_and_nodes():
    root, nodes = _file_b_tree()
    assert math.isclose(root, B_FINAL_CB, rel_tol=REL)
    for key, (hold, final) in B_NODE.items():
        if key == (0, 0):
            got_h, got_f = root, root
        else:
            got_h, got_f = nodes[key]
        assert math.isclose(got_h, hold, rel_tol=REL), (key, got_h, hold)
        assert math.isclose(got_f, final, rel_tol=REL), (key, got_f, final)


def test_file_b_bond_value_is_quarterly_coupon_defect():
    # 'Bond Value' = 액면 100 이산 5% + 분기마다 3.0(연 12% 상당) — 재현
    bond = 100 / 1.05 ** 3 + sum(3.0 / 1.05 ** (0.25 * i) for i in range(1, 13))
    assert math.isclose(bond, B_BOND, rel_tol=REL)
    assert math.isclose(B_FINAL_CB - bond, B_RESIDUAL, rel_tol=1e-9)
    # 반면교사 문서화: 정합한 연 3% 쿠폰 스트레이트 본드(이산 5%)는 훨씬 낮다
    correct = 100 / 1.05 ** 3 + sum(0.75 / 1.05 ** (0.25 * i) for i in range(1, 13))
    assert correct < 100 < bond            # 워크북 채권가치는 쿠폰 4배 결함으로 과대


def test_file_b_engine_collapse_equality():
    # spread=0 이면 정식 TF 는 단일 rf 할인으로 붕괴 → 파일 B 트리(disc=rf)와 완전일치.
    # 액면 floor 는 엔진의 고정 put_price=face 로 동일 표현(홀더 max 선택 규칙 공유).
    ref_root, _ = _file_b_tree(disc_rate=0.03)
    got = price_convertible(ConvertibleInputs(
        face=100.0, stock_price=60.0, conversion_ratio=2.0, maturity_years=3.0,
        volatility=0.2, risk_free=0.03, credit_spread=0.0, coupon_rate=0.0,
        put_price=100.0, steps=12,
    ))
    assert math.isclose(got.value, ref_root, rel_tol=REL)


def test_file_b_engine_tf_dominates_single_risky_rate():
    # 정식 TF(주식성분 rf 할인)는 전 성분 위험할인(파일 B) 대비 상방 — 설계차이의 방향 검증
    got = price_convertible(ConvertibleInputs(
        face=100.0, stock_price=60.0, conversion_ratio=2.0, maturity_years=3.0,
        volatility=0.2, risk_free=0.03, credit_spread=0.02, coupon_rate=0.0,
        put_price=100.0, steps=12,
    ))
    assert got.value > B_FINAL_CB


# ═══════════════ 파일 A — 골든 상수 ═══════════════
A_ROOT_B2 = 1001.5752909636464          # 'Input & CB Value'!B9 = 'CB Value Tree'!B2 (예시 수식)
A_GRID = {                              # CB Value Tree 캐시 (스텝 s, 하향 n)
    (1, 0): 1055.321406804809,
    (1, 1): 1001.471276496636,
    (2, 0): 1103.260741732853,
    (2, 1): 1016.759414516237,
    (3, 1): 1045.409072490904,
    (12, 0): 2615.356980600836,         # 만기 최상단 = 전환가치
}
A_GRID_SELF_ROOT = 1022.724047          # 격자 자기 점화식대로의 루트(±1e-6) — B2 표시수식과 모순


def _file_a_grid():
    """파일 A 격자 재현: u=1.1, d=0.9(비역수), p 위험중립, disc=e^{-0.03·0.25}, floor 1000."""
    s0, face, strike, n = 50.0, 1000.0, 60.0, 12
    u, d = 1.1, 0.9
    p = (math.exp(0.03 * 0.25) - d) / (u - d)
    df = math.exp(-0.03 * 0.25)
    cr = face / strike

    grid: dict[tuple[int, int], float] = {}
    for k in range(n + 1):
        grid[(n, k)] = max(cr * s0 * u ** (n - k) * d ** k, face)
    for s in range(n - 1, -1, -1):
        for k in range(s + 1):
            hold = (p * grid[(s + 1, k)] + (1 - p) * grid[(s + 1, k + 1)]) * df
            grid[(s, k)] = max(hold, cr * s0 * u ** (s - k) * d ** k, face)
    return grid


def test_file_a_grid_and_overwritten_root():
    grid = _file_a_grid()
    for key, exp in A_GRID.items():
        assert math.isclose(grid[key], exp, rel_tol=REL), (key, grid[key], exp)
    # 루트 B2 = 예시 수식(0.5/0.5 가중, 비자식 셀 (1,1)·(2,1) 참조) — as-written 재현
    root_formula = max(
        (0.5 * grid[(1, 1)] + 0.5 * grid[(2, 1)]) * math.exp(-0.03 * 0.25),
        (1000.0 / 60.0) * 50.0, 1000.0,
    )
    assert math.isclose(root_formula, A_ROOT_B2, rel_tol=1e-9)
    # 반면교사: 표시수식 루트 ≠ 격자 자기 점화식 루트(생성로직과 표시수식 불일치)
    assert math.isclose(grid[(0, 0)], A_GRID_SELF_ROOT, rel_tol=1e-6)
    assert abs(grid[(0, 0)] - root_formula) > 20.0


# ═══════════════ 파일 C — 골든 상수 (as-written, 결함 포함 SSOT) ═══════════════
C_D1 = -0.1352652163273806
C_D2_ASIS = -0.3830127018922193         # 결함: = r_adj − σ√T (정상식 d1 − σ√T 아님)
C_CONV_OPT = 1.771369151165164
C_BOND = 86.21008966608072              # 결함: 쿠폰항에 이율 0.05 를 금액으로 사용
C_CB = 87.98145881724588
C_PUT = 33.24996163119711
C_TOTAL = 121.23142044844299


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _file_c_closed_form(corrected: bool = False):
    """파일 C 재현. corrected=True 면 d2=d1−σ√T·쿠폰=연 5 지급으로 교정."""
    s, x, tt, r, sig, lam = 50.0, 60.0, 3.0, 0.03, 0.25, 0.02
    coupon = 5.0 if corrected else 0.05     # as-written 은 이율을 금액으로 오용
    r_adj = r + lam
    d1 = (math.log(s / x) + (r - lam + sig ** 2 / 2.0) * tt) / (sig * math.sqrt(tt))
    d2 = (d1 - sig * math.sqrt(tt)) if corrected else (r_adj - sig * math.sqrt(tt))
    conv_opt = s * math.exp(-lam * tt) * _norm_cdf(d1) - x * math.exp(-r * tt) * _norm_cdf(d2)
    bond = coupon * (1.0 - math.exp(-r_adj * tt)) / r_adj + 100.0 * math.exp(-r_adj * tt)
    cb = bond + conv_opt
    put = 100.0 * math.exp(-r * tt) * _norm_cdf(-d2) - s * math.exp(-lam * tt) * _norm_cdf(-d1)
    return {"d1": d1, "d2": d2, "conv_opt": conv_opt, "bond": bond,
            "cb": cb, "put": put, "total": cb + put}


def test_file_c_as_written():
    got = _file_c_closed_form()
    for key, exp in [("d1", C_D1), ("d2", C_D2_ASIS), ("conv_opt", C_CONV_OPT),
                     ("bond", C_BOND), ("cb", C_CB), ("put", C_PUT), ("total", C_TOTAL)]:
        assert math.isclose(got[key], exp, rel_tol=1e-9), (key, got[key], exp)


def test_file_c_corrected_directions():
    asis, corr = _file_c_closed_form(), _file_c_closed_form(corrected=True)
    assert corr["d2"] < asis["d2"]              # 교정 d2 = d1−σ√T 는 더 음수
    assert corr["conv_opt"] > asis["conv_opt"]  # N(d2)↓ → 차감항↓ → 전환옵션↑
    assert corr["put"] > asis["put"]            # N(−d2)↑ → 풋↑
    assert corr["bond"] > 95.0                  # 연 5 쿠폰 정합 채권 ≈ 액면 부근(과소결함 해소)
    assert corr["total"] > asis["total"]


# ═══════════════ 엔진 회귀 — 워크북 채록이 드러낸 결함의 재발 방지 ═══════════════
def test_engine_value_dominates_immediate_conversion_with_put():
    # 풋-우선 캐스케이드 결함 회귀 테스트: 전환>풋>계속 구간(배당으로 조기전환 유인)에서
    # 홀더 max 선택이면 즉시 전환가치가 하한. (구 코드는 풋을 먼저 골라 과소평가)
    res = price_convertible(ConvertibleInputs(
        face=100.0, stock_price=120.0, conversion_ratio=1.0, maturity_years=3.0,
        volatility=0.05, risk_free=0.03, credit_spread=0.3, coupon_rate=0.0,
        dividend_yield=0.12, put_price=110.0, steps=120,
    ))
    assert res.value >= res.conversion_value_now - 1e-9
    assert res.value >= 110.0 - 1e-9            # 풋 하한도 동시 지배


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
