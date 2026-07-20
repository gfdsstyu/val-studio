"""calc_core — 결정론적 DCF 계산 엔진 (순수 함수).

비올 DCF Model 최종본을 1:1 재현하는 것이 Milestone 1. AI/외부 의존 없음.

- 스파인(Layer A): models·tax·dcf — 비올 골든 테스트로 셀단위 검증.
- 상류: revenue·ebit·fa·wc·wacc — 표준 방법론 일반 엔진, 단위테스트.
- 통합: model.run_model — 가정 → 전체 DCF.
- 검증: three_statement — IS·BS·CF 조립으로 상류 모듈 배관 정합성을 독립 검사.
"""
from . import ebit, fa, revenue, three_statement, wc
from .dcf import run
from .model import ModelConfig, run_model
from .models import DcfResult, DcfSpineInput
from .tax import corporate_tax, effective_rate
from .three_statement import (
    FinancingPlan,
    OpeningBalanceSheet,
    ThreeStatementInput,
    ThreeStatementResult,
    project_three_statements,
)
from .wacc import WaccInputs, WaccResult, build_wacc, relever_beta, unlever_beta

__all__ = [
    "run",
    "run_model",
    "ModelConfig",
    "DcfResult",
    "DcfSpineInput",
    "corporate_tax",
    "effective_rate",
    "build_wacc",
    "WaccInputs",
    "WaccResult",
    "unlever_beta",
    "relever_beta",
    "revenue",
    "ebit",
    "fa",
    "wc",
    "three_statement",
    "project_three_statements",
    "ThreeStatementInput",
    "ThreeStatementResult",
    "OpeningBalanceSheet",
    "FinancingPlan",
]
