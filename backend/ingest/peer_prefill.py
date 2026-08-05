"""사업 설명 프리필 — Step2(사업 유사성) 판정의 **근거**를 원천에서 채운다.

`peer_judge` 는 후보의 사업 설명이 있어야 판정할 수 있고(없으면 uncertain 으로 떨어진다),
지금까지 그 설명은 사람이 손으로 쳤다. 원천은 **상장사 인덱스의 주요 제품**이다 —
FinanceDataReader 2콜로 만든 로컬 인덱스라 **DART 키·쿼터가 필요 없다**(screener 모듈
도입부 참조). 사업보고서를 파싱해 뽑을 생각만 하면 5,000+ 콜이 되는데, 같은 정보가
상장 목록에 이미 있다.

산출물은 문자열이 아니라 **출처를 진 레코드(PrefillFact)** 다. 이유가 둘이다:
  ① 이 값은 확정 사실이 아니라 초안이므로 `approval="suggested"` 로 격리돼야 한다
     (승인 게이트가 그대로 적용된다 — `excel/vs_state.py` 미승인 규약과 같은 어휘).
  ② 이 레코드가 그대로 워크북 공유 원장(`_VS_FACTS`)의 행이 된다
     (docs/plan/workbook_shared_memory.md §2-3 — 행 스키마 = provenance.as_dict 모양).

⚠️ **티커는 호출자가 준 원본 문자열을 그대로 돌려준다.** 조회는 정규화해서 하지만
(`A145020` ↔ `145020`), 되돌려줄 때 정규화된 값을 쓰면 화면·퍼널의 행과 안 맞는다
(`select_peers` 의 판정 매칭이 정규화 없는 정확일치다 — `peer_judge` 와 같은 함정).

⚠️ **신선도 게이트를 걸지 않는다.** 인덱스 `as_of` 는 기록하되 staleness 로 차단하지
않는다 — 시가총액과 달리 **주요 제품 서술은 주 단위로 변하지 않는다**. 시총 비교에
쓰는 `STALE_DAYS` 규율을 그대로 가져오면 멀쩡한 프리필이 막힌다.
"""
from __future__ import annotations

from dataclasses import dataclass

from .peer_selection import normalize_ticker
from .screener import ScreenerIndex, rows_by_code

#: 상장 목록의 제품 서술은 구조화 원천이지만 평가용 사업 설명으로는 거친 요약이다.
BUSINESS_CONFIDENCE = 0.8


@dataclass(frozen=True)
class PrefillFact:
    """원천에서 채운 사실 1건 + 출처. `_VS_FACTS` 한 행과 같은 모양."""

    ticker: str                       # 호출자가 준 **원본** 티커
    name: str                         # 인덱스가 아는 회사명(대조용)
    business: str
    as_of: str = ""                   # 인덱스 vintage
    method: str = "structured"
    source_id: str = "screener"
    locator: str = "FDR/KRX-DESC:Products"
    confidence: float = BUSINESS_CONFIDENCE
    approval: str = "suggested"       # 승인 전 초안 — 게이트가 하류 유출을 막는다

    def key(self) -> str:
        """`_VS_FACTS` 네임스페이스 경로."""
        return f"peer.{normalize_ticker(self.ticker)}.business"

    def to_dict(self) -> dict:
        return {"ticker": self.ticker, "name": self.name, "business": self.business,
                "key": self.key(), "as_of": self.as_of, "method": self.method,
                "source_id": self.source_id, "locator": self.locator,
                "confidence": self.confidence, "approval": self.approval}


def compose_business(products: str, industry: str) -> str:
    """주요제품 + 업종 → 사업 설명 한 줄.

    둘 다 없으면 **빈 문자열**을 돌려준다 — 없는 것을 있는 것처럼 만들지 않는다
    (호출부가 경고로 표면화하고, 판정은 uncertain 으로 간다).
    업종만 있는 경우도 그 사실을 문장에 드러낸다 — '무엇을 파는지 모른다'가 판정에
    영향을 주는 정보이기 때문이다.
    """
    p, i = (products or "").strip(), (industry or "").strip()
    if p and i:
        return f"{p} (업종: {i})"
    if p:
        return p
    if i:
        return f"(주요제품 미상) 업종: {i}"
    return ""


def prefill_business(
    index: ScreenerIndex, items: list[dict],
) -> tuple[dict[str, PrefillFact], list[str]]:
    """[{ticker, name?}] → ({원본티커: PrefillFact}, 경고).

    조회 실패·내용 부재는 **채우지 않고 경고한다** — 빈 값을 사실로 기록하면 원장이
    "조회했는데 없었다"와 "조회하지 않았다"를 구분하지 못하게 된다.
    입력한 회사명이 인덱스와 다르면 티커 오기일 수 있으므로 대조 경고를 낸다.
    """
    by_code = rows_by_code(index)
    facts: dict[str, PrefillFact] = {}
    warnings: list[str] = []

    for it in items:
        raw = str(it.get("ticker") or "").strip()
        if not raw or raw in facts:
            continue
        row = by_code.get(normalize_ticker(raw))
        if row is None:
            warnings.append(
                f"{raw}: 상장사 인덱스에 없음 — 비상장이거나 종목코드 오기(직접 입력 필요)")
            continue
        given = str(it.get("name") or "").strip()
        if given and row.name and given != row.name:
            warnings.append(
                f"{raw}: 입력한 이름 '{given}' ≠ 인덱스 '{row.name}' — 종목코드를 확인하세요")
        business = compose_business(row.products, row.industry)
        if not business:
            warnings.append(f"{raw}({row.name}): 주요제품·업종 모두 미상 — 직접 입력 필요")
            continue
        facts[raw] = PrefillFact(ticker=raw, name=row.name, business=business,
                                 as_of=index.as_of)
    return facts, warnings
