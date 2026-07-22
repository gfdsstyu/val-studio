"""상대가치평가 — peer 배수(PER·PBR·EV/EBITDA) → 통계 → 내재가치.

자본시장법 종합평가(FV·DCF → 상대가치+NAV) 트랙의 상대가치법. 순수 계산(stdlib):
  peer 배수 수집 → median/mean → × 대상회사 지표(EPS·BPS·EBITDA) → 내재 주당가치.

원칙(anthropic comps 정본·우리 4-step 정합): 5-10 Rule — peer 5개 미만 통계취약,
10개 초과 유사성희석. median 권장(이상치 강건). 음수/결측 배수는 제외(경고).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PeerMultiple:
    """유사기업 1사의 관측 배수. 없는 값은 None(통계에서 제외)."""
    name: str
    per: float | None = None
    pbr: float | None = None
    ev_ebitda: float | None = None


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def multiple_stats(values: list[float | None]) -> dict:
    """배수 리스트 → {n, mean, median, min, max}. 양수만 사용(음수 PER 등 제외)."""
    xs = [v for v in values if v is not None and v > 0]
    if not xs:
        return {"n": 0, "mean": None, "median": None, "min": None, "max": None}
    return {"n": len(xs), "mean": sum(xs) / len(xs), "median": _median(xs),
            "min": min(xs), "max": max(xs)}


@dataclass
class RelativeResult:
    per: dict = field(default_factory=dict)       # {stats, implied_per_share}
    pbr: dict = field(default_factory=dict)
    ev_ebitda: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def relative_valuation(
    peers: list[PeerMultiple],
    *,
    target_eps: float | None = None,
    target_bps: float | None = None,
    target_ebitda: float | None = None,
    net_debt: float = 0.0,
    shares_outstanding: float | None = None,
    use: str = "median",
) -> RelativeResult:
    """peer 배수 통계 × 대상 지표 → 방식별 내재 주당가치.

    - PER: stat(PER) × target_eps = 내재 주가
    - PBR: stat(PBR) × target_bps = 내재 주가
    - EV/EBITDA: stat × target_ebitda = EV → (−순차입)/주식수 = 내재 주가
    use='median'|'mean'. 5-10 Rule 경고 동봉.
    """
    res = RelativeResult()
    stat_key = "median" if use == "median" else "mean"

    per_s = multiple_stats([p.per for p in peers])
    res.per = {"stats": per_s, "implied_per_share":
               (per_s[stat_key] * target_eps if per_s[stat_key] and target_eps is not None else None)}

    pbr_s = multiple_stats([p.pbr for p in peers])
    res.pbr = {"stats": pbr_s, "implied_per_share":
               (pbr_s[stat_key] * target_bps if pbr_s[stat_key] and target_bps is not None else None)}

    ev_s = multiple_stats([p.ev_ebitda for p in peers])
    implied_ev_ps = None
    if ev_s[stat_key] and target_ebitda is not None and shares_outstanding:
        ev = ev_s[stat_key] * target_ebitda
        implied_ev_ps = (ev - net_debt) / shares_outstanding
    res.ev_ebitda = {"stats": ev_s, "implied_per_share": implied_ev_ps}

    n = len(peers)
    if n < 5:
        res.warnings.append(f"peer {n}개 < 5 — 통계 취약(배수 median 불안정, 기준 완화 검토)")
    elif n > 10:
        res.warnings.append(f"peer {n}개 > 10 — 유사성 희석(기준 강화 검토)")
    # 결측 경고는 실제 사용한 방식(타깃 지표 제공)에만 — 안 쓰는 배수는 노이즈.
    for label, s, target in (("PER", per_s, target_eps), ("PBR", pbr_s, target_bps),
                             ("EV/EBITDA", ev_s, target_ebitda)):
        if target is not None and s["n"] < n:
            res.warnings.append(f"{label}: {n - s['n']}개 결측/음수 제외(유효 {s['n']}개)")
    return res
