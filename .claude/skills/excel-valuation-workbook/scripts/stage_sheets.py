"""단계별 시트 뼈대 생성기 (W1~W5) — 풀모델 점진 성장.

각 단계에 해당 시트의 뼈대(제목·범례·라벨·입력 placeholder·타시트 참조 스텁)를
결정론으로 찍는다. Claude 는 이 뼈대를 근거·수식으로 채운다(판단·값은 평가인).
색상은 xlsx 에 API 가 없어 **범례 텍스트로 규약을 명시**(Blue 입력/Black 수식/Green 타시트).

vendor/excel.Workbook 사용(자기완결). scaffold.py 가 --stage 로 호출.
"""
from __future__ import annotations

# 셀 레이아웃·세분 롤업 위계는 vendored template_schema SSOT 를 소비(자체 복사 금지).
# scaffold.py 가 _bootstrap 로 vendor 를 path 에 올린 뒤 stage_sheets 를 import 한다.
from excel.template_schema import (
    ALLOCATED_COSTS, CHECK_TOL, DISAGG_BLOCKS, FCST, LABOR_ROLES, ROLLUP, YEAR_COLS,
    fcst_total_cell,
)

_LEGEND = "범례: [입력]=파랑(hard) · [수식]=검정 · [참조]=초록(타시트) · 핵심가정=노랑fill"


def _rollup_block(s, title: str, children: list[str], start_row: int, n: int,
                  target_note: str) -> int:
    """성격별 세분 자식 입력행 + 계(SUM live 롤업) 행 생성. 다음 블록 시작행 반환.

    자식 행 값은 [입력](Claude 가 FS_Disagg 역사앵커+드라이버로 채움), 계 행은 살아있는
    SUM 수식 — 세분→원계정 합보존 롤업을 워크북 수식으로 강제한다(합보존 게이트의 시트 구현).
    """
    s.text(f"B{start_row}", title)
    _years(s, start_row + 1, n)
    first = start_row + 2
    r = first
    for ch in children:
        s.text(f"B{r}", ch)                          # [입력·FS_Disagg 앵커 + 드라이버]
        r += 1
    last = r - 1
    s.text(f"B{r}", f"계 (= Σ세분{target_note})")
    for c in YEAR_COLS[:n]:
        s.formula(f"{c}{r}", f"SUM({c}{first}:{c}{last})")   # 캐시값 없음(placeholder, Excel recalc)
    return r + 2                                     # 블록 간 1행 여백


def _years(s, row: int, n: int, base_year: int = 2024) -> None:
    s.text(f"B{row}", "Year")
    for j, c in enumerate(YEAR_COLS[:n]):
        s.num(f"{c}{row}", base_year + j)


def _check_row(s, row: int, label: str, lhs: str, rhs: str, n: int,
               tol: float = CHECK_TOL, cols: list | None = None) -> None:
    """정합 CHECK 행(R6) — 일치하면 "TRUE", 아니면 **잔차 금액**을 표시한다.

    잔차를 보여주는 게 핵심: TRUE/FALSE 만으로는 어디가 얼마나 틀렸는지 알 수 없다.
    ⚠️ 정확일치 비교 금지 — 부동소수 노이즈로 맞는 연도가 FALSE 로 뜬다
    (모델러스 5.4 §4 D1: 잔차 -7.1e-14 로 2개 연도 오작동). ABS(차이) < 허용오차로 판정.
    lhs/rhs 는 `{col}` 자리표시자를 포함한 수식 조각(예: "{col}20").
    """
    s.text(f"B{row}", label)
    for c in (cols if cols is not None else YEAR_COLS[:n]):
        # ⚠️ 양변을 반드시 괄호로 감싼다 — 우변이 다항식이면(예 "부채+자본")
        # `자산-부채+자본` 이 되어 **부호가 뒤집힌다**(연산자 우선순위 함정).
        a, b = f"({lhs.format(col=c)})", f"({rhs.format(col=c)})"
        s.formula(f"{c}{row}", f'IF(ABS({a}-{b})<{tol},"TRUE",{a}-{b})')


def _header(s, title: str) -> None:
    """제목 + 범례 + **가시 상태 헤더**(R8).

    모델러스 정본은 전 시트 상단에 전역 상태(선택 시나리오·현재 타깃가격)를 노출해
    "지금 이 모델이 어떤 상태인지"를 어느 시트에서든 알 수 있게 한다. 우리 `_VS_STATE`
    는 숨김 시트라 사람이 못 보므로 그 보완재. 값은 Claude/평가인이 채운다.
    """
    s.text("B1", title)
    s.text("B2", _LEGEND)
    for r, (k, hint) in enumerate(
            (("Scenario", "[Base/Up/Down]"), ("Target Price", "[= DCF 주당가치]"),
             ("Stage", "[W0~W9]")), start=1):
        s.text(f"I{r}", f"{k} :")
        s.text(f"J{r}", hint)


# ── W1 Assumption (가정 SSOT) ─────────────────────────────────────────────────
def build_assumption(wb, n: int = 5):
    """가정 SSOT(참고 모델 Assumption 시트). 모든 가정의 단일 소스 — Fcst/Capex_Dep/WC/WACC 가
    Green 참조("hard number 1곳" 절차화). 값=Research 근거로 평가인 확정(연도별 [입력])."""
    s = wb.add_sheet("Assumption")
    _header(s, "Assumption — 가정 SSOT (하류 시트 Green 참조)")
    s.text("B3", "모든 가정의 단일 소스. Fcst_Rev/Fcst_Cost/Capex_Dep/WC/WACC 가 여기를 참조. "
                 "값=Research 근거로 평가인 확정.")
    _years(s, 5, n)
    blocks = [
        ("── 매출 드라이버 ──", ["매출성장률 또는 시장CAGR", "목표 시장점유율"]),
        ("── 마진 ──", ["GP%(=1−원가율)", "EBIT%(판관비 후)"]),
        ("── 원가 성격 ──", ["변동비율(매출연동)", "고정비 증가율(CPI)", "인건비 상승률"]),
        ("── CAPEX·상각 ──", ["CAPEX(% of sales)", "상각연수(정액)"]),
        ("── 운전자본(회전일) ──", ["매출채권 회전일", "재고 회전일", "매입채무 회전일"]),
        ("── 거시·할인 ──", ["Rf 무위험이자율", "MRP 시장위험프리미엄", "목표 세율 t"]),
    ]
    r = 6
    for title, items in blocks:
        s.text(f"B{r}", title)
        r += 1
        for it in items:
            s.text(f"B{r}", it)                       # 값=[입력] 연도별
            r += 1
    s.text(f"B{r + 1}", "sanity(클래시스 벤치마크): GP% 79.8·EBIT% 51.6 고정, 성장 +20% flat")
    return s


# ── W1 Research ──────────────────────────────────────────────────────────────
def build_research(wb, n: int = 5):
    """W1 Research — Company Brief 10섹션(기업리서치_양식 정본). 각 섹션 하위필드 + 소비처(뒤 단계).
    모든 표에 출처 URL 병기(DART rcpNo·fnguide·증권사). 채워진 Brief 를 W2~W9 가 소비."""
    s = wb.add_sheet("Research")
    _header(s, "Research — Company Brief 10섹션 + 리서치 SSOT")
    s.text("B3", "각 항목 [서사]에 출처 URL 병기(DART rcpNo·fnguide·증권사 리서치). Claude 초안→평가인 확정.")

    # (번호+제목·하위필드, → 소비처)
    sections = [
        ("① Summary — 투자포인트 3줄(성장 동인 핵심)", "→ 리포트 서사"),
        ("② 회사개요 — 설립일·대표·사업개요·종속회사·주주구성(지분율)·유통주식비율·신용등급·상장일",
         "→ 유통주식수(주당가치)·Kd(신용등급)"),
        ("③ 자회사 지분율·지배구조 도식", "→ SOTP 파트 정의"),
        ("④ 사업부문·종속별 제품매출·비중(부문·매출액·비중; 지배+종속 각각)",
         "→ 계정매핑·매출 세그먼트 트리(W2.5)"),
        ("⑤ 주요제품 — 제품명·내용·향처(%)·시장점유율(글로벌/국내 순위)", "→ 매출 추정논리(W4 방식)"),
        ("⑥ Value Chain — 전방·후방·자체조달 구조", "→ 원가 성격(변동/고정, W2.5·W4)"),
        ("⑦ 주요 고객사·경쟁사 — 고객 집중도·경쟁사 리스트", "→ QOE 리스크·peer 후보(W5)"),
        ("⑧ 시장 분석 — 제품군별 시장규모·성장·경쟁 지형", "→ 점유율 매출추정·PGR"),
        ("⑨ 경쟁사 밸류에이션 비교 — peer 배수(PER/EV 등)", "→ peer 선정·상대가치"),
        ("⑩ 전방 전망 + Financials — 전방산업 전망·Raw 재무(BS·PL·CF 3개년)", "→ 성장률·β 기준시장"),
    ]
    r = 5
    for title, consumer in sections:
        s.text(f"B{r}", title)
        s.text(f"C{r}", "[서사·출처 URL]")
        s.text(f"D{r}", consumer)
        r += 1

    # ── 하류 시트가 수식 참조하는 숫자 가정(파랑 입력, hard number 1곳) ──
    r += 1
    s.text(f"B{r}", "── 리서치 숫자 가정 (하류 시트 Green 참조 대상) ──")
    r += 1
    for k, dst in (("시장 CAGR", "→ Fcst_Rev"), ("목표 시장점유율", "→ Fcst_Rev"),
                   ("매출채권 회전일", "→ WC"), ("재고 회전일", "→ WC"), ("매입채무 회전일", "→ WC")):
        s.text(f"B{r}", k)
        s.text(f"C{r}", "[입력]")
        s.text(f"D{r}", dst)
        r += 1
    return s


# ── W2 FS_Hist (Raw / Normalized / Map) ──────────────────────────────────────
def build_fs_hist(wb, n: int = 5):
    """W2 FS_Hist — 과거 FS(원본 불변 / 정규화 / 매핑). Normalized 는 표준 IS+BS 라인.
    출처: 모델링_실무 STEP1 FS정리 + Finalize 연결맵. fs_clean.py 정규화 결과가 여기 정착."""
    s = wb.add_sheet("FS_Hist")
    _header(s, "FS_Hist — 과거 재무제표(원본 불변 / 정규화 / 매핑)")

    # ── ① Raw(붙여넣기 원문, 불변) ──
    s.text("B4", "── ① Raw (사업보고서 FS 원문 붙여넣기, 불변) ──")
    s.text("B5", "[당기·전기 포함 원문 그대로 붙여넣기 — fs_clean.py 입력]")

    # ── ② Normalized (표준 IS + BS, fs_clean.py 정규화) ──
    s.text("B8", "── ② Normalized (fs_clean.py 정규화; 단위 백만원) ──")
    _years(s, 9, n)
    is_lines = ["매출액", "매출원가", "매출총이익", "판매관리비", "영업이익",
                "영업외수익", "영업외비용", "법인세비용차감전순이익", "법인세비용", "당기순이익"]
    r = 10
    s.text(f"B{r}", "[IS]")
    r += 1
    for lbl in is_lines:
        s.text(f"B{r}", lbl)
        r += 1
    r += 1
    s.text(f"B{r}", "[BS]")
    r += 1
    for lbl in ["유동자산", "비유동자산", "자산총계", "유동부채", "비유동부채", "부채총계", "자본총계"]:
        s.text(f"B{r}", lbl)
        r += 1

    # ── ③ Map (계정 이관·매핑 대장; W2 연도간 이관 / W3 평가유형은 별도 층) ──
    r += 1
    s.text(f"B{r}", "── ③ Map (계정 이관·매핑 대장) ──")
    for col, h in zip("BCDEF", ["원계정", "표준계정", "이관연도", "금액", "상태(확정/미해결)"]):
        s.text(f"{col}{r + 1}", h)

    # ── Finalize 연결맵(모델링_실무 §3): 이 시트가 하류로 흐르는 경로 ──
    r += 3
    s.text(f"B{r}", "── Finalize 연결(하류 소비): 매출/원가/판관비→EBIT·DCF · "
                    "비영업자산·순차입부채→DCF 브리지 · 자본→NCI 확인 ──")
    return s


# ── W2.5 FS_Disagg (손익 계정 세분화 + 합보존·구성비) ─────────────────────────
def build_fs_disagg(wb, n: int = 5):
    """W2.5 손익 세분 뼈대. 러프한 IS 라인을 성격별로 분해 — 원계정별 블록마다
    자식 행 + 계(합보존) + 구성비 행. 값은 Claude 가 주석·세그먼트 근거로 채운다.
    참조는 FS_Disagg → FS_Hist(뒤→앞). 하류 Fcst_Rev·Fcst_Cost 가 세분 라인 참조."""
    s = wb.add_sheet("FS_Disagg")
    _header(s, "FS_Disagg — 손익 계정 세분화(성격별) + 합보존·구성비")
    s.text("B3", "세분 계 = FS_Hist 원계정(합보존 게이트: fs_disagg.py). "
                 "원천자료(주석·세그먼트·제조원가명세서)가 지지하는 만큼만 세분 — 없으면 총액 유지 + [성격별 미확보].")
    s.text("B4", "구성비 YoY 급변(>15%p)은 WARN(사업 변화/재분류 확인). 하류 Fcst_Rev·Fcst_Cost 가 세분 라인 참조.")

    # 원계정별 세분 블록은 template_schema.DISAGG_BLOCKS SSOT(스파인 롤업 위계와 동일 소스).
    row = 6
    for block in DISAGG_BLOCKS:
        parent, children, src = block["parent"], block["children"], block["source"]
        s.text(f"B{row}", f"── {parent} 세분 (원천: {src}) ──")
        _years(s, row + 1, n)
        r = row + 2
        for ch in children:
            s.text(f"B{r}", ch)           # 값=[입력] (Claude 가 주석 근거로 채움)
            r += 1
        s.text(f"B{r}", f"계 (= Σ세분) [수식]")
        for c in YEAR_COLS[:n]:
            s.formula(f"{c}{r}", f"SUM({c}{row + 2}:{c}{r - 1}))".replace("))", ")"))
        s.text(f"B{r + 1}", f"원계정 (= FS_Hist!{parent}) [참조]")
        # 합보존 CHECK — 세분 계와 원계정이 허용오차 내에서 일치하는지 워크북에서 상시 확인.
        # 게이트(fs_disagg.py)는 인제스트 시점 1회, 이 행은 **편집 중에도 살아있는** 검증.
        _check_row(s, r + 2, "CHECK 세분합 = 원계정",
                   f"{{col}}{r}", f"{{col}}{r + 1}", n)
        s.text(f"B{r + 3}", "구성비(%) [수식]")
        row = r + 5                        # 블록 간 1행 여백
    return s


# ── W3 Reclass (평가목적 재분류 + _A/_F) ──────────────────────────────────────
def build_reclass(wb, n: int = 5):
    s = wb.add_sheet("Reclass")
    _header(s, "Reclass — 평가목적 재분류(Valuation B/S)")
    s.text("B4", "PL 4유형: Sales / COGS / SGA / NO(영업외)")
    s.text("B5", "BS 6유형: WC / FA / NOA(비영업자산) / IBD(이자부채) / OAL / EQU")
    s.text("B6", "⚠️ 현금(최소영업=WC vs 잉여=NOA)·이연법인세 경계는 평가인 판단")
    s.text("B7", "게이트: 분류합=원본 FS합(reclass.py) — 누락·중복·유형오류 0")
    row = 9
    for col, h in zip("BCDEF", ["표준계정", "평가유형", "_A(실사조정)", "_F(최종)", "근거"]):
        s.text(f"{col}{row}", h)
    return s


# ── W4 추정 4시트 ────────────────────────────────────────────────────────────
def build_fcst_rev(wb, n: int = 5):
    """매출 추정 — FS_Disagg 매출 세분(제품/상품/용역/기타)과 동일 성격 라인으로 배선.
    각 세분을 드라이버로 추정 → 계=Σ 살아있는 SUM → DCF!매출(합보존 롤업)."""
    s = wb.add_sheet("Fcst_Rev")
    _header(s, "Fcst_Rev — 매출 추정(성격별 세분, 드라이버=평가인 선택)")
    s.text("B3", "세분 라인 = FS_Disagg 매출 세분(동일 성격). 역사 앵커=FS_Disagg 매출 세분(초록 참조).")
    s.text("B4", "드라이버: 성장률 / 시장점유율 / P×Q / 결합 [평가인]. 가정근거=Research!(시장 CAGR·목표점유율).")
    _rollup_block(s, "── 매출 세분 추정 ──", ROLLUP["rev"], FCST["rev"]["block_start"], n, ", → DCF!매출")
    return s


def build_fcst_cost(wb, n: int = 5):
    """원가·판관비 추정 — FS_Disagg 원가·판관비 세분과 동일 성격 라인으로 배선.
    성격별 세분에 변동/고정 드라이버 적용 → 각 계=Σ SUM → DCF!매출원가·판관비(합보존 롤업)."""
    s = wb.add_sheet("Fcst_Cost")
    _header(s, "Fcst_Cost — 원가·판관비 추정(성격별 세분)")
    s.text("B3", "세분 라인 = FS_Disagg 원가·판관비 세분. 역사 앵커=FS_Disagg(초록 참조).")
    s.text("B4", "각 성격에 변동(매출 연동)/고정(CPI·임금 연동) 드라이버 적용 [평가인 판단].")
    _rollup_block(s, "── 매출원가 세분 추정 ──", ROLLUP["cogs"], FCST["cogs"]["block_start"], n, ", → DCF!매출원가")
    _rollup_block(s, "── 판매관리비 세분 추정 ──", ROLLUP["sga"], FCST["sga"]["block_start"], n, ", → DCF!판관비")
    # 영업이익 롤업(EBIT 검산): 매출(Fcst_Rev 계) − 매출원가계 − 판관비계. 살아있는 수식.
    cogs_tot = FCST["cogs"]["block_start"] + 2 + len(ROLLUP["cogs"])   # 매출원가 계 행
    sga_tot = FCST["sga"]["block_start"] + 2 + len(ROLLUP["sga"])      # 판관비 계 행
    ebit_row = sga_tot + 2
    s.text(f"B{ebit_row}", "영업이익 = 매출 − 매출원가 − 판관비 (→ DCF!EBIT 검산)")
    for c in YEAR_COLS[:n]:
        s.formula(f"{c}{ebit_row}", f"{fcst_total_cell('rev', c)}-{c}{cogs_tot}-{c}{sga_tot}")
    s.text(f"B{ebit_row + 1}", "상각비(원가/판관비)는 Capex_Dep 당기상각에서 배분(아래 ③).")
    _build_labor_and_allocation(s, ebit_row + 3, n)
    return s


def _build_labor_and_allocation(s, start: int, n: int) -> int:
    """인건비 bottom-up + 성격별 비용 배분(R4). 다음 여유행 반환.

    근거: 모델러스_통합모델_5.4 §2.1(b)(c).
      ② 인건비 = Σ직군별 인원 × (연근무일 × 일근무시간 × 시급), 시급성장 ← Macro(임금)
      ③ 배분   = 총액을 매출원가/판관비로. **잔차 방식**(판관비=총액×%, 원가=총액−판관비)
                 이라 합보존이 수식으로 강제되고, CHECK 행이 그것을 다시 확인한다.

    산출(총인건비·배분액)은 위 세분 블록의 `노무비`(원가)·`급여`(판관비) 행이 참조한다 —
    성격별 총액을 먼저 쌓고 배분하는 순서가 정본(총액 추정 → 배분)이다.
    """
    cols = YEAR_COLS[:n]
    r = start
    s.text(f"B{r}", "── ② 인건비 bottom-up (인원 × 시급 × 시간) ──")
    r += 1
    _years(s, r, n)
    r += 1
    head_first = r
    for role in LABOR_ROLES:
        s.text(f"B{r}", f"인원 · {role}")            # [입력] 드라이버당 인원
        for c in cols:
            s.text(f"{c}{r}", "[입력]")
        r += 1
    head_last = r - 1
    head_tot = r
    s.text(f"B{r}", "총인원 (= Σ직군)")
    for c in cols:
        s.formula(f"{c}{r}", f"SUM({c}{head_first}:{c}{head_last})")
    r += 1

    days, hours, wage, per_head, total = r, r + 1, r + 2, r + 3, r + 4
    s.text(f"B{days}", "연 근무일수")
    s.text(f"B{hours}", "일 근무시간")
    s.text(f"B{wage}", "시급 (전기×(1+임금상승률) — 임금상승률은 Macro 참조 [초록])")
    for c in cols:
        for rr in (days, hours, wage):
            s.text(f"{c}{rr}", "[입력]")
    s.text(f"B{per_head}", "1인 인건비 = 연근무일 × 일근무시간 × 시급")
    s.text(f"B{total}", "총인건비 = 총인원 × 1인 인건비")
    for c in cols:
        s.formula(f"{c}{per_head}", f"{c}{days}*{c}{hours}*{c}{wage}")
        s.formula(f"{c}{total}", f"{c}{head_tot}*{c}{per_head}")
    r = total + 2

    s.text(f"B{r}", "── ③ 성격별 비용 배분 (총액 → 매출원가 / 판관비) ──")
    r += 1
    s.text(f"B{r}", "배분은 잔차 방식: 판관비=총액×%, 매출원가=총액−판관비 → 합보존 강제.")
    r += 1
    for label, to_cogs, to_sga in ALLOCATED_COSTS:
        src = f"{{col}}{total}" if label == "인건비" else "[입력·Capex_Dep 당기상각 참조]"
        s.text(f"B{r}", f"{label} 총액" + ("" if label == "인건비" else " (→ Capex_Dep 초록 참조)"))
        if label == "인건비":
            for c in cols:
                s.formula(f"{c}{r}", f"{c}{total}")          # ②에서 산출한 총액을 그대로
        else:
            for c in cols:
                s.text(f"{c}{r}", "[참조]")
        tot_r = r
        r += 1
        s.text(f"B{r}", f"  % 판관비 배분율")
        for c in cols:
            s.text(f"{c}{r}", "[입력]")
        pct_r = r
        r += 1
        s.text(f"B{r}", f"  → 판관비 ({to_sga})")
        for c in cols:
            s.formula(f"{c}{r}", f"{c}{tot_r}*{c}{pct_r}")
        sga_r = r
        r += 1
        s.text(f"B{r}", f"  → 매출원가 ({to_cogs}) = 총액 − 판관비분 [잔차]")
        for c in cols:
            s.formula(f"{c}{r}", f"{c}{tot_r}-{c}{sga_r}")
        cogs_r = r
        r += 1
        _check_row(s, r, f"  CHECK 배분합 = {label} 총액",
                   f"{{col}}{cogs_r}+{{col}}{sga_r}", f"{{col}}{tot_r}", n)
        r += 2
    s.text(f"B{r}", "→ 위 배분 결과를 ① 세분 블록의 해당 행(노무비·급여·경비·감가상각비)이 참조한다.")
    return r + 2


def build_capex_dep(wb, n: int = 5):
    """W4 FA·상각비계산 — CAPEX(신규/유지) + 기존자산 잔여상각 + 신규자산 정액상각 스케줄.
    살아있는 수식: 기초=기말_{t-1}, 당기상각=기존+신규, 기말=기초+CAPEX−상각. → DCF!D&A·CAPEX."""
    s = wb.add_sheet("Capex_Dep")
    _header(s, "Capex_Dep — FA·상각비계산 (기존자산 잔여 + 신규 CAPEX 정액)")
    s.text("B3", "CAPEX=Assumption(%of sales) 신규+유지. 신규자산은 상각연수 정액 → 향후 배분(근사=누적/연수).")
    _years(s, 5, n)
    cols = YEAR_COLS[:n]
    R = {"beg": 6, "capex": 7, "dep_old": 8, "dep_new": 9, "dep": 10, "end": 11}
    labels = {"beg": "기초 유형자산", "capex": "CAPEX (신규+유지)", "dep_old": "기존자산 잔여상각",
              "dep_new": "신규자산 상각 (누적CAPEX/연수)", "dep": "당기 상각 (→ DCF!D&A)",
              "end": "기말 유형자산"}
    for k, r in R.items():
        s.text(f"B{r}", labels[k])
    for j, c in enumerate(cols):
        if j == 0:
            s.text(f"{c}{R['beg']}", "[입력·기초]")
        else:
            s.formula(f"{c}{R['beg']}", f"{cols[j-1]}{R['end']}")            # 기초=전기 기말
        s.text(f"{c}{R['capex']}", "[입력]")
        s.text(f"{c}{R['dep_old']}", "[입력]")
        s.formula(f"{c}{R['dep_new']}", f"SUM({cols[0]}{R['capex']}:{c}{R['capex']})/$C$13")  # 누적/연수
        s.formula(f"{c}{R['dep']}", f"{c}{R['dep_old']}+{c}{R['dep_new']}")   # 당기상각
        s.formula(f"{c}{R['end']}", f"{c}{R['beg']}+{c}{R['capex']}-{c}{R['dep']}")  # 기말
    s.text("B13", "상각연수(정액)")
    s.text("C13", "[입력]")
    s.text("B15", "연결: 당기상각 → DCF!(+)D&A · CAPEX → DCF!(−)CAPEX · 상각비 → EBIT(원가/판관비 배분)")
    return s


def build_wc(wb, n: int = 5):
    """W4 WC — 회전일→잔액→ΔNWC 살아있는 수식. 매출·원가는 Fcst 참조, 회전일은 Assumption.
    매출채권=매출×일/365, 재고·매입채무=원가×일/365, ΔNWC=NWC_t−NWC_{t-1} → DCF!ΔNWC."""
    s = wb.add_sheet("WC")
    _header(s, "WC — 운전자본 (회전일 → 잔액 → ΔNWC)")
    s.text("B3", "매출·원가=Fcst 참조(초록), 회전일=Assumption/Research. ⚠️ 회전율 방향 주의(잔액=드라이버×일/365).")
    # R12: 회전일 드라이버는 대개 과거 N년 평균인데 **N 자체가 판단**이다 — 창과 사유를
    # 시트에 남긴다(실측: 같은 워크북에서 DSO 3년 / DIO·DPO 5년인데 근거 부재).
    s.text("B4", "회전일 lookback: 과거 몇 년 평균인지와 그 사유를 아래 열에 필수 기재(항목별로 달라도 됨).")
    s.text("K5", "lookback(년)")
    s.text("L5", "lookback 사유")
    for rr in (8, 9, 10):                       # DSO·DIO·DPO 행
        s.text(f"K{rr}", "[입력]")
        s.text(f"L{rr}", "[입력·예: 2020 이상치 제외]")
    _years(s, 5, n)
    cols = YEAR_COLS[:n]
    R = {"rev": 6, "cogs": 7, "d_ar": 8, "d_inv": 9, "d_ap": 10,
         "ar": 11, "inv": 12, "ap": 13, "nwc": 14, "dnwc": 15}
    labels = {"rev": "매출 (→Fcst_Rev)", "cogs": "매출원가 (→Fcst_Cost)",
              "d_ar": "매출채권 회전일", "d_inv": "재고 회전일", "d_ap": "매입채무 회전일",
              "ar": "매출채권 = 매출×일/365", "inv": "재고자산 = 원가×일/365",
              "ap": "매입채무 = 원가×일/365", "nwc": "순운전자본 NWC = AR+재고−AP",
              "dnwc": "ΔNWC = NWC_t − NWC_{t-1} (→ DCF!ΔNWC)"}
    for k, r in R.items():
        s.text(f"B{r}", labels[k])
    for k in ("rev", "cogs", "d_ar", "d_inv", "d_ap"):
        for c in cols:
            s.text(f"{c}{R[k]}", "[입력]")
    for j, c in enumerate(cols):
        s.formula(f"{c}{R['ar']}", f"{c}{R['rev']}*{c}{R['d_ar']}/365")
        s.formula(f"{c}{R['inv']}", f"{c}{R['cogs']}*{c}{R['d_inv']}/365")
        s.formula(f"{c}{R['ap']}", f"{c}{R['cogs']}*{c}{R['d_ap']}/365")
        s.formula(f"{c}{R['nwc']}", f"{c}{R['ar']}+{c}{R['inv']}-{c}{R['ap']}")
        if j == 0:
            s.formula(f"{c}{R['dnwc']}", f"{c}{R['nwc']}")      # 첫해=기초NWC(0) 대비; 기초 있으면 입력 차감
        else:
            s.formula(f"{c}{R['dnwc']}", f"{c}{R['nwc']}-{cols[j-1]}{R['nwc']}")
    return s


# ── W5 Peer (유사회사 4-step 퍼널 + Hamada 무부채화) ──────────────────────────
def build_peer(wb, n: int = 5):
    """W5 유사회사 선정 — 4-step 퍼널(peer.py 게이트) + 확정 peer 무부채화(Hamada 살아있는 수식).

    정본: 할인율서식 §1(Step0~3)·참고 모델 §E(83→11→9→6). Step2(사업유사성)만 판단,
    나머지(코드·비중·베타포인트·거래정지) 결정론. 확정 peer 평균 βu·자본구조 → WACC 시트."""
    s = wb.add_sheet("Peer")
    _header(s, "Peer — 유사회사 선정 4-step + 무부채화 (peer.py 미러)")
    s.text("B3", "Step1 모집단(KSIC) → Step2 사업유사성[판정·사유] → Step3 매출비중≥70% "
                 "→ Step4 상장≥2년(베타포인트)·거래정지. peer.py 결정론(Step2만 판단).")

    # ── ① 4-step 퍼널 (후보 → 생존) ──
    s.text("B5", "── ① 4-step 퍼널 (후보 → 생존; peer.py 실행) ──")
    for col, h in zip("BCDEFGHIJ",
                      ["회사", "Ticker", "KSIC", "관련매출%", "상장연수", "거래정지",
                       "판정(유사/비유사/애매)", "사유", "생존스텝"]):
        s.text(f"{col}6", h)
    cand_first, cand_n = 7, 5
    for i in range(cand_n):                               # 후보 placeholder 5행
        s.text(f"B{cand_first + i}", "[후보]")
    cand_last = cand_first + cand_n - 1
    s.text("B13", "게이트: peer.py — Step1 코드매칭·Step2 판정완비(사유)·Step3 비중≥70%·"
                  "Step4 상장≥2Y/거래정지. uncertain→⚖️큐(자동탈락 금지). 5-10 rule(확정 5~10사).")

    # ── ② 확정 peer 무부채화 (Hamada 살아있는 수식) ──
    # ⚠️ ①의 값을 손으로 옮겨 적지 않는다 — **2차원 INDEX/MATCH**(행=티커, 열=필드명)로
    # 조회한다. 열 순서가 바뀌어도 깨지지 않고, ① 수정이 ②에 자동 반영된다(단일 진실원).
    # 근거: 모델러스_통합모델_5.4 §2.4(a) — rTrading 원자료를 전부 이 패턴으로 참조.
    s.text("B15", "── ② 확정 peer 무부채화 (Hamada: βu = βL/(1+(1-t)·D/E)) ──")
    for col, h in zip("BCDEFGHI",
                      ["Ticker", "회사", "세율 t", "D/Cap", "E/Cap", "D/E",
                       "Levered β", "Unlevered β"]):
        s.text(f"{col}16", h)          # ⚠️ 헤더 문자열이 곧 조회 키 — ①의 헤더와 **정확히**
                                       # 같아야 MATCH 가 걸린다("회사(①조회)" 같은 장식 금지)
    s.text("B14", "② 회사명은 ①에서 2차원 INDEX/MATCH 로 조회한다(손으로 옮겨적기 금지).")
    unl_first, unl_n = 17, 4
    tbl, key_col, hdr = f"$B$6:$J${cand_last}", f"$C$6:$C${cand_last}", "$B$6:$J$6"
    for i in range(unl_n):
        rr = unl_first + i
        s.text(f"B{rr}", "[확정 peer Ticker]")             # ①에서 확정된 회사의 티커만 입력
        # 행=티커 매칭, 열=필드명 매칭 → 열 위치에 의존하지 않는 조회
        s.formula(f"C{rr}", f'INDEX({tbl},MATCH($B{rr},{key_col},0),MATCH(C$16,{hdr},0))')
        s.formula(f"G{rr}", f"E{rr}/F{rr}")                # D/E = D/Cap ÷ E/Cap (live)
        s.formula(f"I{rr}", f"H{rr}/(1+(1-D{rr})*G{rr})")  # Hamada 무부채화 (live)
    unl_last = unl_first + unl_n - 1
    avg = unl_last + 1
    s.text(f"B{avg}", "평균 (→ WACC)")
    for col in ("E", "F", "I"):                            # D/Cap·E/Cap·βu 평균
        s.formula(f"{col}{avg}", f"AVERAGE({col}{unl_first}:{col}{unl_last})")
    s.text(f"B{avg + 2}", "→ WACC: 무부채β=I평균, 목표자본구조=D/E(=E평균÷F평균). "
                          "β 2Y weekly 조정베타(adj=⅔·raw+⅓).")
    return s


# ── W5 WACC (CAPM 빌드업) ─────────────────────────────────────────────────────
def build_wacc(wb, n: int = 5):
    """W5 WACC — 재부채화(Hamada) → CAPM Ke/Kd → WACC. 살아있는 수식.

    무부채β·목표자본구조는 Peer 시트 확정 peer 평균에서 입력. 입력셀([입력])을 채우면
    재부채화·Ke·Kd·WACC 수식이 즉시 계산된다. 출처: wacc_할인율서식 빌드업 F19~F42."""
    s = wb.add_sheet("WACC")
    _header(s, "WACC — CAPM 빌드업 (재부채화 → Ke/Kd → WACC)")
    s.text("B3", "무부채β·목표자본구조=Peer 확정 peer 평균에서 입력. "
                 "Ke=Rf+βL·MRP+size+CRP+CSRP, WACC=We·Ke+Wd·Kd·(1-t). → DCF!C3.")

    # ── CAPM 빌드업 (입력=[입력], 나머지 살아있는 수식) ──
    s.text("B5", "── CAPM 빌드업 ──")
    b = 6

    def cc(off: int) -> str:
        return f"C{b + off}"

    items = [
        ("무부채 β (Peer 평균 βu)", None, "[입력·Peer!평균]"),
        ("목표 D/E (Peer 평균 D/E)", None, "[입력·Peer!평균]"),
        ("세율 t", None, "[입력]"),
        ("재부채화 βL = βu·(1+(1-t)·D/E)", f"{cc(0)}*(1+(1-{cc(2)})*{cc(1)})"),
        ("무위험이자율 Rf", None, "[입력·국고채(Bloomberg)]"),
        ("시장위험프리미엄 MRP", None, "[입력·한공회 8%]"),
        ("size premium", None, "[입력·Kroll decile]"),
        ("국가위험프리미엄 CRP", None, "[입력·Damodaran]"),
        ("기업특유위험 CSRP", None, "[입력·판단(보통 0)]"),
        ("자기자본비용 Ke = Rf+βL·MRP+size+CRP+CSRP",
         f"{cc(4)}+{cc(3)}*{cc(5)}+{cc(6)}+{cc(7)}+{cc(8)}"),
        ("세전 부채비용 Kd", None, "[입력·신용등급 회사채]"),
        ("세후 Kd = Kd·(1-t)", f"{cc(10)}*(1-{cc(2)})"),
        ("자기자본 비중 We = 1/(1+D/E)", f"1/(1+{cc(1)})"),
        ("타인자본 비중 Wd = D/E/(1+D/E)", f"{cc(1)}/(1+{cc(1)})"),
        ("WACC = We·Ke + Wd·Kd_at  (→ DCF!C3)", f"{cc(12)}*{cc(9)}+{cc(13)}*{cc(11)}"),
    ]
    for i, item in enumerate(items):
        rr = b + i
        s.text(f"B{rr}", item[0])
        if item[1] is None:
            s.text(f"C{rr}", item[2])
        else:
            s.formula(f"C{rr}", item[1])

    # ── β·MRP provenance (같은 시장에서 와야 — checks β/MRP 정합) ──
    r = b + len(items) + 1
    s.text(f"B{r}", "── β·MRP provenance (β 와 MRP 는 같은 시장에서) ──")
    r += 1
    for lbl in ("β 출처 (bloomberg/kicpa)", "β 기준시장 (SP500/KOSPI/KOSDAQ)",
                "β 조정 (Bloomberg adj = ⅔·raw+⅓)", "MRP 출처 (kicpa/damodaran)",
                "MRP 기준시장 (= β 기준시장 일치)"):
        s.text(f"B{r}", lbl)
        s.text(f"C{r}", "[입력]")
        r += 1
    s.text(f"B{r}", "게이트: β/MRP 시장 정합·β provenance, WACC 8~14% (wacc.py 검증)")
    return s



# ── W6b Model (3표 완전연결 — 정합성 검증) ────────────────────────────────────
# 열 배치: C=기초(실적, FS_Hist 참조) / D.. = 추정연도. 실무 3표 모델처럼 **기초 열**을
# 두어야 롤포워드(기말=기초+증감)가 첫 해부터 같은 수식으로 떨어진다.
_MODEL_COLS = "CDEFGHIJKLMNOP"


def build_model_3s(wb, n: int = 5):
    """W6b 3표 연결 — IS·BS·CF + 부채/이익잉여금/이자 스케줄 + CHECK 행(살아있는 수식).

    목적은 밸류에이션이 아니라 **조립 배관 검증**이다. 우리 DCF 는 무차입 FCFF 라 3표가
    가치산정엔 불필요하지만, `자산=부채+자본`·`Δ현금=CFO+CFI+CFF` 항등식이 FA·WC·원가
    조립의 정합성을 잡아준다. **차액을 '대차조정'으로 메우지 않는다** — 메우는 순간
    검증기가 죽는다.

    ⭐ 순환참조: `이자수익 → 순이익 → 현금 → 이자부자산 → 이자수익`.
    C5 의 **Circuit Switch** 로 통제한다(모델러스 정본 `IF($L$5="ON", 스케줄, 0)` 재현).
    엑셀에서는 스위치 ON + `파일 > 옵션 > 수식 > 반복 계산 사용` 이 필요하다.
    ⚠️ 엔진(`calc_core.three_statement`)은 반복계산 옵션 없이 **고정점 반복을 직접 돌려
    수렴을 검증**한다 — 워크북은 표현, 검증은 엔진이 정본이다.
    """
    s = wb.add_sheet("Model")
    _header(s, "Model — 3표 완전연결 (IS·BS·CF) + 정합성 CHECK")
    s.text("B3", "목적=조립 배관 검증(가치산정 아님). 잔차는 플러그 없이 그대로 노출한다.")
    s.text("B4", "이자=평균잔액 기준(기본·더 정확 — 연중 잔액 변화를 담는다). 순환 발생 → 스위치로 통제.")
    s.text("B5", "Circuit Switch :")
    s.text("C5", "ON")
    s.text("D5", "OFF 면 이자수익 0 → 순이익 과소. 진단·대조용이며 최종 산출에 쓰지 말 것.")
    s.text("B6", "⚠️ 엑셀: 스위치 ON 시 [파일>옵션>수식>반복 계산 사용] 필요. "
                 "엔진은 불요(고정점 반복 내장·수렴 검증).")

    op = _MODEL_COLS[0]                    # 기초(실적) 열
    cols = list(_MODEL_COLS[1:1 + n])      # 추정연도 열
    R = {}
    r = 8

    s.text(f"B{r}", "── [손익계산서] ──")
    s.text(f"{op}{r}", "기초/실적")
    for j, c in enumerate(cols):
        s.text(f"{c}{r}", f"{j + 1}년차")
    r += 1

    def line(key, label, indent=False):
        nonlocal r
        R[key] = r
        s.text(f"B{r}", ("  " if indent else "") + label)
        r += 1

    line("rev", "매출액 (→Fcst_Rev 계)")
    line("cogs", "(−) 매출원가 (→Fcst_Cost 계)", True)
    line("sga", "(−) 판매관리비 (→Fcst_Cost 계)", True)
    line("ebit", "영업이익 EBIT")
    line("ii", "(+) 이자수익  [순환 — 스위치 통제]", True)
    line("ie", "(−) 이자비용  [부채 스케줄]", True)
    line("ebt", "세전이익 EBT")
    line("tax", "(−) 법인세  [입력 또는 세율×EBT]", True)
    line("ni", "당기순이익")
    r += 1

    s.text(f"B{r}", "── [재무상태표] ──"); r += 1
    line("cash", "현금및현금성자산", True)
    line("sti", "단기금융자산 (이자부·NOA)", True)
    line("nwc", "순운전자본 (→WC 시트)", True)
    line("fa", "순유형자산 (→Capex_Dep 기말)", True)
    line("oa", "기타자산", True)
    line("ta", "자산 계")
    line("debt", "이자부부채 (→부채 스케줄)", True)
    line("ol", "기타부채", True)
    line("tl", "부채 계")
    line("cap", "자본금·자본잉여금", True)
    line("re", "이익잉여금 (→RE 스케줄)", True)
    line("oe", "기타자본", True)
    line("te", "자본 계")
    line("chk_bs", "CHECK 대차 (자산 − 부채 − 자본)")
    r += 1

    s.text(f"B{r}", "── [현금흐름표] ──"); r += 1
    line("cfo_ni", "당기순이익", True)
    line("cfo_da", "(+) 감가상각비 (비현금·→Capex_Dep)", True)
    line("cfo_wc", "(−) 순운전자본 증가", True)
    line("cfo", "영업활동 현금흐름 CFO")
    line("capex", "(−) CAPEX (→Capex_Dep)", True)
    line("cfi", "투자활동 현금흐름 CFI")
    line("iss", "(+) 차입 발행", True)
    line("rep", "(−) 차입 상환", True)
    line("div", "(−) 배당", True)
    line("cff", "재무활동 현금흐름 CFF")
    line("dcash", "현금 순증감")
    line("chk_cf", "CHECK 현금연결 (Δ현금 − CF합)")
    r += 1

    s.text(f"B{r}", "── [보조 스케줄] ──"); r += 1
    line("d_avg", "부채 평균잔액 = AVERAGE(기초,기말)", True)
    line("d_rate", "차입 이자율", True)
    line("re_roll", "이익잉여금 기말 = 기초 + NI − 배당", True)
    line("chk_re", "CHECK 이익잉여금 롤포워드")
    line("iba", "이자부자산 = 현금 + 단기금융", True)
    line("iba_avg", "이자부자산 평균잔액 = AVERAGE(기초,기말)", True)
    line("c_rate", "예금 이자율", True)
    note_row = r

    # ── 기초(실적) 열: 잔액 항목만 [참조] placeholder ──
    for key in ("cash", "sti", "nwc", "fa", "oa", "debt", "ol", "cap", "re", "oe"):
        s.text(f"{op}{R[key]}", "[참조·FS_Hist]")
    s.formula(f"{op}{R['ta']}", f"SUM({op}{R['cash']}:{op}{R['oa']})")
    s.formula(f"{op}{R['tl']}", f"SUM({op}{R['debt']}:{op}{R['ol']})")
    s.formula(f"{op}{R['te']}", f"SUM({op}{R['cap']}:{op}{R['oe']})")
    s.formula(f"{op}{R['iba']}", f"{op}{R['cash']}+{op}{R['sti']}")

    # ── 추정연도 살아있는 수식 ──
    for j, c in enumerate(cols):
        p = op if j == 0 else cols[j - 1]        # 직전 열(첫 해는 기초 열)

        def C(key, col=c):
            return f"{col}{R[key]}"

        def P(key):
            return f"{p}{R[key]}"

        # IS
        s.formula(C("ebit"), f"{C('rev')}-{C('cogs')}-{C('sga')}")
        # 순환 스위치 — OFF 면 이자수익 0
        s.formula(C("ii"), f'IF($C$5="ON",{C("iba_avg")}*{C("c_rate")},0)')
        s.formula(C("ie"), f"{C('d_avg')}*{C('d_rate')}")
        s.formula(C("ebt"), f"{C('ebit')}+{C('ii')}-{C('ie')}")
        s.formula(C("ni"), f"{C('ebt')}-{C('tax')}")

        # BS — 롤포워드가 첫 해부터 같은 수식(기초 열 덕분)
        s.formula(C("cash"), f"{P('cash')}+{C('dcash')}")
        s.formula(C("fa"), f"{P('fa')}+{C('capex')}-{C('cfo_da')}")
        s.formula(C("debt"), f"{P('debt')}+{C('iss')}-{C('rep')}")
        s.formula(C("re"), f"{C('re_roll')}")
        s.formula(C("ta"), f"SUM({C('cash')}:{C('oa')})")
        s.formula(C("tl"), f"SUM({C('debt')}:{C('ol')})")
        s.formula(C("te"), f"SUM({C('cap')}:{C('oe')})")

        # CF
        s.formula(C("cfo_ni"), C("ni"))
        s.formula(C("cfo_wc"), f"-({C('nwc')}-{P('nwc')})")
        s.formula(C("cfo"), f"SUM({C('cfo_ni')}:{C('cfo_wc')})")
        s.formula(C("cfi"), f"-{C('capex')}")
        s.formula(C("cff"), f"{C('iss')}-{C('rep')}-{C('div')}")
        s.formula(C("dcash"), f"{C('cfo')}+{C('cfi')}+{C('cff')}")

        # 스케줄
        s.formula(C("d_avg"), f"AVERAGE({P('debt')},{C('debt')})")
        s.formula(C("re_roll"), f"{P('re')}+{C('ni')}-{C('div')}")
        s.formula(C("iba"), f"{C('cash')}+{C('sti')}")
        s.formula(C("iba_avg"), f"AVERAGE({P('iba')},{C('iba')})")

    # ── CHECK 행(허용오차 — 정확일치 금지) ──
    _check_row(s, R["chk_bs"], "CHECK 대차 (자산 − 부채 − 자본)",
               "{col}" + str(R["ta"]),
               "{col}" + str(R["tl"]) + "+{col}" + str(R["te"]), n, cols=cols)
    _check_row(s, R["chk_cf"], "CHECK 현금연결 (Δ현금 − CF합)",
               "{col}" + str(R["dcash"]),
               "{col}" + str(R["cfo"]) + "+{col}" + str(R["cfi"]) + "+{col}" + str(R["cff"]),
               n, cols=cols)
    _check_row(s, R["chk_re"], "CHECK 이익잉여금 롤포워드",
               "{col}" + str(R["re"]), "{col}" + str(R["re_roll"]), n, cols=cols)

    s.text(f"B{note_row + 1}",
           "기초 열(C)=FS_Hist 실적 [참조]. 기초 BS 가 스스로 대차가 맞아야 한다 — "
           "안 맞으면 그 불균형이 전 추정기간에 상수로 지속된다.")
    s.text(f"B{note_row + 2}",
           "⚠️ 대차는 D&A·CAPEX 오류를 흡수한다(CFO+ 와 FA롤− 로 상쇄) — 대차 TRUE 를 "
           "'모델이 맞다'로 읽지 말 것. 그 대사는 엔진 checks.check_three_statement_vs_spine 담당.")
    return s


STAGE_BUILDERS = {
    "W1": [build_research, build_assumption],
    "W2": [build_fs_hist],
    "W2.5": [build_fs_disagg],
    "W3": [build_reclass],
    "W4": [build_fcst_rev, build_fcst_cost, build_capex_dep, build_wc],
    "W5": [build_peer, build_wacc],
    "W6B": [build_model_3s],
}


def build_stage(wb, stage: str, n: int = 5) -> list[str]:
    """stage(W1~W5, W2.5, W6b) 시트 뼈대를 wb 에 추가. 생성된 시트명 리스트 반환."""
    builders = STAGE_BUILDERS.get(stage.upper())
    if not builders:
        raise ValueError(f"알 수 없는 단계: {stage} (W1~W5, W2.5, W6b)")
    return [b(wb, n).name for b in builders]
