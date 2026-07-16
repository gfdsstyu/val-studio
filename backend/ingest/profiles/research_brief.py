"""기업리서치(Company Brief) 프리필 프로파일 — XBRL 이 기계로 채울 수 있는 섹션만 채운다.

[[기업리서치_양식]] 10섹션 중 XBRL 태그로 결정론 추출 가능한 3개 섹션을 프리필:
  ② 회사개요 일부  — 엔티티명·홈페이지·발행/자기주식(→유통주식비율, 주당가치 분모)
  ④ 사업부문별 매출 — SegmentsAxis(사업부문) + GeographicalAreasAxis(지역) Revenue fact
  ⑩ Financials     — 핵심계정 × 전 기간(당기·전기 비교 포함) 표

나머지 섹션(①③⑤~⑨)은 LLM 몫 — render_brief_md() 가 10섹션 골격에 프리필을 심고
LLM TODO 슬롯을 남긴 markdown 을 산출한다(0단계 워크플로우의 시작점).

실측 근거(삼성 2026Q1 원문 XBRL):
  - 사업부문 매출 = SegmentConsolidationItemsAxis=OperatingSegmentsMember + SegmentsAxis
  - 지역 매출     = GeographicalAreasAxis (CountryOfDomicileMember=국내)
  - 자기주식      = SharesInEntityHeldByEntityOrByItsSubsidiariesOrAssociates × 주식종류축
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .business_report import _CONCEPT_MAP

_SEGMENT_AXIS = "SegmentsAxis"
_SEGMENT_GATE = ("SegmentConsolidationItemsAxis", "OperatingSegmentsMember")
_GEO_AXIS = "GeographicalAreasAxis"
_SHARE_CLASS_AXIS = "ClassesOfShareCapitalAxis"
_TREASURY = "SharesInEntityHeldByEntityOrByItsSubsidiariesOrAssociates"
_ISSUED = ("NumberOfSharesIssued", "NumberOfSharesOutstanding")


@dataclass(frozen=True)
class SegmentRevenue:
    """부문/지역 1개의 매출(백만원). label 은 lab-ko 라벨(없으면 member id)."""
    axis: str
    member: str
    label: str
    period: str
    revenue: float


@dataclass
class BriefPrefill:
    """Brief ②④⑩ 기계 채움 결과. 값 없으면 None/빈 컬렉션(회귀 0 원칙)."""
    company: str | None = None
    homepage: str | None = None
    doc_period: str | None = None
    consolidation: str | None = None
    # ⑩ Financials: period → (정규필드 → 백만원)
    financials: dict[str, dict[str, float]] = field(default_factory=dict)
    # ④ 부문·지역 매출
    segments: list[SegmentRevenue] = field(default_factory=list)
    regions: list[SegmentRevenue] = field(default_factory=list)
    # ② 주식수(주) — 주식종류(라벨) → 수량. 최신 instant 기준.
    issued_shares: dict[str, float] = field(default_factory=dict)
    treasury_shares: dict[str, float] = field(default_factory=dict)

    def floating_ratio(self) -> dict[str, float]:
        """주식종류별 유통주식비율 = (발행−자기)/발행. 둘 다 있는 종류만."""
        out = {}
        for cls, issued in self.issued_shares.items():
            if issued > 0 and cls in self.treasury_shares:
                out[cls] = (issued - self.treasury_shares[cls]) / issued
        return out


def _label(labels: dict[str, str], key: str) -> str:
    lab = labels.get(key, key)
    return lab.replace(" [구성요소]", "").strip()


def _dedupe_latest_instant(cands: list) -> dict[str, float]:
    """주식종류 멤버별 최신 instant fact 값. cands = (member, period, value)."""
    best: dict[str, tuple[str, float]] = {}
    for member, period, value in cands:
        cur = best.get(member)
        if cur is None or period > cur[0]:
            best[member] = (period, value)
    return {m: v for m, (_, v) in best.items()}


def extract_research_brief(parser) -> BriefPrefill:
    """XbrlParser(extract 완료) → BriefPrefill.

    financials 는 primary_facts(연결·무차원) 전 기간을 남긴다 — 분기 XBRL 에도
    전기 비교 fact 가 태깅돼 있어 ⑩의 다개년 표가 공짜로 나온다.
    """
    labels = parser.labels
    pre = BriefPrefill()

    # ② 엔티티 (비숫자 fact)
    for f in parser.facts:
        if f.unit is not None:
            continue
        if f.concept in ("EntityRegistrantName", "EntityRegistrantNameInKorean"):
            pre.company = pre.company or f.value
        elif f.concept == "EntityHomepage":
            pre.homepage = pre.homepage or f.value

    # ⑩ Financials — 주재무제표(연결·무차원), 개념×기간별 (중복 fact 는 첫 값)
    concept_to_field = {c: fname for fname, cs in _CONCEPT_MAP for c in cs}
    seen: set[tuple[str, str]] = set()
    for f in parser.primary_facts():
        fname = concept_to_field.get(f.concept)
        if fname is None or f.unit != "KRW":
            continue
        key = (fname, f.context.period)
        if key in seen:
            continue
        seen.add(key)
        try:
            pre.financials.setdefault(f.context.period, {})[fname] = float(f.value) * 1e-6
        except ValueError:
            continue
    if pre.financials:
        latest = max(pre.financials)
        pre.doc_period = latest
        pre.consolidation = "ConsolidatedMember"

    # ④ 부문·지역 매출 (연결 Revenue + 해당 축)
    issued_cands, treasury_cands = [], []
    for f in parser.facts:
        if f.unit is None:
            continue
        dims = f.context.non_consolidation_dims
        if f.concept == "Revenue" and f.context.consolidation == "ConsolidatedMember":
            if dims.get(_SEGMENT_GATE[0]) == _SEGMENT_GATE[1] and _SEGMENT_AXIS in dims:
                m = dims[_SEGMENT_AXIS]
                pre.segments.append(SegmentRevenue(
                    _SEGMENT_AXIS, m, _label(labels, m),
                    f.context.period, float(f.value) * 1e-6))
            elif _GEO_AXIS in dims and len(dims) == 1:
                m = dims[_GEO_AXIS]
                pre.regions.append(SegmentRevenue(
                    _GEO_AXIS, m, _label(labels, m),
                    f.context.period, float(f.value) * 1e-6))
        # ② 주식수 (SHARES 단위 + 주식종류 축)
        elif f.unit and f.unit != "KRW" and _SHARE_CLASS_AXIS in dims:
            cls = _label(labels, dims[_SHARE_CLASS_AXIS])
            try:
                v = float(f.value)
            except ValueError:
                continue
            if f.concept == _TREASURY:
                treasury_cands.append((cls, f.context.period, v))
            elif f.concept in _ISSUED:
                issued_cands.append((cls, f.context.period, v))
    pre.issued_shares = _dedupe_latest_instant(issued_cands)
    pre.treasury_shares = _dedupe_latest_instant(treasury_cands)
    return pre


# ── Brief markdown 렌더(10섹션 골격 + 프리필 + LLM 슬롯) ─────────────────────
_FIELD_KO = {
    "revenue": "매출액", "operating_income": "영업이익", "profit_before_tax": "세전이익",
    "net_income": "당기순이익", "net_income_owners": "지배주주순이익",
    "total_assets": "자산총계", "total_liabilities": "부채총계", "equity": "자본총계",
    "operating_cf": "영업활동현금흐름", "cash": "현금및현금성자산",
}


def _fmt(v: float) -> str:
    return f"{v:,.0f}"


def _seg_table(rows: list[SegmentRevenue]) -> str:
    if not rows:
        return "_(XBRL 에 해당 축 없음 — LLM 이 사업보고서 본문에서 채움)_"
    periods = sorted({r.period for r in rows}, reverse=True)
    members = []
    for r in rows:                                  # 등장 순서 보존 dedupe
        if r.member not in [m for m, _ in members]:
            members.append((r.member, r.label))
    by = {(r.member, r.period): r.revenue for r in rows}
    latest = periods[0]
    total = sum(by.get((m, latest), 0.0) for m, _ in members) or 1.0
    head = "| 부문 | " + " | ".join(periods) + " | 비중(최근) |"
    sep = "|---|" + "---|" * (len(periods) + 1)
    lines = [head, sep]
    for m, lab in members:
        cells = [(_fmt(by[(m, p)]) if (m, p) in by else "-") for p in periods]
        share = by.get((m, latest), 0.0) / total
        lines.append(f"| {lab} | " + " | ".join(cells) + f" | {share:.1%} |")
    return "\n".join(lines)


def render_brief_md(pre: BriefPrefill, company_hint: str = "") -> str:
    """BriefPrefill → 10섹션 Brief 골격 markdown.

    ②④⑩은 프리필 표, 나머지는 `_(LLM: ...)_` 슬롯 — 0단계 LLM 이 이 파일을 이어서
    완성한다(무엇이 기계값·무엇이 판단인지 경계가 문서에 남음).
    """
    name = pre.company or company_hint or "?"
    fr = pre.floating_ratio()
    share_lines = []
    for cls, n in pre.issued_shares.items():
        t = pre.treasury_shares.get(cls)
        r = fr.get(cls)
        share_lines.append(
            f"- {cls}: 발행 {_fmt(n)}주"
            + (f", 자기주식 {_fmt(t)}주" if t is not None else "")
            + (f", **유통비율 {r:.2%}**" if r is not None else ""))
    if not share_lines and pre.treasury_shares:
        share_lines = [f"- {c}: 자기주식 {_fmt(v)}주 (발행주식수는 LLM 보완)"
                       for c, v in pre.treasury_shares.items()]

    periods = sorted(pre.financials, reverse=True)
    fin_rows = []
    if periods:
        fields = [f for f in _FIELD_KO if any(f in pre.financials[p] for p in periods)]
        fin_rows.append("| 계정(백만원) | " + " | ".join(periods) + " |")
        fin_rows.append("|---|" + "---|" * len(periods))
        for f in fields:
            cells = [(_fmt(pre.financials[p][f]) if f in pre.financials[p] else "-")
                     for p in periods]
            fin_rows.append(f"| {_FIELD_KO[f]} | " + " | ".join(cells) + " |")
    fin_table = "\n".join(fin_rows) or "_(XBRL 미제공 — LLM 보완)_"

    return f"""# Company Brief — {name}
> 기준: XBRL {pre.doc_period or '?'} ({pre.consolidation or '?'}) — ②④⑩ 기계 프리필,
> 나머지 섹션은 0단계 LLM 이 원자료(사업보고서 본문·IR·리서치)로 완성. 출처 URL 병기 규칙.

## ① Summary (투자 포인트)
_(LLM: 성장 동인 핵심 3줄)_

## ② 회사 개요
- 회사명: {name}
- 홈페이지: {pre.homepage or '_(LLM)_'}
{chr(10).join(share_lines) or '- _(LLM: 발행·자기주식)_'}
- _(LLM: 설립일·대표·주주구성(지분율)·신용등급·상장일)_

## ③ 자회사 지분율·사업 구조도
_(LLM: 지배구조 — SOTP 파트 정의용)_

## ④ 사업부문·종속회사별 매출 (XBRL 프리필, 백만원)
### 사업부문(세그먼트)
{_seg_table(pre.segments)}

### 지역별
{_seg_table(pre.regions)}

## ⑤ 주요 제품 설명
_(LLM: 제품·향처·시장점유율 — 매출 추정방식 선택 근거)_

## ⑥ Value Chain
_(LLM: 전방·후방·자체조달 — 원가 변동/고정 판단 근거)_

## ⑦ 주요 고객사·경쟁사
_(LLM: 고객 집중도·경쟁사 리스트 — QOE·peer 후보)_

## ⑧ 시장 분석
_(LLM: 제품군별 시장규모·성장률(CAGR)·경쟁 지형 — PGR·점유율 추정 근거)_

## ⑨ 경쟁사 밸류에이션 비교
_(LLM: peer 배수(PER/EV 등) — peer 선정·상대가치)_

## ⑩ Financials (XBRL 프리필, 백만원)
{fin_table}

_(LLM: 전방산업 전망 서술 보완)_
"""
