"""유형·무형자산 감가상각 + CAPEX 스케줄 → D&A, CAPEX (DCF 스파인 현금조정).

비올 FA 시트 로직(단순화·일반화):
  기존자산: 마지막 실적 순장부금액을 잔여 내용연수로 정액상각.
  신규 CAPEX: 매년 투자 → 각 빈티지를 내용연수로 정액상각(연차 누적).
  D&A[t]   = 기존자산 상각[t] + 신규 CAPEX 상각 누적[t] (+ 유지보수 CAPEX 상각)
  CAPEX[t] = 신규(성장)투자[t] + 유지보수 CAPEX[t]

신규(growth) vs 유지보수(maintenance) CAPEX 분리(Assumption 시트 6):
  - 신규(성장): 매출 성장에 연동, 새 빈티지로 내용연수 정액상각(감가 증가).
  - 유지보수: 기존 자산 유지(마모 대체). terminal 년엔 관행상 ≈ D&A 로 정규화 →
    영구 과소/과대투자 방지(maintenance_capex_matching_dep 헬퍼).
  두 종류를 분리해 각자 가정(드라이버)을 걸고, detail 에 나눠 기록(감사추적).

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


def _infer_years(*dicts: dict[str, list[float]] | None) -> int:
    """제공된 CAPEX 딕셔너리들에서 투영연수 추론(둘 다 비어도 안전하게 0)."""
    for d in dicts:
        if d:
            for v in d.values():
                return len(v)
    return 0


def project_fixed_assets(
    asset_classes: list[AssetClass],
    new_capex_by_class: dict[str, list[float]],
    maintenance_capex_by_class: dict[str, list[float]] | None = None,
    *,
    maintenance_depreciates: bool = True,
    years: int | None = None,
) -> FaResult:
    """자산군별 기존자산 상각 + 신규/유지보수 CAPEX 정액상각 누적 → D&A, CAPEX.

    new_capex_by_class:         {AssetClass.name: [연도별 신규(성장)투자]}.
    maintenance_capex_by_class: {AssetClass.name: [연도별 유지보수투자]} (선택, 기본 없음).
    maintenance_depreciates: True 면 유지보수 CAPEX 도 새 빈티지로 상각(실물 자산 대체이므로
        기본값). False 면 현금유출만 잡고 감가 미증가(마모분과 상쇄 가정 — 단순 모델).
    각 빈티지는 관용적으로 **투자 당해부터** useful_life 동안 정액상각(월할 무시, 연 단위).
    detail: existing_dep / new_capex / maintenance_capex / new_dep / maint_dep 분리 기록.
    """
    n = years if years is not None else _infer_years(
        new_capex_by_class, maintenance_capex_by_class)
    dep = [0.0] * n
    capex_total = [0.0] * n
    d_existing = [0.0] * n
    d_new = [0.0] * n
    d_maint = [0.0] * n
    cx_new = [0.0] * n
    cx_maint = [0.0] * n

    for ac in asset_classes:
        # 1) 기존자산 상각: 잔여내용연수 동안만
        existing = ac.existing_annual_dep()
        for t in range(n):
            if t < ac.remaining_life:
                dep[t] += existing
                d_existing[t] += existing
        annual_rate = 1.0 / ac.useful_life if ac.useful_life > 0 else 0.0

        def _depreciate_vintages(caps: list[float], into: list[float]) -> None:
            for vintage in range(n):
                invest = caps[vintage] if vintage < len(caps) else 0.0
                for t in range(vintage, n):
                    if (t - vintage) < ac.useful_life:
                        add = invest * annual_rate
                        dep[t] += add
                        into[t] += add

        # 2) 신규(성장) CAPEX — 항상 상각
        new_caps = new_capex_by_class.get(ac.name, [0.0] * n)
        for t in range(n):
            v = new_caps[t] if t < len(new_caps) else 0.0
            capex_total[t] += v
            cx_new[t] += v
        _depreciate_vintages(new_caps, d_new)

        # 3) 유지보수 CAPEX — 현금유출은 항상, 감가는 옵션
        maint_caps = (maintenance_capex_by_class or {}).get(ac.name, [0.0] * n)
        for t in range(n):
            v = maint_caps[t] if t < len(maint_caps) else 0.0
            capex_total[t] += v
            cx_maint[t] += v
        if maintenance_depreciates:
            _depreciate_vintages(maint_caps, d_maint)

    return FaResult(
        dep_amort=dep, capex=capex_total,
        detail={
            "existing_dep": d_existing, "new_dep": d_new, "maint_dep": d_maint,
            "new_capex": cx_new, "maintenance_capex": cx_maint,
        },
    )


def maintenance_capex_as_ratio(driver: list[float], pct: float) -> list[float]:
    """유지보수 CAPEX 드라이버 = driver(매출/기존자산총액 등) × pct. 비올식 매출연동."""
    return [d * pct for d in driver]


def maintenance_capex_matching_dep(fa: FaResult) -> list[float]:
    """유지보수 CAPEX = D&A (steady-state 자본유지 관행) — terminal 정규화 시드.

    사용법: 신규 CAPEX 만으로 1차 투영 → 산출 D&A 를 유지보수 CAPEX 로 재주입해
    terminal 년 FCFF 가 영구 과소/과대투자를 가정하지 않게 한다.
    """
    return list(fa.dep_amort)
