"""FS 계정 → 밸류에이션 버킷 자동 분류(결정론 키워드 규칙). NOA/IBD = EV→지분 브리지 핵심.

타사 는 ChatGPT 자동분류로 하다 "Sales 오분류"를 자인 — 우리는 **순서 있는 결정론 규칙**
으로 그 함정을 코드에 못박는다. 원칙(사용자): 분류는 **제안**이고 최종은 유저 승인.
무매칭은 임의 추측 금지 → uncertain(bucket=None, 유저 분류 필요). 경계 애매(현금 등)는
낮은 confidence + 검토 노트로 표면화.

버킷(프론트 MappingSheet 정합):
  PL: Sales · COGS · SGA · NonOp(영업외)
  BS: WC(운전자본) · FA(유형자산) · NOA(비영업자산) · IBD(이자부부채) · OAL(기타) · EQU(자본)

⚠️ 규칙 순서 = 특이 계정 먼저(매출원가 < 매출, 사채 < 매입채무). 첫 매칭 승리.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import taxonomy_store

# OpenDART 가 표준계정ID 대신 넣는 문자열. 요소명이 아니므로 택사노미 조회 대상이 아니다.
NON_STANDARD_ACCOUNT_ID = "-표준계정코드 미사용-"

# 버킷 라벨(프론트와 바이트 동일)
PL_BUCKETS = ("Sales", "COGS", "SGA", "NonOp(영업외)")
BS_BUCKETS = ("WC(운전자본)", "FA(유형자산)", "NOA(비영업자산)", "IBD(이자부부채)", "OAL(기타)", "EQU(자본)")

# (bucket, [keywords], confidence, note). 순서 = 우선순위(첫 매칭 승리).
_PL_RULES: list[tuple[str, list[str], float, str | None]] = [
    ("COGS", ["매출원가", "제품매출원가", "상품매출원가", "용역원가"], 0.95, None),
    ("Sales", ["매출액", "영업수익", "매출", "수익(매출", "제품매출", "상품매출"], 0.9, None),
    ("NonOp(영업외)", ["금융수익", "금융비용", "금융원가", "이자수익", "이자비용", "외환",
                    "외화", "지분법", "유형자산처분", "법인세비용", "영업외", "기타수익",
                    "기타비용", "기타영업외", "중단영업"], 0.85, None),
    ("SGA", ["판매비와관리비", "판매비와 관리비", "판관비", "급여", "종업원급여", "인건비",
             "감가상각", "무형자산상각", "상각비", "지급수수료", "광고선전", "대손상각",
             "세금과공과", "연구개발", "경상개발", "복리후생", "임차료", "여비교통",
             "접대비", "운반비", "지급임차", "판매수수료"], 0.85, None),
]

_BS_RULES: list[tuple[str, list[str], float, str | None]] = [
    ("IBD(이자부부채)", ["단기차입금", "장기차입금", "차입금", "사채", "리스부채",
                     "유동성장기부채", "전환사채", "신주인수권부사채", "회사채"], 0.9, None),
    ("EQU(자본)", ["자본금", "자본잉여금", "주식발행초과금", "이익잉여금", "결손금",
                "자본조정", "기타포괄손익누계", "자기주식", "이익준비금", "비지배지분",
                "지배기업소유주"], 0.9, None),
    ("WC(운전자본)", ["매출채권", "재고자산", "매입채무", "선급금", "선수금", "미수금",
                   "미지급금", "미수수익", "미지급비용", "선급비용", "선수수익", "예수금",
                   "미청구공사", "초과청구공사", "계약자산", "계약부채"], 0.9, None),
    # 현금·투자 = 비영업(브리지 (+)비영업자산). 영업현금 분리 필요 시 낮은 confidence.
    ("NOA(비영업자산)", ["현금및현금성자산", "현금성자산"], 0.6, "영업현금 분리 검토(초과현금만 NOA)"),
    ("NOA(비영업자산)", ["단기금융상품", "장기금융상품", "투자부동산", "투자자산",
                     "관계기업", "종속기업", "공동기업", "당기손익-공정가치",
                     "기타포괄손익-공정가치", "매도가능", "만기보유", "장기투자", "단기투자"], 0.85, None),
    ("FA(유형자산)", ["유형자산", "무형자산", "토지", "건물", "구축물", "기계장치",
                  "차량운반구", "공구와기구", "비품", "사용권자산", "건설중인자산",
                  "영업권", "개발비", "산업재산권"], 0.9, None),
    ("OAL(기타)", ["이연법인세", "충당부채", "퇴직급여", "확정급여", "순확정급여",
                "당기법인세", "미지급법인세", "기타부채", "기타자산", "기타비유동",
                "기타유동"], 0.7, None),
]

_RULES = {"PL": _PL_RULES, "BS": _BS_RULES}


@dataclass(frozen=True)
class Classification:
    """계정 1건 분류 제안. bucket=None → uncertain(유저 분류 필요, 자동확정 금지).

    judgment=True 는 택사노미가 **회계분류는 알지만 평가목적 재분류는 판단 사항**인
    경우다(미지급비용의 영업성/금융성, 리스부채의 순차입금 포함 여부, 초과현금 등).
    bucket 제안은 있으나 자동 확정 금지 — 유저 승인 대상으로 올려야 한다.
    """
    account: str
    statement: str            # 'PL' | 'BS'
    bucket: str | None
    confidence: float
    rule: str                 # 근거 키워드 or 무매칭 사유
    uncertain: bool
    note: str | None = None
    judgment: bool = False


def _norm(s: str) -> str:
    return "".join(str(s).split())          # 공백 제거(계정명 표기 흔들림 흡수)


def classify(
    account: str, statement: str, *, account_id: str | None = None
) -> Classification:
    """계정명(+표준 요소명) → 버킷 제안. 무매칭 = uncertain.

    statement: 'PL' | 'BS'. 반환은 제안일 뿐 — 최종은 유저 승인(판단 보조 원칙).
    account_id: OpenDART `account_id`(예 `ifrs-full_Revenue`). 주면 [[taxonomy_store]]
        판정을 **먼저** 시도한다. 요소명은 회사가 못 바꾸므로 "매출액 / 영업수익 /
        수익(매출액)" 같은 표기 흔들림에 면역이다. 앵커 무매칭이면 아래 계정명 키워드로
        폴백한다(2단 구조). 판단 계정은 bucket 제안 + judgment=True 로 표면화.
    """
    stmt = statement.upper()
    rules = _RULES.get(stmt)
    if rules is None:
        raise ValueError(f"statement 는 'PL'|'BS': {statement}")

    # 1단: 표준 요소명 → 택사노미. `-표준계정코드 미사용-` 은 요소명이 아니므로 제외.
    if account_id and account_id != NON_STANDARD_ACCOUNT_ID:
        hint = taxonomy_store.bucket_hint(account_id, stmt)
        if hint.bucket:
            return Classification(account, stmt, hint.bucket, hint.confidence,
                                  hint.rule, False, hint.note, hint.judgment)

    # 2단: 계정명 키워드(첫 매칭 승리).
    acc = _norm(account)
    if not acc:
        return Classification(account, stmt, None, 0.0, "빈 계정명", True)
    for bucket, keywords, conf, note in rules:
        for kw in keywords:
            if _norm(kw) in acc:
                return Classification(account, stmt, bucket, conf,
                                      f"'{kw}' 매칭", False, note)
    return Classification(account, stmt, None, 0.0, "무매칭 — 유저 분류 필요", True)


def classify_all(
    accounts: list[str], statement: str, *, account_ids: list[str | None] | None = None
) -> list[Classification]:
    """계정 리스트 일괄 분류. account_ids 를 주면 위치별로 짝지어 택사노미 1단을 태운다."""
    ids = account_ids or []
    return [
        classify(a, statement, account_id=(ids[i] if i < len(ids) else None))
        for i, a in enumerate(accounts)
    ]
