"""WACC 입력 어셈블리 — 커넥터 3종(price/macro/manual_paste) → 검증된 WaccInputs.

data 계층과 순수 엔진(calc_core.wacc.build_wacc) 사이의 다리. 원천값을 모아 CAPM
빌드업 입력을 조립하고, **모든 커넥터 게이트 리포트를 하나로 접어(fold)** FAIL 시
조립을 차단한다("데이터 맞고 + 가정 맞아야 WACC 나온다"의 결정론 강제).

원천 → WaccInputs 매핑:
  Rf     ← paste_risk_free / EcosProvider(RISK_FREE_10Y)      → risk_free
  MRP    ← paste_mrp(한공회)                                   → market_risk_premium
  βu     ← peers 무부채화(price_client β 또는 Bloomberg 복붙)  → unlevered_beta
  Kd     ← BondYieldMatrix.yield_of(등급,만기)(manual_paste)   → pre_tax_cost_of_debt
  Size   ← kroll_size_premium(market_cap $M)(price_client)     → size_premium
  D/E·t  ← 대상회사 목표 자본구조(유저/peer)                    → target_debt_to_equity, tax_rate

원칙(유저 판단 보조): 애매한 값은 임의 추천하지 않고 report 에 WARN/uncertain 으로 남긴다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from calc_core.checks import check_beta_mrp_consistency, check_beta_provenance
from calc_core.wacc import (
    WaccInputs, build_wacc, kroll_size_premium, peer_unlevered_beta,
)
from ingest.manual_paste import BondYieldMatrix
from ingest.parsers.base import ParseResult
from ingest.provenance import ProvenancedValue
from ingest.validators import Finding, Severity, ValidationReport


@dataclass(frozen=True)
class PeerBeta:
    """유사기업 하나의 관측 레버드 베타 + 자본구조(무부채화 입력).

    levered_beta: price_client.compute_beta 회귀값 또는 Bloomberg 복붙(paste_beta).
    debt_to_equity·tax_rate: 그 peer 의 자본구조(peer_fs / DART).
    """
    ticker: str
    levered_beta: float
    debt_to_equity: float
    tax_rate: float


@dataclass
class WaccAssembly:
    """조립 결과: WaccInputs + 통합 리포트 + WaccResult(게이트 통과 시).

    blocked=True 면 어떤 커넥터/가정 게이트가 FAIL — WaccInputs 는 참고용이고 result=None.
    provenance: 필드명 → 사람이 읽는 출처 라벨(감사 추적).
    """
    inputs: WaccInputs | None
    report: ValidationReport
    result: object | None = None            # WaccResult | None
    provenance: dict[str, str] = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return not self.report.ok


def _pull(src: object, field_name: str, report: ValidationReport,
          prov: dict[str, str]) -> float | None:
    """원천값을 float 로 정규화하고 부속 리포트/출처를 통합.

    - ParseResult(복붙 커넥터): 그 report 를 통째로 fold(range/numeric FAIL 전파) +
      value_of(field_name) 추출 + provenance 라벨 수집.
    - ProvenancedValue: 값 + 라벨(리포트 없음).
    - Decimal/float/int: 그대로(출처 미상 → WARN 로 남길지는 호출측 판단).
    - None: None 반환(호출측이 필수여부 판정).
    """
    if src is None:
        return None
    if isinstance(src, ParseResult):
        for f in src.report.findings:
            report.add(f)
        pv = src.by_name(field_name)
        if pv is None:
            report.add(Finding("assemble", Severity.FAIL,
                               f"{field_name}: 복붙 결과에 필드 없음", {"field": field_name}))
            return None
        if pv.value is not None:
            prov[field_name] = pv.provenance.label()
        return None if pv.value is None else float(pv.value)
    if isinstance(src, ProvenancedValue):
        if src.value is not None:
            prov[field_name] = src.provenance.label()
        return None if src.value is None else float(src.value)
    if isinstance(src, (Decimal, int, float)):
        return float(src)
    raise TypeError(f"{field_name}: 지원 안 되는 원천 타입 {type(src)}")


def assemble_wacc_inputs(
    *,
    risk_free: object,
    mrp: object,
    peers: list[PeerBeta],
    target_debt_to_equity: float,
    tax_rate: float,
    kd_matrix: BondYieldMatrix | None = None,
    kd_grade: str | None = None,
    kd_tenor: str | None = None,
    pre_tax_cost_of_debt: object = None,
    market_cap_musd: float | None = None,
    size_premium: object = None,
    country_risk_premium: float = 0.0,
    company_specific_risk: float = 0.0,
    beta_source: str | None = None,
    beta_market: str | None = None,
    beta_adjusted: bool | None = None,
    mrp_source: str | None = None,
    mrp_market: str | None = None,
) -> WaccAssembly:
    """커넥터 원천값 → 검증된 WaccInputs → (게이트 통과 시) build_wacc.

    Kd 는 kd_matrix+등급+만기(룩업) 또는 pre_tax_cost_of_debt(직접) 중 하나.
    Size premium 은 market_cap_musd(Kroll decile 룩업) 또는 size_premium(직접) 중 하나.
    β/MRP provenance(source·market)를 넘기면 checks 로 정합(같은 시장?)까지 검사한다.
    """
    report = ValidationReport()
    prov: dict[str, str] = {}

    rf = _pull(risk_free, "risk_free", report, prov)
    mrp_val = _pull(mrp, "mrp", report, prov)

    # ── βu: peers 무부채화 ──────────────────────────────────────────────────
    unlevered = None
    if peers:
        unlevered = peer_unlevered_beta(
            [(p.levered_beta, p.debt_to_equity, p.tax_rate) for p in peers])
        prov["unlevered_beta"] = f"peers={','.join(p.ticker for p in peers)} 무부채화 평균"
    else:
        report.add(Finding("assemble", Severity.FAIL,
                           "peers 비어 있음 — 무부채 베타 산출 불가", {}))

    # ── Kd: 매트릭스 룩업 또는 직접 ─────────────────────────────────────────
    kd = _pull(pre_tax_cost_of_debt, "pre_tax_cost_of_debt", report, prov)
    if kd is None and kd_matrix is not None:
        if not (kd_grade and kd_tenor):
            report.add(Finding("assemble", Severity.FAIL,
                               "Kd 매트릭스에 등급/만기 미지정", {}))
        else:
            y = kd_matrix.yield_of(kd_grade, kd_tenor)
            if y is None:
                report.add(Finding("assemble", Severity.FAIL,
                                   f"Kd 매트릭스에 {kd_grade}×{kd_tenor} 없음",
                                   {"grades": kd_matrix.grades(), "tenors": kd_matrix.tenors}))
            else:
                kd = float(y)
                prov["pre_tax_cost_of_debt"] = (
                    f"[manual@{kd_matrix.source_id} {kd_grade}×{kd_tenor} @{kd_matrix.pasted_at}]")
    if kd is None:
        report.add(Finding("assemble", Severity.FAIL, "Kd(pre-tax) 미확보", {}))

    # ── Size premium: Kroll decile 또는 직접 ────────────────────────────────
    size = _pull(size_premium, "size_premium", report, prov)
    if size is None and market_cap_musd is not None:
        size = kroll_size_premium(market_cap_musd)
        prov["size_premium"] = f"Kroll decile(시총 ${market_cap_musd:,.0f}M)"
    if size is None:
        size = 0.0                          # 규모프리미엄 미적용은 정상(대형주) — WARN 없음

    # 필수값 결측 시 조립 차단(엔진 호출 전)
    if None in (rf, mrp_val, unlevered, kd):
        return WaccAssembly(inputs=None, report=report, provenance=prov)

    inputs = WaccInputs(
        risk_free=rf, market_risk_premium=mrp_val, unlevered_beta=unlevered,
        target_debt_to_equity=target_debt_to_equity, tax_rate=tax_rate,
        pre_tax_cost_of_debt=kd, size_premium=size,
        country_risk_premium=country_risk_premium,
        company_specific_risk=company_specific_risk,
        beta_source=beta_source, beta_market=beta_market, beta_adjusted=beta_adjusted,
        mrp_source=mrp_source, mrp_market=mrp_market,
    )
    # 가정 게이트(β provenance·β/MRP 시장 정합) 통합
    check_beta_provenance(inputs, report=report)
    check_beta_mrp_consistency(inputs, report=report)

    result = build_wacc(inputs) if report.ok else None
    return WaccAssembly(inputs=inputs, report=report, result=result, provenance=prov)
