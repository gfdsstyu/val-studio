"""SOTP (Sum-of-the-Parts) — 다개체·다통화 가치합산.

실제 외부평가의견서(예: 다산네트웍스 자산양수도)는 여러 종속회사를 각자의 통화로 개별
DCF 평가한 뒤 기준통화로 환산·지분율 반영해 합산한다. 단일회사 `dcf.run` 을 여러 번
돌려 이 구조를 조립한다.

각 파트: DcfSpineInput(로컬 통화 백만원 단위) → dcf.run → 지분가치(로컬)
       → × fx_to_base(로컬→기준통화) → × ownership(지분율) → 귀속가치(기준통화).
전체 = Σ 귀속가치.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import dcf
from .models import DcfResult, DcfSpineInput


@dataclass(frozen=True)
class SotpPart:
    """SOTP 구성단위. fx_to_base = 로컬통화 1단위 → 기준통화 환율."""
    name: str
    dcf_input: DcfSpineInput
    currency: str = "KRW"
    fx_to_base: float = 1.0
    ownership: float = 1.0  # 지분율 0~1

    def __post_init__(self) -> None:
        if not (0.0 <= self.ownership <= 1.0):
            raise ValueError(f"{self.name}: ownership 은 0~1 ({self.ownership})")
        if self.fx_to_base <= 0:
            raise ValueError(f"{self.name}: fx_to_base 는 양수 ({self.fx_to_base})")


@dataclass(frozen=True)
class SotpPartResult:
    name: str
    currency: str
    result: DcfResult                 # 로컬 통화 DCF 산출
    equity_value_local: float         # 지분가치(로컬, 백만)
    fx_to_base: float
    ownership: float
    attributable_base: float          # 귀속가치(기준통화, 백만)


@dataclass(frozen=True)
class SotpResult:
    base_currency: str
    parts: list[SotpPartResult] = field(default_factory=list)
    total_equity_base: float = 0.0

    def weight_of(self, name: str) -> float:
        """전체 대비 해당 파트 기여 비중."""
        if self.total_equity_base == 0:
            return float("nan")
        for p in self.parts:
            if p.name == name:
                return p.attributable_base / self.total_equity_base
        raise KeyError(name)


def run_sotp(parts: list[SotpPart], *, base_currency: str = "KRW") -> SotpResult:
    """각 파트를 개별 DCF 평가 후 기준통화·지분율로 귀속가치 합산.

    다통화(JPY/VND/USD…) 파트를 fx_to_base 로 환산해 합산한다. 각 파트의 로컬 산출은
    보존되어 파트별 기여·감사추적이 가능하다.
    """
    if not parts:
        raise ValueError("parts 가 비어 있음")
    out: list[SotpPartResult] = []
    total = 0.0
    for part in parts:
        res = dcf.run(part.dcf_input)
        attributable = res.equity_value * part.fx_to_base * part.ownership
        out.append(SotpPartResult(
            name=part.name,
            currency=part.currency,
            result=res,
            equity_value_local=res.equity_value,
            fx_to_base=part.fx_to_base,
            ownership=part.ownership,
            attributable_base=attributable,
        ))
        total += attributable
    return SotpResult(base_currency=base_currency, parts=out, total_equity_base=total)
