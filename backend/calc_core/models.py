"""calc_core 도메인 모델 (Layer A: DCF 스파인).

순수 계산 코어라 외부 의존 없이 표준 dataclass 사용(pip 불필요). API 레이어에서
Pydantic 로 감싸 검증한다. 단위는 전부 백만원(KRW mn), 주식수만 주(shares).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DcfSpineInput:
    """DCF 스파인 입력 — 투영된 라인아이템 + 자본비용 + 브리지 항목.

    revenue/cogs/sga/dep_amort/capex/delta_nwc_cash_adj 는 명시적 추정기간(N년)
    길이의 동일 리스트. capex 는 양수 크기, delta_nwc_cash_adj 는 DCF 시트 현금조정
    부호(원본 row24 = -ΔWC) 그대로.
    """

    wacc: float
    terminal_growth: float
    revenue: list[float]
    cogs: list[float]
    sga: list[float]
    dep_amort: list[float]
    capex: list[float]
    delta_nwc_cash_adj: list[float]
    non_operating_assets: float
    net_debt: float
    shares_outstanding: int
    # 비지배지분(NCI, 연결) — EV→지분 브리지에서 차감(지배주주 귀속 지분가치). K-IFRS
    # 정식 용어=비지배지분(구 소수주주지분). 비올·클래시스 실측 브리지: EV +비영업자산
    # −순차입부채 −비지배지분 = 지분가치. 기본 0.
    non_controlling_interest: float = 0.0
    # 중간연도 할인 컨벤션. 기본 0.5,1.5,... ; terminal 은 마지막 명시연도 factor 로 할인.
    mid_year_periods: list[float] | None = None
    terminal_discount_period: float | None = None
    # ── 세금 주입(개선 A) — 우선순위: tax_override > effective_tax_rate > 구간세율(EBIT).
    # 실무 모델은 분석가 예측세금(세전이익 기반, 종종 절대액 고정)을 쓰므로 재계산 대신 주입.
    tax_override: list[float] | None = None      # 연도별 세금(백만원, 양수 크기)
    effective_tax_rate: float | None = None      # EBIT 대비 유효세율
    # ── 터미널 정규화(개선 B) — 우선순위: fcff_override > reinvestment_rate >
    #    (D&A=CAPEX 기본 − terminal_wc_ratio 정규화 WC).
    # WACC≈g 에서 순진한 Gordon 이 폭발 → 정규화 FCF 주입 또는 재투자율(g/ROIC) 반영.
    terminal_fcff_override: float | None = None  # 영구구간 FCF_{n+1} 직접 주입
    terminal_reinvestment_rate: float | None = None  # NOPLAT_T×(1−rate), rate=g/ROIC
    # 터미널 컨벤션 분기: True → FCFF_T = **마지막 연도 FCFF × (1+g)**.
    # 기본(False)은 EBIT_T 에서 재구축(D&A=CAPEX, ΔWC=0) → 재투자 0 가정이라 g>0 에서
    # FCFF 과대(F1 경고 대상). True 는 마지막 연도의 **실제 재투자 강도(CAPEX·ΔWC 포함)를
    # 영구히 승계**한다 — 모델러스 정본 `TV = X26×(1+g)/(WACC−g)`.
    # 페이드와 함께 쓸 때 특히 정합적이다: 페이드 최종연도는 이미 비율이 동결된
    # 정상상태(steady state)이므로 그 FCFF 를 성장시키는 것이 자연스럽다.
    # 우선순위: fcff_override > terminal_from_last_fcff > reinvestment_rate > (D&A=CAPEX−WC).
    terminal_from_last_fcff: bool = False
    # 정규화 운전자본 재조정(참고 모델 정본 §Normalized CF). 터미널 ΔWC = 추정말매출 × g ×
    # WC비율(운전자본/매출). 기본 None → ΔWC=0(D&A=CAPEX 만) = g>0 시 과대계상 위험.
    # reinvestment_rate 미사용 시에만 적용(둘 다 주면 reinvestment_rate 가 WC 를 이미 번들).
    # 옳은 방식(정본): 추정말매출 × g × ratio (틀린 방식=말WC투자×(1+g), TV 21% 왜곡).
    terminal_wc_ratio: float | None = None
    # ── 페이드(수렴) 구간(R1) — 명시추정 → [페이드] → Gordon 의 3단 구조.
    # 근거: 모델러스_통합모델_5.4(The Modellers, Hugel) — 명시 5년 + 페이드 5년 + Gordon.
    # 명시말기 고성장에서 영구성장률로 **급단절**하면 TV 가 왜곡되고 TV 비중이 치솟는다.
    # 페이드 구간은 마지막 명시연도의 **비율(마진·CAPEX/매출·D&A/매출·ΔWC/매출)을 동결**하고
    # 성장률만 낮춰 자기정합적 정상상태로 수렴시킨다. 실측: 페이드 적용 시
    # TV 비중 57.8%(75% 게이트 통과).
    # ⚠️ 세율 동결은 세금 경로에 따라 다르다: `tax_override`(EBIT 과 같은 속도로 성장)와
    # `effective_tax_rate`(정률)는 동결되지만, **기본 구간세율(tax.corporate_tax)은
    # 누진이라 페이드 구간에서 유효세율이 계속 오른다**(경제적으로는 타당하나 모델러스
    # T19=$F$32 의 고정 세율과는 다르다). 세율 동결이 필요하면 두 필드 중 하나를 쓸 것.
    # 구현은 "전 라인아이템을 fade_growth 로 성장"(⇔ 전 비율 동결과 수학적 동치).
    fade_years: int | None = None
    # None → AVERAGE(마지막 명시연도 매출성장률, terminal_growth). 모델러스 정본:
    # F30 = AVERAGE(S15, F33) = AVERAGE(13.101%, 1.62%) = 7.361%.
    # g 에 의존하므로 민감도에서 g 가 변하면 페이드 성장률도 함께 변한다(_compute 내부 확장).
    fade_growth: float | None = None

    def n_years(self) -> int:
        """명시추정 연수(페이드 제외 — 사용자가 입력한 원 시계열 길이)."""
        return len(self.revenue)


@dataclass(frozen=True)
class DcfResult:
    """DCF 스파인 산출."""

    ebit: list[float]
    tax: list[float]
    noplat: list[float]
    fcff: list[float]
    pv_factor: list[float]
    pv_fcff: list[float]
    terminal_fcff: float
    terminal_value: float          # 할인 전 TV = FCFF_T/(WACC-g)
    terminal_value_pv: float       # 할인 후 TV
    pv_explicit_sum: float
    enterprise_value: float
    non_operating_assets: float
    net_debt: float
    non_controlling_interest: float = 0.0    # 비지배지분(NCI) 차감액
    equity_value: float = 0.0
    shares_outstanding: int = 0
    per_share: float = 0.0
    sensitivity: dict = field(default_factory=dict)
