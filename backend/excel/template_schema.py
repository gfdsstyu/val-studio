"""DCF 워크북 셀 레이아웃 SSOT (single source of truth).

export(계산 결과를 수식으로 기록)와 import(역방향 읽기)가 **같은 이 스키마**를 소비한다 —
셀 주소·행 맵을 양쪽에 중복 선언하지 않는다. (과거엔 `dcf_export.R` 과 `dcf_import._ROW`
가 별개 dict 였고, 가정셀 C3~C7·메타셀 C37~C39 도 양쪽에 리터럴로 흩어져 있었다.)
셀 레이아웃을 바꾸려면 **여기 한 곳**만 고치면 export·import 가 함께 따라온다.

추가로 **롤업 위계**(DCF 스파인 라인 → 성격별 세분 자식)를 선언한다 — W2.5 `FS_Disagg`
세분 뼈대(stage_sheets)와 (향후) W4 추정 시트 배선이 이 `DISAGG_BLOCKS`/`ROLLUP` 을 SSOT
로 소비해, 세분 라인이 스파인 라인으로 **합보존 롤업**되는 관계를 코드 한 곳에 둔다.

전부 순수 표준 라이브러리(상수·헬퍼) — 샌드박스 vendoring 대상.
"""
from __future__ import annotations

# ── 연도 열(명시적 추정기간) ──────────────────────────────────────────────
YEAR_COLS = ["C", "D", "E", "F", "G"]
BASE_YEAR = 2024

# ── 가정 블록(전용 셀, 절대참조 대상). 라벨은 같은 행 B열 ──────────────────
ASSUMP = {
    "wacc": "C3",
    "terminal_growth": "C4",
    "shares_outstanding": "C5",
    "non_operating_assets": "C6",
    "net_debt": "C7",
    "non_controlling_interest": "C8",   # NCI(비지배지분) — EV→지분 브리지 차감(기본 0)
}

# ── 시계열 행 맵(연도=열, key=행번호) ──────────────────────────────────────
ROW = {
    "year": 10, "rev": 11, "cogs": 12, "gp": 13, "sga": 14, "ebit": 15,
    "tax": 16, "noplat": 17, "da": 18, "capex": 19, "nwc": 20, "fcff": 21,
    "period": 22, "pvf": 23, "pv": 24,
}

# ── 평가결과 블록(단일 셀). 라벨은 같은 행 B열 ─────────────────────────────
RESULT = {
    "pv_explicit": "C27", "terminal_fcff": "C28", "terminal_value": "C29",
    "terminal_value_pv": "C30", "enterprise_value": "C31", "equity_value": "C32",
    "per_share": "C33",
}

# ── 모델 메타(개선 A/B 오버라이드; 설정된 것만 기록) ───────────────────────
META = {
    "effective_tax_rate": "C37",
    "terminal_fcff_override": "C38",
    "terminal_reinvestment_rate": "C39",
}
META_FLAG_TAX_OVERRIDE = "B36"   # tax_override 플래그(하드값은 세금 행에서 복원)

# ── 롤업 위계: 스파인 라인 → 성격별 세분 자식(W2.5 FS_Disagg / W4 배선 SSOT) ──
# parent_key 가 있으면 DCF 스파인 행(ROW)과 합보존 롤업으로 연결된다.
# 영업외손익은 스파인에 전용 행이 없어 parent_key 없음(세분만, 롤업 대상 아님).
DISAGG_BLOCKS = [
    {"parent_key": "rev",  "parent": "매출액",     "source": "매출 세그먼트·품목 주석",
     "children": ["제품매출", "상품매출", "용역매출", "기타매출"]},
    {"parent_key": "cogs", "parent": "매출원가",   "source": "제조원가명세서",
     "children": ["재료비", "노무비", "경비", "기타원가"]},
    {"parent_key": "sga",  "parent": "판매관리비", "source": "판관비 성격별 주석",
     "children": ["급여", "감가상각비", "광고선전비", "기타판관비"]},
    {"parent": "영업외손익", "source": "영업외 명세(경상/일회성)",
     "children": ["경상항목", "일회성항목"]},
]

# 스파인 라인 key → 세분 자식(합보존 롤업 대상). 영업외 등 스파인 행 없는 블록은 제외.
ROLLUP = {b["parent_key"]: b["children"] for b in DISAGG_BLOCKS if "parent_key" in b}

# ── W4 Fcst 시트 레이아웃(스파인 라인별 세분 블록 시작행). 계 셀은 파생 ─────────
# stage_sheets.build_fcst_* 와 promote.py(W6 승격)가 이 SSOT 를 공유 — Fcst 계 셀을
# 양쪽이 같은 주소로 참조해야 승격 수식(=Fcst_Rev!C12)이 정확히 걸린다.
# 블록 구조: [title] / [Year] / [children...] / [계]  →  계 행 = start + 2 + len(children).
FCST = {
    "rev":  {"sheet": "Fcst_Rev",  "block_start": 6},
    "cogs": {"sheet": "Fcst_Cost", "block_start": 6},
    "sga":  {"sheet": "Fcst_Cost", "block_start": 14},
}


def fcst_total_row(line: str) -> int:
    """Fcst 시트에서 해당 스파인 라인의 '계'(Σ세분) 행 번호."""
    return FCST[line]["block_start"] + 2 + len(ROLLUP[line])


def fcst_total_cell(line: str, col: str) -> str:
    """Fcst 계 셀의 크로스시트 주소. 예: fcst_total_cell('rev','C') == 'Fcst_Rev!C12'."""
    return f"{FCST[line]['sheet']}!{col}{fcst_total_row(line)}"


# ── 정합 CHECK 허용오차(R6) ────────────────────────────────────────────────
# ⚠️ 정확일치(`=IF(A=B,...)`) 금지 — 부동소수 노이즈로 경제적으로 완전히 일치하는
# 연도가 FALSE 로 뜬다(모델러스 5.4 §4 D1 실측: 잔차 -7.1e-14 로 2개 연도 오작동).
# 단위가 백만원이므로 0.001(=1천원)이면 반올림 잔차는 흡수하고 실오류는 잡는다.
CHECK_TOL = 0.001

# ── 인건비 bottom-up + 비용배분(R4) ───────────────────────────────────────
# 근거: 모델러스_통합모델_5.4 §2.1(b)(c) — 인건비를 "인원 × 시급 × 시간"으로 완전 분해하고
# 임금상승률을 거시 통계에 앵커링. 배분은 `한쪽 = 총액 × %`, `다른쪽 = 총액 − 앞쪽`의
# **잔차 방식** → 합보존이 수식으로 강제된다.
LABOR_ROLES = ["제조·품질", "영업·마케팅", "구매", "경영·전략", "재무·IR", "IT·인사·기타", "연구개발"]

# 총액을 COGS/SGA 로 나누는 배분 대상(성격별 비용). 라벨 → 배분 결과가 흘러갈 세분 라인.
ALLOCATED_COSTS = [
    ("인건비", "노무비", "급여"),          # (총액 라벨, → 매출원가 세분, → 판관비 세분)
    ("감가상각비", "경비", "감가상각비"),   # Capex_Dep 당기상각을 원가/판관비로 배분
]


# 승격 대상 스파인 라인 → (ROW/입력 key, DcfSpineInput 필드명). W6 promote 가 소비.
PROMOTABLE = {"rev": "revenue", "cogs": "cogs", "sga": "sga"}


# ── 헬퍼 ──────────────────────────────────────────────────────────────────
def cell(col: str, row_key: str) -> str:
    """연도 열 + 행 key → 셀 주소. 예: cell('C','rev') == 'C11'."""
    return f"{col}{ROW[row_key]}"


def label_cell(value_ref: str) -> str:
    """값 셀(C열) → 같은 행의 라벨 셀(B열). 예: 'C3' → 'B3', 'C37' → 'B37'."""
    return "B" + value_ref[1:]


def abs_cell(value_ref: str) -> str:
    """상대 참조 → 절대 참조. 예: 'C3' → '$C$3'. 가정셀 수식 참조용."""
    col = value_ref[0]
    rownum = value_ref[1:]
    return f"${col}${rownum}"
