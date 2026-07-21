"""stdlib xlsx 리더 — xlsx_writer 의 대칭(zipfile+xml, 의존 없음).

우리 DCF 모델(살아있는 수식 export)을 되읽는 왕복(round-trip) 리더. 외부 임의 xlsx(리포트
예시·암호화 등)는 openpyxl 기반 `ingest/parsers/xlsx.py` 를 쓰고, 여기선 우리 자체 포맷만
의존 없이 대칭 처리한다.

셀: 숫자 `<v>`, 문자열 `<c t="inlineStr"><is><t>`, 수식 `<f>expr</f><v>cached</v>`.
외부 xlsx 호환(2026-07 실측 보강): `t="s"`(sharedStrings)·`t="str"`(수식의 문자열
결과 — 예: `="Downside"`)·`t="b"`/`t="e"` 도 처리. 이전엔 t="str" 을 숫자로 강제
변환하다 크래시(참고 모델 리포트 예시로 발견).
"""
from __future__ import annotations

import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass

_M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _shared_strings(z: zipfile.ZipFile) -> list[str]:
    """xl/sharedStrings.xml → 인덱스 순 문자열(서식 run 은 이어붙임). 없으면 []."""
    try:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    out = []
    for si in root.iter(f"{{{_M}}}si"):
        out.append("".join(t.text or "" for t in si.iter(f"{{{_M}}}t")))
    return out


@dataclass(frozen=True)
class RCell:
    value: float | str | None          # 문자열이면 텍스트, 아니면 캐시 숫자
    formula: str | None = None

    @property
    def number(self) -> float | None:
        return self.value if isinstance(self.value, (int, float)) else None


def read_workbook(path: str) -> dict[str, dict[str, RCell]]:
    """xlsx → {sheet name: {cell ref: RCell}}. 시트명은 workbook.xml 순서."""
    z = zipfile.ZipFile(path)
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    names = [s.get("name") for s in wb.iter(f"{{{_M}}}sheet")]
    shared = _shared_strings(z)
    out: dict[str, dict[str, RCell]] = {}
    for i, name in enumerate(names, start=1):
        try:
            root = ET.fromstring(z.read(f"xl/worksheets/sheet{i}.xml"))
        except KeyError:
            continue
        cells: dict[str, RCell] = {}
        for c in root.iter(f"{{{_M}}}c"):
            ref = c.get("r")
            if ref is None:
                continue
            t = c.get("t")
            f_el = c.find(f"{{{_M}}}f")
            formula = f_el.text if f_el is not None else None
            if t == "inlineStr":
                is_el = c.find(f"{{{_M}}}is")
                t_el = is_el.find(f"{{{_M}}}t") if is_el is not None else None
                cells[ref] = RCell(value=t_el.text if t_el is not None else None,
                                   formula=formula)
                continue
            v_el = c.find(f"{{{_M}}}v")
            raw = v_el.text if v_el is not None else None
            if raw is None:
                cells[ref] = RCell(value=None, formula=formula)
            elif t == "s":                          # sharedStrings 인덱스
                idx = int(raw)
                cells[ref] = RCell(value=shared[idx] if idx < len(shared) else None,
                                   formula=formula)
            elif t in ("str", "e"):                 # 수식 문자열 결과 / 에러 텍스트
                cells[ref] = RCell(value=raw, formula=formula)
            elif t == "b":                          # bool → 1.0/0.0
                cells[ref] = RCell(value=float(raw), formula=formula)
            else:                                   # 숫자(기본)
                try:
                    cells[ref] = RCell(value=float(raw), formula=formula)
                except ValueError:                  # 방어: 비표준 생산자
                    cells[ref] = RCell(value=raw, formula=formula)
        out[name] = cells
    return out
