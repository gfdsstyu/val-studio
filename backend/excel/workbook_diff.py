"""워크북 왕복 diff — 중간 엑셀 산출물의 블랙박스 변화를 셀 단위로 분류.

용도(사용자 설계): export 한 모델을 유저가 엑셀에서 손보고 재업로드할 때, 두 워크북을
비교해 "무엇이 어떻게 바뀌었나"를 3버킷으로 분류한다(Claude in Excel 식 왕복 정합):
  ① 입력 변경  — 수식 없는 셀의 값 변경(파랑 경로). 정상 — 재계산 대상.
  ② 수식 변경  — 수식 문자열 자체가 바뀜(모델 로직 변경). ⚠️ 리뷰 필요.
  ③ 구조 변경  — 시트/셀 추가·삭제, 앵커(고정 입력셀) 이동. 🔴 템플릿 불일치 위험.

추가 검사(공식 anthropics xlsx 스킬 채록): "행 중간의 외딴 수식 편집(lone edited
cell mid-row)이 가장 흔한 조용한 오류" → 행 내 수식 균일성 검사(R1C1 정규화 후
같은 행의 연속 수식 셀이 동일 패턴인지).

입력은 xlsx_reader.read_workbook() 산출({sheet: {ref: RCell}}) — 파일 두 번 읽어
diff_workbooks(old, new) 호출.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_REF = re.compile(r"(\$?)([A-Z]{1,3})(\$?)([0-9]{1,7})")


def _col_num(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - 64)
    return n


def _split_ref(ref: str) -> tuple[int, int]:
    m = _REF.fullmatch(ref)
    if not m:
        raise ValueError(f"셀 주소 아님: {ref}")
    return _col_num(m.group(2)), int(m.group(4))


def to_r1c1(formula: str, ref: str) -> str:
    """A1 수식 → R1C1 상대 정규화. 같은 패턴의 수식은 어느 셀에 있든 같은 문자열.

    `=C5*D5` (E5 에서) → `=R[0]C[-2]*R[0]C[-1]` — 행 균일성 비교의 기준.
    절대참조($)는 RnCn 절대 표기. 따옴표 문자열 내 치환은 하지 않음(단순 구현 —
    시트명 내 좌표꼴 텍스트는 실무 모델에서 드묾, 한계는 여기 명시).
    """
    base_c, base_r = _split_ref(ref)

    def sub(m: re.Match) -> str:
        c_abs, col, r_abs, row = m.group(1), _col_num(m.group(2)), m.group(3), int(m.group(4))
        c = f"C{col}" if c_abs else f"C[{col - base_c}]"
        r = f"R{row}" if r_abs else f"R[{row - base_r}]"
        return r + c

    return _REF.sub(sub, formula)


@dataclass(frozen=True)
class CellChange:
    sheet: str
    ref: str
    kind: str            # 'input' | 'formula' | 'added' | 'removed' | 'anchor'
    old: str
    new: str


@dataclass
class WorkbookDiff:
    sheets_added: list[str] = field(default_factory=list)
    sheets_removed: list[str] = field(default_factory=list)
    input_changes: list[CellChange] = field(default_factory=list)     # ① 정상 경로
    formula_changes: list[CellChange] = field(default_factory=list)   # ② 리뷰 필요
    structure_changes: list[CellChange] = field(default_factory=list) # ③ 위험
    row_uniformity_warnings: list[str] = field(default_factory=list)

    @property
    def safe(self) -> bool:
        """입력 변경만 있는가(자동 재계산해도 되는가)."""
        return not (self.sheets_added or self.sheets_removed
                    or self.formula_changes or self.structure_changes)

    def to_markdown(self) -> str:
        lines = ["## 워크북 왕복 diff"]
        lines.append(f"- 판정: {'✅ 입력 변경만 — 자동 반영 가능' if self.safe else '⚠️ 구조/수식 변경 포함 — 리뷰 필요'}")
        if self.sheets_added or self.sheets_removed:
            lines.append(f"- 시트: +{self.sheets_added} −{self.sheets_removed}")
        for title, changes in [("① 입력 변경(정상)", self.input_changes),
                               ("② 수식 변경(리뷰)", self.formula_changes),
                               ("③ 구조 변경(위험)", self.structure_changes)]:
            if changes:
                lines.append(f"### {title} — {len(changes)}건")
                for ch in changes[:30]:
                    lines.append(f"- {ch.sheet}!{ch.ref}: `{ch.old}` → `{ch.new}`")
                if len(changes) > 30:
                    lines.append(f"- …외 {len(changes) - 30}건")
        if self.row_uniformity_warnings:
            lines.append("### ⚠️ 행 수식 균일성(외딴 편집 감지)")
            lines.extend(f"- {w}" for w in self.row_uniformity_warnings)
        return "\n".join(lines)


def _fmt(cell) -> str:
    if cell is None:
        return "(없음)"
    if cell.formula:
        return f"={cell.formula}"
    return str(cell.value)


def diff_workbooks(
    old: dict[str, dict],
    new: dict[str, dict],
    *,
    anchors: dict[str, dict[str, str]] | None = None,
) -> WorkbookDiff:
    """old/new 워크북(read_workbook 산출) 비교 → 3버킷 분류.

    anchors = {sheet: {ref: 기대 라벨}} — 템플릿 고정셀(예: 행 라벨·메타셀)이 새
    파일에서 그 자리에 그대로 있는지 검사(이동/삭제 = 구조 변경, 최우선 경고).
    """
    d = WorkbookDiff()
    d.sheets_added = sorted(set(new) - set(old))
    d.sheets_removed = sorted(set(old) - set(new))

    for sheet in sorted(set(old) & set(new)):
        o, n = old[sheet], new[sheet]
        for ref in sorted(set(o) | set(n), key=lambda r: (_split_ref(r)[1], _split_ref(r)[0])):
            oc, nc = o.get(ref), n.get(ref)
            if oc is None or nc is None:
                # 빈칸↔값 전이: 둘 다 수식 아니면 입력 취급, 수식 관여 시 구조
                gone, came = _fmt(oc), _fmt(nc)
                kind = ("formula" if (oc and oc.formula) or (nc and nc.formula)
                        else "input")
                bucket = d.formula_changes if kind == "formula" else d.input_changes
                bucket.append(CellChange(sheet, ref, "added" if oc is None else "removed",
                                         gone, came))
                continue
            if (oc.formula or "") != (nc.formula or ""):
                d.formula_changes.append(
                    CellChange(sheet, ref, "formula", _fmt(oc), _fmt(nc)))
            elif oc.formula:
                continue                          # 같은 수식 — 캐시값 차이는 무시(재계산 몫)
            elif oc.value != nc.value:
                d.input_changes.append(
                    CellChange(sheet, ref, "input", _fmt(oc), _fmt(nc)))

    # 앵커 가드: 템플릿 고정셀이 그 자리에 그 라벨로 존재하는가
    for sheet, cells in (anchors or {}).items():
        for ref, label in cells.items():
            cur = new.get(sheet, {}).get(ref)
            cur_text = str(cur.value) if cur is not None and cur.value is not None else None
            if cur_text is None or label not in cur_text:
                d.structure_changes.append(CellChange(
                    sheet, ref, "anchor", f"기대 라벨 '{label}'", _fmt(cur)))

    d.row_uniformity_warnings = check_row_uniformity(new)
    return d


def check_row_uniformity(wb: dict[str, dict], *, min_run: int = 3) -> list[str]:
    """행 내 연속 수식 셀의 R1C1 패턴 균일성 — '외딴 편집' 감지.

    같은 행에서 min_run 개 이상 셀이 수식이고 지배 패턴이 있는데 한두 셀만 다르면
    경고(공식 xlsx 스킬: 'a lone edited cell mid-row is the commonest silent error').
    """
    warnings: list[str] = []
    for sheet, cells in wb.items():
        rows: dict[int, list[tuple[int, str, str]]] = {}
        for ref, c in cells.items():
            if not c.formula:
                continue
            col, row = _split_ref(ref)
            rows.setdefault(row, []).append((col, ref, to_r1c1(c.formula, ref)))
        for row, items in rows.items():
            if len(items) < min_run:
                continue
            items.sort()
            patterns: dict[str, list[str]] = {}
            for _, ref, p in items:
                patterns.setdefault(p, []).append(ref)
            dominant = max(patterns.values(), key=len)
            if len(dominant) >= max(min_run, len(items) - 2):
                for p, refs in patterns.items():
                    if refs is not dominant and len(refs) <= 2:
                        warnings.append(
                            f"{sheet} r{row}: {','.join(refs)} 수식이 행 지배 패턴과 다름"
                            f"(지배 {len(dominant)}셀) — 외딴 편집/오타 의심")
    return warnings
