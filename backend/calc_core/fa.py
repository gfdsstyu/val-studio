"""유형·무형자산 감가상각 + CAPEX 스케줄 → D&A, CAPEX (DCF 스파인 현금조정).

비올 FA 시트 로직(단순화·일반화):
  기존자산: 마지막 실적 순장부금액을 잔여 내용연수로 정액상각.
  신규 CAPEX: 매년 투자 → 각 빈티지를 내용연수로 정액상각(연차 누적).
  D&A[t]   = 기존자산 상각[t] + 신규 CAPEX 상각 누적[t]
  CAPEX[t] = 신규투자[t] (+ 유지보수 CAPEX)

내용연수·잔여내용연수는 DART 주석(유형자산 증감표/회계정책)에서 추출 → parsers 백본.
정액법 기준. 체감법 등은 이후 확장.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AssetClass:
    """자산군별 감가상각 정의."""

    name: str
    opening_net_book: float   # 기초 순장부금액(마지막 실적)
    remaining_life: float     # 잔여 내용연수(년)
    useful_life: float        # 신규자산 내용연수(년) — DART 주석 출처

    def existing_annual_dep(self) -> float:
        """기존자산 연 정액상각 = 순장부금액 / 잔여내용연수."""
        if self.remaining_life <= 0:
            return 0.0
        return self.opening_net_book / self.remaining_life


@dataclass(frozen=True)
class FaResult:
    dep_amort: list[float]   # D&A (양수)
    capex: list[float]       # CAPEX (양수 크기)
    detail: dict = field(default_factory=dict)


def project_fixed_assets(
    asset_classes: list[AssetClass],
    new_capex_by_class: dict[str, list[float]],
) -> FaResult:
    """자산군별 기존자산 상각 + 신규 CAPEX 정액상각 누적 → D&A, CAPEX.

    new_capex_by_class: {AssetClass.name: [투영연도별 신규투자]}.
    각 빈티지는 투자 다음 해(또는 당해)부터 useful_life 동안 정액상각.
    여기선 관용적으로 **투자 당해부터** 상각 시작(월할 무시, 연 단위).
    """
    n = len(next(iter(new_capex_by_class.values())))
    dep = [0.0] * n
    capex_total = [0.0] * n

    for ac in asset_classes:
        # 1) 기존자산 상각: 잔여내용연수 동안만
        existing = ac.existing_annual_dep()
        for t in range(n):
            if t < ac.remaining_life:
                dep[t] += existing
        # 2) 신규 CAPEX 빈티지별 정액상각
        caps = new_capex_by_class.get(ac.name, [0.0] * n)
        annual_rate = 1.0 / ac.useful_life if ac.useful_life > 0 else 0.0
        for vintage in range(n):
            invest = caps[vintage]
            capex_total[vintage] += invest
            for t in range(vintage, n):
                if (t - vintage) < ac.useful_life:
                    dep[t] += invest * annual_rate

    return FaResult(dep_amort=dep, capex=capex_total)
