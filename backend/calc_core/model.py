"""엔드투엔드 오케스트레이터 — 가정 → revenue → ebit → fa → wc → wacc → dcf.

상류 모듈을 조립해 DcfSpineInput 을 만들고 dcf.run 으로 밸류에이션을 완성한다.
revenue 전략(top_down|bottom_up)·원가/판관비 드라이버·FA/WC/WACC 설정을 받는다.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import ebit as ebit_mod
from . import fa as fa_mod
from . import wc as wc_mod
from .dcf import run as dcf_run
from .models import DcfResult, DcfSpineInput
from .wacc import WaccInputs, build_wacc


@dataclass
class ModelConfig:
    """전체 모델 입력 묶음."""

    revenue: list[float]                 # 확정된 매출 벡터(전략 결과)
    cogs_pct: list[float]
    sga_pct: list[float]
    asset_classes: list[fa_mod.AssetClass]
    new_capex_by_class: dict[str, list[float]]
    wc_items: list[wc_mod.WcItem]
    wc_driver_by_item: dict[str, list[float]]  # 매출/매출원가 연동
    base_net_working_capital: float
    wacc_inputs: WaccInputs
    terminal_growth: float
    non_operating_assets: float
    net_debt: float
    shares_outstanding: int
    mid_year_periods: list[float] | None = None
    terminal_discount_period: float | None = None


def run_model(cfg: ModelConfig) -> DcfResult:
    """가정 → 전체 DCF. 상류 모듈을 순서대로 조립."""
    n = len(cfg.revenue)

    eb = ebit_mod.build_ebit_from_ratios(cfg.revenue, cfg.cogs_pct, cfg.sga_pct)
    fa_res = fa_mod.project_fixed_assets(cfg.asset_classes, cfg.new_capex_by_class)
    wc_res = wc_mod.project_working_capital(
        cfg.wc_items, cfg.wc_driver_by_item, cfg.base_net_working_capital
    )
    wacc_res = build_wacc(cfg.wacc_inputs)

    spine = DcfSpineInput(
        wacc=wacc_res.wacc,
        terminal_growth=cfg.terminal_growth,
        revenue=eb.revenue,
        cogs=eb.cogs,
        sga=eb.sga,
        dep_amort=fa_res.dep_amort,
        capex=fa_res.capex,
        delta_nwc_cash_adj=wc_res.delta_nwc_cash_adj,
        non_operating_assets=cfg.non_operating_assets,
        net_debt=cfg.net_debt,
        shares_outstanding=cfg.shares_outstanding,
        mid_year_periods=cfg.mid_year_periods,
        terminal_discount_period=cfg.terminal_discount_period,
    )
    assert len(fa_res.dep_amort) == n and len(wc_res.delta_nwc_cash_adj) == n
    return dcf_run(spine)
