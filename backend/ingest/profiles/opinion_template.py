"""외부평가의견서 시맨틱 프로파일 — 고정양식 앵커로 유의적 가정 추출.

한글 라벨이 CID로 깨져도 **영문·수식 앵커는 생존**한다. 그 앵커로 필드를 특정:
  - `WACC = Ke` / `WACC =` 공식 → 엔티티(평가대상) 경계·개수 (SOTP)
  - `(1 + B)` / `(1+B)` 성장 수식 근처 % → 영구성장률(관행 1.00%)
  - `Size Risk Premium` 근처 % → 규모프리미엄
  - `(: JPY)` / iso4217 → 통화(다통화 SOTP)

감사인 트랙 입구: 의견서에서 WACC·영구성장률·통화·엔티티수를 뽑아 우리 calc_core 독립
재계산과 대조. 라벨 손실로 정밀도 한계 → confidence 로 표기(정밀 필드는 OCR 후 보강).
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

# 앵커 패턴(고정양식, 한글 무관)
_WACC_FORMULA = re.compile(r"WACC\s*=\s*Ke", re.I)
_WACC_ANY = re.compile(r"\bWACC\b", re.I)
_PCT = re.compile(r"(\d{1,2}\.\d{2})\s*%")
# 영구성장률 수식: (1 + B), (C = A x (1+B)), (C=A+B), Terminal 근처
_GROWTH_CTX = re.compile(r"\(\s*1\s*\+|1\s*\+\s*B|\(C\s*=\s*A|Terminal", re.I)
# 한글 라벨이 살아있는 경우(정상 추출) — 위치·빈도 앵커보다 **압도적으로 강한 신호**.
# 이 모듈은 원래 CID 손실 전제로 설계돼 라벨을 아예 보지 않았는데, 추출기가 정상일 때
# 오히려 무관한 비율을 줍는 역전이 실측됐다(다산 의견서: 원문에 "영구성장률: 0.00%/2.00%"가
# 명시돼 있는데 결과는 0.08%·0.46%). 라벨이 있으면 라벨을 정본으로 쓴다.
_GROWTH_LABEL = re.compile(r"영구\s*성장\s*률\s*[:：]?\s*(\d+(?:\.\d+)?)\s*%")
_SIZE_PREM = re.compile(r"Size\s*Risk\s*Premium", re.I)
# 영구성장률 상한(한국 관행 0~1%, 여유 2.5%)
_TERMINAL_MAX = 0.025
# 통화: (: JPY) / (단위: USD) / iso4217:VND 등
_CURRENCY = re.compile(r"(?:iso4217:)?\b(KRW|USD|JPY|EUR|CNY|VND|HKD|GBP|INR)\b")


@dataclass
class OpinionExtract:
    """의견서에서 앵커로 뽑은 유의적 가정(후보). 라벨손실로 값은 후보 성격."""
    entity_count: int = 0                       # WACC 공식 수 = 평가대상 개수(SOTP)
    terminal_growths: list[float] = field(default_factory=list)  # 영구성장률 후보(비율)
    size_premiums: list[float] = field(default_factory=list)
    currencies: list[str] = field(default_factory=list)
    is_sotp: bool = False
    confidence: float = 1.0
    note: str = ""


def _pcts_near(text: str, anchor: re.Pattern, window: int = 80) -> list[float]:
    """anchor 매치 주변 window 문자 내의 퍼센트값(비율로) 수집."""
    out: list[float] = []
    for m in anchor.finditer(text):
        seg = text[m.start(): m.end() + window]
        for pm in _PCT.finditer(seg):
            out.append(round(float(pm.group(1)) / 100, 6))
    return out


def extract_opinion(text: str, *, garble_confidence: float = 1.0) -> OpinionExtract:
    """의견서 텍스트(PDF 추출) → OpinionExtract. garble_confidence 는 pdf 신뢰도 전달."""
    entity_count = len(_WACC_FORMULA.findall(text)) or len(_WACC_ANY.findall(text))

    # 영구성장률 — ⓪한글 라벨(있으면 정본) > ①위치 앵커 > ②빈도 앵커.
    # ⚠️ 0.00% 를 배제하지 않는다(`0 <= g`) — 영구성장률 0% 는 보수적 평가에서 흔한 실제
    # 선택이고, 이 의견서에도 하한 케이스로 실재한다. `0 <` 로 거르면 "값이 없다"가 아니라
    # **틀린 값만 남는다**.
    labeled = sorted({
        g for g in (round(float(m.group(1)) / 100, 6) for m in _GROWTH_LABEL.finditer(text))
        if 0 <= g <= _TERMINAL_MAX
    })
    growth_source = "label"
    if labeled:
        terminal = labeled
    else:
        growth_source = "anchor"
        near = {g for g in _pcts_near(text, _GROWTH_CTX, window=120) if 0 < g <= _TERMINAL_MAX}
        all_small = Counter(
            round(float(m.group(1)) / 100, 6) for m in _PCT.finditer(text)
            if 0 < float(m.group(1)) / 100 <= _TERMINAL_MAX
        )
        # 빈도 앵커: 최빈 소수%(엔티티당 반복). 압도적 1위(최대의 80%↑)만 채택해 노이즈 억제.
        freq: set[float] = set()
        if all_small:
            mx = max(all_small.values())
            if mx >= max(2, entity_count):
                freq = {g for g, c in all_small.items() if c >= mx * 0.8}
        terminal = sorted(near | freq)

    size = sorted({p for p in _pcts_near(text, _SIZE_PREM, window=60) if 0 < p < 0.10})
    currencies = sorted(set(_CURRENCY.findall(text)))

    is_sotp = entity_count > 1 or len(currencies) > 1

    note_bits = []
    if not terminal:
        note_bits.append("영구성장률 앵커 실패(OCR 보강 필요)")
    elif growth_source == "anchor":
        # 출처를 명시해야 감사인이 "라벨을 읽은 값"과 "패턴으로 추정한 값"을 구분한다.
        note_bits.append("영구성장률=앵커 추정(라벨 미검출 — 값 확인 필요)")
    if garble_confidence < 0.6:
        note_bits.append("한글 CID 손실 — 라벨 필드 저신뢰")

    return OpinionExtract(
        entity_count=entity_count,
        terminal_growths=terminal,
        size_premiums=size,
        currencies=currencies,
        is_sotp=is_sotp,
        confidence=round(garble_confidence, 2),
        note="; ".join(note_bits),
    )
