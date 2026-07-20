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
    # CAPEX 신규/유지보수 분리 — 유지보수는 현금유출 항상, 감가는 옵션(fa.project_fixed_assets).
    maintenance_capex_by_class: dict[str, list[float]] | None = None
    maintenance_depreciates: bool = True
    # 터미널 정규화 운전자본 재조정(정본 공식): 터미널 ΔWC = 추정말매출 × g × 이 비율.
    terminal_wc_ratio: float | None = None
    # 페이드(수렴) 구간(R1) — 명시 → 페이드 → Gordon 3단. 근거: 모델러스_통합모델_5.4.
    fade_years: int | None = None
    fade_growth: float | None = None
    # 터미널 컨벤션: True 면 FCFF_T = 마지막 연도 FCFF × (1+g)(재투자 강도 승계).
    terminal_from_last_fcff: bool = False


def build_spine(cfg: ModelConfig) -> DcfSpineInput:
    """가정 → 상류 모듈 조립 → DcfSpineInput(dcf_run 입력). run_model 과 검증 계층 공용.

    분리 이유: assemble 계층이 spine 을 얻어 dcf_run *전에* 검증 게이트(터미널성장·YoY
    급변)를 걸고, *후에* 사후검사(TV비중·WC burn)를 하려면 spine 이 노출돼야 한다.
    """
    n = len(cfg.revenue)
    eb = ebit_mod.build_ebit_from_ratios(cfg.revenue, cfg.cogs_pct, cfg.sga_pct)
    fa_res = fa_mod.project_fixed_assets(
        cfg.asset_classes, cfg.new_capex_by_class,
        cfg.maintenance_capex_by_class,
        maintenance_depreciates=cfg.maintenance_depreciates)
    wc_res = wc_mod.project_working_capital(
        cfg.wc_items, cfg.wc_driver_by_item, cfg.base_net_working_capital
    )
    wacc_res = build_wacc(cfg.wacc_inputs)
    assert len(fa_res.dep_amort) == n and len(wc_res.delta_nwc_cash_adj) == n
    return DcfSpineInput(
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
        terminal_wc_ratio=cfg.terminal_wc_ratio,
        fade_years=cfg.fade_years,
        fade_growth=cfg.fade_growth,
        terminal_from_last_fcff=cfg.terminal_from_last_fcff,
    )


def run_model(cfg: ModelConfig) -> DcfResult:
    """가정 → 전체 DCF. build_spine 조립 후 dcf_run."""
    return dcf_run(build_spine(cfg))
