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

from .workbook_diff import is_known_state_sheet

_LEDGER_HEADER = "가정 대장"
_ROW = re.compile(r"([A-Z]{1,3})([0-9]{1,7})")

# 가정 대장 5열 → 필드명(scaffold.py 헤더 순서 SSOT). **위치 폴백 전용** —
# 정상 경로는 아래 _LEDGER_LABELS 로 열이름을 읽는다.
_LEDGER_COLS = ["name", "value", "source_type", "basis", "approval"]

# ⚠️ 열 **위치**로 파싱하면 누군가 열을 하나 끼우는 순간 오류가 아니라 **조용한 오독**이
# 된다(값이 다른 필드로 들어감). 스킬 쪽 SKILL.md 와 웹 쪽 이 파서는 독립적으로 갱신되는
# 두 리더라, 위치 결합은 전형적인 프로토콜 버전 사고다 → **열이름으로 파싱**한다.
# 모르는 열은 실패시키지 않고 `x_<라벨>` 로 보존한다(전방 호환).
_LEDGER_LABELS = {
    "가정명": "name", "값": "value", "출처유형": "source_type",
    "근거": "basis", "승인상태": "approval",
    "lookback": "lookback", "lookback사유": "lookback_reason",
}
# 이 빌드가 아는 `_VS_STATE` 스키마 버전. 워크북이 더 높은 버전을 선언하면 경고만 하고
# 계속 읽는다(모르는 항목 무시) — 하위 리더가 상위 워크북을 만나도 죽지 않아야 한다.
STATE_SCHEMA_VERSION = 1
_SCHEMA_KEY = "state_schema"

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
        # **해석할 수 있는** 원장만 파싱한다. 미등록 `_VS_*` 는 여기서 조용히 건너뛰고,
        # "해석 못 함"의 표면화는 diff 쪽(`diff_workbooks` 경고) 책임이다 — 파서가
        # 모르는 시트를 _VS_STATE 로 착각해 읽으면 없는 키가 생긴다.
        if not is_known_state_sheet(name):
            continue
        norm = name.replace("_", "").replace(" ", "").lower()
        if norm == "claudelog":
            st.log.extend(_parse_log(sheet))
        elif norm == "vsstate":
            _parse_state(sheet, st)
        # `_VS_FACTS` 는 소유자가 달라 여기서 읽지 않는다(excel/facts_sheet.py 소관).
        # 아는 원장이라고 전부 같은 파서에 넣으면 없는 키가 생긴다.
    _check_schema(st)
    _check_ledger(st)
    return st


def _check_schema(st: SkillState) -> None:
    """워크북이 선언한 스키마 버전 점검 — 상위 버전이어도 읽기를 멈추지 않는다.

    두 리더(스킬·웹)가 독립적으로 갱신되므로 하위 리더가 상위 워크북을 만나는 일이
    정상적으로 발생한다. 그때 죽는 대신 "모르는 항목이 있을 수 있다"를 알린다.
    """
    raw = st.keys.get(_SCHEMA_KEY)
    if raw in (None, ""):
        return
    try:
        ver = int(float(str(raw)))
    except (TypeError, ValueError):
        st.warnings.append(f"{_SCHEMA_KEY} 값을 해석할 수 없음: {raw!r}")
        return
    if ver > STATE_SCHEMA_VERSION:
        st.warnings.append(
            f"_VS_STATE 스키마 v{ver} — 이 빌드는 v{STATE_SCHEMA_VERSION} 까지 안다"
            "(모르는 항목은 무시하고 계속 읽음)")


def _ledger_columns(
    cells: dict[tuple[int, str], object], label_row: int,
) -> tuple[dict[str, str], dict[str, str]]:
    """열이름 행 → ({필드명: 열문자}, {모르는 라벨: 열문자}).

    라벨은 공백·대소문자를 무시해 맞춘다. 아는 열은 필드로, 모르는 열은 그대로 보존해
    상위 버전 워크북을 만나도 정보가 소실되지 않게 한다.
    """
    known: dict[str, str] = {}
    extras: dict[str, str] = {}
    for (r, c), v in cells.items():
        if r != label_row or v in (None, ""):
            continue
        label = str(v).strip()
        field_name = _LEDGER_LABELS.get(label) or _LEDGER_LABELS.get(label.lower())
        if field_name:
            known.setdefault(field_name, c)
        else:
            extras.setdefault(label, c)
    return known, extras


def _parse_state(sheet: dict, st: SkillState) -> None:
    """A열 키/B열 값 → keys, `가정 대장` 헤더 이후 → assumptions(열이름 기반)."""
    cells = _cellmap(sheet)
    rows = sorted({r for r, _ in cells})
    label_row: int | None = None
    for r in rows:
        a = cells.get((r, "A"))
        if a is None:
            continue
        text = str(a)
        if _LEDGER_HEADER in text:
            label_row = r + 1            # 헤더 라인 다음이 열이름 라인
            continue
        if label_row is None:
            st.keys[text] = cells.get((r, "B"))

    if label_row is None:
        return
    colmap, extras = _ledger_columns(cells, label_row)
    if "name" not in colmap:
        # 열이름 행이 없거나 깨진 구버전 워크북 — 위치로 폴백하되 **침묵하지 않는다**.
        colmap, extras = dict(zip(_LEDGER_COLS, "ABCDE")), {}
        st.warnings.append(
            "가정 대장 열이름을 읽지 못해 위치(A~E)로 해석 — 열 구성이 바뀌면 값이 밀린다")
    for r in rows:
        if r <= label_row:
            continue
        row: dict[str, object] = {f: cells.get((r, c)) for f, c in colmap.items()}
        if row.get("name") in (None, ""):
            continue
        for label, c in extras.items():          # 전방 호환: 모르는 열도 보존
            v = cells.get((r, c))
            if v not in (None, ""):
                row[f"x_{label}"] = v
        st.assumptions.append(row)


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
