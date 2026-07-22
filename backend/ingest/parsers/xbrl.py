"""XBRL 파서 — DART 원문 XBRL(태그된 재무제표)의 결정론적 추출.

XBRL = 가장 깨끗한 입력: OCR·CID 무관, 기계 태그. 구조:
  - fact  : `<ifrs-full:Revenue contextRef=".." unitRef="KRW" decimals="-6">값</>` (값)
  - context: 기간(instant/duration) × 차원(연결/별도·세그먼트) (좌표)
  - unit  : KRW / shares
  - lab-ko: 요소 QName → 한글 계정명

핵심: fact ⋈ context 조인. 주재무제표 = ConsolidatedMember 차원만 있고 세그먼트 축이
없는 context. JSON API(fnlttSinglAcntAll)가 파싱된 요약이라면, XBRL 은 세그먼트·차원까지
원본 태그로 주는 최상위 신뢰 소스.

값 단위: XBRL 은 원(KRW) → parse_number(unit='원')으로 백만원 환산 → calc_core 투입.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from ..provenance import ExtractMethod, Locator, SourceKind
from .base import BaseParser, ParseResult

_XBRLI = "http://www.xbrl.org/2003/instance"
_XBRLDI = "http://xbrl.org/2006/xbrldi"
# fact 로 취급할 요소 네임스페이스 접두(재무 개념). 링크베이스/컨텍스트류는 제외.
_FACT_PREFIXES = ("ifrs-full", "ifrs", "dart", "dart-gcd", "entity")


@dataclass(frozen=True)
class Context:
    id: str
    period: str                       # "2026-03-31" 또는 "2026-01-01~2026-03-31"
    is_instant: bool
    dims: dict[str, str] = field(default_factory=dict)  # {axis(local): member(local)}

    @property
    def consolidation(self) -> str | None:
        """연결/별도 구분(ConsolidatedMember/SeparateMember)."""
        for axis, member in self.dims.items():
            if "ConsolidatedAndSeparate" in axis:
                return member
        return None

    @property
    def non_consolidation_dims(self) -> dict[str, str]:
        """연결/별도 축을 제외한 나머지 차원(세그먼트 등). 주재무제표면 비어있음."""
        return {a: m for a, m in self.dims.items() if "ConsolidatedAndSeparate" not in a}


@dataclass(frozen=True)
class XbrlFact:
    concept: str                      # 요소 local name (예: Revenue)
    prefix: str                       # 네임스페이스 접두 (ifrs-full 등)
    context: Context
    unit: str | None
    decimals: str | None
    value: str

    @property
    def qname(self) -> str:
        return f"{self.prefix}:{self.concept}"


def _local(tag: str) -> tuple[str, str]:
    """'{ns}Local' → (ns, Local)."""
    if tag.startswith("{"):
        ns, local = tag[1:].split("}", 1)
        return ns, local
    return "", tag


def _prefix_for_ns(ns: str) -> str:
    """네임스페이스 URI → 접두 추정."""
    if "ifrs-full" in ns or "/ifrs-full" in ns:
        return "ifrs-full"
    if "/dart-gcd" in ns:
        return "dart-gcd"
    if "/dart" in ns:
        return "dart"
    if "entity" in ns:
        return "entity"
    return ns.rsplit("/", 1)[-1]


def parse_contexts(root: ET.Element) -> dict[str, Context]:
    contexts: dict[str, Context] = {}
    for c in root.findall(f"{{{_XBRLI}}}context"):
        cid = c.get("id")
        period = c.find(f"{{{_XBRLI}}}period")
        instant = period.find(f"{{{_XBRLI}}}instant") if period is not None else None
        if instant is not None:
            per, is_inst = instant.text, True
        else:
            sd = period.find(f"{{{_XBRLI}}}startDate") if period is not None else None
            ed = period.find(f"{{{_XBRLI}}}endDate") if period is not None else None
            per = f"{sd.text}~{ed.text}" if sd is not None and ed is not None else "?"
            is_inst = False
        dims: dict[str, str] = {}
        for em in c.iter(f"{{{_XBRLDI}}}explicitMember"):
            # dimension·member 는 'prefix:Local' QName → local 만 취함(접두 제거)
            axis = em.get("dimension", "").split(":")[-1]
            member = (em.text or "").split(":")[-1].strip()
            dims[axis] = member
        contexts[cid] = Context(cid, per, is_inst, dims)
    return contexts


def parse_facts(root: ET.Element, contexts: dict[str, Context]) -> list[XbrlFact]:
    facts: list[XbrlFact] = []
    for el in root.iter():
        cref = el.get("contextRef")
        if not cref or cref not in contexts:
            continue
        ns, local = _local(el.tag)
        prefix = _prefix_for_ns(ns)
        if not any(prefix.startswith(p) for p in _FACT_PREFIXES):
            continue
        if el.text is None or not el.text.strip():
            continue
        facts.append(XbrlFact(
            concept=local, prefix=prefix, context=contexts[cref],
            unit=el.get("unitRef"), decimals=el.get("decimals"),
            value=el.text.strip(),
        ))
    return facts


_LABEL_ID = re.compile(r"Label_label_(.+?)_(?:ko|en)(?:_\d+)?$")


def load_ko_labels(lab_ko_path: str | Path) -> dict[str, str]:
    """lab-ko.xml → {요소 local name: 한글 표준라벨}.

    라벨 id 'Label_label_{prefix}_{Concept}_ko' 에서 Concept 추출(휴리스틱, 표준 role 우선).
    """
    labels: dict[str, str] = {}
    try:
        root = ET.parse(str(lab_ko_path)).getroot()
    except (ET.ParseError, FileNotFoundError, OSError):
        return labels
    for lab in root.iter():
        _, local = _local(lab.tag)
        if local != "label":
            continue
        role = lab.get("{http://www.w3.org/1999/xlink}role", "")
        lid = lab.get("{http://www.w3.org/1999/xlink}label", "")
        m = _LABEL_ID.match(lid)
        if not m or not lab.text:
            continue
        pfx_concept = m.group(1)                      # 'dart_OtherGains' | 'ifrs-full_Revenue'
        concept = pfx_concept.split("_", 1)[1] if "_" in pfx_concept else pfx_concept
        # 표준 라벨(role=.../label) 우선, 없으면 첫 값 유지
        if role.endswith("/label") or concept not in labels:
            labels[concept] = lab.text.strip()
    return labels


class XbrlParser(BaseParser):
    """DART 원문 XBRL instance → 재무 fact 를 ProvenancedValue 로 방출.

    필드명 = '{연결구분}:{한글계정명 or QName}'. locator 에 account_id(QName)·기간.
    세그먼트 등 추가 차원이 있는 fact 는 note 에 차원 표기(주재무제표와 구분).
    """
    source_kind = SourceKind.DART
    default_method = ExtractMethod.STRUCTURED

    def __init__(self, source_id: str) -> None:
        super().__init__(source_id)
        self.contexts: dict[str, Context] = {}
        self.facts: list[XbrlFact] = []
        self.labels: dict[str, str] = {}

    def extract(self, raw: object) -> ParseResult:
        """raw = .xbrl instance 경로. 형제 *_lab-ko.xml 자동 로드(있으면)."""
        path = Path(str(raw))
        root = ET.parse(str(path)).getroot()
        self.contexts = parse_contexts(root)
        self.facts = parse_facts(root, self.contexts)
        lab = path.with_name(path.stem + "_lab-ko.xml")
        if not lab.exists():
            # entity..._2026-03-31.xbrl → entity..._2026-03-31_lab-ko.xml
            lab = path.parent / (path.stem + "_lab-ko.xml")
        self.labels = load_ko_labels(lab)

        for f in self.facts:
            # 숫자 fact 만 방출(unitRef 有). 비숫자(정책·날짜·엔티티명)는 숫자검증 대상 아님.
            if f.unit is None:
                continue
            name = self.labels.get(f.concept, f.qname)
            con = f.context.consolidation or "?"
            field_name = f"{con}:{name}"
            seg = f.context.non_consolidation_dims
            self.emit(
                field_name, f.value,
                unit="원" if f.unit == "KRW" else None,   # shares 등은 단위환산 안 함
                locator=Locator(account_id=f.qname),
                note=f"period={f.context.period}"
                     + (f" dims={seg}" if seg else " [주재무제표]"),
            )
        return self.result

    @property
    def numeric_facts(self) -> list[XbrlFact]:
        """단위(unitRef) 있는 숫자 fact 만."""
        return [f for f in self.facts if f.unit is not None]

    # ── 편의 필터 ────────────────────────────────────────────────────────────
    def primary_facts(self, consolidation: str = "ConsolidatedMember") -> list[XbrlFact]:
        """주재무제표 fact: 지정 연결구분 + 세그먼트 등 추가차원 없음."""
        return [
            f for f in self.facts
            if f.context.consolidation == consolidation
            and not f.context.non_consolidation_dims
        ]
