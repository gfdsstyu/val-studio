"""평가방법론 셀렉터 — 목적·거래유형·상장여부 → 방법론 결정론 추천.

근거(북): [[합병_주식교환_방법론]] §3 방법론 트랙 표 + [[MnA_구조화_합병규제_세무]]
§3 합병가액 법제 + [[MnA_실사_가격구조_SPA]] §8 활용목적 3분류 +
[[외부평가의견서_활용]](비상장 타법인주식양수 = DCF 기본, 실측 11/13).

원칙: 이 매핑은 법제·실무 관행의 **결정론 규칙**이라 LLM 없이 코드가 담당한다.
단 추천이지 강제가 아니다 — 유저가 다른 방법을 확정할 수 있고(판단보조), 규칙이
없는 조합은 uncertain 으로 표면화한다. 미구현 엔진은 available=False 로 정직하게.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 평가 목적 (활용목적 3분류)
PURPOSES = {
    "transaction": "거래 목적 (양수도·투자·내부 의사결정)",
    "regulatory": "법규 목적 (합병비율·양수도 외부평가의견서)",
    "financial_reporting": "재무보고 목적 (PPA·손상·공정가치)",
    "tax": "세무 목적 (상증세 주식평가)",
}

# 거래 유형 (regulatory/transaction 하위)
DEAL_TYPES = {
    "merger": "합병·주식교환",
    "business_transfer": "영업·자산양수도",
    "share_purchase": "타법인 주식양수도",
    "investment": "투자유치·내부검토",
    "ppa": "사업결합원가배분(PPA)",
    "impairment": "자산손상 검토",
    "inheritance_gift": "상속·증여",
}

# 방법론 카탈로그 — available: 엔진 가동 여부(정직 표기)
METHODS = {
    "dcf": {"label": "DCF(수익가치)", "available": True,
            "engine": "calc_core.dcf"},
    "base_price": {"label": "기준시가(1M·1W·최근일 산술평균)", "available": True,
                   "engine": "calc_core.merger.base_share_price"},
    "intrinsic": {"label": "본질가치(자산 0.4 : 수익 0.6)", "available": True,
                  "engine": "calc_core.merger.intrinsic_value (수익가치=DCF 투입)"},
    "comps": {"label": "상대가치(유사회사 배수)", "available": False,
              "engine": "⏳ 트랙 예정 — LTM·계절성 유틸만 가동"},
    "nav": {"label": "조정순자산", "available": False, "engine": "⏳ 미구현"},
    "viu": {"label": "사용가치(VIU)", "available": False, "engine": "⏳ 손상 트랙 예정"},
    "fv_ppa": {"label": "공정가치(MEEM·RFRM 등)", "available": False, "engine": "⏳ PPA 트랙 예정"},
    "tax_supplementary": {"label": "상증세법 보충적 평가", "available": False, "engine": "⏳ 미구현"},
}


@dataclass(frozen=True)
class MethodRecommendation:
    primary: list[str]                    # 방법 id (복수 = 병행·가중)
    secondary: list[str] = field(default_factory=list)
    legal_basis: str = ""
    notes: list[str] = field(default_factory=list)
    uncertain: bool = False               # 규칙 없음 → 유저 판단 필요

    def to_dict(self) -> dict:
        def expand(ids):
            return [{"id": m, **METHODS[m]} for m in ids]
        return {"primary": expand(self.primary), "secondary": expand(self.secondary),
                "legal_basis": self.legal_basis, "notes": self.notes,
                "uncertain": self.uncertain}


def recommend_method(
    purpose: str,
    deal_type: str | None = None,
    target_listed: bool | None = None,
    counterparty_listed: bool | None = None,
) -> MethodRecommendation:
    """목적·거래유형·상장여부 → 방법론 추천(법적 근거 병기).

    counterparty_listed 는 합병에서 상대방(존속/소멸 반대편) 상장여부.
    규칙에 없는 조합은 uncertain=True — 결론을 지어내지 않는다.
    """
    if purpose == "regulatory" and deal_type == "merger":
        if target_listed and counterparty_listed:
            return MethodRecommendation(
                ["base_price"],
                legal_basis="자본시장법 시행령 — 상장법인 간 합병가액 = 기준시가, "
                            "±30%(계열사 10%) 할인·할증 범위",
                notes=["10% 초과 할인·할증 시 외부평가 필요",
                       "주식매수청구 가격은 별도 기간 세트(2M·1M·1W)"])
        if target_listed is False:
            return MethodRecommendation(
                ["intrinsic"], secondary=["comps"],
                legal_basis="자본시장법 — 비상장측 = 본질가치(자산 0.4 : 수익 0.6), "
                            "상대가치 비교 공시",
                notes=["수익가치는 DCF·이익할인 등 공정·타당 모형 — 우리 DCF 주당가치 투입",
                       "상장 상대방 측은 기준시가 적용",
                       "특수관계자 간 비상장 합병은 상증세법 보충적 평가 관행(세무 검토 병행)"])
        return MethodRecommendation(
            ["base_price", "intrinsic"], uncertain=True,
            legal_basis="자본시장법 — 상장여부에 따라 기준시가/본질가치",
            notes=["대상·상대방 상장여부를 확정해야 방법이 갈립니다"])

    if purpose == "regulatory" and deal_type == "business_transfer":
        return MethodRecommendation(
            ["dcf"], secondary=["nav"],
            legal_basis="자본시장법(중요 영업·자산양수도 외부평가 의무) + "
                        "금감원 외부평가업무 가이드라인 — 가액 산정방법 비법제, "
                        "공정·타당 방법(DCF 지배적)",
            notes=["Carve-out 재무제표 기준 — 운전자본/순자산 정산 구조 확인"])

    if purpose in ("regulatory", "transaction") and deal_type == "share_purchase":
        if target_listed:
            return MethodRecommendation(
                ["base_price"], secondary=["dcf"],
                legal_basis="상장주식 — 시가 존재. 경영권 프리미엄 등은 별도 판단",
                notes=["대량거래·경영권 이전이면 DCF 로 내재가치 교차검증 권장"])
        return MethodRecommendation(
            ["dcf"], secondary=["comps", "nav"],
            legal_basis="외부평가업무 가이드라인 — 비상장 타법인주식 양수도는 "
                        "DCF 법이 기본(공시 의견서 실측 11/13)",
            notes=["자산 성격(부동산 등) 강하면 조정순자산, 옵션성이면 이항모형 병행"])

    if purpose == "transaction":
        return MethodRecommendation(
            ["dcf"], secondary=["comps"],
            legal_basis="내부 의사결정 — 법정 방법 없음, DCF + 상대가치 병행 관행",
            notes=[])

    if purpose == "financial_reporting":
        if deal_type == "impairment":
            return MethodRecommendation(
                ["viu"], secondary=["dcf"],
                legal_basis="K-IFRS 1036 — 회수가능액 = max(VIU, FVLCD)",
                notes=["VIU 는 entity-specific·세전·성능 CAPEX 제외 — 계속기업 DCF 와 다름",
                       "VIU 엔진은 트랙 예정 — 현재는 DCF 골격으로 근사 불가 항목 명시 필요"])
        if deal_type == "ppa":
            return MethodRecommendation(
                ["fv_ppa"], secondary=["dcf"],
                legal_basis="K-IFRS 1103 — 식별가능 무형자산 공정가치(MEEM·RFRM 등)",
                notes=["WARA↔IRR↔WACC ±1%p reconciliation 검토(checks 가동)"])
        return MethodRecommendation(
            ["dcf"], uncertain=True,
            legal_basis="재무보고 목적 — 세부 대상(손상/PPA/투자지분 등) 확정 필요",
            notes=[])

    if purpose == "tax" or deal_type == "inheritance_gift":
        return MethodRecommendation(
            ["tax_supplementary"], secondary=["dcf"],
            legal_basis="상속세 및 증여세법 — 보충적 평가방법",
            notes=["보충적 평가 엔진 미구현 — 세무 전문가 검토 필수",
                   "특수관계 거래는 부당행위계산부인(시가±5%/3억) 리스크 검토"])

    return MethodRecommendation(
        ["dcf"], uncertain=True,
        legal_basis="해당 조합의 확립된 규칙 없음",
        notes=["목적·거래유형 조합을 확인해 주세요 — 임의 추천하지 않습니다"])
