"""DART 직원현황(empSttus) 커넥터 — 노무비 headcount 드라이버 실측 시드 + cross-source tie-out.

계정세분화 워크플로우에서 footnote_costs 의 성격='급여/인건비'(what)에 DART 직원현황의
인원수·급여총액(how much)을 붙여 cost_build 의 headcount 드라이버(인원×인당급여)를 채운다.

감사 가치(cross-source tie-out): 주석 성격별 '급여' == DART 연간급여총액 — 같은 노무비를
두 출처가 독립적으로 말하므로, 어긋나면 발견사항(validators.tie_out).

단위 주의: 직원수(sm)는 **명(count, 무단위)**, 급여총액(fyer_salary_totamt)은 **원**.
같은 파서 안에서 필드별 unit 을 달리 준다. 출처: SourceKind.DART + STRUCTURED.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .parsers.base import BaseParser, ParseResult
from .provenance import ExtractMethod, Locator, ProvenancedValue, SourceKind
from .validators import Finding, Severity, ValidationReport, tie_out


class EmployeeParser(BaseParser):
    """DART empSttus 응답 list[] → 행별 인원수·급여총액(출처부착).

    행 필드: fo_bbm(사업부문), sexdstn(성별), sm(합계 인원), fyer_salary_totamt(연간급여
    총액·원), jan_salary_am(1인평균급여·원), rcept_no. '-'/공백은 blank 로 기록(오제외 방지).
    """
    source_kind = SourceKind.DART
    default_method = ExtractMethod.STRUCTURED

    def extract(self, raw: object) -> ParseResult:
        rows = raw if isinstance(raw, list) else []
        for i, row in enumerate(rows):
            div = str(row.get("fo_bbm", "")).strip() or f"부문{i+1}"
            sex = str(row.get("sexdstn", "")).strip()
            tag = f"{div}/{sex}" if sex else div
            loc = Locator(rcept_no=row.get("rcept_no"))
            # 인원수 — 무단위(명)
            self.emit_blank_aware(f"{tag}:인원", row.get("sm"), locator=loc,
                                  note=f"직원현황 {tag} 합계인원")
            # 연간급여총액 — 원 → 백만원 자동환산
            self.emit_blank_aware(f"{tag}:급여총액", row.get("fyer_salary_totamt"),
                                  unit="원", locator=loc, note=f"직원현황 {tag} 연간급여총액")
        return self.result


@dataclass
class EmployeeSnapshot:
    """한 보고서(연도)의 직원현황 집계 — cost_build headcount 드라이버 base 시드."""
    year: str
    headcount: Decimal                        # 총 인원(전 부문·성별 합)
    total_salary: Decimal                     # 연간급여총액 합(백만원)
    avg_wage: Decimal | None                  # 인당급여 = 급여총액/인원(백만원/명)
    by_division: dict[str, dict]              # {부문: {'인원':.., '급여총액':..}}
    values: list[ProvenancedValue] = field(default_factory=list)
    report: ValidationReport = field(default_factory=ValidationReport)


def aggregate_employee_status(rows: list, *, source_id: str, year: str
                              ) -> EmployeeSnapshot:
    """empSttus 행들 → 총인원·급여총액·인당급여 집계 + 부문별 세부.

    인원 0 이면 avg_wage=None + WARN(급여만 있고 인원 결측 = 인당 산출 불가).
    """
    p = EmployeeParser(source_id)
    p.extract(rows)
    report = p.result.report

    total_hc = Decimal(0)
    total_sal = Decimal(0)
    by_div: dict[str, dict] = {}
    for i, row in enumerate(rows):
        div = str(row.get("fo_bbm", "")).strip() or f"부문{i+1}"
        sex = str(row.get("sexdstn", "")).strip()
        tag = f"{div}/{sex}" if sex else div
        hc = p.result.value_of(f"{tag}:인원")
        sal = p.result.value_of(f"{tag}:급여총액")
        if hc is not None:
            total_hc += hc
        if sal is not None:
            total_sal += sal
        slot = by_div.setdefault(div, {"인원": Decimal(0), "급여총액": Decimal(0)})
        slot["인원"] += hc or Decimal(0)
        slot["급여총액"] += sal or Decimal(0)

    avg_wage: Decimal | None = None
    if total_hc > 0:
        avg_wage = (total_sal / total_hc).quantize(Decimal("0.0001"))
    else:
        report.add(Finding("employee", Severity.WARN,
                           f"{year} 총 인원 0/결측 — 인당급여 산출 불가", {"year": year}))

    return EmployeeSnapshot(
        year=year, headcount=total_hc, total_salary=total_sal, avg_wage=avg_wage,
        by_division=by_div, values=p.result.values, report=report,
    )


def _grow(base: float, rate: float, years: int) -> list[float]:
    """base 를 연율 rate 로 years 년 복리 전개 → [base·(1+r), base·(1+r)^2, ...]."""
    out, acc = [], base
    for _ in range(years):
        acc *= (1.0 + rate)
        out.append(acc)
    return out


def to_headcount_costline(snap: EmployeeSnapshot, *, name: str = "노무비",
                          category: str = "sga", years: int = 5,
                          headcount_growth: float = 0.0, wage_growth: float = 0.0,
                          bonus_rate: float = 0.0, severance_rate: float = 0.0) -> dict:
    """직원현황 집계 → cost_build.CostLine(headcount) 생성용 dict.

    base 인원·인당급여를 성장률로 전개해 headcount[]·wage_per_head[] 벡터 시드.
    method='headcount' → 노무비 = 인원×인당급여×(1+상여율+퇴직급여율). growth 는 유저 가정.
    avg_wage 없으면(인원0) None 반환 — 드라이버 구성 불가(유저 수기 필요).
    """
    if snap.avg_wage is None:
        return {"name": name, "category": category, "method": "headcount",
                "headcount": None, "wage_per_head": None,
                "note": "인당급여 산출 불가(인원 결측) — 수기 입력 필요"}
    base_hc = float(snap.headcount)
    base_wage = float(snap.avg_wage)
    return {
        "name": name, "category": category, "method": "headcount",
        "headcount": _grow(base_hc, headcount_growth, years),
        "wage_per_head": _grow(base_wage, wage_growth, years),
        "bonus_rate": bonus_rate, "severance_rate": severance_rate,
        "note": f"DART 직원현황 {snap.year} base: 인원 {base_hc:.0f}명 × "
                f"인당 {base_wage:.2f}백만원",
    }


def tieout_labor_cost(footnote_salary: Decimal | None, snap: EmployeeSnapshot,
                      *, rel_tol: Decimal = Decimal("0.05"),
                      report: ValidationReport | None = None) -> Finding:
    """cross-source tie-out: 주석 성격별 '급여' 금액 == DART 연간급여총액(백만원).

    두 독립 출처가 같은 노무비를 말하는지 대조. rel_tol 5%(급여총액엔 상여·복리후생 포함/
    미포함 차이가 있어 정합성 tie_out 기본 1e-4 보다 느슨). 어긋나면 FAIL(발견사항).
    """
    return tie_out("노무비 주석 vs DART 급여총액", footnote_salary, snap.total_salary,
                   rel_tol=rel_tol, abs_tol=Decimal("1"), report=report)
