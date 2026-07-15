"""최소 stdlib xlsx 라이터 — "살아있는 수식" export.

의존 없이(zipfile+문자열) 유효한 .xlsx 를 생성한다. 추출(zipfile+xml)과 대칭.
셀은 값/문자열/수식 3종:
  - 숫자:   <c r="A1"><v>123</v></c>
  - 문자열: <c r="A1" t="inlineStr"><is><t>라벨</t></is></c>
  - 수식:   <c r="A1"><f>B1-C1</f><v>캐시값</v></c>   ← 감사 추적 + Excel 없이도 표시

감사 추적성이 목표라 계산 결과 셀은 하드값이 아니라 **수식**으로 쓴다.
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from xml.sax.saxutils import escape


@dataclass
class Cell:
    value: float | str | None = None
    formula: str | None = None
    cached: float | None = None  # 수식 셀의 캐시값


@dataclass
class Sheet:
    name: str
    cells: dict[str, Cell] = field(default_factory=dict)

    def num(self, ref: str, value: float) -> None:
        self.cells[ref] = Cell(value=value)

    def text(self, ref: str, value: str) -> None:
        self.cells[ref] = Cell(value=value)

    def formula(self, ref: str, expr: str, cached: float | None = None) -> None:
        self.cells[ref] = Cell(formula=expr, cached=cached)

    def _row_index(self, ref: str) -> int:
        return int("".join(ch for ch in ref if ch.isdigit()))

    def to_xml(self) -> str:
        # 행 단위 그룹핑(정렬)
        rows: dict[int, list[tuple[str, Cell]]] = {}
        for ref, c in self.cells.items():
            rows.setdefault(self._row_index(ref), []).append((ref, c))
        parts = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
            "<sheetData>",
        ]
        for r in sorted(rows):
            cells = sorted(rows[r], key=lambda x: _col_key(x[0]))
            parts.append(f'<row r="{r}">')
            for ref, c in cells:
                parts.append(_cell_xml(ref, c))
            parts.append("</row>")
        parts.append("</sheetData></worksheet>")
        return "".join(parts)


def _col_key(ref: str) -> tuple[int, int]:
    col = "".join(ch for ch in ref if ch.isalpha())
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - 64)
    return n, 0


def _cell_xml(ref: str, c: Cell) -> str:
    if c.formula is not None:
        v = f"<v>{_num(c.cached)}</v>" if c.cached is not None else ""
        return f'<c r="{ref}"><f>{escape(c.formula)}</f>{v}</c>'
    if isinstance(c.value, str):
        return f'<c r="{ref}" t="inlineStr"><is><t>{escape(c.value)}</t></is></c>'
    if c.value is not None:
        return f'<c r="{ref}"><v>{_num(c.value)}</v></c>'
    return f'<c r="{ref}"/>'


def _num(x: float) -> str:
    # 정수는 정수로, 아니면 반복소수 최대정밀도
    if x == int(x):
        return str(int(x))
    return repr(x)


class Workbook:
    def __init__(self) -> None:
        self.sheets: list[Sheet] = []

    def add_sheet(self, name: str) -> Sheet:
        s = Sheet(name)
        self.sheets.append(s)
        return s

    def save(self, path: str) -> None:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", _content_types(len(self.sheets)))
            z.writestr("_rels/.rels", _root_rels())
            z.writestr("xl/workbook.xml", _workbook_xml(self.sheets))
            z.writestr("xl/_rels/workbook.xml.rels", _workbook_rels(self.sheets))
            for i, s in enumerate(self.sheets, start=1):
                z.writestr(f"xl/worksheets/sheet{i}.xml", s.to_xml())


def _content_types(n: int) -> str:
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
        f'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, n + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        f"{overrides}</Types>"
    )


def _root_rels() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    )


def _workbook_xml(sheets: list[Sheet]) -> str:
    els = "".join(
        f'<sheet name="{escape(s.name)}" sheetId="{i}" r:id="rId{i}"/>'
        for i, s in enumerate(sheets, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{els}</sheets></workbook>"
    )


def _workbook_rels(sheets: list[Sheet]) -> str:
    rels = "".join(
        f'<Relationship Id="rId{i}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, len(sheets) + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{rels}</Relationships>"
    )
