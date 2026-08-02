"""사용가치(VIU) — IAS 36 손상검사 전용 DCF 제약 모드.

계속기업 DCF([[손상검사_impairment]])와 달리 VIU 는:
  · **TV 없음** — 자산의 유한 내용연수(N년)만. 영구성장 Gordon 미적용.
  · **성능 개선/향상 CAPEX 제외** — 현재 상태 유지 현금흐름만(호출자가 필터해 주입).
  · **세전 기준** — IAS 36 은 세전 현금흐름·세전 할인율 요구. 단 세전 VIU == 세후 VIU
    여야 하므로 실무는 세후 계산 후 **유효세전율을 역산**(단순 gross-up 아님, 234).
  · 회수가능액 = max(FVLCD, VIU).

새 엔진이 아니라 스파인의 '제약 모드' — 계속기업 dcf.py 와 수학 백본(mid-year 할인)을
공유하되 터미널을 제거하고 이중(세전/세후) 관점을 추가한다. 금지 현금흐름 스코프·할인율
정합은 checks.check_viu_cashflow_scope / check_viu_discount_rate 가 게이트한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ViuInputs:
    """VIU 입력. 현금흐름은 이미 금지항목(금융·세금·미확정 구조조정·성능향상 CAPEX)이
    배제된 **영업 현금흐름**이어야 한다(호출자 책임 — 게이트가 교차검증)."""
    post_tax_cashflows: list[float]     # 세후 영업현금흐름(내용연수 N년, TV 없음)
    post_tax_rate: float                # 세후 할인율(자산 특유 위험 반영)
    tax_rate: float                     # 유효 법인세율(세전 현금흐름 복원용)
    fvlcd: float | None = None          # 순공정가치(처분부대원가 차감) — 있으면 회수가능액 비교
    carrying_amount: float | None = None  # CGU 장부금액 — 있으면 손상액 산정
    mid_year: bool = True               # 중간연도 할인(기본) vs 연말
    provision_carrying: float = 0.0     # 이미 인식된 복구충당부채 장부액(746: VIU 에서 차감)


@dataclass
class ViuResult:
    viu_post_tax: float
    viu_pre_tax: float                  # 유효세전율로 할인한 세전 VIU(== viu_post_tax 목표)
    effective_pre_tax_rate: float       # 역산된 유효세전율
    recoverable_amount: float | None    # max(FVLCD, VIU)
    impairment_loss: float | None       # max(0, 장부금액 − 회수가능액)
    warnings: list[str] = field(default_factory=list)


def _pv(cashflows: list[float], rate: float, mid_year: bool) -> float:
    """유한 시계열 현가(TV 없음). 기간 = mid-year(t−0.5) 또는 연말(t)."""
    total = 0.0
    for i, cf in enumerate(cashflows, start=1):
        period = i - 0.5 if mid_year else float(i)
        total += cf / (1.0 + rate) ** period
    return total


def _solve_pre_tax_rate(pre_tax_cfs: list[float], target_viu: float,
                        mid_year: bool, *, lo: float = 1e-6, hi: float = 1.0,
                        tol: float = 1e-10, max_iter: int = 200) -> float:
    """세전 현금흐름을 할인해 target_viu 와 일치시키는 유효세전율 역산(이분탐색).

    세전 현금흐름 > 세후 현금흐름이므로 동일 VIU 를 만들려면 r_pre > r_post — 단순
    gross-up(r/(1−t)) 은 현금흐름 시점 분포에 따라 우연히만 일치(234). PV 는 할인율에
    단조감소하므로 이분탐색이 수렴한다.
    """
    # 상한 확장: r=hi 에서도 PV 가 target 을 웃돌면 hi 를 키운다
    for _ in range(60):
        if _pv(pre_tax_cfs, hi, mid_year) <= target_viu:
            break
        hi *= 2.0
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        pv = _pv(pre_tax_cfs, mid, mid_year)
        if abs(pv - target_viu) <= tol * max(abs(target_viu), 1.0):
            return mid
        if pv > target_viu:         # 할인 부족 → 율 상향
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def compute_viu(inp: ViuInputs) -> ViuResult:
    """VIU 산정 + 유효세전율 역산 + 회수가능액/손상액.

    세전 현금흐름 = 세후 / (1 − t) 근사(NOPLAT↔EBIT 관계). 복구충당부채 장부액은
    VIU 에서 차감(746: 현금흐름에서 복구유출 제외했으므로 FVLCD 와 동일 척도로 맞춤).
    """
    warnings: list[str] = []
    if not inp.post_tax_cashflows:
        raise ValueError("VIU 현금흐름이 비어 있음")
    if not (0.0 <= inp.tax_rate < 1.0):
        raise ValueError("tax_rate 는 [0,1) 범위")

    viu_post = _pv(inp.post_tax_cashflows, inp.post_tax_rate, inp.mid_year)
    viu_post -= inp.provision_carrying          # 746 일관성 조정

    # 세전 현금흐름 복원(세금 제거) 후 유효세전율 역산
    if inp.tax_rate > 0:
        pre_tax_cfs = [cf / (1.0 - inp.tax_rate) for cf in inp.post_tax_cashflows]
    else:
        pre_tax_cfs = list(inp.post_tax_cashflows)
    target = viu_post + inp.provision_carrying  # 충당부채 차감 전 값과 매칭(현금흐름 기준)
    eff_pre = _solve_pre_tax_rate(pre_tax_cfs, target, inp.mid_year)
    viu_pre = _pv(pre_tax_cfs, eff_pre, inp.mid_year) - inp.provision_carrying

    simple_gross_up = inp.post_tax_rate / (1.0 - inp.tax_rate) if inp.tax_rate > 0 else inp.post_tax_rate
    if abs(eff_pre - simple_gross_up) > 1e-4:
        warnings.append(
            f"유효세전율 {eff_pre:.4%} ≠ 단순 gross-up {simple_gross_up:.4%} "
            f"(차이 {(eff_pre - simple_gross_up) * 100:+.2f}%p) — gross-up 사용 금지(234)")

    recoverable = None
    impairment = None
    if inp.fvlcd is not None:
        recoverable = max(inp.fvlcd, viu_post)
    else:
        recoverable = viu_post
    if inp.carrying_amount is not None and recoverable is not None:
        impairment = max(0.0, inp.carrying_amount - recoverable)
        if impairment > 0:
            warnings.append(
                f"손상차손 {impairment:,.0f} — 장부금액({inp.carrying_amount:,.0f}) > "
                f"회수가능액({recoverable:,.0f}). 영업권 먼저 차감(IAS 36.104)")

    return ViuResult(
        viu_post_tax=viu_post,
        viu_pre_tax=viu_pre,
        effective_pre_tax_rate=eff_pre,
        recoverable_amount=recoverable,
        impairment_loss=impairment,
        warnings=warnings,
    )
