"""수동 복붙 커넥터 — API 없는 소스(Bloomberg β·KOFIABOND Kd 매트릭스·한공회 MRP).

사용자 확정 UX: Bloomberg/한공회 값은 **사용자가 복붙**한다. 복붙도 자동(DART/ECOS)과
**동일한 validators 게이트**를 통과해야 calc_core 에 입력된다 — 소스만 다르고 규율은 하나.

복붙 특유 위험(사람 손 = 오타·행열 밀림·단위 혼동)에 두 방어선:
  ① validators.parse_number  — 콤마·괄호음수·%→비율·단위(자동/복붙 공통 ① 숫자형 게이트)
  ② 도메인 범위 sanity        — 베타 0~3·금리 0~30%·MRP 2~15% 밖이면 FAIL/WARN

provenance: SourceKind.MANUAL + ExtractMethod.MANUAL + 붙여넣은 날짜/사용자.
confidence=0.9(<1) 로 방출 → merge_confidence(약한 고리)가 이 값 파생 WACC 신뢰도를 낮춤.
BaseParser 백본 재사용(emit = 정규화·검증·출처부착 자동).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ingest.parsers.base import BaseParser, ParseResult
from ingest.provenance import ExtractMethod, Locator, SourceKind
from ingest.validators import Finding, Severity


# ── 도메인 범위 sanity (hard=FAIL 경계, soft=WARN 경계) ────────────────────────
# (hard_lo, hard_hi, soft_lo, soft_hi). 값은 파싱 후 기준(rate/mrp 는 비율).
_SANITY: dict[str, tuple[Decimal, Decimal, Decimal, Decimal]] = {
    "beta": (Decimal("0"), Decimal("3.0"), Decimal("0.2"), Decimal("2.0")),
    "rate": (Decimal("0"), Decimal("0.30"), Decimal("0.005"), Decimal("0.15")),
    "mrp":  (Decimal("0.02"), Decimal("0.15"), Decimal("0.05"), Decimal("0.11")),
}


def check_range(field_name: str, value: Decimal | None, kind: str,
                *, report=None) -> Finding:
    """도메인 범위 sanity: hard 경계 밖=FAIL, soft 경계 밖=WARN, 안=PASS.

    복붙 오타(베타 4.5·금리 350%)를 결정론적으로 잡는 2차 방어선. kind 미등록이면 PASS.
    value 가 None(파싱 실패)이면 numeric 게이트가 이미 fail 기록 → 여기선 WARN 스킵.
    """
    bounds = _SANITY.get(kind)
    if value is None:
        f = Finding("range", Severity.WARN, f"{field_name}: 값 없음(파싱 실패) — 범위검사 불가",
                    {"kind": kind})
    elif bounds is None:
        f = Finding("range", Severity.PASS, f"{field_name}: 범위규칙 없음({kind})", {"kind": kind})
    else:
        hlo, hhi, slo, shi = bounds
        detail = {"kind": kind, "value": str(value), "hard": [str(hlo), str(hhi)]}
        if not (hlo <= value <= hhi):
            f = Finding("range", Severity.FAIL,
                        f"{field_name}={value} 이 {kind} 허용범위[{hlo}~{hhi}] 밖 — 복붙 오타/단위 의심",
                        detail)
        elif not (slo <= value <= shi):
            f = Finding("range", Severity.WARN,
                        f"{field_name}={value} 이 {kind} 통상범위[{slo}~{shi}] 밖 — 확인 권장",
                        detail)
        else:
            f = Finding("range", Severity.PASS, f"{field_name}={value} {kind} 범위 OK", detail)
    if report is not None:
        report.add(f)
    return f


class PasteParser(BaseParser):
    """복붙 텍스트 → ProvenancedValue. MANUAL 출처 + 붙여넣은 날짜/사용자 태깅.

    scalar(β·MRP·Rf 단건)와 matrix(Kd 등급×만기) 두 형태를 지원. 각 값에 도메인 범위
    sanity 를 걸어 report 에 Finding 추가. 게이트: report.ok=False(FAIL) 면 인제스트 차단.
    """
    source_kind = SourceKind.MANUAL
    default_method = ExtractMethod.MANUAL

    def __init__(self, source_id: str, *, pasted_at: str, user: str | None = None,
                 confidence: float = 0.9) -> None:
        super().__init__(source_id, default_confidence=confidence)
        self.pasted_at = pasted_at
        self.user = user

    def _note(self, extra: str | None = None) -> str:
        who = f"/{self.user}" if self.user else ""
        base = f"복붙 @{self.pasted_at}{who}"
        return f"{base}; {extra}" if extra else base

    def extract(self, raw: object) -> ParseResult:
        """기본 경로: 'label<TAB/공백>값' 줄들을 rate 로 방출(범용 복붙).

        형태 특화가 필요하면 parse_scalar / parse_bond_matrix 를 직접 호출한다.
        """
        for line in str(raw).strip().splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.replace("\t", " ").split()
            if len(parts) < 2:
                continue
            self.parse_scalar(parts[0], parts[-1], kind="rate")
        return self.result

    def parse_scalar(self, field_name: str, raw_text: str, *, kind: str,
                     note: str | None = None) -> ParseResult:
        """단건 값(β·MRP·Rf) 방출 + 범위검사. rate/mrp 는 %가 없으면 붙여 비율화."""
        rt = raw_text
        if kind in ("rate", "mrp") and isinstance(rt, str) and not rt.strip().endswith("%"):
            rt = rt.strip() + "%"
        pv = self.emit(field_name, rt, note=self._note(note))
        check_range(field_name, pv.value, kind, report=self.result.report)
        return self.result

    def parse_bond_matrix(self, text: str, *, tenors: list[str] | None = None
                          ) -> "BondYieldMatrix":
        """Kd 신용등급×만기 회사채 수익률 매트릭스 복붙 → 구조화 + 셀별 방출·검사.

        형태(헤더행 선택): 첫 토큰=등급 라벨, 이후 토큰=만기별 수익률(%).
            등급\\  1Y    2Y    3Y    5Y
            AAA    3.21  3.35  3.48  3.72
            AA+    3.45  ...
        tenors 미지정 시 헤더행(숫자 아닌 첫 줄)에서 만기 라벨 추출. 각 셀은
        f'{grade}_{tenor}' 필드로 rate 방출(범위검사 포함). 셀 결측은 건너뜀.
        """
        lines = [ln.rstrip() for ln in text.strip().splitlines() if ln.strip()]
        matrix: dict[str, dict[str, Decimal]] = {}
        # 헤더행 판정: 첫 줄의 값 토큰이 대부분 비숫자면 만기 헤더
        if tenors is None and lines:
            head = lines[0].replace("\t", " ").split()
            val_tokens = head[1:]
            if val_tokens and not _mostly_numeric(val_tokens):
                tenors = val_tokens
                lines = lines[1:]
        for row in lines:
            cells = row.replace("\t", " ").split()
            if len(cells) < 2:
                continue
            grade, vals = cells[0], cells[1:]
            cols = tenors or [f"c{i+1}" for i in range(len(vals))]
            matrix.setdefault(grade, {})
            for tenor, cell in zip(cols, vals):
                fn = f"{grade}_{tenor}"
                self.parse_scalar(fn, cell, kind="rate",
                                  note=f"Kd matrix {grade}×{tenor}")
                pv = self.result.by_name(fn)
                if pv and pv.value is not None:
                    matrix[grade][tenor] = pv.value
        return BondYieldMatrix(matrix=matrix, tenors=tenors or [],
                               source_id=self.source_id, pasted_at=self.pasted_at)


def _mostly_numeric(tokens: list[str]) -> bool:
    ok = 0
    for t in tokens:
        try:
            Decimal(t.replace(",", "").rstrip("%"))
            ok += 1
        except Exception:  # noqa: BLE001
            pass
    return ok >= max(1, len(tokens) // 2 + 1)


# ── 구조화 산출 (wacc.py Kd 소비) ─────────────────────────────────────────────
@dataclass(frozen=True)
class BondYieldMatrix:
    """신용등급×만기 수익률 매트릭스(비율). Kd(pre-tax) 룩업의 소스."""
    matrix: dict[str, dict[str, Decimal]]
    tenors: list[str]
    source_id: str = ""
    pasted_at: str = ""

    def yield_of(self, grade: str, tenor: str) -> Decimal | None:
        return self.matrix.get(grade, {}).get(tenor)

    def grades(self) -> list[str]:
        return list(self.matrix)


# ── 편의 함수 (단건 복붙) ─────────────────────────────────────────────────────
def paste_beta(raw_text: str, *, source_id: str, pasted_at: str,
               user: str | None = None, field_name: str = "beta") -> ParseResult:
    """Bloomberg/한공회 β 단건 복붙. 범위 0~3(통상 0.2~2.0) sanity."""
    p = PasteParser(source_id, pasted_at=pasted_at, user=user)
    return p.parse_scalar(field_name, raw_text, kind="beta")


def paste_mrp(raw_text: str, *, source_id: str, pasted_at: str,
              user: str | None = None, field_name: str = "mrp") -> ParseResult:
    """한공회 시장위험프리미엄(MRP) 단건 복붙. 범위 2~15%(통상 5~11%) sanity."""
    p = PasteParser(source_id, pasted_at=pasted_at, user=user)
    return p.parse_scalar(field_name, raw_text, kind="mrp")


def paste_risk_free(raw_text: str, *, source_id: str, pasted_at: str,
                    user: str | None = None, field_name: str = "risk_free") -> ParseResult:
    """국고채 무위험이자율 Rf 단건 복붙(KOFIABOND/Bloomberg). 금리 0~30% sanity."""
    p = PasteParser(source_id, pasted_at=pasted_at, user=user)
    return p.parse_scalar(field_name, raw_text, kind="rate")
