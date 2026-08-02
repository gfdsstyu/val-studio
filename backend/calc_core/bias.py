"""경영진 편의(management bias) 징후 — 기준서 540 문단 14·32 의 코드화 (A5).

두 검사 모두 **개별 항목의 옳고 그름을 판정하지 않는다**. 문단 32 의 문장이 정확히
그 지점이다: "개별적으로는 합리적일지라도" 판단·결정의 **총합**이 한쪽을 향하는지 —
개별 게이트(PGR·TV비중·산업 대조)가 전부 통과한 모델에서도 잡아야 할 것이 있다는
뜻이고, 그래서 기존 게이트 아키텍처 위에 별도의 '방향성 집계 층'이 필요하다.

  · 소급 검토(문단 14): 전기 추정치 vs 실제 결과. 목적은 "당시 판단에 의문 제기"가
    아니라(기준서가 명시적으로 금지) **오차의 방향이 일관되게 한쪽인지** — 항상
    유리한 쪽으로 빗나가는 추정 프로세스는 그 자체가 편의 징후다.
  · 방향성 집계(문단 32): 감사인이 유의적 판단마다 "이 선택이 가치를 올리는 쪽(+1)
    인가 내리는 쪽(-1)인가"를 표시하면, 쏠림을 집계한다. 유리/불리의 **판정은 사람**,
    집계와 임계만 코드가 맡는다.
"""
from __future__ import annotations

from dataclasses import dataclass

from ingest.validators import Finding, Severity

LARGE_ERROR = 0.10          # 개별 추정오차 |10%| 초과 — 소급 검토 소재로 표면화
MIN_N = 3                   # 방향성 판정 최소 표본 — 2개의 일치는 우연과 구분 불가
STRONG_RATIO = 0.75         # n>=4 에서 75% 이상 쏠림이면 WARN(전부 일치가 아니어도)


@dataclass
class RetroRow:
    label: str
    estimated: float
    actual: float
    error: float | None      # (추정-실제)/실제. 실제=0 이면 None(무한대 방지)


def check_retrospective(items: list[dict]) -> tuple[list[Finding], list[RetroRow]]:
    """전기 추정 vs 실제(문단 14). rows 는 UI 표 재료, findings 는 판정."""
    findings: list[Finding] = []
    rows: list[RetroRow] = []
    for it in items:
        est, act = float(it["estimated"]), float(it["actual"])
        err = (est - act) / act if act else None
        rows.append(RetroRow(str(it.get("label", "?")), est, act,
                             round(err, 6) if err is not None else None))

    for r in rows:
        if r.error is not None and abs(r.error) > LARGE_ERROR:
            findings.append(Finding(
                "retrospective_error", Severity.WARN,
                f"'{r.label}': 당초 추정 {r.estimated:,.4g} vs 실제 {r.actual:,.4g} — "
                f"오차 {r.error:+.1%}. 당시 판단에 의문을 제기하려는 것이 아니라(540 문단 "
                "14), 추정 프로세스·가정의 당기 재사용 가능성을 점검하라",
                {"label": r.label, "error": r.error, "layer": "judgment"}))

    signed = [r for r in rows if r.error is not None and r.error != 0]
    if len(signed) >= MIN_N:
        pos = sum(1 for r in signed if r.error > 0)
        neg = len(signed) - pos
        top, side = max((pos, "과대(추정>실제)"), (neg, "과소(추정<실제)"))
        if top == len(signed):
            findings.append(Finding(
                "retrospective_direction", Severity.WARN,
                f"전기 추정오차 {len(signed)}건이 **전부 {side} 방향** — 개별 오차가 "
                "작더라도 항상 같은 쪽으로 빗나가는 프로세스는 편의 징후다(540 문단 32). "
                "유리한 방향인지의 판단은 항목 성격(수익/비용)에 따라 감사인이 한다",
                {"n": len(signed), "direction": side, "layer": "judgment"}))
        elif len(signed) >= 4 and top >= STRONG_RATIO * len(signed):
            findings.append(Finding(
                "retrospective_direction", Severity.WARN,
                f"전기 추정오차 {len(signed)}건 중 {top}건({top / len(signed):.0%})이 "
                f"{side} 방향 — 쏠림 점검 필요(540 문단 32)",
                {"n": len(signed), "top": top, "direction": side, "layer": "judgment"}))
    if not findings:
        findings.append(Finding(
            "retrospective", Severity.PASS,
            f"소급 검토 {len(rows)}건 — 방향 쏠림·대형 오차 없음", {"n": len(rows)}))
    return findings, rows


def check_bias_directionality(judgments: list[dict]) -> list[Finding]:
    """유의적 판단들의 가치 방향 집계(문단 32).

    judgments: [{label, direction}] — direction ∈ {+1: 가치 증가 쪽, -1: 감소 쪽}.
    방향 표시는 감사인의 입력이다(예: 성장률을 컨센서스 상단으로 = +1, 할인율을
    peer 하단으로 = +1). 코드는 집계·임계만 담당한다.
    """
    findings: list[Finding] = []
    dirs = [int(j["direction"]) for j in judgments if int(j.get("direction", 0)) in (1, -1)]
    n = len(dirs)
    if n < MIN_N:
        findings.append(Finding(
            "bias_directionality", Severity.WARN if n else Severity.PASS,
            (f"방향 표시된 판단이 {n}건 — 최소 {MIN_N}건은 있어야 쏠림과 우연을 구분할 "
             "수 있다(표본 부족은 통과가 아니다)") if n else "판단 미입력",
            {"n": n, "layer": "judgment"}))
        return findings
    pos = sum(1 for d in dirs if d > 0)
    neg = n - pos
    top, side = max((pos, "가치 증가"), (neg, "가치 감소"))
    if top == n:
        findings.append(Finding(
            "bias_directionality", Severity.WARN,
            f"유의적 판단 {n}건이 **전부 {side} 방향** — 각각은 합리적이어도 총합이 "
            "한쪽을 향하면 편의 징후다(540 문단 32). 오도 의도가 있다면 부정에 해당",
            {"n": n, "pos": pos, "neg": neg, "layer": "judgment"}))
    elif n >= 4 and top >= STRONG_RATIO * n:
        findings.append(Finding(
            "bias_directionality", Severity.WARN,
            f"유의적 판단 {n}건 중 {top}건({top / n:.0%})이 {side} 방향 — 쏠림 점검"
            f"(540 문단 32)", {"n": n, "pos": pos, "neg": neg, "layer": "judgment"}))
    else:
        findings.append(Finding(
            "bias_directionality", Severity.PASS,
            f"판단 {n}건 — 방향 균형(증가 {pos}·감소 {neg})", {"n": n, "pos": pos, "neg": neg}))
    return findings
