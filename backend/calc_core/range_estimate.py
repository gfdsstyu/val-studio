"""감사인 범위추정치 — 기준서 540 문단 28~29 의 코드화.

경영진 점추정치를 평가하기 위해 감사인이 **가정별 합리 구간**을 세우고, 엔진이 그
구간들이 함의하는 주당가치 범위를 산출한다. 경영진 주장값이 범위 밖이면 **최소
조정액**(가까운 경계까지)을 계산해 미수정왜곡표시 집계(기준서 450)의 재료로 넘긴다.

기준서 규율을 게이트로 승격한 지점 두 곳:
  · **29(a)** "충분하고 적합한 감사증거에 의하여 뒷받침되며 … 합리적이라고 평가된
    금액만 포함" → 구간의 **양끝 각각에 근거(basis) 필수**. 근거 없는 끝은 계산을
    차단한다(넓게 잡아 안전해 보이려는 유혹이 증거 없는 범위를 만든다 — 이 레포의
    "무의미한 결과를 만들어놓고 경고하지 않는다" 원칙 그대로).
  · **A124-A125** 취지: 범위가 지나치게 넓으면 그 자체가 증거 불충분의 신호 →
    폭이 기준값 대비 임계를 넘으면 WARN 으로 표면화한다.

계산은 근사 없이 **전 조합 평가**다: 가정 n 개 → 2^n 개 끝점 조합 전부를 엔진으로
실행해 min/max 를 취한다. 단조성 가정(예: "WACC 가 낮으면 항상 가치가 높다")을 쓰지
않는 이유는 페이드·구간세율처럼 비단조 상호작용이 실재하기 때문이다. n 은 상한으로
막는다(조합 폭발 방지 — 상한 초과는 차단이지 조용한 절단이 아니다).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from itertools import product

from ingest.validators import Finding, Severity

from .dcf import run
from .models import DcfSpineInput

# 구간을 걸 수 있는 필드 화이트리스트 — DcfSpineInput 의 스칼라 가정.
SCALAR_FIELDS = frozenset({
    "wacc", "terminal_growth", "non_operating_assets", "net_debt",
    "non_controlling_interest", "effective_tax_rate", "terminal_fcff_override",
    "terminal_reinvestment_rate", "terminal_wc_ratio", "fade_growth",
})
# 시계열 필드는 절대치가 아니라 **곱셈 스케일**로 건다(예: revenue_scale [0.95, 1.05]
# = 매출 시계열 전체 ±5%). 연도별 개별 구간은 조합 폭발·근거 관리가 비현실적이다.
SERIES_SCALE_FIELDS = frozenset({
    "revenue_scale", "cogs_scale", "sga_scale",
    "dep_amort_scale", "capex_scale", "delta_nwc_cash_adj_scale",
})
MAX_ASSUMPTIONS = 10          # 2^10 = 1,024 평가 — 엔진이 순수 산술이라 충분히 빠르다
WIDE_RANGE_RATIO = 0.5        # (high-low)/base_per_share 초과 시 WARN (A124-A125 취지)


@dataclass
class RangeAssumption:
    """가정 하나의 합리 구간. 양끝 근거가 없으면 게이트가 계산을 차단한다(29(a))."""
    field: str
    low: float
    high: float
    basis_low: str = ""
    basis_high: str = ""


@dataclass
class RangeEstimateResult:
    blocked: bool
    findings: list[Finding] = field(default_factory=list)
    low: float | None = None                  # 주당가치 하한
    high: float | None = None                 # 주당가치 상한
    base_per_share: float | None = None       # 구간 미적용(base 입력) 점추정
    combo_low: dict | None = None             # 하한을 만든 끝점 조합 {field: 값}
    combo_high: dict | None = None
    claimed_per_share: float | None = None
    claimed_within: bool | None = None
    min_adjustment: float | None = None       # 범위 밖일 때 가까운 경계까지의 조정액
    n_evaluations: int = 0


def _apply(base: DcfSpineInput, choice: dict[str, float]) -> DcfSpineInput:
    """끝점 조합 하나를 입력에 적용. 스칼라는 치환, *_scale 은 시계열 전체 곱."""
    scalars = {k: v for k, v in choice.items() if k in SCALAR_FIELDS}
    inp = replace(base, **scalars) if scalars else base
    for k, v in choice.items():
        if k in SERIES_SCALE_FIELDS:
            series_name = k[: -len("_scale")]
            inp = replace(inp, **{series_name: [x * v for x in getattr(inp, series_name)]})
    return inp


def _gate(assumptions: list[RangeAssumption]) -> list[Finding]:
    """실행 전 게이트 — FAIL 이 하나라도 있으면 계산하지 않는다."""
    findings: list[Finding] = []
    if not assumptions:
        findings.append(Finding("range_no_assumptions", Severity.FAIL,
                                "구간을 건 가정이 없습니다 — 범위추정이 성립하지 않음",
                                {"layer": "judgment"}))
    if len(assumptions) > MAX_ASSUMPTIONS:
        findings.append(Finding(
            "range_too_many", Severity.FAIL,
            f"가정 {len(assumptions)}개 — 상한 {MAX_ASSUMPTIONS}(2^n 전 조합 평가). "
            "핵심 가정으로 줄이거나 나눠서 평가하라",
            {"layer": "judgment", "count": len(assumptions)}))
    seen: set[str] = set()
    for a in assumptions:
        allowed = SCALAR_FIELDS | SERIES_SCALE_FIELDS
        if a.field not in allowed:
            findings.append(Finding(
                "range_unknown_field", Severity.FAIL,
                f"'{a.field}' 는 구간을 걸 수 없는 필드 — 허용: "
                f"{', '.join(sorted(allowed))}", {"field": a.field}))
            continue
        if a.field in seen:
            findings.append(Finding("range_duplicate_field", Severity.FAIL,
                                    f"'{a.field}' 구간이 중복 지정됨", {"field": a.field}))
        seen.add(a.field)
        if a.low > a.high:
            findings.append(Finding(
                "range_inverted", Severity.FAIL,
                f"'{a.field}': 하한 {a.low} > 상한 {a.high}", {"field": a.field}))
        # 29(a): 양끝 각각 근거 필수. low == high(점)면 근거 하나로 족하다.
        missing = []
        if not a.basis_low.strip():
            missing.append("하한")
        if a.low != a.high and not a.basis_high.strip():
            missing.append("상한")
        if missing:
            findings.append(Finding(
                "range_basis_missing", Severity.FAIL,
                f"'{a.field}': {'·'.join(missing)} 근거 없음 — 기준서 540 문단 29(a): "
                "감사인의 범위는 증거로 뒷받침되는 금액만 포함해야 한다. "
                "근거 없이 넓힌 범위는 안전이 아니라 증거 부재다",
                {"field": a.field, "missing": missing, "layer": "judgment"}))
    return findings


def range_estimate(
    base: DcfSpineInput,
    assumptions: list[RangeAssumption],
    *,
    claimed_per_share: float | None = None,
) -> RangeEstimateResult:
    """가정별 구간 → 주당가치 범위 [low, high] + 경영진 주장값 판정."""
    findings = _gate(assumptions)
    if any(f.severity is Severity.FAIL for f in findings):
        return RangeEstimateResult(blocked=True, findings=findings,
                                   claimed_per_share=claimed_per_share)

    base_ps = run(base).per_share

    # 전 조합 평가 — 각 가정은 {low, high} 두 끝점(점 구간이면 한 값).
    axes: list[list[tuple[str, float]]] = []
    for a in assumptions:
        vals = [a.low] if a.low == a.high else [a.low, a.high]
        axes.append([(a.field, v) for v in vals])
    lo = hi = None
    combo_lo = combo_hi = None
    n = 0
    for combo in product(*axes):
        choice = dict(combo)
        ps = run(_apply(base, choice)).per_share
        n += 1
        if lo is None or ps < lo:
            lo, combo_lo = ps, choice
        if hi is None or ps > hi:
            hi, combo_hi = ps, choice

    # A124-A125 취지: 지나치게 넓은 범위는 증거 불충분의 신호.
    if base_ps and (hi - lo) > WIDE_RANGE_RATIO * abs(base_ps):
        findings.append(Finding(
            "range_too_wide", Severity.WARN,
            f"범위 폭 {hi - lo:,.0f}원이 기준 점추정 {base_ps:,.0f}원의 "
            f"{(hi - lo) / abs(base_ps):.0%} — 범위가 넓다는 것은 안전이 아니라 "
            "**증거가 부족하다는 신호**다(540 A124-A125). 구간을 좁힐 증거를 더 구하라",
            {"width": hi - lo, "base": base_ps, "layer": "judgment"}))

    within = adj = None
    if claimed_per_share is not None:
        within = lo <= claimed_per_share <= hi
        if within:
            adj = 0.0
        else:
            # 최소 조정액: 가까운 경계까지. 부호 = 주장값이 조정돼야 할 방향의 반대
            # (양수 = 주장값이 그만큼 과대 → 하향 조정 필요).
            nearest = hi if claimed_per_share > hi else lo
            adj = claimed_per_share - nearest
            findings.append(Finding(
                "claimed_outside_range", Severity.WARN,
                f"경영진 주장 {claimed_per_share:,.0f}원이 감사인 범위 "
                f"[{lo:,.0f}, {hi:,.0f}] 밖 — 최소 조정액 {adj:+,.0f}원"
                f"({'과대' if adj > 0 else '과소'}). 미수정왜곡표시 집계(기준서 450) "
                "대상 후보", {"claimed": claimed_per_share, "low": lo, "high": hi,
                             "min_adjustment": adj, "layer": "judgment"}))

    return RangeEstimateResult(
        blocked=False, findings=findings,
        low=lo, high=hi, base_per_share=base_ps,
        combo_low=combo_lo, combo_high=combo_hi,
        claimed_per_share=claimed_per_share,
        claimed_within=within, min_adjustment=adj,
        n_evaluations=n,
    )
