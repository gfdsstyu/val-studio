"""외부 모델 정적 감사 — 수식 패턴 린트·하드코딩 스캔·민감도 중심셀 검산.

플랫폼 네이티브 엔진은 수식 복사가 없고 민감도를 셀마다 재계산하므로 참조 밀림·
축 오류가 구조적으로 불가능하다. 이 모듈의 대상은 **워크북**(유저 업로드·외부
모델·엔진 export 의 사후 편집본)이다. 재계산 없이(COM 불요) 수식 문자열의 정적
분석만으로 작동한다 — Cloud Run 호환.

근거(귀납, 비올 DCF 리뷰 §7.1·§9): 결함 ①계열(참조 밀림 6건)은 전부 "수식을
옆·아래로 복사하며 시작 참조를 고정하지 않은" 동일 병리 = **이웃 패턴을 깨는
수식**으로 표면화된다. R1C1 정규화(호스트 셀 기준 상대 오프셋) 후 이웃과 대조하면
레이아웃 지식 없이 잡힌다. 단 **행 전체가 균일하게 밀린 경우**(비올 E-3: ΔNWC 5열
밀림 — 이웃도 같이 틀림)는 못 잡는다 — 그 유형은 L3 분석적 절차(접합부·성장-운전
자본 정합)가 담당한다. 두 계층은 상호 보완이지 대체가 아니다.

검사 3종:
  formula_pattern_lint : 같은 행/열 연속 수식 구간에서 다수 패턴과 다른 셀 (E-6·E-10 계열)
  hardcode_scan        : 수식 내 숫자 리터럴 (비올 T164 의 `*32` = +2,435백만 진원지;
                         "하드코딩 오버라이드가 조용한 버그 1위 — 공격적으로 수색")
  check_sensitivity_center : 민감도 표 중심 ≟ 본계산 — 한 검사로 축 오류(E-9)·stale·
                         연결 끊김·값 파손 4유형 동시 적발 (비용 대비 효과 최대)
"""
from __future__ import annotations

import re
from collections import Counter

from ingest.validators import Finding, Severity, ValidationReport

# 민감도 중심셀 허용오차(주당가치 단위). 비올 실측 괴리는 221원(8,634.7 vs 8,413.4).
SENSITIVITY_CENTER_TOL = 0.01
# 수식 리터럴 화이트리스트 — 구조 상수(연산 관용값)만. 그 외 숫자는 가정이므로
# 셀 참조여야 한다(R4 Key-in 금지). 0.5=mid-year, 365/12=기간, 10·100·1000=자릿수.
HARDCODE_WHITELIST = frozenset({0.0, 1.0, 2.0, 6.0, 10.0, 12.0, 100.0, 365.0,
                                1000.0, 0.5})
# 시트당 패턴 finding 상한(스팸 방지) — 초과분은 잘렸음을 detail 에 남긴다.
MAX_PATTERN_FINDINGS = 50

# A1 참조(시트 프리픽스·절대/상대 혼합) 토크나이저.
# lookbehind: LOG10/ATAN2 등 함수명 중간 매칭 방지. lookahead: 뒤에 문자·괄호 금지.
_REF_RE = re.compile(
    r"(?<![A-Za-z0-9_$])"
    r"((?:'[^']*'|[A-Za-z0-9_.가-힣]+)!)?"
    r"(\$?)([A-Z]{1,3})(\$?)([1-9][0-9]{0,6})"
    r"(?![\w(])")
_QUOTED_RE = re.compile(r'"[^"]*"')
_UNIT_CONV_RE = re.compile(r"10\^6")


def _col_idx(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def _ref_rc(ref: str) -> tuple[int, int]:
    """'M162' → (row=162, col=13)."""
    m = re.fullmatch(r"([A-Z]{1,3})([0-9]+)", ref)
    if not m:
        raise ValueError(f"셀 주소 아님: {ref}")
    return int(m.group(2)), _col_idx(m.group(1))


def normalize_r1c1(formula: str, host_ref: str) -> str:
    """수식의 A1 참조를 호스트 셀 기준 R1C1(상대 오프셋)로 정규화.

    같은 패턴으로 복사된 수식은 호스트가 달라도 정규화 결과가 같아진다 —
    "이웃과 다른 셀"이 곧 참조 밀림/구조 이탈 후보. 절대참조($)는 절대 표기
    유지(전 열이 $G$162 를 참조하면 전부 R162C7 로 동일해진다).
    """
    host_row, host_col = _ref_rc(host_ref)

    def _sub(m: re.Match) -> str:
        sheet = m.group(1) or ""
        r = f"R{m.group(5)}" if m.group(4) else f"R[{int(m.group(5)) - host_row:+d}]"
        c = (f"C{_col_idx(m.group(3))}" if m.group(2)
             else f"C[{_col_idx(m.group(3)) - host_col:+d}]")
        return f"{sheet}{r}{c}"

    return _REF_RE.sub(_sub, _QUOTED_RE.sub('""', formula))


def _contiguous_runs(sorted_keys: list[int]) -> list[list[int]]:
    runs, cur = [], [sorted_keys[0]]
    for k in sorted_keys[1:]:
        if k == cur[-1] + 1:
            cur.append(k)
        else:
            runs.append(cur)
            cur = [k]
    runs.append(cur)
    return runs


def formula_pattern_lint(
    cells: dict,
    *,
    sheet_name: str = "",
    min_run: int = 3,
    report: ValidationReport | None = None,
) -> list[Finding]:
    """행·열 방향 연속 수식 구간에서 다수 패턴을 깨는 셀 감지 (WARN, 셀 단위).

    구간 내 최빈 패턴이 과반이고 소수 셀이 있으면 그 셀을 지목한다. 비올 실측:
    E-6(`M162=J162` vs 이웃 `$G$162`)·E-10(합계가 SUM vs 이웃 ×)·E-8(열별 항 개수
    상이)이 전부 이 형태. 정상적 구조 변화(구간 경계)는 연속 구간 분리로 배제된다.
    """
    findings: list[Finding] = []
    parsed = []
    for ref, cell in cells.items():
        f = getattr(cell, "formula", None)
        if not f:
            continue
        try:
            row, col = _ref_rc(ref)
        except ValueError:
            continue
        parsed.append((row, col, ref, f))

    def _scan(axis: str) -> None:
        groups: dict[int, dict[int, tuple[str, str]]] = {}
        for row, col, ref, f in parsed:
            g, k = (row, col) if axis == "row" else (col, row)
            groups.setdefault(g, {})[k] = (ref, f)
        for g, members in sorted(groups.items()):
            for run in _contiguous_runs(sorted(members)):
                if len(run) < min_run:
                    continue
                norm = {k: normalize_r1c1(members[k][1], members[k][0]) for k in run}
                mode, mode_n = Counter(norm.values()).most_common(1)[0]
                if mode_n <= len(run) // 2:            # 과반 아님 — 판정 불가
                    continue
                sample = next(members[k][0] + "=" + members[k][1]
                              for k in run if norm[k] == mode)
                for k in run:
                    if norm[k] == mode:
                        continue
                    ref, f = members[k]
                    findings.append(Finding(
                        "formula_pattern", Severity.WARN,
                        f"{sheet_name}!{ref}: 이웃 {mode_n}개 패턴과 다른 수식 "
                        f"`={f}` (다수 예: `{sample}`) — 참조 밀림/구조 이탈 의심",
                        {"sheet": sheet_name, "ref": ref, "formula": f,
                         "direction": axis, "run_size": len(run),
                         "mode_pattern": mode, "cell_pattern": norm[k],
                         "mode_sample": sample, "layer": "execution"}))

    _scan("row")
    _scan("col")
    if len(findings) > MAX_PATTERN_FINDINGS:
        dropped = len(findings) - MAX_PATTERN_FINDINGS
        findings = findings[:MAX_PATTERN_FINDINGS]
        findings.append(Finding(
            "formula_pattern", Severity.WARN,
            f"{sheet_name}: 패턴 이탈 {dropped}건 추가 생략(상한 {MAX_PATTERN_FINDINGS})"
            f" — 계통적 결함 의심, 시트 전수 재검토",
            {"sheet": sheet_name, "dropped": dropped, "layer": "execution"}))
    if report is not None:
        for f in findings:
            report.add(f)
    return findings


def hardcode_scan(
    cells: dict,
    *,
    sheet_name: str = "",
    whitelist: frozenset = HARDCODE_WHITELIST,
    report: ValidationReport | None = None,
) -> Finding:
    """수식 내 숫자 리터럴(`=M165*32` 형태) 검출 — R4 Key-in 금지의 수식 버전.

    참조·문자열·단위환산(10^6)을 걷어낸 뒤 남는 숫자가 화이트리스트 밖이면 지목.
    가정은 셀 참조여야 출처(provenance)가 생긴다 — 리터럴은 그 자체로 숨은 가정.
    """
    offenders = []
    for ref, cell in cells.items():
        f = getattr(cell, "formula", None)
        if not f:
            continue
        stripped = _UNIT_CONV_RE.sub("", _REF_RE.sub("", _QUOTED_RE.sub("", f)))
        nums = [float(t) for t in
                re.findall(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])", stripped)]
        bad = sorted({n for n in nums if n not in whitelist})
        if bad:
            offenders.append({"ref": ref, "formula": f, "literals": bad})
    detail = {"sheet": sheet_name, "offenders": offenders, "layer": "execution"}
    if offenders:
        f = Finding("formula_hardcode", Severity.WARN,
                    f"{sheet_name}: 수식 내 리터럴 {len(offenders)}셀 "
                    f"(예 {offenders[0]['ref']}=`{offenders[0]['formula']}`) — "
                    f"가정이면 참조화(R4), 불가피하면 별도 서식 표시",
                    detail)
    else:
        f = Finding("formula_hardcode", Severity.PASS,
                    f"{sheet_name}: 수식 내 비관용 리터럴 없음", detail)
    if report is not None:
        report.add(f)
    return f


def check_sensitivity_center(
    reported: float,
    recomputed: float,
    *,
    tol: float = SENSITIVITY_CENTER_TOL,
    report: ValidationReport | None = None,
) -> Finding:
    """민감도 표 중심셀 ≟ 본계산 값 — 한 줄로 4개 결함 유형 동시 적발.

    ① 축이 입력셀을 참조하는 순환(비올 E-9: 표 전체 밀림, 재계산해도 안 고쳐짐)
    ② stale 데이터테이블(리포트 내장본 파손 유형) ③ 축 설정 오류 ④ 수식 연결
    끊김. 비올 실측: 표시 8,634.7 vs 실제 8,413.4 (+2.6% 과대 오독, 민감도 폭은
    절반으로 축소 표시).
    """
    diff = reported - recomputed
    detail = {"reported": reported, "recomputed": recomputed, "diff": diff,
              "tol": tol, "layer": "execution"}
    if abs(diff) > tol:
        f = Finding("sensitivity_center", Severity.WARN,
                    f"민감도 중심셀 {reported:,.2f} ≠ 본계산 {recomputed:,.2f} "
                    f"(차이 {diff:+,.2f}) — 축 순환(E-9형)/stale/연결 끊김 의심, "
                    f"표 재생성 후 재검증",
                    detail)
    else:
        f = Finding("sensitivity_center", Severity.PASS,
                    f"민감도 중심셀 = 본계산({recomputed:,.2f}) 정합", detail)
    if report is not None:
        report.add(f)
    return f


def audit_workbook(
    wb: dict[str, dict],
    *,
    report: ValidationReport | None = None,
) -> ValidationReport:
    """워크북 전 시트에 패턴 린트 + 하드코딩 스캔 적용 (중심셀 검산은 값이 필요해
    호출자가 재계산 결과와 함께 check_sensitivity_center 를 별도 호출)."""
    if report is None:
        report = ValidationReport()
    for sheet_name, cells in wb.items():
        formula_pattern_lint(cells, sheet_name=sheet_name, report=report)
        hardcode_scan(cells, sheet_name=sheet_name, report=report)
    return report
