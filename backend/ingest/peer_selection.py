"""유사회사(peer) 선정 워크플로우 — 할인율 서식 4-step 의 실행 엔진.

방법론 정본: [[리포트예시_클래시스]] §E (클래시스 실측 83→11→9→6사),
[[wacc_할인율서식]] §1 (서식 Step0~3). 원칙 = **LLM 은 Step2(사업 유사성)만**,
나머지는 결정론 — 재현·감사 가능. 모든 후보는 선정/탈락 스텝·사유가 남는다
(감사인 "왜 이 peer 인가" 방어 산출물).

  Step0 대상 리서치  → Company Brief 재사용(이 모듈 밖, 0단계 산출물)
  Step1a 코드 확정   → rough 유사회사 시드 → 그들의 KSIC 역산 [판단+역산]
  Step1b 모집단 필터 → 확정 코드(2~3개 union)로 풀 필터       [결정론]
  Step2 사업 유사성  → LLM 판정(Step2Judgment 스키마) 주입   [LLM, 사유 필수]
  Step3 매출 비중    → 관련사업 매출비중 임계(기본 70%)      [결정론]
  Step4 기타         → 상장연수(베타포인트)·거래정지          [결정론]

⚠️ Step1 실무 교정(사용자): KSIC 코드만으로 업종이 완전히 갈리지 않아 **코드 2~3개를
가져오는 게 실무 표준**이고, 어떤 코드를 쓸지 자체가 "먼저 유사회사를 rough 하게
조사 → 걔네 KSIC 를 찾아 역산"하는 반복 과정이다 → codes_from_seed_peers() 가
그 역산을 지원(Brief ⑦⑨ 경쟁사가 시드 후보). 코드 선택 근거도 params 에 남는다.

이중 소비자: 최종 peer 셋은 WACC(β·자본구조, peer_fs)와 상대가치평가(⏳향후,
peer 배수) 둘 다에 쓰인다. 여기서는 선정까지만 — FS 적재는 peer_fs 몫.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PeerCandidate:
    """모집단 후보 1사. 결정론 필터에 필요한 필드만 — 없으면 None(해당 스텝 warn)."""
    ticker: str
    name: str
    industry_code: str | None = None        # KRX/KSIC 산업코드
    revenue_share_related: float | None = None   # 관련사업 매출비중(0~1, DART)
    listed_years: float | None = None       # 상장 경과연수(베타포인트 판단)
    suspended: bool = False                 # 거래정지 여부


@dataclass(frozen=True)
class Step2Judgment:
    """LLM 의 사업 유사성 판정 — 사유(reason) 없는 판정은 거부된다.

    ⭐ LLM 원칙(사용자): LLM 은 **유저 판단의 보조** — 명확한 규칙이 없어 애매하면
    similar true/false 를 강제하지 말고 uncertain=True 로 "XX회사는 ~해서 애매합니다"를
    표면화한다. uncertain 후보는 탈락시키지 않고 유저 결정 큐(리포트 ⚖️ 섹션)로."""
    ticker: str
    similar: bool
    reason: str                             # 근거(사업보고서·홈페이지 무엇을 봤나)
    uncertain: bool = False                 # 애매 — 유저 판단 필요(자동 탈락 금지)


@dataclass
class CandidateTrace:
    """후보 1사의 여정 — 어느 스텝에서 왜 탈락/생존했나."""
    candidate: PeerCandidate
    dropped_at: str | None = None           # 'step1'.. / None=최종 선정
    reason: str = ""
    review_reason: str = ""                 # ⚖️ 애매 사유(비면 없음) — 유저 결정 큐
    warnings: list[str] = field(default_factory=list)


@dataclass
class PeerSelectionResult:
    traces: list[CandidateTrace]
    funnel: dict[str, int]                  # step→생존 수 (83→11→9→6 스타일)
    params: dict[str, object]

    @property
    def selected(self) -> list[PeerCandidate]:
        """확정 선정(애매 제외). 애매분은 needs_review — 유저 결정 후 재실행/수동 편입."""
        return [t.candidate for t in self.traces
                if t.dropped_at is None and not t.review_reason]

    @property
    def needs_review(self) -> list[CandidateTrace]:
        """⚖️ 애매 — 생존했지만 유저 판단이 필요한 후보들."""
        return [t for t in self.traces if t.dropped_at is None and t.review_reason]

    def size_note(self) -> str | None:
        """5-10 Rule(anthropic comps 정본·우리 4-step 실측 6사 정합): 확정 peer 가
        5개 미만이면 통계 취약(평균·중앙값 불안정), 10개 초과면 유사성 희석."""
        n = len(self.selected)
        if n < 5:
            return f"⚠️ 확정 peer {n}개 < 5 — 통계 취약(기준 완화 또는 애매 후보 재검토)"
        if n > 10:
            return f"⚠️ 확정 peer {n}개 > 10 — 유사성 희석(기준 강화 검토)"
        return None

    def to_markdown(self) -> str:
        """감사 방어용 리포트 — 퍼널 + 최종 peer + 회사별 탈락 사유 전량."""
        lines = ["## 유사회사 선정 결과 (4-step)", ""]
        note = self.size_note()
        if note:
            lines.append(note)
            lines.append("")
        lines.append("| 단계 | 생존 |")
        lines.append("|---|--:|")
        for step, n in self.funnel.items():
            lines.append(f"| {step} | {n} |")
        lines.append("")
        lines.append("### 최종 peer (확정)")
        for c in self.selected:
            lines.append(f"- **{c.name}** ({c.ticker})")
        if self.needs_review:
            lines.append("")
            lines.append("### ⚖️ 애매 — 유저 판단 필요 (자동 탈락하지 않음)")
            for t in self.needs_review:
                lines.append(f"- **{t.candidate.name}**({t.candidate.ticker}) — "
                             f"{t.review_reason}")
        lines.append("")
        lines.append("### 탈락 사유 (전량 — 감사 방어)")
        for t in self.traces:
            if t.dropped_at:
                lines.append(f"- {t.candidate.name}({t.candidate.ticker}) — "
                             f"{t.dropped_at}: {t.reason}")
        warns = [f"- {t.candidate.name}: {w}" for t in self.traces for w in t.warnings]
        if warns:
            lines.append("")
            lines.append("### ⚠️ 데이터 결측 경고")
            lines.extend(warns)
        lines.append("")
        lines.append("> 최종 확정은 유저 승인(human-in-the-loop) 후. "
                     "Step2 판정 사유는 LLM 산출 — 원출처(사업보고서) 재확인 가능.")
        return "\n".join(lines)


def codes_from_seed_peers(seeds: list[PeerCandidate]) -> set[str]:
    """Step1a 역산 — rough 유사회사 시드들의 KSIC 코드 union(실무: 2~3개).

    실무 플로우: 대상과 비슷해 보이는 회사 몇 개를 먼저 찾고(LLM/리서치, Brief ⑦⑨),
    그들의 산업코드를 조회해 모집단 코드로 쓴다. 코드 결측 시드는 무시."""
    return {s.industry_code for s in seeds if s.industry_code}


def normalize_ticker(ticker: str) -> str:
    """티커 비교용 정규화 — 한국 종목코드의 'A' 접두 유무·대소문자·공백 흡수.

    같은 종목이 자료원에 따라 'A145020'(FnGuide 계열) / '145020'(KRX·DART) 로 온다.
    자기제외(R11) 가 표기 차이 때문에 뚫리면 안 되므로 여기서 통일한다.
    """
    t = (ticker or "").strip().upper()
    # 한국 종목코드는 6자리 **영숫자**다(신형우선주 '00104K' 등) — `A`+6숫자 전제로 짜면
    # 'A00104K' 와 '00104K' 가 서로 다른 값이 되어 자기제외가 조용히 미발동한다.
    if len(t) == 7 and t[0] == "A" and t[1:].isalnum() and any(c.isdigit() for c in t[1:]):
        return t[1:]
    return t


def select_peers(
    candidates: list[PeerCandidate],
    *,
    target_ticker: str | None = None,
    target_industry_codes: set[str] | None = None,
    judgments: list[Step2Judgment] | None = None,
    revenue_share_threshold: float = 0.70,
    min_listed_years: float = 2.0,          # 2년 주간 베타 → 상장 ≥2년
) -> PeerSelectionResult:
    """4-step 퍼널 실행. Step2 는 judgments(LLM 산출) 주입 — 생존 후보 전원분이
    없거나 사유가 비어 있으면 ValueError(검증 게이트: 무근거 판정 금지).

    target_ticker 를 주면 **Step0 자기제외**(R11)가 먼저 돈다.
    """
    traces = [CandidateTrace(c) for c in candidates]
    funnel: dict[str, int] = {"step0 모집단(입력)": len(traces)}

    # ── Step0 자기제외(R11) ──
    # 평가대상 자신을 peer 통계에 넣으면 배수가 현재 주가 쪽으로 끌려간다(순환논법)
    # — 자기 배수로 자기를 평가하는 꼴이라 상승여력이 구조적으로 희석된다.
    # 실측 근거: 모델러스_통합모델_5.4 §4 D4 — Hugel 이 자기 peer 5사에 포함되어
    # EV/EBITDA 평균 15.595(자기제외 시 16.813), 주당가치 **7.9% 과소**.
    tgt = normalize_ticker(target_ticker) if target_ticker else ""
    if tgt:                       # 공백만 준 경우 no-op — 빈 티커 후보를 전량 오탈락시킨다
        for t in traces:
            cand = normalize_ticker(t.candidate.ticker)
            if cand and cand == tgt:
                t.dropped_at = "step0"
                t.reason = "평가대상 자기 자신 — peer 통계 자기포함은 순환논법"
        # ⚠️ target_ticker 가 없을 땐 이 행을 **찍지 않는다** — 찍으면 감사 리포트가
        # "자기제외를 돌렸고 탈락자가 없었다"로 읽혀 거짓 안심을 준다(기능 미실행인데).
        funnel["step0 자기제외"] = sum(1 for t in traces if not t.dropped_at)

    # ── Step1 산업코드 ──
    if target_industry_codes:
        for t in traces:
            code = t.candidate.industry_code
            if code is None:
                t.dropped_at, t.reason = "step1", "산업코드 결측"
            elif code not in target_industry_codes:
                t.dropped_at, t.reason = "step1", f"산업코드 불일치({code})"
    funnel["step1 산업코드"] = sum(1 for t in traces if not t.dropped_at)

    # ── Step2 사업 유사성 (LLM 판정 주입) ──
    alive = [t for t in traces if not t.dropped_at]
    jmap = {j.ticker: j for j in (judgments or [])}
    missing = [t.candidate.ticker for t in alive if t.candidate.ticker not in jmap]
    if judgments is not None and missing:
        raise ValueError(f"Step2 판정 누락: {missing} — 생존 후보 전원 판정 필요")
    unreasoned = [j.ticker for j in (judgments or []) if not j.reason.strip()]
    if unreasoned:
        raise ValueError(f"Step2 사유 없는 판정 거부: {unreasoned} — 감사 방어 불가")
    if judgments is not None:
        for t in alive:
            j = jmap[t.candidate.ticker]
            if j.uncertain:                 # 애매 → 자동 탈락 금지, 유저 결정 큐
                t.review_reason = j.reason
            elif not j.similar:
                t.dropped_at, t.reason = "step2", f"사업 비유사 — {j.reason}"
    funnel["step2 사업유사성"] = sum(1 for t in traces if not t.dropped_at)

    # ── Step3 매출 비중 ──
    for t in traces:
        if t.dropped_at:
            continue
        share = t.candidate.revenue_share_related
        if share is None:
            t.warnings.append("관련사업 매출비중 결측 — step3 통과 처리(확인 필요)")
        elif share < revenue_share_threshold:
            t.dropped_at = "step3"
            t.reason = f"관련 매출비중 {share:.0%} < 임계 {revenue_share_threshold:.0%}"
    funnel["step3 매출비중"] = sum(1 for t in traces if not t.dropped_at)

    # ── Step4 상장연수·거래정지 ──
    for t in traces:
        if t.dropped_at:
            continue
        c = t.candidate
        if c.suspended:
            t.dropped_at, t.reason = "step4", "거래정지"
        elif c.listed_years is None:
            t.warnings.append("상장연수 결측 — step4 통과 처리(확인 필요)")
        elif c.listed_years < min_listed_years:
            t.dropped_at = "step4"
            t.reason = (f"상장 {c.listed_years:.1f}년 < {min_listed_years:.0f}년 "
                        f"(베타포인트 부족)")
    funnel["step4 상장·거래"] = sum(1 for t in traces if not t.dropped_at)

    return PeerSelectionResult(
        traces=traces, funnel=funnel,
        params={"target_ticker": target_ticker,
                "industry_codes": sorted(target_industry_codes or []),
                "revenue_share_threshold": revenue_share_threshold,
                "min_listed_years": min_listed_years},
    )
