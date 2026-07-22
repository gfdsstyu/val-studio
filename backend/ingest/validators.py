"""4종 검증 엔진 — 감사 tie-out (숫자형·공백·합계·정합성).

인제스트되는 모든 값(자동 DART / 수동 복붙 / 주석 추출)이 통과해야 하는 결정론적 게이트.
철학(감린이 clean-truth 오라클): 검증은 *재구성/라운드트립 일치*로 하지, "이전 추출과의
상관"으로 하지 않는다. LLM 변형 결과도 여기서 반드시 검증된다.

4종:
  ① 숫자형(numeric-typing): 단위·콤마·괄호음수·%·년 정규화 → Decimal, 비숫자는 fail.
  ② 공백유무(blank detection): 진짜 0 / 공백 / '-' / 결측 구분.
  ③ 합계검증(sum reconciliation): 소계·총계 = 구성요소 합(허용오차).
  ④ 정합성(cross-statement tie-out): 주석↔재무제표 교차(예: 주석 감가상각 = CF D&A).

산출: ValidationReport(규칙별 pass/warn/fail + 근거). fail 있으면 인제스트 게이트가 막는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum


class Severity(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class CellKind(str, Enum):
    VALUE = "value"     # 실제 숫자
    ZERO = "zero"       # 명시적 0
    BLANK = "blank"     # 빈 문자열/공백
    DASH = "dash"       # '-' / '–' (관행상 0 또는 미해당)
    MISSING = "missing" # None (셀 부재)


@dataclass
class Finding:
    rule: str
    severity: Severity
    message: str
    detail: dict = field(default_factory=dict)


@dataclass
class ValidationReport:
    findings: list[Finding] = field(default_factory=list)

    def add(self, f: Finding) -> None:
        self.findings.append(f)

    @property
    def ok(self) -> bool:
        """fail 이 하나도 없으면 True(게이트 통과)."""
        return not any(f.severity is Severity.FAIL for f in self.findings)

    @property
    def fails(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.FAIL]

    @property
    def warns(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.WARN]


# ── 단위 스케일 (→ 백만원 기준) ────────────────────────────────────────────
UNIT_TO_MILLION = {
    "원": Decimal("1e-6"),
    "천원": Decimal("1e-3"),
    "백만원": Decimal(1),
    "백만": Decimal(1),
    "억원": Decimal(100),
    "억": Decimal(100),
    "조원": Decimal("1e6"),
    "조": Decimal("1e6"),
}

_DASH_CHARS = {"-", "–", "—", "―", "△", "▲"}  # △/▲: 회계 관행 음수 표기도 있음(문맥주의)


# ── ① 숫자형 ────────────────────────────────────────────────────────────────
def classify_cell(raw: object) -> CellKind:
    """② 공백유무 판별: 값/0/공백/대시/결측."""
    if raw is None:
        return CellKind.MISSING
    s = str(raw).strip()
    if s == "":
        return CellKind.BLANK
    if s in _DASH_CHARS:
        return CellKind.DASH
    if s in {"0", "0.0", "0.00"}:
        return CellKind.ZERO
    return CellKind.VALUE


def parse_number(raw: object, *, unit: str | None = None,
                 report: ValidationReport | None = None,
                 field_name: str = "value") -> Decimal | None:
    """① 숫자형 정규화. 실패 시 report 에 fail 기록하고 None 반환.

    처리: 천단위 콤마, 괄호음수 (1,234)→-1234, 후행 %/원/천원/백만원/억,
    선행/후행 공백. 단위 인자 주면 백만원 기준으로 스케일.
    공백/결측/대시는 fail 이 아니라 None(호출측이 blank 처리) — classify_cell 로 구분.
    """
    kind = classify_cell(raw)
    if kind in (CellKind.MISSING, CellKind.BLANK, CellKind.DASH):
        return None
    if kind is CellKind.ZERO:
        return Decimal(0)

    s = str(raw).strip()
    negative = False
    # 괄호 음수
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1].strip()
    if s.startswith("△") or s.startswith("▲"):
        negative = True
        s = s[1:].strip()

    is_percent = s.endswith("%")
    if is_percent:
        s = s[:-1].strip()

    # 내장 단위 접미사 감지
    inline_unit = None
    for u in sorted(UNIT_TO_MILLION, key=len, reverse=True):
        if s.endswith(u):
            inline_unit = u
            s = s[: -len(u)].strip()
            break
    if s.endswith("년"):
        s = s[:-1].strip()  # 내용연수

    s = s.replace(",", "").replace(" ", "")

    try:
        val = Decimal(s)
    except (InvalidOperation, ValueError):
        if report is not None:
            report.add(Finding("numeric", Severity.FAIL,
                               f"{field_name}: 숫자 파싱 실패 '{raw}'",
                               {"raw": str(raw)}))
        return None

    if negative:
        val = -val
    if is_percent:
        val = val / Decimal(100)
    eff_unit = inline_unit or unit
    if eff_unit and eff_unit in UNIT_TO_MILLION:
        val = val * UNIT_TO_MILLION[eff_unit]
    return val


# ── ③ 합계검증 ──────────────────────────────────────────────────────────────
def reconcile_sum(name: str, components: list[Decimal | None], stated_total: Decimal | None,
                  *, rel_tol: Decimal = Decimal("1e-6"), abs_tol: Decimal = Decimal("0.5"),
                  report: ValidationReport | None = None) -> Finding:
    """소계·총계 = 구성요소 합 검증. 결측 구성요소 있으면 warn."""
    present = [c for c in components if c is not None]
    if stated_total is None:
        f = Finding("sum", Severity.WARN, f"{name}: 표기 합계 결측", {"components": len(present)})
    elif len(present) < len(components):
        f = Finding("sum", Severity.WARN,
                    f"{name}: 구성요소 {len(components)-len(present)}개 결측 → 합계 불완전",
                    {"missing": len(components) - len(present)})
    else:
        s = sum(present, Decimal(0))
        diff = abs(s - stated_total)
        tol = max(abs_tol, abs(stated_total) * rel_tol)
        if diff <= tol:
            f = Finding("sum", Severity.PASS, f"{name}: 합계 일치", {"sum": str(s), "stated": str(stated_total)})
        else:
            f = Finding("sum", Severity.FAIL,
                        f"{name}: 합계 불일치 Σ={s} ≠ 표기={stated_total} (차이 {diff})",
                        {"sum": str(s), "stated": str(stated_total), "diff": str(diff)})
    if report is not None:
        report.add(f)
    return f


# ── ④ 정합성(cross-statement tie-out) ──────────────────────────────────────
def tie_out(name: str, a: Decimal | None, b: Decimal | None,
            *, rel_tol: Decimal = Decimal("1e-4"), abs_tol: Decimal = Decimal("1"),
            report: ValidationReport | None = None) -> Finding:
    """두 출처 값 교차검증(예: 주석 감가상각비 = CF D&A)."""
    if a is None or b is None:
        f = Finding("tie_out", Severity.WARN, f"{name}: 한쪽 값 결측", {"a": str(a), "b": str(b)})
    else:
        diff = abs(a - b)
        tol = max(abs_tol, abs(b) * rel_tol)
        sev = Severity.PASS if diff <= tol else Severity.FAIL
        f = Finding("tie_out", sev,
                    f"{name}: {'일치' if sev is Severity.PASS else '불일치'} ({a} vs {b}, 차이 {diff})",
                    {"a": str(a), "b": str(b), "diff": str(diff)})
    if report is not None:
        report.add(f)
    return f
