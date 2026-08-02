"""셀 의존성 그래프 — 모델 연결성 진단·값-only 복원의 공통 기반 (P0).

배경(docs/plan/model_connectivity_and_recovery.md): "WACC 를 고쳤는데 주당가치가 안
변한다"는 사람이 못 알아챈다 — 숫자는 멀쩡히 나오고 대차도 맞고 정적 감사도 통과한다.
오직 그래프만 **"이 가정은 결과에 도달하지 못한다"** 고 말할 수 있다(비올 진본 실사례:
WACC 탭이 빈 템플릿인데 `DCF!H37` 이 11.3% 상수 → WACC 시트를 고쳐도 결과 불변).

설계 결정(계획 문서 §3-1에서 고정):
  · 범위 참조(`SUM(A1:A10)`)는 **범위 노드**로 두고 멤버는 필요 시 확장 — 즉시 확장하면
    대형 워크북에서 노드가 폭발한다. 도달성 판정에는 확장 시점이 늦어도 결과가 같다.
  · 동적 참조(`INDIRECT`·`OFFSET`)는 **추적 불가(unknown)로 표면화**한다. 조용히 무시하면
    "도달 안 함"이라는 **거짓 결론**이 난다 — 이 레포가 금지하는 조용한 실패의 그래프판.
  · 순환은 검출하되 정상 순환(3표 이자 등)은 호출부가 화이트리스트로 거른다(R14 정합).
  · ⚠️ 이름 정의(named range)는 **미해석**(이번 단계 한계) — 이름 참조가 있는 수식은
    해당 토큰이 무시되어 도달성이 과소평가될 수 있다. 비올 계열(연수 템플릿)은 이름
    정의를 쓰지 않아 P0 검증에는 영향이 없고, 필요해지는 시점에 xlsx_reader 확장으로 푼다.

용법:
    wb = read_workbook(path)                  # {sheet: {ref: RCell}}
    g = build_graph(wb)
    b = find_breaks(g, target="DCF!H44")      # 도달/미도달·상수 잎·고아·unknown
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

# ── 참조 토크나이저 ─────────────────────────────────────────────────────────
_QUOTED_RE = re.compile(r'"[^"]*"')
_EXTERNAL_RE = re.compile(r"\[[^\]]+\]")            # 존재 감지용: [다른파일.xlsx]Sheet!A1
# 파싱 제거용은 **참조 토큰 전체**를 걷어내야 한다 — 대괄호만 지우면 `Sheet1!B2` 가
# 남아 내부 참조로 오인된다(테스트가 실제로 잡은 결함). 따옴표형('[Book]Sheet 1'!A1)과
# 비따옴표형([Book]Sheet1!A1) 모두 커버.
_EXTERNAL_TOKEN_RE = re.compile(
    r"(?:'\[[^']*'|\[[^\]]+\][A-Za-z0-9_.가-힣]*)"
    r"!\$?[A-Z]{1,3}\$?[0-9]+(?:\s*:\s*\$?[A-Z]{1,3}\$?[0-9]+)?")
_DYNAMIC_RE = re.compile(r"\b(INDIRECT|OFFSET)\s*\(", re.I)
_SHEET_PART = r"(?:'([^']+)'|([A-Za-z0-9_.가-힣]+))!"
# 범위를 단일 셀보다 먼저 매칭해야 A1:B10 이 A1, B10 두 참조로 쪼개지지 않는다.
_REF_RE = re.compile(
    rf"(?<![A-Za-z0-9_$])(?:{_SHEET_PART})?"
    r"\$?([A-Z]{1,3})\$?([1-9][0-9]{0,6})"
    r"(?:\s*:\s*\$?([A-Z]{1,3})\$?([1-9][0-9]{0,6}))?"
    r"(?![\w(])")


def _col_idx(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def _key(sheet: str, col: str, row: str) -> str:
    return f"{sheet}!{col}{row}"


# ── 노드·그래프 ────────────────────────────────────────────────────────────
@dataclass
class CellNode:
    sheet: str
    ref: str                       # "A1" (절대기호 제거·대문자)
    kind: str                      # formula | constant | text | empty | error
    formula: str | None = None
    value: object = None


@dataclass
class DependencyGraph:
    nodes: dict[str, CellNode] = field(default_factory=dict)
    # key → 선행 토큰들. 토큰 = ("cell", key) | ("range", sheet, r1, c1, r2, c2)
    precedents: dict[str, list[tuple]] = field(default_factory=dict)
    dependents: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    unknown_cells: set[str] = field(default_factory=set)    # INDIRECT/OFFSET 포함 수식
    external_cells: set[str] = field(default_factory=set)   # 타 워크북 참조 수식
    _sheet_index: dict[str, list[tuple[int, int, str]]] = field(default_factory=dict)
    _range_cache: dict[tuple, list[str]] = field(default_factory=dict)

    def range_members(self, token: tuple) -> list[str]:
        """범위 토큰 → 워크북에 실재하는 멤버 셀 key 들(lazy + 캐시)."""
        if token in self._range_cache:
            return self._range_cache[token]
        _, sheet, r1, c1, r2, c2 = token
        members = [k for (row, col, k) in self._sheet_index.get(sheet, [])
                   if r1 <= row <= r2 and c1 <= col <= c2]
        self._range_cache[token] = members
        return members


def _cell_kind(cell) -> tuple[str, object, str | None]:
    f = getattr(cell, "formula", None)
    v = getattr(cell, "value", None)
    if v is None:
        v = getattr(cell, "number", None)
    if f:
        return "formula", v, f
    if isinstance(v, str):
        if v.startswith("#"):
            return "error", v, None
        return ("empty", None, None) if not v.strip() else ("text", v, None)
    if v is None:
        return "empty", None, None
    return "constant", v, None


def _parse_refs(formula: str, host_sheet: str) -> list[tuple]:
    """수식 → 선행 토큰 목록. 문자열 리터럴·외부참조 구간은 제거 후 파싱."""
    body = _EXTERNAL_TOKEN_RE.sub("", _QUOTED_RE.sub('""', formula))
    tokens: list[tuple] = []
    for m in _REF_RE.finditer(body):
        sheet = (m.group(1) or m.group(2) or host_sheet)
        c1, r1 = m.group(3), int(m.group(4))
        if m.group(5):                                   # 범위 A1:B10
            c2, r2 = m.group(5), int(m.group(6))
            lo_r, hi_r = sorted((r1, r2))
            lo_c, hi_c = sorted((_col_idx(c1), _col_idx(c2)))
            tokens.append(("range", sheet, lo_r, lo_c, hi_r, hi_c))
        else:
            tokens.append(("cell", _key(sheet, c1, str(r1))))
    return tokens


def build_graph(workbook: dict[str, dict]) -> DependencyGraph:
    """read_workbook 산출({sheet: {ref: RCell}}) → 의존성 그래프."""
    g = DependencyGraph()
    for sheet, cells in workbook.items():
        idx: list[tuple[int, int, str]] = []
        for ref, cell in cells.items():
            m = re.fullmatch(r"([A-Z]{1,3})([0-9]+)", ref)
            if not m:
                continue
            kind, value, formula = _cell_kind(cell)
            key = f"{sheet}!{ref}"
            g.nodes[key] = CellNode(sheet, ref, kind, formula, value)
            idx.append((int(m.group(2)), _col_idx(m.group(1)), key))
            if kind != "formula":
                continue
            if _DYNAMIC_RE.search(formula):
                g.unknown_cells.add(key)
            if _EXTERNAL_RE.search(formula):
                g.external_cells.add(key)
            toks = _parse_refs(formula, sheet)
            g.precedents[key] = toks
            for t in toks:
                if t[0] == "cell":
                    g.dependents[t[1]].add(key)
        g._sheet_index[sheet] = idx
    # 범위 토큰의 dependents 는 멤버 확장 시점에 필요해지므로 여기서 한 번 배선한다.
    for key, toks in g.precedents.items():
        for t in toks:
            if t[0] == "range":
                for mk in g.range_members(t):
                    g.dependents[mk].add(key)
    return g


# ── 분석 ───────────────────────────────────────────────────────────────────
def ancestors(g: DependencyGraph, target: str) -> set[str]:
    """target 의 선행 폐포(역방향 BFS) — target 에 **실제로 도달하는** 셀 집합."""
    seen: set[str] = set()
    stack = [target]
    while stack:
        k = stack.pop()
        if k in seen:
            continue
        seen.add(k)
        for t in g.precedents.get(k, ()):  # 상수·빈 셀은 precedents 없음 → 잎
            if t[0] == "cell":
                if t[1] not in seen:
                    stack.append(t[1])
            else:                          # 범위 → 멤버 확장
                for mk in g.range_members(t):
                    if mk not in seen:
                        stack.append(mk)
    return seen


def descendants(g: DependencyGraph, source: str) -> set[str]:
    """source 의 후행 폐포(순방향 BFS)."""
    seen: set[str] = set()
    stack = [source]
    while stack:
        k = stack.pop()
        if k in seen:
            continue
        seen.add(k)
        stack.extend(d for d in g.dependents.get(k, ()) if d not in seen)
    return seen


def cycles(g: DependencyGraph, *, whitelist_sheets: frozenset = frozenset()) -> list[list[str]]:
    """순환 참조 검출(Tarjan SCC, size>1 또는 자기참조).

    whitelist_sheets: 정상 순환으로 인정할 시트(3표 이자 순환 등, R14) — 순환의
    **모든** 셀이 화이트리스트 시트에 있으면 보고에서 제외.
    """
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on: set[str] = set()
    stack: list[str] = []
    out: list[list[str]] = []
    counter = [0]

    def adj(k: str) -> list[str]:
        res = []
        for t in g.precedents.get(k, ()):
            if t[0] == "cell":
                res.append(t[1])
            else:
                res.extend(g.range_members(t))
        return res

    def strong(v: str) -> None:                      # 재귀 대신 명시 스택(대형 워크북 안전)
        work = [(v, iter(adj(v)))]
        index[v] = low[v] = counter[0]; counter[0] += 1
        stack.append(v); on.add(v)
        while work:
            node, it = work[-1]
            advanced = False
            for w in it:
                if w not in g.nodes:
                    continue
                if w not in index:
                    index[w] = low[w] = counter[0]; counter[0] += 1
                    stack.append(w); on.add(w)
                    work.append((w, iter(adj(w))))
                    advanced = True
                    break
                if w in on:
                    low[node] = min(low[node], index[w])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                scc = []
                while True:
                    w = stack.pop(); on.discard(w); scc.append(w)
                    if w == node:
                        break
                if len(scc) > 1 or node in adj(node):
                    out.append(sorted(scc))

    for k in g.precedents:
        if k not in index:
            strong(k)
    if whitelist_sheets:
        out = [c for c in out
               if not all(k.split("!")[0] in whitelist_sheets for k in c)]
    return out


def formula_ratio(g: DependencyGraph) -> float:
    """수식 셀 비율 — 임계 미만이면 값-only 워크북(감사인 복원 모드 분기 신호)."""
    numeric = [n for n in g.nodes.values() if n.kind in ("formula", "constant")]
    if not numeric:
        return 0.0
    return sum(1 for n in numeric if n.kind == "formula") / len(numeric)


@dataclass
class BreaksReport:
    """연결성 진단 — '파악'의 산출물. 수정 제안·tie-out 은 P1 소비자 몫."""
    target: str
    reach: set[str]                                 # target 에 도달하는 셀(ancestors)
    sheet_summary: dict[str, dict[str, int]]        # 시트별 {reaching, not_reaching} (수식만)
    dead_sheets: list[str]                          # 수식이 있는데 단 하나도 도달 못 하는 시트
    constant_inputs_in_path: list[str]              # 경로상 상수 잎(숫자) — 승격 후보
    orphan_formulas: list[str]                      # out-degree 0 수식(고아 계산, target 제외)
    unknown_cells: list[str]                        # 동적 참조 — 진단이 과소평가될 수 있는 지점
    external_cells: list[str]


@dataclass
class ReconnectProposal:
    """끊김 수정 제안 — "이 상수를 저 수식 참조로 교체하라" + 캐시값 tie-out.

    tie_out 의미(정직 표기): 재계산 엔진이 없으므로 **캐시값 비교**가 한계다.
      · "pass"        — 후보 수식의 캐시값 == 상수(연결해도 결과 불변이 강하게 시사됨)
      · "value_change" — 값이 다름. 연결하면 결과가 바뀐다 = **원래 상수가 낡았거나
        틀렸다는 뜻**이므로 자동 적용 금지, 변화율을 보여주고 사람이 판단한다.
    실사례: 비올 DCF!H37=0.113(하드) vs WACC!F43=0.11252(빌드업) — 0.4% 차이가
    "하드코딩이 낡은 값"의 증거였다(포폴판에서 참조 연결로 수정됨).
    """
    constant_cell: str
    constant_value: float
    candidate_cell: str
    candidate_value: float
    diff_ratio: float
    tie_out: str                    # "pass" | "value_change"
    suggested_formula: str          # 예: "=WACC!F43"


def propose_reconnections(
    g: DependencyGraph,
    breaks: BreaksReport,
    *,
    pass_tol: float = 1e-6,
    match_tol: float = 0.02,
    max_proposals: int = 20,
) -> list[ReconnectProposal]:
    """경로상 상수 잎마다, **결과에 도달하지 못하는 수식** 중 캐시값이 일치/근사한
    후보를 찾아 참조 교체를 제안한다.

    후보를 '미도달 수식'으로 한정하는 이유: 이미 도달하는 수식과 값이 같은 상수는
    표시 중복일 뿐이고, 진짜 끊김은 "계산은 존재하는데 소비자가 상수를 쓰는" 형태다
    (비올 WACC 시트). 0 값 상수는 제외 — 0 끼리는 어디서나 일치해 제안이 무의미하다.
    """
    dead = [(k, n) for k, n in g.nodes.items()
            if n.kind == "formula" and k not in breaks.reach
            and isinstance(n.value, (int, float))]
    out: list[ReconnectProposal] = []
    for ck in breaks.constant_inputs_in_path:
        cv = g.nodes[ck].value
        if not isinstance(cv, (int, float)) or cv == 0:
            continue
        best: tuple[float, str, float] | None = None      # (diff, key, value)
        for k, n in dead:
            d = abs(n.value - cv) / max(abs(cv), 1e-12)
            if d <= match_tol and (best is None or d < best[0]):
                best = (d, k, n.value)
        if best is None:
            continue
        d, k, val = best
        sheet, ref = k.split("!", 1)
        pref = f"'{sheet}'" if re.search(r"[^\w가-힣.]", sheet) else sheet
        out.append(ReconnectProposal(
            constant_cell=ck, constant_value=cv,
            candidate_cell=k, candidate_value=val, diff_ratio=d,
            tie_out="pass" if d <= pass_tol else "value_change",
            suggested_formula=f"={pref}!{ref}",
        ))
    out.sort(key=lambda p: p.diff_ratio)
    return out[:max_proposals]


def find_breaks(g: DependencyGraph, target: str) -> BreaksReport:
    if target not in g.nodes:
        raise KeyError(f"목표 셀 '{target}' 이 워크북에 없음")
    reach = ancestors(g, target)
    down = descendants(g, target)

    sheet_summary: dict[str, dict[str, int]] = defaultdict(lambda: {"reaching": 0, "not_reaching": 0})
    for k, n in g.nodes.items():
        if n.kind != "formula":
            continue
        if k in reach:
            sheet_summary[n.sheet]["reaching"] += 1
        elif k not in down:
            # target 하류(표시·비율 셀)는 '도달 안 함'으로 세지 않는다 — 정상이다.
            sheet_summary[n.sheet]["not_reaching"] += 1

    dead = sorted(s for s, c in sheet_summary.items()
                  if c["reaching"] == 0 and c["not_reaching"] > 0)

    consts = sorted(
        k for k in reach
        if g.nodes[k].kind == "constant" and isinstance(g.nodes[k].value, (int, float)))

    orphans = sorted(
        k for k, n in g.nodes.items()
        if n.kind == "formula" and k != target and not g.dependents.get(k))

    return BreaksReport(
        target=target, reach=reach, sheet_summary=dict(sheet_summary),
        dead_sheets=dead, constant_inputs_in_path=consts,
        orphan_formulas=orphans,
        unknown_cells=sorted(g.unknown_cells),
        external_cells=sorted(g.external_cells),
    )
