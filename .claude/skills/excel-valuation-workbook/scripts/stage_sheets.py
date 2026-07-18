"""단계별 시트 뼈대 생성기 (W1~W5) — 풀모델 점진 성장.

각 단계에 해당 시트의 뼈대(제목·범례·라벨·입력 placeholder·타시트 참조 스텁)를
결정론으로 찍는다. Claude 는 이 뼈대를 근거·수식으로 채운다(판단·값은 평가인).
색상은 xlsx 에 API 가 없어 **범례 텍스트로 규약을 명시**(Blue 입력/Black 수식/Green 타시트).

vendor/excel.Workbook 사용(자기완결). scaffold.py 가 --stage 로 호출.
"""
from __future__ import annotations

# 셀 레이아웃·세분 롤업 위계는 vendored template_schema SSOT 를 소비(자체 복사 금지).
# scaffold.py 가 _bootstrap 로 vendor 를 path 에 올린 뒤 stage_sheets 를 import 한다.
from excel.template_schema import DISAGG_BLOCKS, FCST, ROLLUP, YEAR_COLS

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


def _header(s, title: str) -> None:
    s.text("B1", title)
    s.text("B2", _LEGEND)


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


# ── W5 Peer (유사회사 4-step 퍼널 + Hamada 무부채화) ──────────────────────────
def build_peer(wb, n: int = 5):
    """W5 유사회사 선정 — 4-step 퍼널(peer.py 게이트) + 확정 peer 무부채화(Hamada 살아있는 수식).

    정본: 할인율서식 §1(Step0~3)·MSVALUE §E(83→11→9→6). Step2(사업유사성)만 판단,
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
    for i in range(5):                                    # 후보 placeholder 5행
        s.text(f"B{7 + i}", "[후보]")
    s.text("B13", "게이트: peer.py — Step1 코드매칭·Step2 판정완비(사유)·Step3 비중≥70%·"
                  "Step4 상장≥2Y/거래정지. uncertain→⚖️큐(자동탈락 금지). 5-10 rule(확정 5~10사).")

    # ── ② 확정 peer 무부채화 (Hamada 살아있는 수식) ──
    s.text("B15", "── ② 확정 peer 무부채화 (Hamada: βu = βL/(1+(1-t)·D/E)) ──")
    for col, h in zip("BCDEFGH",
                      ["회사", "세율 t", "D/Cap", "E/Cap", "D/E", "Levered β", "Unlevered β"]):
        s.text(f"{col}16", h)
    unl_first, unl_n = 17, 4
    for i in range(unl_n):
        rr = unl_first + i
        s.text(f"B{rr}", "[확정 peer]")                   # ①에서 확정된 회사
        s.formula(f"F{rr}", f"D{rr}/E{rr}")               # D/E = D/Cap ÷ E/Cap (live)
        s.formula(f"H{rr}", f"G{rr}/(1+(1-C{rr})*F{rr})")  # Hamada 무부채화 (live)
    unl_last = unl_first + unl_n - 1
    avg = unl_last + 1
    s.text(f"B{avg}", "평균 (→ WACC)")
    for col in ("D", "E", "H"):                            # D/Cap·E/Cap·βu 평균
        s.formula(f"{col}{avg}", f"AVERAGE({col}{unl_first}:{col}{unl_last})")
    s.text(f"B{avg + 2}", "→ WACC: 무부채β=H평균, 목표자본구조=D/E(=D평균÷E평균). "
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


STAGE_BUILDERS = {
    "W1": [build_research],
    "W2": [build_fs_hist],
    "W2.5": [build_fs_disagg],
    "W3": [build_reclass],
    "W4": [build_fcst_rev, build_fcst_cost, build_capex_dep, build_wc],
    "W5": [build_peer, build_wacc],
}


def build_stage(wb, stage: str, n: int = 5) -> list[str]:
    """stage(W1~W5, W2.5) 시트 뼈대를 wb 에 추가. 생성된 시트명 리스트 반환."""
    builders = STAGE_BUILDERS.get(stage.upper())
    if not builders:
        raise ValueError(f"알 수 없는 단계: {stage} (W1~W5, W2.5)")
    return [b(wb, n).name for b in builders]
