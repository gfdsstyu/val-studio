"""PDF 파서 — 표에 강한 구조화 추출 + LLM RAG용 텍스트 청크(이중 출력).

두 소비자를 서빙:
  ① 감사인 트랙 → 표를 셀 격자로 복원(우측정렬 숫자 클러스터링) → ProvenancedValue(tie-out·엔진투입)
  ② LLM RAG   → 페이지별 클린 텍스트 청크 + garble 신뢰도(사업보고서/IR 검색 컨텍스트)

표 복원의 핵심: 한글 라벨이 CID폰트로 깨져도(외부평가의견서) **숫자는 우측정렬로 살아있다**.
그래서 "라벨 파싱"이 아니라 **숫자 토큰의 우측 끝 char 위치 클러스터링**으로 컬럼을 복원한다.

텍스트 추출 백엔드는 교체 가능(TextExtractor). 기본은 pdftotext -layout(spatial 보존).
스캔/CID 문서는 garble_ratio 로 감지 → confidence<1 + OCR 필요 플래그.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from typing import Callable

from ..provenance import ExtractMethod, Locator, SourceKind
from .base import BaseParser, ParseResult

# ── 텍스트 추출 백엔드 ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PdfPage:
    page_no: int          # 1-based
    text: str
    char_offset: int      # 문서 전체 기준 이 페이지 시작 offset


TextExtractor = Callable[[str], "list[PdfPage]"]


def pdftotext_layout(path: str) -> list[PdfPage]:
    """pdftotext -layout 로 페이지별 텍스트 추출(spatial 컬럼 보존). \\f 로 페이지 분리."""
    out = subprocess.run(
        ["pdftotext", "-layout", path, "-"],
        capture_output=True, timeout=120,
    )
    if out.returncode != 0:
        raise RuntimeError(f"pdftotext 실패: {out.stderr.decode('utf8','ignore')[:200]}")
    raw = out.stdout.decode("utf-8", "ignore")
    pages: list[PdfPage] = []
    offset = 0
    for i, chunk in enumerate(raw.split("\f"), 1):
        pages.append(PdfPage(page_no=i, text=chunk, char_offset=offset))
        offset += len(chunk) + 1  # \f
    return pages


# ── garble(CID 깨짐) 감지 ─────────────────────────────────────────────────────

_HANGUL = re.compile(r"[가-힣]")
_LATIN_DIGIT = re.compile(r"[A-Za-z0-9]")


def garble_ratio(text: str) -> float:
    """텍스트 신뢰도 저하 추정(0=정상, 1=심각). 한글 문서인데 한글이 거의 없고

    공백·숫자·기호만 남으면 CID 매핑 실패로 본다. 한글 비율이 지나치게 낮으면서
    (한글+라틴숫자) 대비 공백이 과다하면 garble 로 간주.
    """
    stripped = text.strip()
    if not stripped:
        return 1.0
    hangul = len(_HANGUL.findall(text))
    latin = len(_LATIN_DIGIT.findall(text))
    content = hangul + latin
    if content == 0:
        return 1.0
    # 한글 문서 가정: 내용문자 중 한글 비중이 아주 낮으면(숫자·기호만) 라벨 손실 의심
    hangul_share = hangul / content
    # 숫자 위주 표는 원래 한글이 적으므로, "글자수 대비 내용문자"도 함께 본다
    density = content / max(len(stripped), 1)
    if hangul_share < 0.05 and density < 0.5:
        return 0.7
    if hangul_share < 0.02:
        return 0.5
    return 0.0


def confidence_from_garble(text: str) -> float:
    return round(1.0 - garble_ratio(text), 2)


# ── 표 복원 (우측정렬 숫자 클러스터링) ────────────────────────────────────────

# 숫자 토큰: 콤마·괄호음수·소수·%·부호. 최소 1자리 숫자 포함.
_NUM = re.compile(r"\(?-?[0-9][0-9,]*(?:\.[0-9]+)?%?\)?")


@dataclass(frozen=True)
class Cell:
    text: str
    col: int
    row: int
    char_start: int       # 페이지 내 offset
    char_end: int


@dataclass
class Table:
    page_no: int
    columns: list[int] = field(default_factory=list)  # 컬럼 대표 우측끝 위치
    cells: list[Cell] = field(default_factory=list)

    def rows(self) -> int:
        return 1 + max((c.row for c in self.cells), default=-1)


def _num_tokens(line: str):
    for m in _NUM.finditer(line):
        if re.search(r"[0-9]", m.group(0)):
            yield m.group(0), m.start(), m.end()


def _cluster(edges: list[int], tol: int = 2) -> list[int]:
    """정렬된 우측끝 위치들을 tol 이내로 군집 → 각 군집 대표(최댓값)."""
    if not edges:
        return []
    edges = sorted(edges)
    clusters = [[edges[0]]]
    for e in edges[1:]:
        if e - clusters[-1][-1] <= tol:
            clusters[-1].append(e)
        else:
            clusters.append([e])
    return [max(c) for c in clusters]


def reconstruct_tables(page: PdfPage, *, min_cols: int = 2) -> list[Table]:
    """페이지 텍스트에서 표 블록 복원. 연속된 '숫자 ≥min_cols개' 행을 한 표로 묶고,

    숫자 토큰의 우측끝 위치를 클러스터링해 컬럼을 정의. 각 셀에 (row,col)+char span 부여.
    """
    lines = page.text.split("\n")
    tables: list[Table] = []
    block: list[tuple[int, str, list]] = []  # (line_no, line, tokens)
    line_offset = 0
    offsets: list[int] = []
    off = 0
    for ln in lines:
        offsets.append(off)
        off += len(ln) + 1  # \n

    def flush(blk: list[tuple[int, str, list]]):
        if len(blk) < 2:
            return
        edges = [tok[2] for (_, _, toks) in blk for tok in toks]
        cols = _cluster(edges)
        if len(cols) < min_cols:
            return
        tbl = Table(page_no=page.page_no, columns=cols)
        for r, (line_no, _line, toks) in enumerate(blk):
            for (txt, s, e) in toks:
                # 가장 가까운 컬럼(우측끝 기준)
                ci = min(range(len(cols)), key=lambda i: abs(cols[i] - e))
                tbl.cells.append(Cell(
                    text=txt, col=ci, row=r,
                    char_start=offsets[line_no] + s,
                    char_end=offsets[line_no] + e,
                ))
        tables.append(tbl)

    for line_no, line in enumerate(lines):
        toks = list(_num_tokens(line))
        if len(toks) >= min_cols:
            block.append((line_no, line, toks))
        else:
            flush(block)
            block = []
    flush(block)
    return tables


# ── PdfParser (감사인 트랙: 표 셀 방출) ───────────────────────────────────────


class PdfParser(BaseParser):
    """PDF → 표 셀을 ProvenancedValue 로 방출. garble 신뢰도 반영.

    필드명 = 'p{page}.t{table}.r{row}c{col}'. 라벨이 깨진 표라도 좌표로 추적 가능하고,
    감사인이 페이지·셀 위치로 원문 대조할 수 있다.
    """
    source_kind = SourceKind.PDF
    default_method = ExtractMethod.REGEX

    def __init__(self, source_id: str, *, extractor: TextExtractor = pdftotext_layout,
                 min_cols: int = 2) -> None:
        super().__init__(source_id)
        self.extractor = extractor
        self.min_cols = min_cols
        self.pages: list[PdfPage] = []
        self.tables: list[Table] = []

    def extract(self, raw: object) -> ParseResult:
        """raw = PDF 파일 경로(str). 페이지 추출 → 표 복원 → 셀 방출."""
        path = str(raw)
        self.pages = self.extractor(path)
        for page in self.pages:
            conf = confidence_from_garble(page.text)
            for ti, tbl in enumerate(reconstruct_tables(page, min_cols=self.min_cols)):
                self.tables.append(tbl)
                for cell in tbl.cells:
                    self.emit(
                        f"p{page.page_no}.t{ti}.r{cell.row}c{cell.col}",
                        cell.text,
                        locator=Locator(page=page.page_no, line=cell.row),
                        char_start=page.char_offset + cell.char_start,
                        char_end=page.char_offset + cell.char_end,
                        confidence=conf,
                        method=ExtractMethod.OCR if conf < 0.6 else ExtractMethod.REGEX,
                        note=f"table={ti} col={cell.col}"
                             + (" (garble·OCR권장)" if conf < 0.6 else ""),
                    )
        return self.result


# ── LLM RAG용 텍스트 청크 ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class TextChunk:
    page_no: int
    text: str
    char_start: int       # 문서 전체 기준
    char_end: int
    confidence: float     # garble 반영(사업보고서/IR 디지털=1.0)


def text_chunks(
    pages: list[PdfPage], *, min_chars: int = 40,
) -> list[TextChunk]:
    """LLM RAG용 페이지 텍스트 청크(사업보고서·IR 검색 컨텍스트).

    페이지 단위로 클린 텍스트 + garble 신뢰도 부착. 신뢰도 낮은(스캔/CID) 청크는
    RAG 인덱싱 시 제외하거나 OCR 재처리 대상으로 라우팅한다.
    """
    chunks: list[TextChunk] = []
    for page in pages:
        text = page.text.strip()
        if len(text) < min_chars:
            continue
        chunks.append(TextChunk(
            page_no=page.page_no,
            text=text,
            char_start=page.char_offset,
            char_end=page.char_offset + len(page.text),
            confidence=confidence_from_garble(page.text),
        ))
    return chunks
