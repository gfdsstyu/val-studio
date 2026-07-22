"""DART XBRL 택사노미 배포판(xlsx) → backend/data/dart_taxonomy.json 빌드.

원천: 금융감독원 배포 `DART_Taxonomy_YYYYMMDD_배포용.xlsx`
      (갱신 URL: https://filer.fss.or.kr/Resource/ifrsclient/install/)

`account_id`(= `ifrs-full_Revenue` 같은 표준 요소명) 를 한/영 라벨·부호·계층으로
해석하는 SSOT 를 만든다. OpenDART `fnlttSinglAcntAll` 응답의 `account_id` 가 이
사전의 키와 같은 네임스페이스라, 회사가 지어낸 `account_nm` 문자열에 의존하지 않고
결정론적으로 계정을 정규화할 수 있다.

표준 라이브러리만 사용(zipfile + xml) — openpyxl/pandas 불필요. 프로젝트 규율상
`dependencies = []` 를 깨지 않기 위함이며, 13MB/71K행 시트는 iterparse 로 흘려 읽는다.

수록 범위(의도적 비대칭):
  · elements  — 전 9,451 개념의 ko/en 라벨 + balance/periodType. 사전 그 자체라 전량.
  · roles     — 전 2,004 role 의 ko/en 정의(주석 role 포함). 주석 추출에서 쓸 목차.
  · pres/calc — **주요재무제표 26 role 만.** 주석 role 의 arc 까지 넣으면 수 MB 로
                불어나는데, 버킷 도출에 쓰는 계층은 주요재무제표뿐이다. 주석 arc 가
                필요해지면 PRIMARY_ROLES 를 넓히면 된다.

용법:
  py -3.12 scripts/build_taxonomy_store.py "D:/Valuation/dart/1. DART_Taxonomy_20260630_배포용.xlsx"
"""
from __future__ import annotations

import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterator

M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
OUT = Path(__file__).resolve().parent.parent / "backend" / "data" / "dart_taxonomy.json"

# 주요재무제표 role. 연결(0)/별도(5) 쌍 + 표시방법 변형 전부.
PRIMARY_ROLES = frozenset(
    """
    D210000 D210005 D220000 D220005
    D310000 D310005 D320000 D320005
    D410000 D410005 D420000 D420005
    D431410 D431415 D431420 D431425
    D432410 D432415 D432420 D432425
    D510000 D510005 D520000 D520005
    D610000 D610005
    """.split()
)

# role 코드 → 재무제표 구분. OpenDART 응답의 sj_div 와 맞춘다.
_ROLE_KIND = [
    (("D21", "D22"), "BS"),
    (("D31", "D32"), "IS"),
    (("D41", "D42", "D4314", "D4324"), "CIS"),
    (("D51", "D52"), "CF"),
    (("D61",), "SCE"),
]


def role_kind(code: str) -> str | None:
    """role 코드 → BS/IS/CIS/CF/SCE. 주석(D8·D9·DB·DI·DS·DX)은 None."""
    for prefixes, kind in _ROLE_KIND:
        if code.startswith(prefixes):
            return kind
    return None


# ── xlsx 최소 리더(stdlib) ────────────────────────────────────────────────

def _col_index(ref: str) -> int:
    """셀 주소 'AB12' → 0-based 열 인덱스."""
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + (ord(ch.upper()) - ord("A") + 1)
    return n - 1


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    """sharedStrings.xml → 인덱스 배열. <si> 안의 모든 <t> 를 이어붙인다(rich text)."""
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    out: list[str] = []
    with zf.open("xl/sharedStrings.xml") as fh:
        for event, elem in ET.iterparse(fh, events=("end",)):
            if elem.tag == f"{{{M}}}si":
                out.append("".join(t.text or "" for t in elem.iter(f"{{{M}}}t")))
                elem.clear()
    return out


def _sheet_paths(zf: zipfile.ZipFile) -> dict[str, str]:
    """시트명 → zip 내부 경로. workbook.xml 의 r:id 를 rels 로 해석한다."""
    R_OFF = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    rels = {}
    with zf.open("xl/_rels/workbook.xml.rels") as fh:
        for rel in ET.parse(fh).getroot():
            rels[rel.get("Id")] = rel.get("Target")
    out = {}
    with zf.open("xl/workbook.xml") as fh:
        for sheet in ET.parse(fh).getroot().iter(f"{{{M}}}sheet"):
            target = rels.get(sheet.get(f"{{{R_OFF}}}id"), "")
            target = target[1:] if target.startswith("/") else "xl/" + target.lstrip("/")
            out[sheet.get("name")] = target.replace("xl/xl/", "xl/")
    return out


def rows(zf: zipfile.ZipFile, path: str, sst: list[str]) -> Iterator[list[str]]:
    """워크시트를 행 단위로 흘려 읽는다. 빈 셀은 ''(열 인덱스 보존)."""
    with zf.open(path) as fh:
        for event, elem in ET.iterparse(fh, events=("end",)):
            if elem.tag != f"{{{M}}}row":
                continue
            cells: list[str] = []
            for c in elem.iter(f"{{{M}}}c"):
                idx = _col_index(c.get("r", ""))
                if idx < 0:
                    continue
                v = c.find(f"{{{M}}}v")
                if c.get("t") == "s" and v is not None and v.text:
                    text = sst[int(v.text)]
                elif c.get("t") == "inlineStr":
                    text = "".join(t.text or "" for t in c.iter(f"{{{M}}}t"))
                else:
                    text = (v.text or "") if v is not None else ""
                while len(cells) <= idx:
                    cells.append("")
                cells[idx] = text
            elem.clear()
            yield cells


def _cell(row: list[str], i: int) -> str:
    return row[i].strip() if i < len(row) else ""


# ── 시트별 파서 ───────────────────────────────────────────────────────────

_ROLE_CODE = re.compile(r"\[([A-Za-z0-9]+)\]\s*(.*)")


def _split_definition(text: str) -> tuple[str, str, str]:
    """'[D310000] 손익계산서… | Income statement…' → (code, ko, en)."""
    m = _ROLE_CODE.match(text)
    if not m:
        return "", text, ""
    body = m.group(2)
    ko, _, en = body.partition("|")
    return m.group(1), ko.strip(), en.strip()


def parse_concepts(zf, path, sst) -> dict[str, dict]:
    """Concepts 시트 → element_id → {balance, period, abstract}."""
    out: dict[str, dict] = {}
    header: dict[str, int] = {}
    for row in rows(zf, path, sst):
        if not header:
            if _cell(row, 1) == "prefix":
                header = {name.strip(): i for i, name in enumerate(row) if name.strip()}
            continue
        prefix, name = _cell(row, header["prefix"]), _cell(row, header["name"])
        if not prefix or not name:
            continue
        entry = {}
        if balance := _cell(row, header.get("balance", -1)):
            entry["balance"] = balance
        if period := _cell(row, header.get("periodType", -1)):
            entry["period"] = period
        if _cell(row, header.get("abstract", -1)).lower() == "true":
            entry["abstract"] = True
        out[f"{prefix}_{name}"] = entry
    return out


def parse_labels(zf, path, sst) -> dict[str, tuple[str, str]]:
    """Label Link 시트 → element_id → (ko, en).

    이 시트는 언어별로 같은 컬럼 세트가 두 벌 반복된다. 3행이 언어 마커('ko'/'en'),
    4행이 실제 헤더라, 언어 마커 행에서 각 언어 블록의 시작 열을 잡고 그 블록 안의
    'label' 컬럼을 쓴다. 컬럼 순서를 하드코딩하지 않기 위한 2단 해석.
    """
    lang_at: dict[int, str] = {}
    out: dict[str, tuple[str, str]] = {}
    header: dict[str, int] = {}
    ko_col = en_col = -1
    for row in rows(zf, path, sst):
        if not lang_at:
            marks = {i: v.strip() for i, v in enumerate(row) if v.strip() in ("ko", "en")}
            if marks:
                lang_at = marks
            continue
        if not header:
            if _cell(row, 0) == "#":
                header = {}
                for i, name in enumerate(row):
                    header.setdefault(name.strip(), i)
                # 각 언어 마커 열 이후 첫 'label' 컬럼이 그 언어의 라벨.
                label_cols = [i for i, name in enumerate(row) if name.strip() == "label"]
                for pos, lang in sorted(lang_at.items()):
                    cand = [c for c in label_cols if c >= pos]
                    col = cand[0] if cand else -1
                    if lang == "ko":
                        ko_col = col
                    else:
                        en_col = col
            continue
        prefix, name = _cell(row, header["prefix"]), _cell(row, header["name"])
        if not prefix or not name:
            continue
        out[f"{prefix}_{name}"] = (_cell(row, ko_col), _cell(row, en_col))
    return out


def parse_roles(zf, path, sst) -> dict[str, dict]:
    """RoleTypes 시트 → code → {ko, en, uri, kind}."""
    out: dict[str, dict] = {}
    header: dict[str, int] = {}
    for row in rows(zf, path, sst):
        if not header:
            if _cell(row, 1) == "id":
                header = {name.strip(): i for i, name in enumerate(row) if name.strip()}
            continue
        code, ko, en = _split_definition(_cell(row, header["definition"]))
        if not code:
            continue
        entry = {"ko": ko, "en": en}
        if kind := role_kind(code):
            entry["kind"] = kind
        out[code] = entry
    return out


def parse_arcs(zf, path, sst, *, with_weight: bool) -> dict[str, list[dict]]:
    """Presentation/Calculation Link 시트 → role code → arc 리스트.

    두 시트는 `LinkRole`/`Definition` 헤더 블록으로 role 이 구분되고, 그 아래 행들이
    depth 들여쓰기로 트리를 이룬다. depth 스택으로 부모를 복원한다.
    PRIMARY_ROLES 밖은 건너뛴다(§ 모듈 docstring 의 수록 범위 참조).
    """
    out: dict[str, list[dict]] = {}
    code = ""
    header: dict[str, int] = {}
    stack: dict[int, str] = {}
    for row in rows(zf, path, sst):
        head = _cell(row, 0)
        if head == "LinkRole":
            continue
        if head == "Definition":
            code, _, _ = _split_definition(_cell(row, 1))
            header, stack = {}, {}
            continue
        if head == "prefix":
            header = {name.strip(): i for i, name in enumerate(row) if name.strip()}
            continue
        if not head or code not in PRIMARY_ROLES or not header:
            continue
        name = _cell(row, header["name"])
        if not name:
            continue
        elem = f"{head}_{name}"
        depth_raw = _cell(row, header["depth"])
        depth = int(float(depth_raw)) if depth_raw else 0
        stack = {d: e for d, e in stack.items() if d < depth}
        stack[depth] = elem
        arc: dict = {"e": elem, "d": depth}
        if parent := stack.get(depth - 1):
            arc["p"] = parent
        if with_weight and (w := _cell(row, header.get("weight", -1))):
            try:
                arc["w"] = float(w)
            except ValueError:
                pass
        if not with_weight and (pl := _cell(row, header.get("preferredLabel", -1))):
            arc["pl"] = pl.rsplit("/", 1)[-1]
        out.setdefault(code, []).append(arc)
    return out


# ── 빌드 ─────────────────────────────────────────────────────────────────

def build(src: Path) -> dict:
    with zipfile.ZipFile(src) as zf:
        sst = _shared_strings(zf)
        paths = _sheet_paths(zf)
        concepts = parse_concepts(zf, paths["Concepts"], sst)
        labels = parse_labels(zf, paths["Label Link"], sst)
        roles = parse_roles(zf, paths["RoleTypes"], sst)
        pres = parse_arcs(zf, paths["Presentation Link"], sst, with_weight=False)
        calc = parse_arcs(zf, paths["Calculation Link"], sst, with_weight=True)

    elements: dict[str, dict] = {}
    for elem, meta in concepts.items():
        ko, en = labels.get(elem, ("", ""))
        entry = dict(meta)
        if ko:
            entry["ko"] = ko
        if en:
            entry["en"] = en
        elements[elem] = entry
    # 라벨에만 있고 Concepts 에 없는 요소(타 택사노미 참조분)도 사전에 남긴다.
    for elem, (ko, en) in labels.items():
        if elem not in elements:
            elements[elem] = {k: v for k, v in (("ko", ko), ("en", en)) if v}

    # 버전은 role id(dart_2026-01-31_role-D210000)가 아니라 파일명에서 뽑는다.
    m = re.search(r"(\d{8})", src.name)
    return {
        "_meta": {
            "source": src.name,
            "source_url": "https://filer.fss.or.kr/Resource/ifrsclient/install/",
            "revision": m.group(1) if m else "unknown",
            "builder": "scripts/build_taxonomy_store.py",
            "scope": "elements/roles 전량, presentation·calculation 은 주요재무제표 26 role",
            "counts": {
                "elements": len(elements),
                "roles": len(roles),
                "presentation_arcs": sum(len(v) for v in pres.values()),
                "calculation_arcs": sum(len(v) for v in calc.values()),
            },
        },
        "elements": elements,
        "roles": roles,
        "presentation": pres,
        "calculation": calc,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    src = Path(argv[1])
    if not src.is_file():
        print(f"원본 xlsx 없음: {src}")
        return 1
    data = build(src)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    counts = data["_meta"]["counts"]
    print(f"{OUT}  ({OUT.stat().st_size / 1024:.0f} KB)")
    for k, v in counts.items():
        print(f"  {k}: {v:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
