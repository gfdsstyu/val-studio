"""워크북 diff → 로컬 모델 반영 계획 (apply-policy 엔진).

워크북 왕복 diff(workbook_diff.diff_workbooks)의 3버킷을 "로컬 평가모델(프로젝트 JSON)에
어떻게 반영할지" 계획으로 변환한다:
  ① 입력 변경(input_changes, safe)  → auto_apply: 자동 반영 + 재계산 (로직만, LLM 불요)
  ② 수식 변경(formula_changes)      → review_queue: LLM 해설 → 평가인 승인 후 반영
  ③ 구조 변경(structure_changes)    → blocked: 차단 + 경고 (템플릿 불일치)
  ④ 상태·로그(state_changes)        → state: 모델 반영 대상 아님, 감사증적으로 이관·표시

이 모듈은 **분류만** 한다(순수 diff 로직, calc_core 미의존). 재계산은 API가 safe 일 때
import→run 으로 수행. 역할 3분할: 자동반영은 결정론, 수식변경 채택은 평가인 판단.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .workbook_diff import CellChange, WorkbookDiff


def _ser(ch: CellChange) -> dict:
    return {"sheet": ch.sheet, "ref": ch.ref, "kind": ch.kind,
            "old": ch.old, "new": ch.new}


@dataclass
class ApplyPlan:
    """diff → 반영 계획. safe 면 API가 import→재계산해 new_result 채움."""

    safe: bool                                          # 입력 변경만인가(자동 반영 가능)
    auto_apply: list[dict] = field(default_factory=list)     # ① 자동 반영(입력)
    review_queue: list[dict] = field(default_factory=list)   # ② 승인 대기(수식)
    blocked: list[dict] = field(default_factory=list)        # ③ 차단(구조)
    state: list[dict] = field(default_factory=list)          # ④ 상태·로그(증적)
    row_warnings: list[str] = field(default_factory=list)    # 외딴 편집 감지
    summary_markdown: str = ""

    def to_dict(self) -> dict:
        return {
            "safe": self.safe,
            "auto_apply": self.auto_apply,
            "review_queue": self.review_queue,
            "blocked": self.blocked,
            "state": self.state,
            "row_warnings": self.row_warnings,
            "counts": {"auto_apply": len(self.auto_apply),
                       "review_queue": len(self.review_queue),
                       "blocked": len(self.blocked),
                       "state": len(self.state)},
            "summary_markdown": self.summary_markdown,
        }


def build_apply_plan(diff: WorkbookDiff) -> ApplyPlan:
    """diff 3버킷 → ApplyPlan. 시트 추가/삭제도 blocked 로 편입(구조 변경)."""
    blocked = [_ser(ch) for ch in diff.structure_changes]
    for s in diff.sheets_added:
        blocked.append({"sheet": s, "ref": "-", "kind": "sheet_added",
                        "old": "(없음)", "new": "(새 시트)"})
    for s in diff.sheets_removed:
        blocked.append({"sheet": s, "ref": "-", "kind": "sheet_removed",
                        "old": "(시트)", "new": "(삭제됨)"})
    return ApplyPlan(
        safe=diff.safe,
        auto_apply=[_ser(ch) for ch in diff.input_changes],
        review_queue=[_ser(ch) for ch in diff.formula_changes],
        blocked=blocked,
        state=[_ser(ch) for ch in diff.state_changes],
        row_warnings=list(diff.row_uniformity_warnings),
        summary_markdown=diff.to_markdown(),
    )
