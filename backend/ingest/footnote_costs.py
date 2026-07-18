"""성격별 원가·판관비 주석 추출 백본 — 계정세분화 워크플로우 ①단(주석 표 → 성격별 금액).

fs_disagg(②세분 검증)·cost_build(③성격별 투영) 앞단의 빈 링크를 채운다: 러프한 IS 한 줄
(판관비·매출원가)을 주석 '비용의 성격별 분류' 표에서 성격별로 **추출**하고, 각 성격을
cogs/sga 로 분류 + cost_build 드라이버(method)를 **제안**한다.

원칙(사용자): 추출(숫자를 표에서 뽑기)=결정론, 판정(어느 드라이버로 볼지)=제안(유저 승인).
  - 추출: BaseParser.emit → parse_number(① 숫자형 게이트) + char_span provenance(원문 불변).
  - 분류/드라이버: fs_mapper 식 순서규칙 → confidence + uncertain, 자동확정 금지.
  - tie-out: Σ(성격별, 카테고리별) == IS 표기 판관비/매출원가 (reconcile_sum, FAIL 게이트).

출처: SourceKind.FOOTNOTE + ExtractMethod.REGEX + confidence<1(주석 파싱은 검증 필수).
BaseParser 백본 재사용(manual_paste 와 동일 규율 — 소스만 다르고 게이트는 하나).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from ingest.parsers.base import BaseParser, ParseResult
from ingest.provenance import ExtractMethod, Locator, ProvenancedValue, SourceKind
from ingest.validators import Finding, Severity, ValidationReport, reconcile_sum

# 값 토큰(콤마·괄호음수·△▲·소수·%). 성격명 = 첫 값 토큰 앞 텍스트.
_VALUE_RE = re.compile(r"\(?[−▲△-]?\d[\d,]*(?:\.\d+)?\)?%?")


# ── 성격 → (카테고리, cost_build 드라이버) 제안 규칙 (순서=우선순위, 첫 매칭 승리) ──
# category=None → 카테고리 애매(cogs/sga 둘 다 가능) → 유저 지정. method = cost_build.CostLine.method.
_NATURE_RULES: list[tuple[str | None, str, list[str], float, str]] = [
    ("sga", "headcount",
     ["급여", "임금", "상여", "퇴직급여", "종업원급여", "인건비", "노무비", "복리후생", "복리"],
     0.8, "인원×인당급여(+상여·퇴직) headcount 드라이버 후보 — 승인 필요"),
    (None, "fa_dep",
     ["감가상각", "무형자산상각", "상각비", "감가"],
     0.85, "FA 스케줄 연동(fa_dep) — cogs/sga 배분비율은 유저 지정"),
    ("sga", "cpi",
     ["외주", "지급수수료", "수수료", "용역", "위탁"],
     0.6, "물가연동(cpi) 후보 — 매출연동(ratio)일 수도, 유저 판단"),
    ("cogs", "growth",
     ["원재료", "재료비", "부재료", "소모품", "재료"],
     0.7, "원재료 증가율(growth) 또는 매출연동(ratio)"),
    (None, "ratio",
     ["경비", "수도광열", "전력", "가스", "운반", "임차료", "지급임차"],
     0.6, "매출/생산 연동(ratio) 후보"),
    (None, "growth",
     ["세금과공과", "광고선전", "대손", "접대", "여비", "보험", "수선"],
     0.55, "증가율(growth) 후보"),
]


def suggest_driver(nature: str) -> tuple[str | None, str, float, str | None]:
    """성격명 → (category|None, method, confidence, note). 무매칭=(None,'growth',0,사유).

    fs_mapper 와 동일 철학: 제안일 뿐 유저 승인 전까지 확정 아님. 첫 매칭 규칙 승리.
    """
    n = "".join(str(nature).split())
    for cat, method, kws, conf, note in _NATURE_RULES:
        for kw in kws:
            if kw in n:
                return cat, method, conf, note
    return None, "growth", 0.0, "무매칭 — 카테고리·드라이버 유저 지정 필요"


@dataclass
class NatureCost:
    """성격별 원가 1행. 추출값(amounts) + 분류/드라이버 제안. uncertain 이면 유저 지정 필요."""
    name: str
    category: str | None                 # 'cogs' | 'sga' | None(애매 → 유저 지정)
    method: str                          # 제안 cost_build 드라이버(growth|ratio|headcount|cpi|fa_dep)
    method_confidence: float
    amounts: dict[str, Decimal]          # {year: 금액(백만원 기준)}
    uncertain: bool
    note: str | None = None
    values: list[ProvenancedValue] = field(default_factory=list)  # 셀별 provenance(감사추적)

    def latest(self, years: list[str]) -> Decimal | None:
        """최근 연도 금액(cost_build base 시드용). 열 순서 무관 — 숫자연도면 max 로 선택."""
        present = [y for y in years if y in self.amounts]
        if not present:
            return None
        numeric = [y for y in present if y.isdigit()]
        if numeric:
            return self.amounts[max(numeric, key=int)]
        return self.amounts[present[-1]]              # 비숫자 열 라벨은 마지막 열


class FootnoteCostParser(BaseParser):
    """주석 '비용의 성격별 분류' 표 복붙/HTML텍스트 → 성격별 금액(provenance) + 드라이버 제안.

    입력 형태(헤더행 선택): 첫 토큰=성격명, 이후=연도별 금액.
        구분        2024      2023
        급여        12,340    11,200
        퇴직급여     1,500     1,300
        감가상각비   3,200     3,000
    헤더행(값 토큰이 모두 연도) 자동감지. 각 셀은 f'{성격}_{연도}' 필드로 emit(숫자형 게이트
    + char_span). 성격명은 첫 값 토큰 앞 텍스트로 잘라낸다.
    """
    source_kind = SourceKind.FOOTNOTE
    default_method = ExtractMethod.REGEX

    def __init__(self, source_id: str, *, note_no: int | None = None,
                 unit: str | None = None, confidence: float = 0.85) -> None:
        super().__init__(source_id, default_confidence=confidence)
        self.note_no = note_no
        self.unit = unit
        self.text = ""
        self.years: list[str] = []

    @staticmethod
    def _is_year(tok: str) -> bool:
        t = tok.strip().replace(",", "").rstrip("년")
        return t.isdigit() and 1990 <= int(t) <= 2100

    def extract(self, raw: object) -> ParseResult:
        # 원문 불변: 정규화한 text 를 기준으로 char span(text[start:end]==raw_text 불변식).
        text = str(raw).replace("\r\n", "\n").replace("\r", "\n")
        self.text = text

        natures: list[NatureCost] = []
        years: list[str] | None = None
        pos = 0
        for line in text.split("\n"):
            line_start = pos
            pos += len(line) + 1                     # +1 = '\n' 구분자
            matches = list(_VALUE_RE.finditer(line))
            if not matches:
                # 값 없는 줄: 섹션 헤더일 수도, 값 읽기 실패일 수도. 성격 라벨로 보이면
                # WARN(감사 표면화) — 값 못 읽은 성격이 조용히 드롭돼 tie-out 만 어긋나는 걸 방지.
                stripped = line.strip()
                if stripped and years is not None and suggest_driver(stripped)[2] > 0:
                    self.result.report.add(Finding(
                        "numeric", Severity.WARN,
                        f"'{stripped}' 성격 라벨인데 값 토큰 없음 — 읽기 실패/공백 확인",
                        {"line": stripped}))
                continue
            label = line[: matches[0].start()].strip()
            val_tokens = [m.group() for m in matches]

            # 헤더행 자동감지: 값 토큰이 모두 연도 → 열 라벨로 채택(1회)
            if years is None and val_tokens and all(self._is_year(t) for t in val_tokens):
                years = [t.strip().replace(",", "").rstrip("년") for t in val_tokens]
                continue
            if not label:
                continue                              # 성격명 없는 값 줄은 건너뜀

            cols = years or [f"c{i + 1}" for i in range(len(matches))]
            cat, method, conf, note = suggest_driver(label)
            amounts: dict[str, Decimal] = {}
            cells: list[ProvenancedValue] = []
            for col, m in zip(cols, matches):
                fn = f"{label}_{col}"
                cs = line_start + m.start()
                ce = line_start + m.end()
                pv = self.emit(
                    fn, m.group(), unit=self.unit,
                    locator=Locator(note_no=self.note_no),
                    char_start=cs, char_end=ce,
                    note=f"성격별 분류 '{label}'×{col}",
                )
                cells.append(pv)
                if pv.value is not None:
                    amounts[col] = pv.value
            natures.append(NatureCost(
                name=label, category=cat, method=method, method_confidence=conf,
                amounts=amounts, uncertain=(cat is None), note=note, values=cells,
            ))

        self.years = years or (
            [f"c{i + 1}" for i in range(len(natures[0].values))] if natures else []
        )
        self._natures = natures
        return self.result

    @property
    def natures(self) -> list["NatureCost"]:
        return getattr(self, "_natures", [])


# ── tie-out: Σ(성격별, 카테고리별) == IS 표기 판관비/매출원가 (④ 정합성) ──────────
def _roll_up(natures: list[NatureCost], category: str, year: str) -> list[Decimal | None]:
    """해당 카테고리로 확정된 성격들의 연도 금액 리스트(reconcile_sum 구성요소)."""
    return [n.amounts.get(year) for n in natures if n.category == category]


def costs_tieout(natures: list[NatureCost], *, year: str,
                 stated_sga: Decimal | None = None,
                 stated_cogs: Decimal | None = None,
                 report: ValidationReport | None = None) -> ValidationReport:
    """성격별 합계 tie-out 게이트. category 미지정(uncertain) 성격은 롤업 불가 → WARN.

    stated_sga/stated_cogs: IS 표기 판관비/매출원가(백만원). 준 것만 검증한다.
    reconcile_sum(③ 합계검증)을 카테고리별로 재사용 — 검증 primitive 는 validators, 도메인
    조합만 여기(레이어 분리).
    """
    report = report or ValidationReport()
    uncertain = [n.name for n in natures if n.category is None]
    if uncertain:
        report.add(Finding(
            "by_nature_tieout", Severity.WARN,
            f"카테고리 미지정 성격 {len(uncertain)}건 {uncertain} — 롤업 제외, tie-out 불완전 "
            f"(유저가 cogs/sga 지정 필요)",
            {"uncertain": uncertain, "year": year},
        ))
    if stated_sga is not None:
        reconcile_sum(f"판관비 성격별 Σ({year})", _roll_up(natures, "sga", year),
                      stated_sga, report=report)
    if stated_cogs is not None:
        reconcile_sum(f"매출원가 성격별 Σ({year})", _roll_up(natures, "cogs", year),
                      stated_cogs, report=report)
    return report


# ── 하류 배선: fs_disagg(②) 프리필 + cost_build(③) CostLine 초안 ─────────────────
def to_disagg_block(natures: list[NatureCost], category: str, *, parent: str,
                    years: list[str], unit: str | None = "백만원") -> dict:
    """해당 카테고리 성격들 → fs_disagg 블록(children). 세분 합보존을 ②단이 재검증하도록.

    stated total 은 fs_disagg 가 요구하므로 호출측이 periods[year]['total'] 을 채운다
    (여기선 children 만; total 은 IS 값으로 상위에서 주입).
    """
    periods: dict[str, dict] = {}
    for y in years:
        children = {n.name: str(n.amounts[y]) for n in natures
                    if n.category == category and y in n.amounts}
        periods[y] = {"total": None, "children": children}
    return {"parent": parent, "unit": unit, "periods": periods}


def to_cost_line_drafts(natures: list[NatureCost], years: list[str]) -> list[dict]:
    """성격별 추출 → cost_build.CostLine 생성용 초안(dict). base=최근연도, method=제안.

    dict 로 방출(유저가 UI 에서 파라미터 채움 후 CostLine 생성) — 자동확정 금지 원칙.
    headcount/ratio 등은 인원·pct 벡터가 유저 입력이라 여기선 base·method·category 만 시드.
    """
    drafts: list[dict] = []
    for n in natures:
        base = n.latest(years)
        drafts.append({
            "name": n.name,
            "category": n.category,          # None 이면 유저 지정 필요
            "method": n.method,
            "base": None if base is None else float(base),
            "confidence": n.method_confidence,
            "uncertain": n.uncertain,
            "note": n.note,
        })
    return drafts


def parse_footnote_costs(text: str, *, source_id: str = "주석", note_no: int | None = None,
                         unit: str | None = None, confidence: float = 0.85
                         ) -> tuple[list[NatureCost], ParseResult]:
    """편의 진입점: 복붙 텍스트 → (성격별 리스트, ParseResult). report.ok=False 면 게이트 차단."""
    p = FootnoteCostParser(source_id, note_no=note_no, unit=unit, confidence=confidence)
    p.extract(text)
    return p.natures, p.result
