"""분석적 절차 계층 (L3) — 시계열·파생지표 연속성 검사 (ISA 520 동형).

검증 3층 구조의 세 번째 층:
  L1 tie-out (ingest/validators)  : 데이터가 원본과 일치하나 — 라운드트립 정합
  L2 가정 게이트 (checks.py)      : 가정이 경제적으로 말이 되나 — 판단 게이트
  L3 분석적 절차 (이 모듈)         : 시계열·파생지표가 과거·구성요소와 정합하나

항등식(L1·L2)은 잘못된 비율로도 성립한다 — 원가율 자체가 틀리면 "영업이익 = 매출 ×
(1−원가율−판관비율)" 검산은 통과한다. 잘못된 비율을 잡는 축은 **연속성**이다:
비율을 실적→추정으로 늘어놓고 튀는 지점을 분해 역추적한다.

근거(귀납): 비올 DCF 리뷰 실측 — 결함 8건 중 5건(참조 밀림 계열)이 전부 이 절차로
발견되었고, 항등식 검산으로는 단 한 건도 잡히지 않았다. 상세 패턴은
docs/reference/모델감사_분석적절차.md (승격 예정), 계획은
docs/plan/analytical_review_workflow.md.

모든 검사는 WARN-only(재검토 신호)다 — 급변이 실제 사업 이벤트(신제품·구조 변화)라면
근거를 남기고 무시하면 된다. 실적(prior)이 없으면 PASS(정보)로 강등하고 차단하지
않는다(check_metric_vs_industry 의 "벤치마크 없음 — 대조 생략" 패턴).

Finding.detail["layer"] 태그: 리뷰 리포트의 4층 판정(방법론/구조/실행/검산)에서
이 finding 이 가리키는 층위. "execution"=참조·합산 오류 시그니처,
"judgment"=가정 수준 선택 의심, "execution|judgment"=양쪽 모두 가능.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from ingest.validators import Finding, Severity, ValidationReport

from .models import DcfSpineInput

# ── 임계값 (전부 비올 리뷰 실측 근거 — WARN-only 라 보수적으로 좁게 시작) ──────
# 접합부 비율 이탈 허용 %p. 근거: 비올 E-6 검증법 "추정 첫해 원가율이 직전 실적
# 대비 ±3%p 이내" — 실제 결함(+6.6%p)은 2배 이상 이탈, 정상 연결(−1.3%p)은 절반.
SEAM_TOL_PP = 0.03
# 회전기일 등 %p 개념이 없는 지표의 상대 허용폭. 비올 J-3(재고 130~225일 변동)
# 수준의 실적 변동성을 감안해 ±20%. 산업 분포 연동은 후속(benchmarks).
SEAM_REL_TOL = 0.20
# V자 스파이크: 이웃 평균 대비 이탈 임계. 비올 E-6 실측 이탈 +2.99%p 를 포착.
SPIKE_PP = 0.02
# V자 스파이크: "이웃끼리는 일치" 판정 임계. 비올 실측 이웃차 1.13%p(12.90 vs
# 11.77)를 포함하되, 레벨 시프트(가정 변경 — 이웃차가 이탈만큼 큼)는 배제하는 값.
SPIKE_NEIGHBOR_PP = 0.015
# 파생지표(인당 인건비 등) YoY 허용. 근거: 비올 J-1 검증장치 "전년 대비 ±10% 초과
# 변동 시 경고" — 실제 결함은 +40%.
DERIVED_YOY_TOL = 0.10
# 컨센서스 앵커 괴리 허용 %p. 비올 실측 GPM 6.8%p 괴리(71.2 vs 78)를 포착.
CONSENSUS_TOL_PP = 0.05
# 가중평균 재현(믹스 검산) 허용오차. 비올 §3.5(a) 실측 재현 잔차 0.1~0.2%p 의
# 2~5배 여유 — 세그먼트 커버리지 불완전(기타 부문)까지 흡수.
MIX_RECON_TOL = 0.005
# 성장-운전자본 정합: 매출 YoY 가 이 이상인데
NWC_GROWTH_REV_YOY = 0.10
# |ΔNWC| < Δ매출 × 이 비율이면 "성장의 대가 없는 밸류에이션" 신호.
# 근거: 비올 E-1·E-3 — 매출 +33.5% 성장에 ΔNWC=0 (운전자산 전액 누락).
NWC_DELTA_MIN_SHARE = 0.02


# ── 데이터 모델 ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SegmentSeries:
    """부문(세그먼트) 연도별 매출·매출원가 — 믹스 분해·부문별 접합부 검사용.

    provenance: 출처(사업보고서 부문정보 문단 등) — 감사추적. 수동 복붙 입력이면 필수.
    """

    name: str
    revenue: list[float]
    cogs: list[float]
    provenance: str | None = None


@dataclass(frozen=True)
class FinancialHistory:
    """실적 연도별 시계열(오래된→최신). 전부 optional — 있는 것만 검사한다.

    출처: /api/dart/financials(재무)·/api/dart/employee(인원·급여) 커넥터.
    ⚠️ 기준 정합: cogs·sga 는 스파인 입력(DcfSpineInput)과 **같은 기준**(D&A 포함
    여부)으로 넣을 것 — 접합부 검사는 양쪽을 같은 산식으로 비교하므로 기준이
    다르면 D&A 비율만큼(통상 1~3%p) 가짜 이탈이 생긴다.
    """

    years: list[int]
    revenue: list[float] | None = None
    cogs: list[float] | None = None
    sga: list[float] | None = None
    headcount: list[float] | None = None
    labor_cost: list[float] | None = None    # 원가 노무비 + 판관 인건비 합
    nwc: list[float] | None = None
    segments: list[SegmentSeries] | None = None

    def __post_init__(self) -> None:
        n = len(self.years)
        for attr in ("revenue", "cogs", "sga", "headcount", "labor_cost", "nwc"):
            v = getattr(self, attr)
            if v is not None and len(v) != n:
                raise ValueError(f"FinancialHistory.{attr} 길이 {len(v)} ≠ years {n}")


def _ratios(num: list[float], den: list[float]) -> list[float] | None:
    """연도별 비율. 분모 ≤ 0 이 하나라도 있으면 None(비율 정의 불가 — 검사 생략)."""
    if len(num) != len(den) or any(d <= 0 for d in den):
        return None
    return [n / d for n, d in zip(num, den)]


# ── 3.1 접합부 비율 연속성 ───────────────────────────────────────────────────
def check_ratio_seam(
    actuals: list[float],
    forecast: list[float],
    *,
    name: str,
    tol_pp: float = SEAM_TOL_PP,
    relative: bool = False,
    tol_rel: float = SEAM_REL_TOL,
    report: ValidationReport | None = None,
) -> Finding:
    """실적 마지막 ↔ 추정 첫해 비율의 계단 이탈 감지 (실적↔추정 접합부).

    check_projection_smoothness 와 축이 다르다: smoothness 는 **레벨**의 상대
    YoY·추정 구간만 / seam 은 **비율**의 %p 이탈·실적↔추정 **경계**. 비올 E-6
    (원가율 22.2%→28.8%, +6.6%p 역행)의 진입점이 된 검사.

    relative=True 면 %p 대신 상대 이탈(회전기일 등 %p 개념 없는 지표용).
    사업 근거(일회성·구조 변화)가 있으면 기재하고 무시한다 — WARN only.
    """
    if not actuals or not forecast:
        f = Finding("ratio_seam", Severity.PASS,
                    f"{name}: 실적 부재 — 접합부 대조 생략(정보)",
                    {"series_name": name, "layer": "execution|judgment"})
    else:
        last, first = actuals[-1], forecast[0]
        delta = first - last
        if relative:
            breach = last != 0 and abs(delta) / abs(last) > tol_rel
            desc = f"상대 {delta / last:+.0%} (허용 ±{tol_rel:.0%})" if last else "n/a"
        else:
            breach = abs(delta) > tol_pp
            desc = f"{delta:+.1%}p (허용 ±{tol_pp:.0%}p)"
        detail = {"series_name": name, "actual_last": last, "forecast_first": first,
                  "delta": delta, "actuals": actuals, "forecast": forecast,
                  "layer": "execution|judgment"}
        if breach:
            f = Finding("ratio_seam", Severity.WARN,
                        f"{name}: 실적 {last:.1%} → 추정 첫해 {first:.1%}, 접합부 이탈 "
                        f"{desc} — 참조·드라이버 오류 재검토 또는 사업 근거 기재",
                        detail)
        else:
            f = Finding("ratio_seam", Severity.PASS,
                        f"{name}: 접합부 연속({last:.1%}→{first:.1%}, {desc} 내)", detail)
    if report is not None:
        report.add(f)
    return f


# ── 3.2 V자(스파이크-복귀) 시그니처 ─────────────────────────────────────────
def check_spike_revert(
    series: list[float],
    *,
    name: str,
    spike_pp: float = SPIKE_PP,
    neighbor_pp: float = SPIKE_NEIGHBOR_PP,
    report: ValidationReport | None = None,
) -> Finding:
    """한 해만 이탈 후 트렌드 복귀(V자) = 참조 밀림 시그니처 감지.

    "오류 vs 가정" 구분 휴리스틱: 사업 이벤트는 지속되고(레벨 시프트 — 이웃끼리도
    벌어짐), 복사 시 시작 참조를 고정하지 않은 참조 밀림은 한 해만 튄다(이웃끼리는
    일치). 비올 E-6 판정 논리("2025년부터 정상 평균으로 돌아오므로 의도된 가정이
    아니라 참조 실수")의 코드화.

    내부점 i 판정: |x[i] − (x[i−1]+x[i+1])/2| > spike_pp AND |x[i+1]−x[i−1]| < neighbor_pp.
    series 는 실적+추정 결합 비율 시계열(접합부 스파이크·추정 중간 스파이크 모두 커버).
    """
    spikes = []
    for i in range(1, len(series) - 1):
        dev = series[i] - (series[i - 1] + series[i + 1]) / 2.0
        neighbors_agree = abs(series[i + 1] - series[i - 1]) < neighbor_pp
        if abs(dev) > spike_pp and neighbors_agree:
            spikes.append({"index": i, "value": series[i], "deviation": dev,
                           "neighbors": [series[i - 1], series[i + 1]]})
    detail = {"series_name": name, "series": series, "spikes": spikes,
              "spike_pp": spike_pp, "neighbor_pp": neighbor_pp, "layer": "execution"}
    if spikes:
        worst = max(spikes, key=lambda s: abs(s["deviation"]))
        f = Finding("spike_revert", Severity.WARN,
                    f"{name}: t={worst['index']} 만 {worst['deviation']:+.1%}p 이탈 후 "
                    f"트렌드 복귀({len(spikes)}건) — 참조 밀림(복사 시 시작참조 미고정) "
                    f"시그니처. 사업 이벤트라면 근거 기재",
                    detail)
    else:
        f = Finding("spike_revert", Severity.PASS,
                    f"{name}: V자 스파이크 없음", detail)
    if report is not None:
        report.add(f)
    return f


# ── 3.3 마진 브리지 분해 (검사 + 리포트 소재 이중 목적) ──────────────────────
def opm_bridge(gpm: list[float], sga_ratio: list[float]) -> list[dict]:
    """연도별 ΔOPM = ΔGPM 기여 − Δ판관비율 기여 분해 표 (비올 §3.5(b) 재현).

    리뷰어의 첫 질문("마진이 왜 들쭉날쭉한가")에 답하는 표 — 변동이 두 요인으로
    완전 분해되면 정상 변동, 분해로 설명 안 되는 잔차는 없다(항등식: OPM=GPM−판관비율).
    """
    if len(gpm) != len(sga_ratio):
        raise ValueError(f"gpm 길이 {len(gpm)} ≠ sga_ratio {len(sga_ratio)}")
    rows = []
    for t in range(1, len(gpm)):
        gpm_contrib = gpm[t] - gpm[t - 1]
        sga_contrib = -(sga_ratio[t] - sga_ratio[t - 1])   # 판관비율 하락 = OPM 개선(+)
        rows.append({
            "t": t,
            "gpm_contrib": gpm_contrib,
            "sga_contrib": sga_contrib,
            "d_opm": gpm_contrib + sga_contrib,
            "opm_from": gpm[t - 1] - sga_ratio[t - 1],
            "opm_to": gpm[t] - sga_ratio[t],
        })
    return rows


def mix_decomposition(segments: list[SegmentSeries]) -> dict:
    """전체 원가율 변동을 믹스 효과 + 부문 원가율 효과로 완전 분해.

    Δ(Σ wₛcₛ) = Σ Δwₛ·c̄ₛ (믹스) + Σ w̄ₛ·Δcₛ (원가율),  w̄·c̄ = 양연도 평균(midpoint)
    — midpoint 가중이라 잔차가 항등적으로 0 (w'c'−wc = Δw·c̄ + w̄·Δc).

    비올 §3.5(a): 상품(저마진 유통) 비중이 GPM 을 지배 — 믹스 효과를 분리해야
    "실적 변동은 정상 / 추정만 결함" 판정이 가능하다.
    가중치 분모는 Σ 부문매출(입력된 부문 범위 내 비중).
    """
    if not segments:
        raise ValueError("segments 비어 있음")
    n = len(segments[0].revenue)
    for s in segments:
        if len(s.revenue) != n or len(s.cogs) != n:
            raise ValueError(f"부문 '{s.name}' 시계열 길이 불일치")
    total_rev = [sum(s.revenue[t] for s in segments) for t in range(n)]
    if any(tr <= 0 for tr in total_rev):
        raise ValueError("부문매출 합 ≤ 0 인 연도 존재 — 비중 정의 불가")
    w = {s.name: [s.revenue[t] / total_rev[t] for t in range(n)] for s in segments}
    c = {s.name: [(s.cogs[t] / s.revenue[t]) if s.revenue[t] > 0 else 0.0
                  for t in range(n)] for s in segments}
    ratio = [sum(w[s.name][t] * c[s.name][t] for s in segments) for t in range(n)]
    steps = []
    for t in range(1, n):
        mix = sum((w[s.name][t] - w[s.name][t - 1])
                  * (c[s.name][t] + c[s.name][t - 1]) / 2.0 for s in segments)
        rate = sum((w[s.name][t] + w[s.name][t - 1]) / 2.0
                   * (c[s.name][t] - c[s.name][t - 1]) for s in segments)
        steps.append({"t": t, "mix_effect": mix, "rate_effect": rate,
                      "total": ratio[t] - ratio[t - 1]})
    return {"ratio": ratio, "weights": w, "seg_ratios": c, "steps": steps}


def check_mix_reconciliation(
    segments: list[SegmentSeries],
    total_cogs_ratio: list[float],
    *,
    tol: float = MIX_RECON_TOL,
    report: ValidationReport | None = None,
) -> Finding:
    """가중평균 재현 검산: Σ(부문비중×부문원가율) ≟ 전체 원가율 (비올 §3.5(a)).

    불일치는 부문표↔손익 불일치 또는 부문 커버리지 누락 신호. 재현이 성립해야
    믹스 분해(mix_decomposition)의 판정을 신뢰할 수 있다 — 분해의 전제 검사.
    """
    implied = [sum(s.cogs[t] for s in segments) / sum(s.revenue[t] for s in segments)
               for t in range(len(total_cogs_ratio))]
    diffs = [i - r for i, r in zip(implied, total_cogs_ratio)]
    offenders = [{"t": t, "implied": implied[t], "reported": total_cogs_ratio[t],
                  "diff": d} for t, d in enumerate(diffs) if abs(d) > tol]
    detail = {"implied": implied, "reported": total_cogs_ratio, "tol": tol,
              "offenders": offenders, "layer": "execution"}
    if offenders:
        worst = max(offenders, key=lambda o: abs(o["diff"]))
        f = Finding("mix_reconciliation", Severity.WARN,
                    f"부문 가중평균 재현 실패 {len(offenders)}건(최대 t={worst['t']} "
                    f"{worst['diff']:+.1%}p) — 부문표↔손익 불일치 또는 커버리지 누락",
                    detail)
    else:
        f = Finding("mix_reconciliation", Severity.PASS,
                    f"부문 가중평균 재현 성립(잔차 ≤ {tol:.1%}p, {len(implied)}개년)",
                    detail)
    if report is not None:
        report.add(f)
    return f


# ── 3.4 단위경제 파생지표 연속성 ────────────────────────────────────────────
def check_derived_continuity(
    numerator: list[float],
    denominator: list[float],
    *,
    name: str,
    tol: float = DERIVED_YOY_TOL,
    report: ValidationReport | None = None,
) -> Finding:
    """파생지표(분자/분모) YoY 급변 감지 — "각 셀은 맞는데 결합하면 틀리는" 유형.

    분자·분모가 각각 자연스러워도 나눗셈이 튀면 경고. 비올 J-1(인당 인건비
    46.0→64.5, +40% — 동일 인원을 원가·판관 양쪽에 100% 배부)은 이 검산으로만
    드러난다. 1차 적용: 인당 인건비·인당 매출액(DART employee 커넥터 데이터).
    """
    derived = _ratios(numerator, denominator)
    if derived is None or len(derived) < 2:
        f = Finding("derived_continuity", Severity.PASS,
                    f"{name}: 시계열 부족/분모 ≤ 0 — 검사 생략(정보)",
                    {"series_name": name, "layer": "execution|judgment"})
    else:
        jumps = []
        for i in range(1, len(derived)):
            if derived[i - 1] == 0:
                continue
            yoy = derived[i] / derived[i - 1] - 1.0
            if abs(yoy) > tol:
                jumps.append({"index": i, "prev": derived[i - 1],
                              "cur": derived[i], "yoy": yoy})
        detail = {"series_name": name, "derived": derived, "jumps": jumps,
                  "tol": tol, "layer": "execution|judgment"}
        if jumps:
            worst = max(jumps, key=lambda j: abs(j["yoy"]))
            f = Finding("derived_continuity", Severity.WARN,
                        f"{name}: YoY 급변 {len(jumps)}건(최대 {worst['yoy']:+.0%}, "
                        f"t={worst['index']}) — 분자·분모 결합 정합성 재검토"
                        f"(배분 중복·모집단 불일치 의심)",
                        detail)
        else:
            f = Finding("derived_continuity", Severity.PASS,
                        f"{name}: YoY 변동 ±{tol:.0%} 내", detail)
    if report is not None:
        report.add(f)
    return f


# ── 3.5 컨센서스 앵커 ────────────────────────────────────────────────────────
def check_consensus_anchor(
    metric: str,
    own: float,
    consensus: float,
    *,
    source: str,
    tol_pp: float = CONSENSUS_TOL_PP,
    report: ValidationReport | None = None,
) -> Finding:
    """자기 추정 ↔ 증권사 컨센서스 괴리 게이트 (회사별 앵커).

    check_metric_vs_industry(산업 분포 prior)와 별개 — 비올 실측: 같은 파일
    research 탭에 컨센서스 GPM 78% 가 있었는데 자기 추정 71.2%(결함 산물)와
    대조가 이뤄지지 않았다. 괴리 자체는 결함이 아니다(컨센서스가 틀릴 수도) —
    "왜 다른가"를 설명할 수 있어야 한다는 신호.

    source 는 필수(가정 provenance 원칙) — 비면 provenance WARN 을 먼저 낸다.
    """
    if not source:
        f = Finding("consensus_provenance", Severity.WARN,
                    f"{metric}: 컨센서스 출처 미기재 — 대조 불가(출처 있는 값만 인정)",
                    {"metric": metric, "layer": "judgment"})
    else:
        delta = own - consensus
        detail = {"metric": metric, "own": own, "consensus": consensus,
                  "delta": delta, "source": source, "layer": "judgment"}
        if abs(delta) > tol_pp:
            f = Finding("consensus_anchor", Severity.WARN,
                        f"{metric}: 자기 추정 {own:.1%} vs 컨센서스 {consensus:.1%}"
                        f"({source}) 괴리 {delta:+.1%}p (> ±{tol_pp:.0%}p) — "
                        f"차이의 근거를 문서화하거나 추정 재검토",
                        detail)
        else:
            f = Finding("consensus_anchor", Severity.PASS,
                        f"{metric}: 컨센서스({source}) 대비 {delta:+.1%}p 내 정합",
                        detail)
    if report is not None:
        report.add(f)
    return f


# ── 3.6 성장-운전자본 정합 ───────────────────────────────────────────────────
def check_nwc_growth_consistency(
    revenue: list[float],
    delta_nwc_cash_adj: list[float],
    *,
    prior_revenue: float | None = None,
    rev_yoy_min: float = NWC_GROWTH_REV_YOY,
    min_share: float = NWC_DELTA_MIN_SHARE,
    report: ValidationReport | None = None,
) -> Finding:
    """고성장인데 운전자본 변동이 ~0 = "성장의 대가를 치르지 않는 밸류에이션" 감지.

    비올 E-1·E-3 현상: 매출 +33.5% 성장 첫해에 ΔNWC 가 0 으로 계상(참조 5년
    밀림 + 운전자산 통째 누락) — *"매출이 2.6배 늘면서 매출채권과 재고가 전혀
    늘지 않는다고 가정"* 은 사업적으로 성립 불가. |ΔNWC| 를 쓰므로 부호규약
    (현금조정/증감)과 무관하게 작동한다.

    check_working_capital_burn(과다 유출 → 흑자도산)과 반대 방향의 짝 검사
    (유출 **부재** → 밸류 과대). 선수금 사업 등 구조적 음(−)운전자본이면 근거
    기재 후 무시 — WARN only.
    """
    flags = []
    for t in range(len(revenue)):
        prev = prior_revenue if t == 0 else revenue[t - 1]
        if prev is None or prev <= 0:
            continue
        d_rev = revenue[t] - prev
        yoy = d_rev / prev
        if yoy > rev_yoy_min and abs(delta_nwc_cash_adj[t]) < min_share * abs(d_rev):
            flags.append({"index": t, "rev_yoy": yoy, "d_rev": d_rev,
                          "delta_nwc": delta_nwc_cash_adj[t]})
    detail = {"flags": flags, "rev_yoy_min": rev_yoy_min, "min_share": min_share,
              "layer": "execution|judgment"}
    if flags:
        worst = max(flags, key=lambda x: x["rev_yoy"])
        f = Finding("nwc_growth_consistency", Severity.WARN,
                    f"매출 고성장({worst['rev_yoy']:+.0%})인데 ΔNWC≈0 인 연도 "
                    f"{len(flags)}건(t={[x['index'] for x in flags]}) — 운전자본 배선"
                    f"(참조·부호) 재검토 또는 구조적 음(−)운전자본 근거 기재",
                    detail)
    else:
        f = Finding("nwc_growth_consistency", Severity.PASS,
                    "성장-운전자본 정합: 고성장 연도의 ΔNWC 반영 확인", detail)
    if report is not None:
        report.add(f)
    return f


# ── 오류 영향 분리 원장 ──────────────────────────────────────────────────────
def impact_ledger(base: DcfSpineInput, patches: list[dict]) -> list[dict]:
    """결함 수정을 한 건씩 누적 적용→재계산해 주당가치 영향을 분리 기록.

    반대 방향 오류들은 순 효과에서 서로를 가린다 — 실측: 개별 −111원/+26원이
    순 −3.0%에 은폐되어, 분리 측정 없이는 "결함이 사소했다"로 오독된다. 수정
    리뷰의 표준 산출물 형식(결함별 Δ 표)이며, 각 행이 직전 행 대비 Δ 라서
    적용 순서가 곧 원장의 서사가 된다(상류→하류 순 권장).

    patches: [{"label": 결함 설명, "fields": {DcfSpineInput 필드: 새 값}}]
    반환: [{"label", "per_share", "delta"(직전 대비), "cum_delta"(기준선 대비)}]
          — 첫 행은 기준선(base).
    """
    from .dcf import run                      # 순환 임포트 회피(런타임 지연 로드)

    valid = {f.name for f in dataclasses.fields(DcfSpineInput)}
    current = base
    baseline = run(current).per_share
    rows = [{"label": "기준선", "per_share": baseline, "delta": 0.0, "cum_delta": 0.0}]
    prev = baseline
    for p in patches:
        fields = p.get("fields") or {}
        unknown = set(fields) - valid
        if unknown:
            raise ValueError(f"알 수 없는 필드: {sorted(unknown)}")
        current = dataclasses.replace(current, **fields)
        ps = run(current).per_share
        rows.append({"label": str(p.get("label", "")), "per_share": ps,
                     "delta": ps - prev, "cum_delta": ps - baseline})
        prev = ps
    return rows


# ── 종합 실행 ────────────────────────────────────────────────────────────────
def analytical_review(
    history: FinancialHistory,
    inp: DcfSpineInput | None = None,
    *,
    forecast_segments: list[SegmentSeries] | None = None,
    report: ValidationReport | None = None,
) -> ValidationReport:
    """실적(history) × 추정(inp) 에 분석적 절차 전 검사를 적용해 리포트로 합류.

    있는 데이터만 검사한다(부재 → 해당 검사 생략, 차단 없음). 비율 산식은
    양쪽에 동일하게 적용되므로 history 의 cogs·sga 기준(D&A 포함 여부)을 스파인
    입력과 맞춰야 한다(FinancialHistory docstring).

    브리지 표(opm_bridge·mix_decomposition)는 검사가 아니라 리포트 소재라 여기서
    만들지 않는다 — API/리포트 계층이 직접 호출.
    """
    if report is None:
        report = ValidationReport()

    hist_ratio: dict[str, list[float]] = {}
    fc_ratio: dict[str, list[float]] = {}
    if history.revenue and history.cogs:
        r = _ratios(history.cogs, history.revenue)
        if r:
            hist_ratio["매출원가율"] = r
    if history.revenue and history.sga:
        r = _ratios(history.sga, history.revenue)
        if r:
            hist_ratio["판관비율"] = r
    if inp is not None:
        r = _ratios(inp.cogs, inp.revenue)
        if r:
            fc_ratio["매출원가율"] = r
        r = _ratios(inp.sga, inp.revenue)
        if r:
            fc_ratio["판관비율"] = r
        if "매출원가율" in fc_ratio and "판관비율" in fc_ratio:
            fc_ratio["영업마진(감가비 반영 전)"] = [
                1.0 - c - s for c, s in zip(fc_ratio["매출원가율"], fc_ratio["판관비율"])]
    if "매출원가율" in hist_ratio and "판관비율" in hist_ratio:
        hist_ratio["영업마진(감가비 반영 전)"] = [
            1.0 - c - s
            for c, s in zip(hist_ratio["매출원가율"], hist_ratio["판관비율"])]

    # 접합부 + V자: 실적·추정이 둘 다 있는 비율만
    for name in hist_ratio:
        if name in fc_ratio:
            check_ratio_seam(hist_ratio[name], fc_ratio[name], name=name, report=report)
            check_spike_revert(hist_ratio[name] + fc_ratio[name], name=name, report=report)

    # 성장-운전자본 정합 (추정 구간, 실적 마지막 매출을 prior 로)
    if inp is not None:
        prior = history.revenue[-1] if history.revenue else None
        check_nwc_growth_consistency(list(inp.revenue), list(inp.delta_nwc_cash_adj),
                                     prior_revenue=prior, report=report)

    # 단위경제: 인당 인건비 (실적 구간 — 추정 인원·인건비는 스파인에 없음)
    if history.labor_cost and history.headcount:
        check_derived_continuity(history.labor_cost, history.headcount,
                                 name="인당 인건비", report=report)

    # 부문: 가중평균 재현 + 부문별 원가율 접합부·V자
    if history.segments:
        if "매출원가율" in hist_ratio:
            check_mix_reconciliation(history.segments, hist_ratio["매출원가율"],
                                     report=report)
        if forecast_segments:
            fc_by_name = {s.name: s for s in forecast_segments}
            for seg in history.segments:
                fc = fc_by_name.get(seg.name)
                if fc is None:
                    continue
                a = _ratios(seg.cogs, seg.revenue)
                f = _ratios(fc.cogs, fc.revenue)
                if a and f:
                    label = f"부문 원가율({seg.name})"
                    check_ratio_seam(a, f, name=label, report=report)
                    check_spike_revert(a + f, name=label, report=report)

    return report
