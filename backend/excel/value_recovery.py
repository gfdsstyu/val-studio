"""값-only 워크북 복원(P2) — 기준서 540 문단 22~25(경영진 방법 테스트)의 전제.

감사인이 받는 모델은 대개 **값 붙여넣기**다: 수식이 없으니 정적 감사·의존성 그래프가
전부 무력하다. 그러나 숫자들 사이의 **산술 관계는 값만으로도 복원**할 수 있다 —
할인계수는 PV/FCFF 비율에 새겨져 있고, 세금 정책은 EBIT 대비 세액 패턴에 새겨져 있다.

두 모드:
  · **standard** — Val-Studio 표준 레이아웃(template_schema 좌표)이면 값만으로 전체
    스파인을 복원한다. 수식 기반 판정(dcf_import 의 tax_override 추론)을 **산술
    지문**으로 대체: 세금행 값이 구간세율 재계산과 일치하면 override 아님, 유효세율이
    일정하면 effective_tax_rate, 둘 다 아니면 tax_override.
  · **detected** — 임의 레이아웃이면 행 쌍 자동 탐지로 **암묵 WACC·mid-year 여부**를
    역산한다. 원리: PV_i/FCFF_i = 1/(1+w)^t_i 에서 연속 열의 비율
    (PV_{i+1}/PV_{i})·(FCFF_i/FCFF_{i+1}) = 1/(1+w) 가 **기간 간격(1년)만으로 성립**
    — mid-year 여부를 몰라도 w 가 먼저 나오고, 그다음 t_1 = ln(FCFF_1/PV_1)/ln(1+w)
    로 mid-year(≈0.5)인지 기말(≈1.0)인지 판별된다.

산출물은 "복원된 모델"이 아니라 **복원 후보 + 미해결 목록**이다(계획 §3-3) — 미해결
항목이 곧 감사인의 질의사항이 된다. 이 경계를 흐리면 도구가 감사증거인 척하게 된다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from calc_core.dcf import run
from calc_core.models import DcfSpineInput
from calc_core.tax import corporate_tax
from ingest.validators import Finding, Severity

from .dependency_graph import _col_idx
from .template_schema import ASSUMP, META, RESULT, YEAR_COLS
from .template_schema import ROW as _ROW

# 산술 지문 허용오차 — 백만원 단위 반올림 잔차 흡수(CHECK_TOL 과 동일 철학).
_TAX_TOL = 0.5
_EFF_RATE_TOL = 1e-4
# 역산 WACC 의 열간 일관성(상대) — 이보다 흩어지면 "일정 할인율" 가설 기각.
_WACC_CONSIST_TOL = 1e-3


@dataclass
class RecoveryResult:
    mode: str                                  # standard | detected | failed
    findings: list[Finding] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    input: DcfSpineInput | None = None         # standard 모드에서만
    recomputed_per_share: float | None = None
    cached_per_share: float | None = None
    implied: dict = field(default_factory=dict)  # detected: wacc·mid_year·행 좌표
    candidates: list[dict] = field(default_factory=list)


def _num(cells: dict, ref: str) -> float | None:
    c = cells.get(ref)
    v = getattr(c, "number", None) if c is not None else None
    return v if isinstance(v, (int, float)) else None


def _classify_tax(ebit: list[float], tax: list[float]) -> tuple[str, object]:
    """세금행 값의 산술 지문 → (정책, 파라미터).

    수식이 없으니 "하드값이면 override"(dcf_import 방식)를 쓸 수 없다 — 값-only 에선
    모든 행이 하드값이다. 대신 **값이 어떤 정책과 일치하는가**로 판정한다.
    우선순위는 엔진과 동일(bracket > effective > override) — 구간세율과 일치하는데
    override 로 복원하면 등가지만 파라메트릭 정보(정책)를 잃는다.
    """
    if all(abs(t - corporate_tax(e)) <= _TAX_TOL for e, t in zip(ebit, tax)):
        return "bracket", None
    rates = [t / e for e, t in zip(ebit, tax) if e]
    if rates and max(rates) - min(rates) <= _EFF_RATE_TOL:
        return "effective", round(sum(rates) / len(rates), 6)
    return "override", list(tax)


def recover_standard(workbook: dict) -> RecoveryResult:
    """표준 레이아웃 값-only → DcfSpineInput 복원 + 캐시 주당가치 대조."""
    if "DCF" not in workbook:
        return RecoveryResult("failed", findings=[Finding(
            "recovery_layout", Severity.FAIL, "DCF 시트 없음 — 표준 레이아웃 아님", {})])
    cells = workbook["DCF"]
    n = sum(1 for c in YEAR_COLS
            if _num(cells, f"{c}{_ROW['year']}") is not None)
    need = [ASSUMP["wacc"], ASSUMP["shares_outstanding"]]
    if n == 0 or any(_num(cells, r) is None for r in need):
        return RecoveryResult("failed", findings=[Finding(
            "recovery_layout", Severity.FAIL,
            "표준 좌표(가정셀·연도행)에 값 없음 — 표준 레이아웃 아님", {})])
    cols = YEAR_COLS[:n]

    def row(key: str) -> list[float]:
        return [_num(cells, f"{c}{_ROW[key]}") or 0.0 for c in cols]

    findings: list[Finding] = []
    unresolved: list[str] = []

    revenue, cogs, sga = row("rev"), row("cogs"), row("sga")
    ebit = [revenue[i] - cogs[i] - sga[i] for i in range(n)]
    policy, param = _classify_tax(ebit, row("tax"))
    tax_override = param if policy == "override" else None
    eff_rate = param if policy == "effective" else None
    if policy == "bracket":
        msg = "세금행이 구간세율 재계산과 일치 — 표준 정책으로 복원"
    elif policy == "effective":
        msg = f"세금행이 유효세율 {param:.2%} 로 일정 — effective_tax_rate 복원"
    else:
        msg = ("세금행이 구간세율·일정 유효세율 어느 쪽과도 불일치 — tax_override 로 "
               "복원(실적세액 주입 또는 오류 가능성, 원천 확인 필요)")
    findings.append(Finding(
        "recovery_tax_policy", Severity.WARN if policy == "override" else Severity.PASS,
        msg, {"policy": policy, "layer": "execution"}))
    if policy == "override":
        unresolved.append("세금 정책 근거(실적세액 주입인지, 계산 오류인지) — 질의 필요")

    periods = row("period")
    # 페이드(R1): META 는 값 셀이라 값-only 에서도 살아 있다 — 파라메트릭 복원.
    fade_raw = _num(cells, META["fade_years"])
    fade_years = int(round(fade_raw)) if fade_raw else None
    n_exp = n - fade_years if fade_years else n

    def explicit(series):
        return series[:n_exp] if series is not None else None

    inp = DcfSpineInput(
        wacc=_num(cells, ASSUMP["wacc"]),
        terminal_growth=_num(cells, ASSUMP["terminal_growth"]) or 0.0,
        revenue=explicit(revenue), cogs=explicit(cogs), sga=explicit(sga),
        dep_amort=explicit(row("da")), capex=explicit(row("capex")),
        delta_nwc_cash_adj=explicit(row("nwc")),
        non_operating_assets=_num(cells, ASSUMP["non_operating_assets"]) or 0.0,
        net_debt=_num(cells, ASSUMP["net_debt"]) or 0.0,
        non_controlling_interest=_num(cells, ASSUMP["non_controlling_interest"]) or 0.0,
        shares_outstanding=int(round(_num(cells, ASSUMP["shares_outstanding"]))),
        mid_year_periods=explicit(periods),
        terminal_discount_period=periods[-1] if periods else None,
        tax_override=explicit(tax_override) if tax_override else None,
        effective_tax_rate=eff_rate,
        terminal_fcff_override=_num(cells, META["terminal_fcff_override"]),
        terminal_reinvestment_rate=_num(cells, META["terminal_reinvestment_rate"]),
        fade_years=fade_years,
        fade_growth=_num(cells, META["fade_growth"]),
    )
    res = run(inp)
    cached = _num(cells, RESULT["per_share"])
    if cached is not None:
        rel = abs(res.per_share - cached) / max(abs(cached), 1e-9)
        findings.append(Finding(
            "recovery_tieout", Severity.PASS if rel < 1e-6 else Severity.WARN,
            (f"복원 재계산 {res.per_share:,.2f} vs 워크북 표기 {cached:,.2f} — "
             + ("일치(복원 신뢰)" if rel < 1e-6 else
                f"불일치 {rel:.2%}. 워크북 값이 조작·수정됐거나 복원이 원 모델과 다른 "
                "구조라는 뜻 — 그 자체가 발견사항이다")),
            {"recomputed": res.per_share, "cached": cached, "rel": rel,
             "layer": "execution"}))
    else:
        unresolved.append("워크북에 주당가치 표기 없음 — 재계산 대조 불가")

    unresolved.append("가정의 원천·근거(방법·데이터의 적합성)는 값에서 복원 불가 — "
                      "문서·질의로 확인(540 문단 23~25)")
    return RecoveryResult("standard", findings=findings, unresolved=unresolved,
                          input=inp, recomputed_per_share=res.per_share,
                          cached_per_share=cached)


def detect_discount_pairs(cells: dict, *, min_cols: int = 4,
                          max_candidates: int = 5) -> list[dict]:
    """임의 값-only 시트에서 (FCFF행, PV행) 쌍을 자동 탐지해 암묵 WACC 를 역산.

    판별 신호 3중: ①비율 q_i = PV/FCFF ∈ (0,1) 전 열 성립 ②연속 비 q_{i+1}/q_i 가
    상수(=1/(1+w)) ③그로부터 나온 w 가 현실 대역(1%~60%). 셋 다 만족하는 행 쌍만
    후보로 — 우연히 비례하는 행(매출 vs 원가)은 ②는 통과해도 q>1 이거나 w 가 대역
    밖이라 걸러진다.
    """
    by_row: dict[int, dict[int, float]] = {}
    for ref, cell in cells.items():
        v = getattr(cell, "number", None)
        if not isinstance(v, (int, float)) or v == 0:
            continue
        m = __import__("re").fullmatch(r"([A-Z]{1,3})([0-9]+)", ref)
        if not m:
            continue
        by_row.setdefault(int(m.group(2)), {})[_col_idx(m.group(1))] = v

    out: list[dict] = []
    rows = sorted(by_row)
    for i, rf in enumerate(rows):
        for rp in rows[i + 1:]:
            shared = sorted(set(by_row[rf]) & set(by_row[rp]))
            if len(shared) < min_cols:
                continue
            # 연속 열 구간만(중간에 빈 열이 있으면 기간 간격 가정이 깨진다)
            runs, cur = [], [shared[0]]
            for c in shared[1:]:
                if c == cur[-1] + 1:
                    cur.append(c)
                else:
                    runs.append(cur); cur = [c]
            runs.append(cur)
            for cols_run in runs:
                if len(cols_run) < min_cols:
                    continue
                f = [by_row[rf][c] for c in cols_run]
                p = [by_row[rp][c] for c in cols_run]
                if any(x <= 0 or y <= 0 for x, y in zip(f, p)):
                    continue
                q = [y / x for x, y in zip(f, p)]
                if not all(0 < v < 1 for v in q):
                    continue
                ratios = [q[i + 1] / q[i] for i in range(len(q) - 1)]
                mean_r = sum(ratios) / len(ratios)
                if not all(abs(r - mean_r) / mean_r < _WACC_CONSIST_TOL for r in ratios):
                    continue
                w = 1.0 / mean_r - 1.0
                if not (0.01 <= w <= 0.60):
                    continue
                t1 = math.log(1.0 / q[0]) / math.log(1.0 + w)
                out.append({
                    "fcff_row": rf, "pv_row": rp, "cols": len(cols_run),
                    "implied_wacc": round(w, 6),
                    "first_period": round(t1, 3),
                    "mid_year": abs(t1 - round(t1) + 0.5) < 0.05 or abs(t1 - 0.5) < 0.05,
                    "fit_error": max(abs(r - mean_r) / mean_r for r in ratios),
                })
    out.sort(key=lambda c: (c["fit_error"], -c["cols"]))
    return out[:max_candidates]


def recover(workbook: dict) -> RecoveryResult:
    """진입점: standard 시도 → 실패 시 시트별 자동 탐지(detected)."""
    r = recover_standard(workbook)
    if r.mode == "standard":
        return r
    candidates = []
    for sheet, cells in workbook.items():
        for c in detect_discount_pairs(cells):
            candidates.append({"sheet": sheet, **c})
    if not candidates:
        return RecoveryResult("failed", findings=r.findings + [Finding(
            "recovery_detect", Severity.WARN,
            "할인 구조(FCFF↔PV 행 쌍)를 값에서 찾지 못함 — PV 행이 없거나 할인율이 "
            "연도별로 다른 모델. 행 좌표를 아는 경우 수동 지정으로 재시도", {})],
            unresolved=["모델 구조 전반 — 평가인에게 원본(수식 살아있는 판) 요청 권고"])
    candidates.sort(key=lambda c: (c["fit_error"], -c["cols"]))
    best = candidates[0]
    findings = [Finding(
        "recovery_implied_wacc", Severity.WARN,
        f"{best['sheet']} 시트 {best['fcff_row']}행(FCFF 후보)↔{best['pv_row']}행(PV 후보)"
        f"에서 **암묵 할인율 {best['implied_wacc']:.4%}** 역산"
        f"({'mid-year' if best['mid_year'] else '기말'} 할인, 첫 기간 {best['first_period']}). "
        "의견서가 주장하는 할인율과 대조하라 — 표기 할인율과 암묵 할인율이 다르면 "
        "그 자체가 발견사항(540 문단 23(c) 수학적 정확성)", {**best, "layer": "execution"})]
    return RecoveryResult("detected", findings=findings, candidates=candidates,
                          implied={"wacc": best["implied_wacc"],
                                   "mid_year": best["mid_year"]},
                          unresolved=["영구성장률·브리지(비영업/순차입/주식수)는 행 미탐지 "
                                      "— TV·EV 셀 위치 확인 후 수동 역산 필요"])
