"""서사 표현 가드 — 평가의견서·감사조서 텍스트의 결정론 린터.

지식→로직 승격의 텍스트 판. 근거는 [[앤트로픽_금융스킬_벤치마크]] §4
variance-analysis 정본의 서사 규격과 안티패턴 목록:

  규격   `[항목]: [유/불리] 금액(%) / Driver: 왜 / Outlook: 지속·일회성 / Action: 조치`
  금지   순환설명("예상보다 높음") · 무설명("timing") · 뭉뚱그리기("various small items")

여기에 회계 실무 규범 하나를 더한다 — **근거 없는 단정 금지**. 감사인이 "분식입니다",
"확실합니다" 처럼 감사 trail 없이 결론을 확정하면 그 자체가 감사 위험이다. 실무는
"가능성 / 확인 필요 / 권고" 로 표현한다.

## 왜 FAIL 이 아니라 WARN 인가
프로젝트 규약상 FAIL 은 "결과 무효"(계산을 못 믿는다)다. 표현이 나쁘다고 숫자가
틀린 건 아니므로 진행을 막지 않고 표면화만 한다 — 판단은 평가인·감사인 몫이라는
역할 3분할과도 정합. 다만 게이트 산출물에는 반드시 노출된다.

## 오탐 정책
패턴을 넓게 잡으면 정상 문장까지 걸려 사람이 경고를 무시하게 된다(가드가 죽는다).
그래서 **좁게 잡고 매치 구간(span)을 함께 반환**해 왜 걸렸는지 즉시 보이게 한다.
부정문("확실하지 않다")·완화어 동반은 단정으로 보지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ingest.validators import Finding, Severity, ValidationReport

# 서사 필수 슬롯(variance 규격). 값이 비면 "왜·앞으로·무엇을" 이 빠진 조서다.
SLOT_LABELS = {"driver": "Driver(원인)", "outlook": "Outlook(지속·일회성)",
               "action": "Action(조치)"}

# 슬롯 미기재를 뜻하는 자리표시자(UI 기본값·템플릿 잔재). 채운 걸로 치지 않는다.
_PLACEHOLDER = re.compile(
    r"^\s*(?:[-–—]|n/?a|tbd|todo|미정|없음\s*$|_?\(.*필요\)_?|_.*_)\s*$", re.I)


@dataclass(frozen=True)
class _Rule:
    key: str
    label: str
    pattern: re.Pattern
    hint: str


# ── 규칙 정의 ────────────────────────────────────────────────────────────────
# 단정: 감사 trail 없이 결론 확정. 부정·완화 동반형은 아래 _HEDGED 로 면제한다.
_ASSERTION = re.compile(
    r"(분식(?:회계)?(?:이다|입니다|임)|"
    r"확실(?:하다|합니다|히|시)|"
    r"틀림없|의심의\s*여지가?\s*없|"
    r"명백(?:하다|합니다|히|한)|"
    r"단정(?:할\s*수\s*있|적으로)|"
    r"반드시\s*(?:이다|입니다)|"
    r"100%\s*(?:확실|정확)|"
    r"부정(?:이|은)\s*(?:확실|명백))")
# 완화 표현이 같은 문장에 있으면 단정으로 보지 않는다(오탐 억제).
_HEDGED = re.compile(
    r"(가능성|추정|것으로\s*보|판단된다|판단됩니다|권고|확인\s*필요|검토\s*필요|"
    r"의심|시사|우려|않(?:다|음|습니다)|없다고\s*단정)")

# 순환설명: 결과를 원인으로 되풀이. "왜"가 없다.
_CIRCULAR = re.compile(
    r"(예상(?:치)?\s*(?:보다|대비)\s*(?:높|낮|많|적)|"
    r"기대(?:치)?\s*(?:보다|대비)\s*(?:높|낮)|"
    r"higher\s+than\s+expected|lower\s+than\s+expected|"
    r"증가(?:했기\s*때문|한\s*것이\s*원인)|감소(?:했기\s*때문|한\s*것이\s*원인))")

# 무설명: 원인처럼 보이지만 아무 정보가 없는 상투어.
_NON_EXPLANATION = re.compile(
    r"(^|[\s(])(?:시기\s*차이|시점\s*차이|timing(?:\s+difference)?|"
    r"일시적\s*요인|계절적\s*요인)\s*(?:$|[.\s,)]|으?로\s*(?:인한|보임|판단))")

# 뭉뚱그리기: 개별 규명을 회피한 집계 표현.
_VAGUE = re.compile(
    r"(기타\s*(?:소액|항목|사항)|여러\s*(?:항목|요인)|각종\s*요인|"
    r"various\s+(?:small\s+)?items|miscellaneous|등등)")

# 허위정밀(spurious precision, R16) — 주당가치를 원 단위까지 제시하면 모델 정밀도를
# 넘어선 확신을 준다. 관행은 DCF=천원, 상대가치=백원 단위 반올림
# (모델러스 정본 `ROUND(F41/F45*10^3,-3)` / Trading `ROUND(...,-2)`).
# 4자리 이상 금액이 00 으로 끝나지 **않으면서** 주당/목표주가 문맥에 있으면 지적한다.
_SPURIOUS_PRECISION = re.compile(
    r"(?:주당\s*(?:가치|가격)?|목표\s*주가|평가액|내재\s*가치)\s*(?:는|은|이|가|:|=)?\s*"
    r"(?:약\s*)?(\d{1,3}(?:,\d{3})+|\d{4,})\s*원"
)


def _is_spurious_amount(m: "re.Match[str]") -> bool:
    """반올림 규약 위반 여부 — 백원 단위 미만(끝 두 자리가 00 이 아님)이면 위반."""
    return not m.group(1).replace(",", "").endswith("00")


_RULES = (
    _Rule("spurious_precision", "허위정밀(반올림 규약)", _SPURIOUS_PRECISION,
          "주당가치를 원 단위까지 제시했습니다 — 모델 정밀도를 넘어선 확신을 줍니다. "
          "DCF=천원, 상대가치=백원 단위로 반올림하세요."),
    _Rule("assertion", "근거 없는 단정", _ASSERTION,
          "감사 trail 없이 결론을 확정했습니다 — '가능성/확인 필요/권고'로 표현하세요."),
    _Rule("circular", "순환설명", _CIRCULAR,
          "결과를 원인으로 되풀이했습니다 — 무엇이 그렇게 만들었는지 쓰세요."),
    _Rule("non_explanation", "무설명 상투어", _NON_EXPLANATION,
          "'시기 차이/일시적 요인'만으로는 설명이 아닙니다 — 무엇이 언제 왜 밀렸는지 쓰세요."),
    _Rule("vague", "뭉뚱그리기", _VAGUE,
          "개별 규명을 회피했습니다 — 금액이 큰 항목부터 이름을 붙이세요."),
)

# 매치 주변에서 잘라 보여줄 문맥 폭(문자).
_SPAN_PAD = 24


def _sentence_of(text: str, pos: int) -> str:
    """매치 위치가 속한 문장(대략) — 완화어 동반 판정과 근거 표시에 쓴다."""
    start = max(text.rfind(".", 0, pos), text.rfind("\n", 0, pos)) + 1
    end = min((p for p in (text.find(".", pos), text.find("\n", pos)) if p != -1),
              default=len(text))
    return text[start:end].strip()


def check_language(text: str, *, where: str = "", report: ValidationReport | None = None
                   ) -> ValidationReport:
    """서사 텍스트 → 표현 규칙 위반 findings. 위반 없으면 PASS 1건.

    where: 어느 산출물인지(예 'W9 리포트', 'finding:gap'). 메시지에 함께 실린다.
    """
    rep = report if report is not None else ValidationReport()
    prefix = f"{where}: " if where else ""
    hits = 0

    for rule in _RULES:
        for m in rule.pattern.finditer(text or ""):
            sentence = _sentence_of(text, m.start())
            # 단정은 같은 문장에 완화 표현이 있으면 면제(오탐 억제).
            if rule.key == "assertion" and _HEDGED.search(sentence):
                continue
            # 허위정밀은 **반올림 규약을 지킨 금액이면 면제** — 정규식만으로는
            # "주당가치 N원" 형태를 전부 잡으므로 자릿수 판정이 따로 필요하다.
            if rule.key == "spurious_precision" and not _is_spurious_amount(m):
                continue
            lo = max(0, m.start() - _SPAN_PAD)
            hi = min(len(text), m.end() + _SPAN_PAD)
            hits += 1
            rep.add(Finding(
                f"language_{rule.key}", Severity.WARN,
                f"{prefix}{rule.label} — '{m.group(0).strip()}' … {rule.hint}",
                {"rule": rule.key, "match": m.group(0).strip(),
                 "span": [m.start(), m.end()], "context": text[lo:hi].strip(),
                 "sentence": sentence, "where": where},
            ))

    if hits == 0:
        rep.add(Finding("language_guard", Severity.PASS,
                        f"{prefix}표현 규칙 위반 없음", {"where": where}))
    return rep


def check_finding_note(note: dict, *, where: str = "",
                       report: ValidationReport | None = None) -> ValidationReport:
    """발견사항 1건의 Driver/Outlook/Action 슬롯 완비 + 각 슬롯 표현 검사.

    슬롯이 비면 "무엇이 문제인지"만 있고 "왜·앞으로·무엇을"이 없는 조서가 된다
    (variance 규격의 핵심은 이 3슬롯이다).
    """
    rep = report if report is not None else ValidationReport()
    prefix = f"{where}: " if where else ""
    for slot, label in SLOT_LABELS.items():
        val = str(note.get(slot) or "").strip()
        if not val or _PLACEHOLDER.match(val):
            rep.add(Finding("language_slot_missing", Severity.WARN,
                            f"{prefix}{label} 미기재 — 기계가 채울 수 없는 칸입니다(판단 몫).",
                            {"slot": slot, "where": where}))
        else:
            check_language(val, where=f"{where}·{slot}" if where else slot, report=rep)
    return rep


def lint_report(text: str = "", *, notes: dict[str, dict] | None = None,
                where: str = "리포트") -> ValidationReport:
    """조서 전체(본문 + 발견사항 슬롯) 일괄 린트 — API·스킬 W9 공용 진입점."""
    rep = ValidationReport()
    if text:
        check_language(text, where=where, report=rep)
    for key, note in (notes or {}).items():
        check_finding_note(note, where=f"finding:{key}", report=rep)
    return rep
