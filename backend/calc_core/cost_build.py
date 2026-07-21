"""성격별 원가·판관비 빌드업 — 비올/참고 모델 모델의 다중 드라이버 구조.

단일 COGS%/SGA% 가 아니라 **성격별 라인 항목**을 각자의 경제동인으로 투영 후 합산.
근거(plan §표준 Assumption 4·5):
  매출원가: 원재료 / 노무비(인원수×인당급여+상여+퇴직급여) / 경비 / 외주비(CPI) / 감가상각(FA)
  판관비:   인건비 / 외주비 / 경비 / 감가상각

각 라인의 투영법(method):
  growth   : base × Π(1+g_t)              — 원재료·경비 증가율
  ratio    : driver_t × pct_t             — 매출/매출원가 연동(경비·변동비)
  headcount: 인원수_t × 인당급여_t × (1+상여율+퇴직급여율)   — 노무비·인건비
  cpi      : base × CPI누적_t             — 외주비(물가 연동)
  fa_dep   : 외부 감가상각 벡터를 카테고리에 배분  — 감가상각(FA 스케줄 연동)
  fixed    : 연도별 고정값

성격별 Σ = IS 매출원가/판관비 (validators 합계검증 대상). build_ebit_from_lines 소비.
"""
from __future__ import annotations

from dataclasses import dataclass, field


def _cumulative(rates: list[float]) -> list[float]:
    """연율 리스트 → 누적계수. [0.02,0.03] → [1.02, 1.0506]."""
    out, acc = [], 1.0
    for r in rates:
        acc *= (1.0 + r)
        out.append(acc)
    return out


@dataclass(frozen=True)
class CostLine:
    """성격별 원가 1항목. category='cogs'|'sga', method 별 파라미터만 채운다."""
    name: str
    category: str                        # 'cogs' | 'sga'
    method: str                          # growth|ratio|headcount|cpi|fa_dep|fixed
    base: float = 0.0
    growth: list[float] | None = None    # growth
    driver: list[float] | None = None    # ratio (매출/매출원가 벡터)
    pct: list[float] | None = None       # ratio
    headcount: list[float] | None = None # headcount
    wage_per_head: list[float] | None = None
    bonus_rate: float = 0.0              # 상여율(급여 대비)
    severance_rate: float = 0.0          # 퇴직급여율(급여 대비)
    fa_share: float = 0.0                # fa_dep: 감가상각 중 이 카테고리 배분비율

    def project(self, years: int, *, cpi_cumulative: list[float] | None = None,
               fa_dep: list[float] | None = None) -> list[float]:
        m = self.method
        if m == "growth":
            return [self.base * f for f in _cumulative((self.growth or [0.0] * years))][:years]
        if m == "ratio":
            drv, pct = self.driver or [0.0] * years, self.pct or [0.0] * years
            return [drv[t] * pct[t] for t in range(years)]
        if m == "headcount":
            hc, wg = self.headcount or [0.0] * years, self.wage_per_head or [0.0] * years
            mult = 1.0 + self.bonus_rate + self.severance_rate
            return [hc[t] * wg[t] * mult for t in range(years)]
        if m == "cpi":
            cum = cpi_cumulative or [1.0] * years
            return [self.base * cum[t] for t in range(years)]
        if m == "fa_dep":
            dep = fa_dep or [0.0] * years
            return [dep[t] * self.fa_share for t in range(years)]
        if m == "fixed":
            v = self.growth or []                     # fixed 는 growth 필드에 연도값 재사용
            return [(v[t] if t < len(v) else 0.0) for t in range(years)]
        raise ValueError(f"알 수 없는 method: {m}")


@dataclass
class CostBuildResult:
    cogs: list[float]
    sga: list[float]
    detail: dict = field(default_factory=dict)        # {line name: [연도별]}


def project_costs(lines: list[CostLine], years: int, *,
                  cpi: list[float] | None = None,
                  fa_dep: list[float] | None = None) -> CostBuildResult:
    """성격별 라인 투영 → 카테고리(cogs/sga)별 합산 + 라인별 detail.

    cpi: 연율 리스트(cpi method 용, 누적계수로 변환). fa_dep: FA 스케줄 감가상각 벡터.
    """
    cpi_cum = _cumulative(cpi) if cpi else None
    cogs = [0.0] * years
    sga = [0.0] * years
    detail: dict[str, list[float]] = {}
    for ln in lines:
        vec = ln.project(years, cpi_cumulative=cpi_cum, fa_dep=fa_dep)
        detail[ln.name] = vec
        target = cogs if ln.category == "cogs" else sga
        for t in range(years):
            target[t] += vec[t]
    return CostBuildResult(cogs=cogs, sga=sga, detail=detail)
