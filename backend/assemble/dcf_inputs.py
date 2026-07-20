"""DCF 전체 어셈블리 — WACC 서브어셈블리 + 운영가정 → 검증된 ModelConfig → DcfResult.

wacc_inputs.py(WACC 조립)를 **합성**하고 운영 드라이버(매출·원가·판관비·FA·WC·브리지)를
얹어 엔드투엔드 밸류에이션을 조립한다. 게이트 fold 는 동일 원칙 + **실행 순서 게이트**:

  1) WACC 서브어셈블리 fold (β provenance·복붙 range·look-ahead 전부 포함)
  2) 실행 전 게이트: 터미널성장(PGR≥WACC=FAIL, Gordon 발산 방지)·매출 YoY 급변
     → FAIL 이면 dcf_run 호출 안 함(무의미한 결과 생성 차단)
  3) build_spine → dcf_run → DcfResult
  4) 실행 후 게이트: TV 비중 과다·운전자본 흑자도산(spine·result 필요)
  5) result 는 report.ok 일 때만 채택(FAIL 있으면 blocked, result=None)

원칙: calc_core(순수)는 계산만, 타당성/데이터 게이트는 이 계층이 책임(관심사 분리).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from calc_core.checks import (
    check_projection_smoothness, check_terminal_growth,
    check_terminal_value_weight, check_working_capital_burn,
)
from calc_core.model import ModelConfig, build_spine
from calc_core.models import DcfResult, DcfSpineInput
from calc_core.dcf import run as dcf_run
from ingest.validators import ValidationReport

from .wacc_inputs import WaccAssembly


@dataclass
class DcfAssembly:
    """조립 결과: ModelConfig + 통합 리포트 + spine/result(게이트 통과 시).

    blocked=True 면 커넥터/데이터/타당성 게이트 중 하나가 FAIL. spine 은 실행 전 게이트를
    통과했을 때만, result 는 실행 후까지 전부 통과했을 때만 채워진다.
    """
    config: ModelConfig | None
    report: ValidationReport
    spine: DcfSpineInput | None = None
    result: DcfResult | None = None
    provenance: dict[str, str] = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return not self.report.ok


def assemble_dcf_inputs(
    *,
    wacc: WaccAssembly,
    revenue: list[float],
    cogs_pct: list[float],
    sga_pct: list[float],
    asset_classes: list,
    new_capex_by_class: dict,
    wc_items: list,
    wc_driver_by_item: dict,
    base_net_working_capital: float,
    terminal_growth: float,
    non_operating_assets: float,
    net_debt: float,
    shares_outstanding: int,
    mid_year_periods: list[float] | None = None,
    terminal_discount_period: float | None = None,
    maintenance_capex_by_class: dict | None = None,
    maintenance_depreciates: bool = True,
    terminal_wc_ratio: float | None = None,
    fade_years: int | None = None,
    fade_growth: float | None = None,
    terminal_from_last_fcff: bool = False,
    long_term_gdp: float = 0.02,
) -> DcfAssembly:
    """WACC 어셈블리 + 운영가정 → 검증된 ModelConfig → (게이트 통과 시) DcfResult.

    wacc.blocked 면 즉시 차단(하류 무의미). 실행 전/후 타당성 게이트를 순서대로 걸고,
    모든 리포트를 하나로 fold 한다. long_term_gdp 는 터미널성장 상한 경고 기준.
    """
    report = ValidationReport()
    prov: dict[str, str] = dict(wacc.provenance)

    # (1) WACC 서브어셈블리 fold — β provenance·복붙 range·look-ahead 전부 여기 포함
    for f in wacc.report.findings:
        report.add(f)
    if wacc.blocked or wacc.inputs is None:
        return DcfAssembly(config=None, report=report, provenance=prov)

    cfg = ModelConfig(
        revenue=revenue, cogs_pct=cogs_pct, sga_pct=sga_pct,
        asset_classes=asset_classes, new_capex_by_class=new_capex_by_class,
        wc_items=wc_items, wc_driver_by_item=wc_driver_by_item,
        base_net_working_capital=base_net_working_capital,
        wacc_inputs=wacc.inputs, terminal_growth=terminal_growth,
        non_operating_assets=non_operating_assets, net_debt=net_debt,
        shares_outstanding=shares_outstanding,
        mid_year_periods=mid_year_periods,
        terminal_discount_period=terminal_discount_period,
        maintenance_capex_by_class=maintenance_capex_by_class,
        maintenance_depreciates=maintenance_depreciates,
        terminal_wc_ratio=terminal_wc_ratio,
        fade_years=fade_years,
        fade_growth=fade_growth,
        terminal_from_last_fcff=terminal_from_last_fcff,
    )
    wacc_val = wacc.result.wacc if wacc.result is not None else wacc.inputs.risk_free

    # (2) 실행 전 게이트 — PGR≥WACC(Gordon 발산)면 dcf_run 무의미 → 차단
    check_terminal_growth(terminal_growth, wacc_val,
                          long_term_gdp=long_term_gdp,
                          reinvestment_modeled=terminal_wc_ratio is not None,
                          report=report)
    check_projection_smoothness(list(revenue), name="revenue", report=report)
    if not report.ok:
        return DcfAssembly(config=cfg, report=report, provenance=prov)

    # (3) 조립 실행
    spine = build_spine(cfg)
    result = dcf_run(spine)

    # (4) 실행 후 게이트 — spine·result 필요(TV 비중·운전자본 흑자도산)
    check_terminal_value_weight(result, report=report)
    check_working_capital_burn(list(spine.revenue), list(spine.delta_nwc_cash_adj),
                               report=report)

    # (5) 전부 통과해야 result 채택
    return DcfAssembly(
        config=cfg, report=report, spine=spine,
        result=result if report.ok else None, provenance=prov,
    )
