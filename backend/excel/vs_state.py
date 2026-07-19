"""`_VS_STATE`·`Claude Log` 시트 파서 — 스킬 세션의 감사증적을 웹 모델로 이관.

Claude for Excel 에서 `excel-valuation-workbook` 스킬이 워크북에 남기는 두 증적을
읽어 구조화한다. 워크북이 곧 상태라는 규약(SKILL.md 1.7) 때문에, 웹이 이걸 읽지
않으면 스킬 세션에서 통과한 게이트·확정한 가정·출처가 import 시 전부 유실된다.

  `_VS_STATE` : A열 키/B열 값 + `가정 대장`(가정명·값·출처유형·근거·승인상태) 블록.
                레이아웃 정본은 스킬 `scripts/scaffold.py::_add_state_sheet`.
  `Claude Log`: Claude for Excel 세션 로깅 탭(설정에서 켬). 턴별 작업 서술 —
                자유형식이라 행 텍스트를 순서대로 보존만 한다.

두 시트 모두 **읽기 전용**으로 다룬다. 웹은 이관·표시만 하고 되쓰지 않는다
(되쓰기는 스킬·평가인 몫 — 역할 3분할).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .workbook_diff import is_state_sheet

_LEDGER_HEADER = "가정 대장"
_ROW = re.compile(r"([A-Z]{1,3})([0-9]{1,7})")

# 가정 대장 5열 → 필드명(scaffold.py 헤더 순서 SSOT).
_LEDGER_COLS = ["name", "value", "source_type", "basis", "approval"]
# 승인되지 않은 채 하류로 흐르면 안 되는 출처유형(SKILL.md 1.6 게이트 규칙).
_UNAPPROVED = "suggested"


def _cellmap(sheet: dict) -> dict[tuple[int, str], object]:
    """{ref: RCell} → {(row, col): value} — 행 단위 순회용."""
    out: dict[tuple[int, str], object] = {}
    for ref, c in sheet.items():
        m = _ROW.fullmatch(ref)
        if m:
            out[(int(m.group(2)), m.group(1))] = c.value
    return out


@dataclass
class SkillState:
    """스킬 워크북에서 읽어낸 세션 증적."""

    keys: dict[str, object] = field(default_factory=dict)          # skill_version·stage 등
    assumptions: list[dict] = field(default_factory=list)          # 가정 대장
    log: list[str] = field(default_factory=list)                   # Claude Log 행
    warnings: list[str] = field(default_factory=list)              # 이관 시 표면화

    @property
    def present(self) -> bool:
        return bool(self.keys or self.assumptions or self.log)

    def to_dict(self) -> dict:
        return {"keys": self.keys, "assumptions": self.assumptions,
                "log": self.log, "warnings": self.warnings,
                "stage": self.keys.get("stage"),
                "engine_tieout_per_share": self.keys.get("engine_tieout_per_share")}


def parse_vs_state(wb: dict[str, dict]) -> SkillState:
    """워크북 전체 → SkillState. 상태 시트가 없으면 빈 SkillState(present=False)."""
    st = SkillState()
    for name, sheet in wb.items():
        if not is_state_sheet(name):
            continue
        if name.replace("_", "").replace(" ", "").lower() == "claudelog":
            st.log.extend(_parse_log(sheet))
        else:
            _parse_state(sheet, st)
    _check_ledger(st)
    return st


def _parse_state(sheet: dict, st: SkillState) -> None:
    """A열 키/B열 값 → keys, `가정 대장` 헤더 이후 5열 → assumptions."""
    cells = _cellmap(sheet)
    rows = sorted({r for r, _ in cells})
    ledger_from: int | None = None
    for r in rows:
        a = cells.get((r, "A"))
        if a is None:
            continue
        text = str(a)
        if _LEDGER_HEADER in text:
            ledger_from = r + 2          # 헤더 라인 + 열이름 라인 다음부터
            continue
        if ledger_from is None:
            st.keys[text] = cells.get((r, "B"))

    if ledger_from is None:
        return
    for r in rows:
        if r < ledger_from:
            continue
        row = {k: cells.get((r, c)) for k, c in zip(_LEDGER_COLS, "ABCDE")}
        if row["name"] in (None, ""):
            continue
        st.assumptions.append({k: v for k, v in row.items()})


def _parse_log(sheet: dict) -> list[str]:
    """Claude Log 탭 → 행별 텍스트(열은 공백 결합). 자유형식이라 보존만."""
    cells = _cellmap(sheet)
    out: list[str] = []
    for r in sorted({r for r, _ in cells}):
        vals = [str(v) for (rr, _c), v in sorted(cells.items())
                if rr == r and v not in (None, "")]
        if vals:
            out.append(" | ".join(vals))
    return out


def _check_ledger(st: SkillState) -> None:
    """가정 대장 게이트 — 미승인 `suggested` 가정을 표면화(SKILL.md 1.6).

    스킬 쪽 게이트는 W6 유입 시 WARN 이지만, 웹으로 이관될 때도 같은 규율을
    유지해야 "승인 안 된 AI 제안"이 조용히 확정 가정으로 둔갑하지 않는다.
    """
    for a in st.assumptions:
        src = str(a.get("source_type") or "").strip().lower()
        approved = str(a.get("approval") or "").strip()
        if src == _UNAPPROVED and approved in ("", "미승인", "pending"):
            st.warnings.append(
                f"가정 '{a.get('name')}' = AI 제안(suggested) 미승인 상태 — 평가인 확정 필요")
        if not str(a.get("basis") or "").strip():
            st.warnings.append(f"가정 '{a.get('name')}' 근거 공란 — 출처 없는 가정")
