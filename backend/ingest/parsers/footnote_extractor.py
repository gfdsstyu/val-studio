"""주석(footnote) 추출기 — classifyJu 위치규칙 + charIndex provenance.

재무제표·주석 텍스트에서 (주N) 참조를 위치규칙으로 분류하고, 본문포인터가 달린
라인아이템의 값을 출처(char span + note_no)와 함께 방출한다. 감사인 트랙의
"주석 감가상각비 = CF D&A" 같은 정합검증(tie_out)의 원재료.

핵심(감린이 structured_meta 각주규칙과 동형): 같은 '주5' 토큰도 위치로 의미가 갈린다.
  - 본문포인터(POINTER): `유형자산 (주5) 1,234` — 괄호 안, 라인이 주석을 가리킴 → 값=1,234
  - 정의블록(DEFINITION): `주5. 유형자산` — 라인 시작 + 제목, 주석이 정의됨 → 값 아님
이 분리로 포인터를 값으로 오독하거나 정의 헤딩을 데이터로 긁는 오류를 막는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from ..provenance import ExtractMethod, Locator, SourceKind
from ..validators import Finding, Severity, ValidationReport, parse_number, tie_out
from .base import BaseParser, ParseResult


class JuKind(str, Enum):
    POINTER = "pointer"        # (주N) 본문포인터
    DEFINITION = "definition"  # 주N. 정의블록


@dataclass(frozen=True)
class JuRef:
    """분류된 주석 참조 하나."""
    note_no: int
    kind: JuKind
    char_start: int
    char_end: int
    line_no: int
    line_text: str


# (주5) / (주 5) / (주5,6) / (주5, 6) — 괄호로 감싼 본문포인터
_POINTER = re.compile(r"\(\s*주\s*([0-9]+(?:\s*[,，]\s*[0-9]+)*)\s*\)")
# 라인 시작 "주5." / "5." / "주석 5." + 제목(숫자로 시작하지 않는 텍스트)
_DEFINITION = re.compile(r"^\s*(?:주\s*석?\s*)?([0-9]+)\s*[.．]\s+(?=\D)(\S.*)$")
# 라인에서 숫자값 후보(콤마·괄호음수·소수·부호). (주N) 제거 후 스캔.
_NUMBER = re.compile(r"\(?-?[0-9][0-9,]*(?:\.[0-9]+)?\)?")


def classify_ju(text: str) -> list[JuRef]:
    """텍스트의 모든 주석 참조를 위치규칙으로 분류. char span 은 원문 절대 offset.

    한 줄에 포인터가 여러 개(여러 note_no)면 각각 별도 JuRef. 정의블록은 라인당 최대 1개.
    """
    refs: list[JuRef] = []
    offset = 0
    for line_no, line in enumerate(text.splitlines(keepends=True)):
        stripped_len = len(line)
        core = line.rstrip("\n")

        # ① 본문포인터: 괄호 안 (주N[,M...])
        for m in _POINTER.finditer(core):
            nums = re.split(r"[,，]", m.group(1))
            # 괄호 전체 span 을 각 note_no 가 공유(정확 위치는 그룹으로 좁힐 수 있음)
            for n in nums:
                n = n.strip()
                if n.isdigit():
                    refs.append(JuRef(int(n), JuKind.POINTER,
                                      offset + m.start(), offset + m.end(),
                                      line_no, core.strip()))

        # ② 정의블록: 라인 시작 N. + 제목 (포인터가 이미 잡은 라인이라도 헤딩이면 정의)
        dm = _DEFINITION.match(core)
        if dm:
            # 제목이 실제 서술(숫자/기호만이 아님)일 때만 정의로 인정
            title = dm.group(2).strip()
            if any(ch.isalpha() or "가" <= ch <= "힣" for ch in title):
                refs.append(JuRef(int(dm.group(1)), JuKind.DEFINITION,
                                  offset + dm.start(1), offset + dm.end(1),
                                  line_no, core.strip()))
        offset += stripped_len
    return refs


def _last_number_span(core: str) -> tuple[str, int, int] | None:
    """(주N) 토큰 제거 후 라인에서 마지막 숫자 토큰(값)과 그 span 반환."""
    masked = _POINTER.sub(lambda m: " " * (m.end() - m.start()), core)
    last = None
    for m in _NUMBER.finditer(masked):
        tok = m.group(0)
        # 단독 '(주5)' 잔재나 순수 구분자 제외 — 숫자 1자리 이상
        if re.search(r"[0-9]", tok):
            last = (tok, m.start(), m.end())
    return last


class FootnoteExtractor(BaseParser):
    """재무제표/주석 텍스트 → 본문포인터가 달린 라인아이템 값 방출(출처=note_no+span).

    각 포인터 라인에서 마지막 숫자를 값으로 보고, 참조하는 note_no 를 locator 에 부착한다.
    필드명은 라인의 계정명(포인터·숫자 제거한 선두 텍스트)으로 붙인다.
    """
    source_kind = SourceKind.FOOTNOTE
    default_method = ExtractMethod.REGEX

    def extract(self, raw: object) -> ParseResult:
        text = str(raw)
        refs = classify_ju(text)
        self.definitions = {r.note_no: r for r in refs if r.kind is JuKind.DEFINITION}
        self.pointers = [r for r in refs if r.kind is JuKind.POINTER]

        # 라인별 포인터 그룹핑 → 그 라인의 값 추출
        by_line: dict[int, list[JuRef]] = {}
        for r in self.pointers:
            by_line.setdefault(r.line_no, []).append(r)

        lines = text.splitlines()
        for line_no, prs in by_line.items():
            core = lines[line_no]
            num = _last_number_span(core)
            note_nos = sorted({r.note_no for r in prs})
            # 계정명 = 라인 선두에서 (주N)·숫자 앞까지
            head = _POINTER.split(core)[0].strip() or f"line{line_no}"
            field_name = re.sub(r"\s+", "_", head)[:40]
            if num is None:
                # 포인터는 있으나 값 없음(서술형 참조) — 기록만
                self.result.report.add(Finding(
                    "footnote", Severity.WARN,
                    f"{field_name}: (주{note_nos}) 포인터 있으나 값 없음", {"line": line_no}))
                continue
            tok, s, e = num
            self.emit(
                field_name, tok,
                locator=Locator(note_no=note_nos[0], line=line_no),
                char_start=core_offset(text, line_no) + s,
                char_end=core_offset(text, line_no) + e,
                note=f"refs={note_nos}" + (
                    "" if all(n in self.definitions for n in note_nos)
                    else f" (정의없음:{[n for n in note_nos if n not in self.definitions]})"),
            )
        return self.result


def core_offset(text: str, line_no: int) -> int:
    """text 내 line_no 번째 줄의 시작 char offset."""
    off = 0
    for i, line in enumerate(text.splitlines(keepends=True)):
        if i == line_no:
            return off
        off += len(line)
    return off


def tie_footnote_to_statement(
    name: str,
    footnote_value: object,
    statement_value: object,
    *,
    report: ValidationReport | None = None,
) -> Finding:
    """④ 정합성: 주석 값 == 재무제표/CF 값 (예: 주석 감가상각 = CF D&A).

    parse_number 로 양쪽 정규화 후 validators.tie_out 위임.
    """
    a = parse_number(footnote_value)
    b = parse_number(statement_value)
    return tie_out(name, a, b, report=report)
