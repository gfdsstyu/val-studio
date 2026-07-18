"""단계별 시트 뼈대 생성기 (W1~W5) — 풀모델 점진 성장.

각 단계에 해당 시트의 뼈대(제목·범례·라벨·입력 placeholder·타시트 참조 스텁)를
결정론으로 찍는다. Claude 는 이 뼈대를 근거·수식으로 채운다(판단·값은 평가인).
색상은 xlsx 에 API 가 없어 **범례 텍스트로 규약을 명시**(Blue 입력/Black 수식/Green 타시트).

vendor/excel.Workbook 사용(자기완결). scaffold.py 가 --stage 로 호출.
"""
from __future__ import annotations

# 셀 레이아웃·세분 롤업 위계는 vendored template_schema SSOT 를 소비(자체 복사 금지).
# scaffold.py 가 _bootstrap 로 vendor 를 path 에 올린 뒤 stage_sheets 를 import 한다.
from excel.template_schema import DISAGG_BLOCKS, YEAR_COLS

_LEGEND = "범례: [입력]=파랑(hard) · [수식]=검정 · [참조]=초록(타시트) · 핵심가정=노랑fill"


def _years(s, row: int, n: int, base_year: int = 2024) -> None:
    s.text(f"B{row}", "Year")
    for j, c in enumerate(YEAR_COLS[:n]):
        s.num(f"{c}{row}", base_year + j)


def _header(s, title: str) -> None:
    s.text("B1", title)
    s.text("B2", _LEGEND)


# ── W1 Research ──────────────────────────────────────────────────────────────
def build_research(wb, n: int = 5):
    s = wb.add_sheet("Research")
    _header(s, "Research — Company Brief + 리서치 SSOT")
    sections = [
        "①Summary(투자포인트)", "②회사개요(주주·유통비율·신용등급)", "③자회사 지분·구조",
        "④사업부문·제품 매출·비중", "⑤주요 제품(향처·점유율)", "⑥Value Chain",
        "⑦고객사·경쟁사", "⑧시장 분석(규모·성장)", "⑨경쟁사 밸류에이션", "⑩전방 전망+Financials",
    ]
    for i, sec in enumerate(sections, start=4):
        s.text(f"B{i}", sec)
        s.text(f"C{i}", "[서사: 출처 URL 병기 — Claude 채움, 평가인 확정]")
    # 하류가 참조하는 숫자 가정 블록(파랑 입력)
    base = 4 + len(sections) + 1
    s.text(f"B{base}", "── 리서치 숫자 가정(하류 시트 참조 대상) ──")
    nums = ["시장 CAGR", "목표 시장점유율", "매출채권 회전일", "재고 회전일", "매입채무 회전일"]
    for i, k in enumerate(nums, start=base + 1):
        s.text(f"B{i}", k)
        s.text(f"C{i}", "[입력]")
    return s


# ── W2 FS_Hist (Raw / Normalized / Map) ──────────────────────────────────────
def build_fs_hist(wb, n: int = 5):
    s = wb.add_sheet("FS_Hist")
    _header(s, "FS_Hist — 과거 재무제표(원본 불변 / 정규화 / 매핑)")
    s.text("B4", "── ① Raw(붙여넣기 원문, 불변) ──")
    s.text("B5", "[여기에 사업보고서 FS 원문을 그대로 붙여넣기]")
    s.text("B8", "── ② Normalized(fs_clean.py 정규화 결과) ──")
    _years(s, 9, n)
    for i, lbl in enumerate(["매출액", "매출원가", "판관비", "자산총계", "부채총계", "자본총계"], start=10):
        s.text(f"B{i}", lbl)
    row = 18
    s.text(f"B{row}", "── ③ Map(계정 이관·매핑 대장) ──")
    for col, h in zip("BCDEF", ["원계정", "표준계정", "이관연도", "금액", "상태(확정/미해결)"]):
        s.text(f"{col}{row + 1}", h)
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
        s.text(f"B{r}", f"계 (= FS_Hist!{parent}) [수식·합보존]")
        s.text(f"B{r + 1}", "구성비(%) [수식]")
        row = r + 3                        # 블록 간 1행 여백
    return s


# ── W3 Reclass (평가목적 재분류 + _A/_F) ──────────────────────────────────────
def build_reclass(wb, n: int = 5):
    s = wb.add_sheet("Reclass")
    _header(s, "Reclass — 평가목적 재분류(Valuation B/S)")
    s.text("B4", "PL 4유형: Sales / COGS / SGA / NO(영업외)")
    s.text("B5", "BS 6유형: WC / FA / NOA(비영업자산) / IBD(이자부채) / OAL / EQU")
    s.text("B6", "⚠️ 현금(최소영업=WC vs 잉여=NOA)·이연법인세 경계는 평가인 판단")
    row = 8
    for col, h in zip("BCDEF", ["표준계정", "평가유형", "_A(실사조정)", "_F(최종)", "근거"]):
        s.text(f"{col}{row}", h)
    return s


# ── W4 추정 4시트 ────────────────────────────────────────────────────────────
def build_fcst_rev(wb, n: int = 5):
    s = wb.add_sheet("Fcst_Rev")
    _header(s, "Fcst_Rev — 매출 추정(드라이버=평가인 선택)")
    s.text("B4", "드라이버 선택: 성장률 / 시장점유율 / P×Q / 결합 — [평가인 판단]")
    s.text("B5", "근거: Research!(시장 CAGR·목표점유율) 참조(초록)")
    _years(s, 7, n)
    s.text("B8", "드라이버 값")
    s.text("B9", "매출(→ DCF!매출 행 참조 대상)")
    return s


def build_fcst_cost(wb, n: int = 5):
    s = wb.add_sheet("Fcst_Cost")
    _header(s, "Fcst_Cost — 원가·판관비(성격별)")
    _years(s, 4, n)
    for i, lbl in enumerate(
        ["변동비(매출 연동)", "고정비(CPI 연동)", "인건비(임금상승률)", "상각비(FA 연동)",
         "매출원가 계", "판관비 계"], start=5):
        s.text(f"B{i}", lbl)
    return s


def build_capex_dep(wb, n: int = 5):
    s = wb.add_sheet("Capex_Dep")
    _header(s, "Capex_Dep — CAPEX 계획 + 상각 스케줄")
    _years(s, 4, n)
    for i, lbl in enumerate(
        ["CAPEX(계획)", "기초 유형자산", "당기 상각", "기말 유형자산",
         "→ DCF!CAPEX 참조", "→ DCF!D&A 참조"], start=5):
        s.text(f"B{i}", lbl)
    return s


def build_wc(wb, n: int = 5):
    s = wb.add_sheet("WC")
    _header(s, "WC — 운전자본(회전일 기반)")
    _years(s, 4, n)
    for i, lbl in enumerate(
        ["매출채권(회전일→잔액)", "재고자산", "매입채무", "순운전자본(NWC)",
         "ΔNWC(→ DCF!ΔNWC 참조)"], start=5):
        s.text(f"B{i}", lbl)
    s.text("B11", "회전일 근거: Research!(회전일 가정) 참조(초록)")
    return s


# ── W5 WACC (CAPM 빌드업) ─────────────────────────────────────────────────────
def build_wacc(wb, n: int = 5):
    s = wb.add_sheet("WACC")
    _header(s, "WACC — CAPM 빌드업")
    rows = [
        ("무위험이자율 Rf", "[입력]"), ("무부채 베타 βu", "[입력·peer 평균]"),
        ("목표 D/E", "[입력]"), ("세율 t", "[입력]"),
        ("재부채화 베타 βL", "[수식: Hamada]"), ("시장위험프리미엄 ERP", "[입력]"),
        ("size premium", "[입력·Kroll 제안]"), ("자기자본비용 Ke", "[수식: Rf+βL·ERP+size]"),
        ("세전 부채비용 Kd", "[입력]"), ("세후 Kd", "[수식: Kd·(1-t)]"),
        ("자기자본 비중", "[수식]"), ("타인자본 비중", "[수식]"),
        ("WACC (→ DCF!C3 참조)", "[수식]"),
    ]
    for i, (lbl, hint) in enumerate(rows, start=4):
        s.text(f"B{i}", lbl)
        s.text(f"C{i}", hint)
    s.text(f"B{4 + len(rows) + 1}", "게이트: β/ERP 시장 정합·provenance, WACC 8~14% (wacc.py 검증)")
    return s


STAGE_BUILDERS = {
    "W1": [build_research],
    "W2": [build_fs_hist],
    "W2.5": [build_fs_disagg],
    "W3": [build_reclass],
    "W4": [build_fcst_rev, build_fcst_cost, build_capex_dep, build_wc],
    "W5": [build_wacc],
}


def build_stage(wb, stage: str, n: int = 5) -> list[str]:
    """stage(W1~W5, W2.5) 시트 뼈대를 wb 에 추가. 생성된 시트명 리스트 반환."""
    builders = STAGE_BUILDERS.get(stage.upper())
    if not builders:
        raise ValueError(f"알 수 없는 단계: {stage} (W1~W5, W2.5)")
    return [b(wb, n).name for b in builders]
