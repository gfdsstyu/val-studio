"""DART XBRL 택사노미 로컬 조회 — `account_id` 를 라벨·부호·계층으로 해석한다.

데이터: backend/data/dart_taxonomy.json (빌드: scripts/build_taxonomy_store.py,
원천은 금감원 배포 xlsx — `_meta` 에 provenance).

**왜 필요한가.** OpenDART `fnlttSinglAcntAll` 는 계정마다 `account_nm`(회사가 지어낸
한글명)과 `account_id`(표준 요소명, 예 `ifrs-full_Revenue`)를 함께 준다. 이름은
"매출액 / 영업수익 / 수익(매출액)" 처럼 회사마다 흔들리지만 요소명은 흔들리지 않는다.
[[fs_mapper]] 의 키워드 규칙은 이름에 의존하므로, 요소명이 있는 행은 이 사전으로
**결정론적으로** 분류하고 키워드는 폴백으로 내린다.

**수록 범위의 비대칭**(빌드 스크립트 참조):
  · elements/roles — 전량(주석 role 포함)
  · presentation/calculation — 주요재무제표 26 role 만
따라서 `ancestors()`/`bucket_hint()` 는 주요재무제표 계정에만 답한다. 주석 전용
요소는 `entry()` 로 라벨만 얻을 수 있고 계층은 비어 있다 — 이는 결손이 아니라 설계다.

**구간별 신뢰도 차이(실측)**: 현금흐름표는 표준 택사노미가 완전히 계층적이라
조상 규칙이 잘 듣지만(투자활동 → 유형자산의 취득 → …), 재무상태표·손익계산서의
표준 트리는 의도적으로 얕다(실제 계층은 각 회사 제출분의 자체 linkbase 에 있다).
그래서 BS/IS 는 계층 추론이 아니라 **요소명 앵커 일치**로 간다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parents[1] / "data" / "dart_taxonomy.json"

# 현금흐름표 3구간 — 조상 규칙이 신뢰도 높게 듣는 유일한 구간.
CF_OPERATING = "ifrs-full_CashFlowsFromUsedInOperatingActivities"
CF_INVESTING = "ifrs-full_CashFlowsFromUsedInInvestingActivities"
CF_FINANCING = "ifrs-full_CashFlowsFromUsedInFinancingActivities"

# ── 버킷 앵커 ────────────────────────────────────────────────────────────
#
# ⚠️ **택사노미가 답할 수 있는 것과 없는 것.** 택사노미는 *회계분류*(이 계정이 IFRS 상
# 무엇인가)의 권위이지 *평가목적 재분류*(운전자본인가·차입금성인가·비영업인가)의
# 권위가 아니다. 둘은 다른 층이고, 후자에는 판단이 들어간다.
#
# 특히 표준 트리의 상위 노드 상당수는 밸류에이션 범주가 아니라 **표시목적 묶음**이다.
# 실례: `ifrs-full_TradeAndOtherCurrentPayables`(매입채무 및 기타 유동 채무)의 자식에는
# 단기매입채무(WC)뿐 아니라 **유동 차입금·단기 사채·유동성전환사채·유동 리스부채(IBD)**
# 와 미지급비용·예수금·선수금(판단 필요)이 함께 들어 있다. 이런 묶음을 앵커로 삼아
# 후손 전체를 한 버킷에 넣으면 순차입금이 조용히 틀어진다.
#
# 그래서 앵커는 두 종류로만 쓴다:
#   · SUBTREE — 후손까지 동질적임이 확인된 것만(유형자산·무형자산·자본 등)
#   · EXACT   — 그 요소 하나만. 묶음 노드는 앵커로 쓰지 않는다.
# 그리고 판단이 필요한 계정은 침묵시키지 않고 `judgment=True` 로 표면화해 유저 결정에
# 넘긴다(원칙: 무매칭·모호는 임의 추측 금지 — [[fs_mapper]]).
#
# 차감계정(대손충당금·감가상각누계액·정부보조금)은 본계정의 **형제**이지 자식이 아니다.
# 따라서 조상 규칙으로 상속되지 않으며, 개별 EXACT 항목이거나 무매칭으로 떨어진다.
# 부호는 calculation weight(±1)가 따로 알려준다.
SUBTREE = "subtree"   # 앵커 자신 + 후손 전부(동질성이 확인된 경우에만)
EXACT = "exact"       # 앵커 요소 하나만

# (bucket, mode, elements, confidence, judgment, note)
_Anchor = tuple[str, str, tuple[str, ...], float, bool, str | None]

_PL_ANCHORS: list[_Anchor] = [
    ("COGS", SUBTREE, ("ifrs-full_CostOfSales",), 0.95, False, None),
    ("Sales", SUBTREE, ("ifrs-full_Revenue",
                        "ifrs-full_RevenueFromContractsWithCustomers"), 0.95, False, None),
    ("SGA", SUBTREE, (
        "dart_TotalSellingGeneralAdministrativeExpenses",
        "ifrs-full_SellingGeneralAndAdministrativeExpense",
        "ifrs-full_AdministrativeExpense",
        "ifrs-full_DistributionCosts",
    ), 0.9, False, None),
    # 지분법손익은 영업/영업외 귀속이 회사·평가자마다 갈린다 → 제안하되 판단 요청.
    ("NonOp(영업외)", SUBTREE, (
        "ifrs-full_ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod",
    ), 0.6, True, "지분법손익 — 영업/영업외 귀속 판단 필요"),
    ("NonOp(영업외)", SUBTREE, (
        "ifrs-full_FinanceIncome",
        "ifrs-full_FinanceCosts",
        "ifrs-full_OtherIncome",
        "ifrs-full_OtherExpenses",
        "dart_OtherGains",
        "dart_OtherLosses",
        "ifrs-full_IncomeTaxExpenseContinuingOperations",
        "ifrs-full_ProfitLossFromDiscontinuedOperations",
    ), 0.9, False, None),
]

_BS_ANCHORS: list[_Anchor] = [
    # ── 차입성 부채. 묶음(TradeAndOtherCurrentPayables) 밑에 섞여 있으므로 EXACT 로
    #    하나씩 못박는다. 여기서 새면 순차입금이 그대로 틀어진다.
    ("IBD(이자부부채)", EXACT, (
        "ifrs-full_ShorttermBorrowings",
        "ifrs-full_CurrentPortionOfLongtermBorrowings",
        "ifrs-full_NoncurrentPortionOfOtherNoncurrentBorrowings",
        "ifrs-full_OtherCurrentBorrowingsAndCurrentPortionOfOtherNoncurrentBorrowings",
        "ifrs-full_CurrentLoansReceivedAndCurrentPortionOfNoncurrentLoansReceived",
        "ifrs-full_NoncurrentPortionOfNoncurrentLoansReceived",
        "dart_LongTermBorrowingsGross",
        "dart_BondsIssuedNominalValue",
        "dart_CurrentBondsIssued",
        "dart_ConvertibleBonds",
        "dart_BondWithWarrant",
        "dart_ExchangeableBonds",
        "dart_CurrentPortionOfConvertibleBonds",
        "dart_CurrentPortionOfBondWithWarrant",
        "dart_CurrentPortionOfExchangeableBond",
        "dart_CurrentPortionOfConvertibleRedeemablePreferredStockLiabilities",
        "dart_CurrentPortionOfLongtermOtherPayables",
    ), 0.95, False, None),
    # 리스부채는 IFRS16 이후 차입금성으로 보는 게 통설이나, 영업리스 성격을 EBITDA·
    # 순차입금 어느 쪽에 태울지는 평가자 결정 → 제안 + 판단 요청.
    ("IBD(이자부부채)", EXACT, (
        "ifrs-full_CurrentLeaseLiabilities",
        "ifrs-full_NoncurrentLeaseLiabilities",
        "dart_CurentPortionOfFinanceLeaseLiabilities",   # 원본 택사노미 철자 그대로
        "dart_NonCurrentFinanceLeaseLiabilities",
    ), 0.7, True, "리스부채 — 순차입금 포함 여부 및 사용권자산 대응 판단 필요"),

    # ── 운전자본. 영업순환에 직결되는 계정만 EXACT.
    ("WC(운전자본)", EXACT, (
        "dart_ShortTermTradeReceivable",
        "dart_AllowanceForDoubtfulAcccountShortTermTradeReceivable",
        "dart_LongTermTradeReceivablesGross",
        "dart_AllowanceForDoubtfulAcccountLongTermTradeReceivablesGross",
        "dart_ShortTermTradePayables",
        "dart_LongTermTradePayablesGross",
        "ifrs-full_CurrentContractAssets",
        "ifrs-full_NoncurrentContractAssets",
        "ifrs-full_CurrentContractLiabilities",
        "ifrs-full_NoncurrentContractLiabilities",
        "dart_ShortTermDueFromCustomersForContractWork",
        "dart_ShortTermDueToCustomersForContractWork",
        "dart_ShortTermAdvancePayments",
        "dart_ShortTermAdvancesCustomers",
        "dart_ShortTermPrepaidExpenses",
        "dart_ReceivablesOnConstructionContracts",
    ), 0.9, False, None),
    ("WC(운전자본)", SUBTREE, ("ifrs-full_Inventories",), 0.9, False, None),
    # 기타채권·기타채무 — 영업성/금융성이 회사마다 갈린다. 이 층이 바로 사용자가
    # 지적한 "결정론으로 못 푸는" 구간이다. 제안만 하고 판단을 넘긴다.
    ("WC(운전자본)", EXACT, (
        "dart_ShortTermOtherReceivables",       # 단기미수금
        "dart_ShortTermAccruedIncome",          # 단기미수수익
        "dart_ShortTermOtherPayables",          # 단기미지급금
        "dart_ShortTermAccruedExpenses",        # 단기미지급비용
        "dart_ShortTermWithholdings",           # 단기예수금
        "ifrs-full_CurrentValueAddedTaxReceivables",
        "ifrs-full_CurrentValueAddedTaxPayables",
        "dart_ShortTermIncomeReceivedInAdvance",
        "dart_DeferredIncomeClassifiedAsCurrent",
    ), 0.6, True, "기타채권·기타채무 — 영업성/금융성 판단 필요(비영업분은 브리지로)"),
    ("NOA(비영업자산)", EXACT, (
        "dart_ShortTermLoans",                  # 단기대여금 = 금융자산
        "dart_AllowanceForDoubtfulAcccountShortTermLoans",
        "dart_ShortTermDepositsProvided",       # 단기보증금
        "dart_LeaseholdDeposits",               # 임차보증금
    ), 0.6, True, "대여금·보증금 — 영업 관련성 판단 필요"),
    ("IBD(이자부부채)", EXACT, (
        "dart_ShortTermGuaranteeDepositRent",   # 임대보증금
        "dart_ShortTermOtherGuaranteeDepositReceived",
        "ifrs-full_DividendsPayable",           # 미지급배당금 = 확정 지급의무
    ), 0.6, True, "보증금·미지급배당 — 차입금성 여부 판단 필요"),

    # ── 영업고정자산. 하위가 동질적이라 SUBTREE 안전.
    ("FA(유형자산)", SUBTREE, (
        "ifrs-full_PropertyPlantAndEquipment",
        "ifrs-full_IntangibleAssetsOtherThanGoodwill",
        "ifrs-full_Goodwill",
        "dart_GoodwillGross",
    ), 0.95, False, None),
    ("FA(유형자산)", SUBTREE, ("ifrs-full_RightofuseAssets",), 0.7, True,
     "사용권자산 — 리스부채 처리와 짝을 맞출 것"),

    # ── 비영업자산. 현금은 초과현금만 NOA 이므로 항상 판단 대상.
    ("NOA(비영업자산)", EXACT, ("ifrs-full_CashAndCashEquivalents",), 0.6, True,
     "영업현금 분리 검토(초과현금만 NOA)"),
    ("NOA(비영업자산)", SUBTREE, ("ifrs-full_InvestmentProperty",), 0.9, False, None),
    ("NOA(비영업자산)", EXACT, (
        "ifrs-full_ShorttermDepositsNotClassifiedAsCashEquivalents",
        "ifrs-full_InvestmentsInAssociates",
        "ifrs-full_InvestmentsInJointVentures",
        "ifrs-full_InvestmentsInSubsidiariesJointVenturesAndAssociates",
        "ifrs-full_InvestmentAccountedForUsingEquityMethod",
        "ifrs-full_OtherCurrentFinancialAssets",
        "ifrs-full_OtherNoncurrentFinancialAssets",
    ), 0.9, False, None),

    # ── 자본. [개요] 하위 전량 동질.
    ("EQU(자본)", SUBTREE, ("ifrs-full_EquityAbstract",), 0.95, False, None),
]

_ANCHORS = {"PL": _PL_ANCHORS, "BS": _BS_ANCHORS}


@dataclass(frozen=True)
class TaxonomyEntry:
    """요소 1건. 계층(`ancestors`)은 주요재무제표 role 기준 합집합."""
    element_id: str
    label_ko: str | None
    label_en: str | None
    balance: str | None          # 'debit' | 'credit'
    period: str | None           # 'instant' | 'duration'
    abstract: bool
    statements: tuple[str, ...]  # ('BS',) ('IS','CIS') 등 — OpenDART sj_div 와 동일 코드
    ancestors: frozenset[str]

    def label(self, lang: str = "ko") -> str | None:
        return self.label_ko if lang == "ko" else self.label_en


@dataclass(frozen=True)
class BucketHint:
    """버킷 제안. bucket=None 이면 택사노미로는 판정 불가 → 호출자가 폴백해야 한다.

    judgment=True 는 "택사노미가 회계분류는 알지만 **평가목적 재분류는 판단 사항**"이라는
    뜻이다(미지급비용의 영업성/금융성, 리스부채의 순차입금 포함 여부, 초과현금 등).
    호출자는 이 제안을 자동 확정하지 말고 유저 승인 대상으로 올려야 한다.
    """
    bucket: str | None
    statement: str               # 'PL' | 'BS'
    confidence: float
    rule: str                    # 근거(앵커 요소명) 또는 무매칭 사유
    note: str | None = None
    judgment: bool = False


@lru_cache(maxsize=1)
def _raw() -> dict:
    return json.loads(_DATA.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _index() -> dict[str, dict]:
    """요소별 조상 집합 · 등장 재무제표 구분을 presentation arc 에서 1회 구성.

    같은 요소가 여러 role(연결/별도, 기능별/성격별)에 나타나므로 조상은 **합집합**이다.
    합집합이 버킷 판정을 흐리는 경우는 없다 — 한 요소가 서로 다른 버킷 앵커 밑에
    동시에 걸리는 구조가 표준 택사노미엔 없기 때문(앵커 우선순위가 남은 모호성을 처리).
    """
    raw = _raw()
    roles = raw["roles"]
    out: dict[str, dict] = {}
    for code, arcs in raw["presentation"].items():
        kind = roles.get(code, {}).get("kind")
        parent_of = {a["e"]: a.get("p") for a in arcs}
        for arc in arcs:
            elem = arc["e"]
            slot = out.setdefault(elem, {"anc": set(), "stm": set()})
            if kind:
                slot["stm"].add(kind)
            cur, guard = parent_of.get(elem), 0
            while cur and guard < 32:            # guard: 순환 arc 방어
                slot["anc"].add(cur)
                cur, guard = parent_of.get(cur), guard + 1
    return out


def entry(element_id: str) -> TaxonomyEntry | None:
    """요소명 → 항목. 사전에 없으면 None(회사 확장계정 등)."""
    meta = _raw()["elements"].get(element_id)
    if meta is None:
        return None
    idx = _index().get(element_id, {})
    return TaxonomyEntry(
        element_id=element_id,
        label_ko=meta.get("ko"),
        label_en=meta.get("en"),
        balance=meta.get("balance"),
        period=meta.get("period"),
        abstract=bool(meta.get("abstract")),
        statements=tuple(sorted(idx.get("stm", ()))),
        ancestors=frozenset(idx.get("anc", ())),
    )


def label(element_id: str, lang: str = "ko") -> str | None:
    """요소명 → 표준 라벨. `account_nm` 이 회사 임의 표기일 때 정규 표기로 대체."""
    meta = _raw()["elements"].get(element_id)
    return None if meta is None else meta.get("ko" if lang == "ko" else "en")


def is_under(element_id: str, ancestor: str) -> bool:
    """요소가 `ancestor` 자신이거나 그 후손인가."""
    if element_id == ancestor:
        return True
    return ancestor in _index().get(element_id, {}).get("anc", ())


def calc_weight(element_id: str) -> float | None:
    """계산 링크베이스의 부모 대비 가산부호(±1). role 간 불일치·미수록이면 None.

    None 은 "가중치 0" 이 아니라 **모른다**는 뜻이다. 합계 검증에 쓸 때 None 을 0 으로
    떨어뜨리면 차감계정이 조용히 사라지므로, 호출자는 반드시 구분해서 다뤄야 한다.
    """
    seen: set[float] = set()
    for arcs in _raw()["calculation"].values():
        for arc in arcs:
            if arc["e"] == element_id and "w" in arc:
                seen.add(float(arc["w"]))
    return seen.pop() if len(seen) == 1 else None


def cash_flow_section(element_id: str) -> str | None:
    """현금흐름표 구간 → 'operating' | 'investing' | 'financing' | None."""
    for anchor, name in (
        (CF_OPERATING, "operating"),
        (CF_INVESTING, "investing"),
        (CF_FINANCING, "financing"),
    ):
        if is_under(element_id, anchor):
            return name
    return None


def bucket_hint(element_id: str, statement: str) -> BucketHint:
    """요소명 → 밸류에이션 버킷 제안. 무매칭이면 bucket=None(폴백 신호).

    statement: 'PL' | 'BS'. [[fs_mapper]] 의 버킷 라벨과 바이트 동일하게 돌려준다.
    """
    key = statement.upper()
    anchors = _ANCHORS.get(key)
    if anchors is None:
        raise ValueError(f"statement 는 'PL'|'BS': {statement}")
    if _raw()["elements"].get(element_id) is None:
        return BucketHint(None, key, 0.0, "택사노미 미수록 요소")
    for bucket, mode, elems, conf, judgment, note in anchors:
        for anchor in elems:
            hit = element_id == anchor if mode == EXACT else is_under(element_id, anchor)
            if hit:
                return BucketHint(bucket, key, conf, f"taxonomy:{anchor}", note, judgment)
    return BucketHint(None, key, 0.0, "앵커 무매칭")


def meta() -> dict:
    """데이터 provenance(`_meta`) — 리비전 표시·감사추적용."""
    return dict(_raw()["_meta"])
