---
name: excel-valuation-workbook
description: Excel 워크북 위에서 DCF 기업가치평가 워크플로우를 수행·검증한다. 템플릿 인식/생성,
  기업 리서치, 과거 재무제표 정합성 검증·이관, 계정재분류, 매출·원가 추정, WACC 산정, DCF 계산,
  시나리오·민감도, 리포트까지. **판단(계정분류·가정·드라이버)은 평가인, 계산·검증은 결정론
  scripts/ 도구**. 빈 시트에서 시작하면 수식 live 템플릿을 생성하고, 단계마다 시트를 더해 풀모델로
  키운다. Excel 워크북·재무제표·DCF 모델·외부평가의견서 작업 시 사용.
---

# Excel 밸류에이션 워크플로우 (DCF)

## 핵심 원칙 — 역할 3분할

**제안(Claude) → 판단(평가인) → 검증(결정론 코드).** 이 순서를 절대 뒤섞지 않는다.

- **Claude(이 스킬)**: 기계적 작업(FS 정규화·시트 생성·수식 구현) + 지식기반 제안(계정분류안·드라이버 후보·가정 근거) + 리서치. **애매하면 단정하지 않고 표면화**한다.
- **평가인(사용자)**: 판단·확정. 재분류 승인, 매출 드라이버 선택, 가정값 확정, 자료 투입.
- **결정론 도구(`scripts/`)**: 계산·검증. 골든 재현, audit 룰(PGR≤GDP·TV비중·β/MRP), tie-out. **암산·추정 금지** — 숫자는 반드시 scripts/ 로.

> **가정은 추천만, 판단은 평가인.** 매출추정 드라이버·계정 영업성 판정·가정값은 전부 평가인 몫. Claude는 후보 제시·근거 리서치·선택된 로직의 수식 구현만.

---

## 이중 환경 (계산·검증 방식)

| 환경 | 계산·검증 | 워크북 반영 |
|------|-----------|-------------|
| **Claude for Excel** | `scripts/` 실행 가능하면 사용, 불가하면 지시문-only 폴백 | 셀 직접 기입(색상·수식 규약) |
| **Claude Code / claude.ai** | `scripts/` 실행 (파일 경로) | xlsx 생성·수정(`scaffold.py`) |

**지시문-only 폴백**: scripts 실행 불가 시 references 계산 규약으로 검산하되, 산출물에 **"결정론 미검증"** 라벨을 남기고 로컬 검증을 권고한다.

**리서치 데이터 경로 (런타임 의존)**:
- **Claude for Excel**: 범용 웹검색 없음. 외부 데이터는 ① MCP 커넥터(FactSet·S&P·Moody's 등, Claude 설정) ② 사용자 붙여넣기·업로드로만. **웹검색을 가정하지 말고 가용 소스만 사용·명시.**
- **Claude Code / claude.ai**: 웹검색 사용 가능.
- 방법론 지식(`scripts/vendor/reference/`)은 오프라인이라 항상 사용 가능.

---

## 시작 모드 판별 (W0)

워크북을 읽고 분기한다:

| 모드 | 감지 | 동작 |
|------|------|------|
| **A. 자기 템플릿** | `_VS_STATE` 시트 존재 | 상태 읽고 중단 지점부터 재개 |
| **B. 백지** | 빈 시트/Sheet1만 | 입력 수집 → `scaffold.py`로 수식 live DCF 스파인 생성 |
| **C. 타 템플릿** | 기존 임의 모델 | 구조 파악·셀맵 작성·확인 후 진행. **원본 수식 변경 금지**, `_A/_F` 조정 레이어 |

**B모드 스캐폴딩**: `scaffold.py`로 시작(가정 블록+5개년 스파인+계단식 법인세+결과, 전부 살아있는 수식). Claude Code면 `--xlsx out.xlsx`, Claude for Excel이면 `--emit-cells`로 셀 JSON을 받아 워크북에 기입. `_VS_STATE` 시트가 함께 생성된다.

---

## 점진 성장 풀모델 + 자체 시트 아키텍처

**끝까지 따라가면 풀모델이 완성된다** — 처음부터 멀티시트를 찍지 않고, 각 단계가 자기 시트를 만들며 워크북이 자란다.

| 단계 | 생성 시트 |
|------|-----------|
| W0 | `DCF`(스파인) + `_VS_STATE` |
| W1 | `Research`(10섹션)·`Assumption`(가정 SSOT) |
| W2 | `FS_Hist`(Raw/Normalized/Map) |
| W2.5 | `FS_Disagg`(손익 세분 + 합보존·구성비) |
| W3 | `Reclass`(`_A/_F` 레이어) |
| W4 | `Fcst_Rev`·`Fcst_Cost`(FS_Disagg 세분 롤업)·`Capex_Dep`·`WC` |
| W5 | `Peer`(유사회사 4-step 퍼널 + Hamada 무부채화)·`WACC`(빌드업) |
| W6~W8 | `DCF` 가정 상류참조 승격, **`Model`(3표 정합성, W6b)**, `Scenario`·`Sens` |

**정체성 원칙(중요)**: 시트명·레이아웃은 위 **자체 정의**를 따른다. **참고 모델(H_FS/EBIT/BackData 등) 시트명·레이아웃을 복제하지 않는다.** 참고 모델·타사 지식은 "무엇을 계산·검증할지"로만 쓴다. 규약은 `references/template_conventions.md`.

**단계 시트 뼈대 생성**: 각 단계에서 `scaffold.py --stage W1..W5`(및 `W2.5`)로 그 단계 시트의 뼈대(제목·범례·라벨·입력 placeholder·타시트 참조 스텁)를 결정론으로 찍고, 그 위에 값·수식·근거를 채운다. 뼈대가 색상·참조 규약을 강제하므로 손으로 시트를 그리는 것보다 일관되다. W1=Research·Assumption, W2=FS_Hist, W2.5=FS_Disagg, W3=Reclass, W4=Fcst_Rev·Fcst_Cost·Capex_Dep·WC, W5=Peer·WACC.

W4/W5 시트는 살아있는 수식: Capex_Dep(기말=기초+CAPEX−상각·정액 스케줄), WC(잔액=드라이버×회전일/365·ΔNWC 차분), Fcst_Cost(영업이익=매출−원가−판관비), Assumption 가정 SSOT를 하류가 Green 참조.

- 참조는 **셀 단위 비순환(DAG)**. 기본은 `뒤→앞`이나, 시트 A·B 가 서로를 참조해도 **참조되는 셀 집합이 분리**(과거열/추정열)되면 허용 — 시트 단위로만 읽으면 정당한 패턴을 오탐 금지한다. **셀 단위 순환은 금지**(3표 완결용 이자 순환만 예외, 명시적 차단기 필수 — FCFF DCF 는 무차입이라 원천 불요). 색상 3색: Blue(입력)/Black(수식)/Green(타시트) + 핵심가정 yellow.
- **원자료 격리**: 붙여넣은 외부자료는 `r` 접두 시트(`rFS`·`rPeer`·`rMacro`)에 **무수정** 보관, 모델 시트는 참조만.
- **CHECK 행 상시 검증**: 합보존·정합은 `=IF(ABS(좌−우)<0.001,"TRUE",좌−우)` 로 워크북에 상주(잔차 표시). **정확일치 비교 금지**(부동소수 노이즈로 맞는 연도가 FALSE).
- **가시 상태 헤더**(전 시트 I1:J3): Scenario·Target Price·Stage — `_VS_STATE` 는 숨김이라 사람이 못 본다.
- **hard number 승격(W6)**: 상류 시트가 생기면 DCF 스파인 입력셀(매출/원가/판관비)을 상류 참조(`=Fcst_Rev!C12` 등, Green)로 교체하고, **교체 전후 per_share 불변(tie-out)**을 `promote.py`로 검증(불일치 시 라인·연도 델타 표면화).

**Research 시트 = SSOT**: 붙여넣은 자료를 여기 정리(숫자=하류 수식 참조 대상, 서사=판단 맥락). MD Brief는 필요 시 여기서 뽑는 파생뷰(이중 유지 금지).

---

## 워크플로우 단계 + 확인 게이트

**end-to-end 일괄 빌드 금지.** 각 단계 산출물을 평가인에게 보여주고 확인받은 뒤 다음으로. 뒤 단계에서 발견된 앞 단계 오류는 전부 재작업이다.

| 단계 | 작업 | 결정론 게이트 | 지식(references/) |
|------|------|---------------|-------------------|
| **W0 시작** | 모드 판별·`scaffold.py` | `roundtrip.py` 왕복 재검증 | template_conventions |
| **W1 리서치** | Company Brief 초안(가용 소스만) | 필수 슬롯·출처 누락 검사 | 기업리서치_양식·참고보고서_활용 |
| **W2 과거 FS 정합성·무결성 + 이관** | `fs_clean.py`로 정규화·교차검증·재분류 추적 | FAIL 0·재분류 미해결 0·대차·tie-out | 모델링_실무_2강4강·account_dictionary |
| **W2.5 손익 계정 세분화** | ①주석 표(판관비 성격별·제조원가명세서)에서 성격별 금액 **추출** + W4 드라이버 제안 — `footnote_costs.py` → ②러프한 IS 라인을 성격별로 분해 검증 — `fs_disagg.py` | ①**Σ성격별=IS 표기(tie-out) FAIL 0**·카테고리 애매(감가상각 등)는 uncertain 표면화 → ②**세분합=원계정(합보존) FAIL 0**·구성비 YoY 급변 WARN | account_dictionary·모델링_실무_2강4강 |
| **W3 계정재분류** | PL 4유형·BS 6유형 태깅(모호는 표면화) — `reclass.py`로 파티션 검증 | **분류합=원본 FS합(FAIL 게이트)**·누락·중복·유형오류 0 | 계정분류·DCF_교육_정본 |
| **W4 추정** | 드라이버 후보 제시→선택분 수식 구현. **`Fcst_Rev`·`Fcst_Cost`는 FS_Disagg 세분 라인(제품/상품/용역, 재료/노무/경비, 급여/상각/광고)과 동일 성격 행 → `계=Σ세분` 살아있는 SUM 롤업 → DCF!매출/원가/판관비** | projection_smoothness·wc_burn·가정 출처 완비·**세분 계=원계정 롤업 일치** | 리포트예시·모델링_실무 |
| **W5 WACC** | **`peer.py` 유사회사 퍼널(Step0 자기제외 + 4-step)**(Step1 코드→Step2 유사성[판정]→Step3 비중≥70%→Step4 베타포인트·거래정지) → `Peer` 시트 Hamada 무부채화 → `wacc.py` 빌드업(Kroll size) | 퍼널 게이트(**대상 자기포함 거부**·무근거 판정 거부·uncertain→⚖️큐·5-10 rule)·β/MRP 정합·provenance·8~14% | wacc_할인율서식·베타·감사인검토·PGR·리포트예시 §E |
| **W6b 3표 정합성(선택)** | `scaffold.py --stage W6b` → `Model` 시트(IS·BS·CF + 부채·RE·이자 스케줄 + CHECK 행). 엔진 검증은 `three_statement.py` | **대차·현금연결·RE롤 잔차 0**(허용오차)·순환 수렴·**3표↔스파인 영업벡터 대사** | 모델링_워크플로우_기초 §7·앤트로픽_벤치마크 §2 |
| **W6 DCF** | 스파인 입력셀→Fcst 계 참조 승격(`promote.py`) + `dcf.py` 재계산 | **승격 tie-out(per_share 불변)**·워크북 vs 엔진 rel_tol 1e-6·audit 전규칙·gap_diagnosis | engine_spec·검증_클래시스 |
| **W7 시나리오** | `scenario.py`(구성=판단) → Scenario 시트. **두 패러다임 병행**: 가중 SUMPRODUCT(기대값) + `--switch` CHOOSE 단일선택(서사·발표). Base 기본규칙=과거 N년 평균(평균회귀), Up/Down=절대 %p 가감 + 폭을 메모열에 기록 | 가중치 완전일치·합=1 | 리포트예시 부록F |
| **W8 민감도** | `sensitivity.py`로 WACC×PGR 5×5 살아있는 수식 그리드(셀마다 독립 DCF 재계산) | 워크북 중심 == 엔진 3×3 중심 == base·(설치 시)recalc 게이트 | 앤트로픽_금융스킬_벤치마크 §1 |
| **W9 리포트(선택)** | 주요가정 표·차이 서사 | audit findings 누락 없이 반영 · **`lint_report.py` 표현 가드**(근거 없는 단정·순환설명·무설명·뭉뚱그리기·**허위정밀 반올림**·Driver/Outlook/Action 공란) | 리포트예시·장표_작성법·앤트로픽_금융스킬_벤치마크 §4 |

**게이트 공통**: `앤트로픽_금융스킬_벤치마크.md §2`(audit-xls — BS부터·하드코딩 오버라이드·DCF 버그 5종).

> **⚠️ W2/W2.5/W3은 같은 과거 IS를 다른 방향으로 만진다 (혼동 금지)**: **W2**=합이 맞나 **검증**(러프한 계정 그대로), **W2.5**=한 줄→여러 성격으로 **분해**(매출→제품/상품/용역, 원가→재료/노무/경비), **W3**=성격→평가유형으로 **집계**(Sales/COGS/SGA/NO). 세분화는 리서치(W1 제품·매출 구성)와 추정(W4 드라이버)을 잇는 다리 — IS가 통짜면 W4에서 P×Q·변동/고정을 걸 대상이 없다. **과립도는 원천자료(주석·세그먼트·제조원가명세서)가 지지하고 W4 드라이버에 연관되는 만큼만** — 자료 없으면 총액 유지 + `[성격별 미확보]` 표면화(억지 분해 금지). **`footnote_costs.py`(①추출)를 쓰면 이 원칙이 구조적으로 강제된다** — 주석에 있는 성격만 나오므로 억지 분해가 불가능하고, 각 값이 원문 char span provenance를 갖는다. 추출=결정론 / 카테고리·드라이버 판정=평가인 승인(`uncertain`은 자동확정 금지).

---

## 자료 요청 (just-in-time)

체크리스트를 앞에서 통째로 던지지 않는다. **각 단계에서 "지금 이 작업에 무엇이 빠졌나" 판단해, 결핍이 있을 때만 그것만 콕 집어 요청.** 미가용 소스로 가정을 지어내지 않는다 — 없으면 "X가 필요합니다; 없으면 Y 가정으로 진행하되 추정치 표기"로 표면화.

단계별 필요 자료(내부 참조): W1=사업보고서(사업개요·주요제품·원재료/설비·매출/수주)+3개년 FS+주석 / W2=과거 FS 원문(당기·전기)+회계정책 변경 주석 / W2.5=매출 세그먼트·품목 주석·제조원가명세서(재료/노무/경비)·판관비 성격별 주석·영업외 명세 / W3=세그먼트·원가명세서 / W4=드라이버 실데이터·CapEx 계획·경영진 추정 / W5=peer 시드·목표자본구조·Kd.

---

## 도구 (scripts/)

전부 stdin JSON(또는 파일인자) → stdout JSON. 계산·검증은 반드시 이걸로.

```bash
# W0 백지 스캐폴딩 (Claude Code)
echo '{...DcfSpineInput...}' | python scripts/scaffold.py --xlsx out.xlsx
# W0 백지 스캐폴딩 (Claude for Excel — 셀 JSON 받아 기입)
echo '{...}' | python scripts/scaffold.py --emit-cells
# W1~W5 단계 시트 뼈대(stdin 불요; 워크북 성장)
python scripts/scaffold.py --stage W2.5 --emit-cells   # FS_Disagg(손익 세분 뼈대)
python scripts/scaffold.py --stage W4 --emit-cells     # Fcst_Rev·Fcst_Cost·Capex_Dep·WC
python scripts/scaffold.py --stage W6b --emit-cells    # Model(3표 연결 + Circuit Switch)

# W2 과거 FS 무결성 (정규화·교차검증·재분류 추적; 미해결엔 account_dictionary 이관 힌트)
echo '{"sources":[{"label":"FY2024","periods":{"2024":{"매출액":"1,234",...}}}]}' | python scripts/fs_clean.py

# W2.5 ① 주석 성격별 추출 (Σ성격별=IS 표기 tie-out + W4 드라이버 제안 + ②용 payload)
echo '{"text":"구분 2024\n급여 12,340\n퇴직급여 1,500","stated_sga":13840,"year":"2024"}' | python scripts/footnote_costs.py

# W2.5 ② 손익 세분화 (세분합=원계정 합보존 게이트 + 구성비 YoY 추이)
echo '{"blocks":[{"parent":"매출액","periods":{"2024":{"total":"1,234","children":{"제품매출":"800","상품매출":"434"}}}}]}' | python scripts/fs_disagg.py

# ①→② 사슬 (추출 결과를 그대로 세분검증으로)
python scripts/footnote_costs.py in.json \
  | python -c "import json,sys;print(json.dumps(json.load(sys.stdin)['disagg_payload'],ensure_ascii=False))" \
  | python scripts/fs_disagg.py

# W3 평가재분류 (표준계정→유형 파티션; 분류합=원본 FS합·중복·누락·유형오류 0)
echo '{"items":[{"account":"매출채권","amount":100,"type":"WC"},{"account":"유형자산","amount":700,"type":"FA"}],"original_total":800}' | python scripts/reclass.py

# W5 유사회사 4-step 퍼널 (웹 /api/peer/select 미러; Step2만 판단, 나머지 결정론)
echo '{"target_ticker":"TGT","candidates":[{"ticker":"A","industry_code":"2710","revenue_share_related":0.9,"listed_years":5}],"target_industry_codes":["2710"],"judgments":[{"ticker":"A","similar":true,"reason":"동일 사업"}]}' | python scripts/peer.py

# W5 WACC (market_cap_musd 주면 Kroll 제안). 무부채β·목표자본구조는 Peer 확정 peer 평균.
echo '{"risk_free":0.03,"market_risk_premium":0.08,"unlevered_beta":1.0,...}' | python scripts/wacc.py

# W6 DCF 계산 + audit
echo '{"wacc":0.09,"terminal_growth":0.01,"revenue":[...],...}' | python scripts/dcf.py

# W0/W6 워크북 왕복 tie-out
python scripts/roundtrip.py model.xlsx --expect inputs.json
python scripts/roundtrip.py before.xlsx --diff after.xlsx      # 3버킷 diff

# W6 hard number 승격 (스파인 입력셀 → Fcst 계 참조 + per_share 불변 검증)
echo '{"spine":{...DcfSpineInput...},"fcst_totals":{"rev":[...],"cogs":[...],"sga":[...]}}' | python scripts/promote.py

# W7 시나리오 (기본=JSON 분석; --emit-cells 로 Scenario 시트 셀)
echo '{"cases":{"Base":{...},"Up":{...}},"weights":{"Base":0.5,"Up":0.5}}' | python scripts/scenario.py
echo '{...}' | python scripts/scenario.py --emit-cells      # Scenario 시트(가중 SUMPRODUCT)
echo '{...}' | python scripts/scenario.py --emit-cells --switch   # + CHOOSE 단일선택 스위치(발표·서사용)

# W8 민감도 그리드 (WACC×PGR 5×5 살아있는 수식; 중심==base, DCF 있는 워크북에 Sens 추가)
echo '{...DcfSpineInput...}' | python scripts/sensitivity.py --emit-cells

# 감사인 트랙 — 독립 재계산 + 주장값 대조
python scripts/audit.py inputs.json <주장주당가치>

# W9 서사 표현 가드 — 조서·리포트 텍스트의 결정론 린터(전부 WARN, 차단 아님)
echo '{"text":"...","notes":{"gap":{"driver":"...","action":"..."}}}' | python scripts/lint_report.py
python scripts/lint_report.py --text "본 건은 분식입니다."

# 지식 폴백(단계 바인딩에 없는 비정형 질문만)
python scripts/book_search.py "영구성장률 몇 퍼센트?"
```

**DcfSpineInput 필드**: `wacc, terminal_growth, revenue[], cogs[], sga[], dep_amort[], capex[], delta_nwc_cash_adj[], non_operating_assets, net_debt, shares_outstanding` (+ 선택: `non_controlling_interest, mid_year_periods[], terminal_discount_period, tax_override[], effective_tax_rate, terminal_fcff_override, terminal_reinvestment_rate, terminal_wc_ratio`, **페이드**: `fade_years, fade_growth, terminal_from_last_fcff`). 단위 백만원, 주식수만 주.

**⭐ 페이드(수렴) 구간 — 명시 → 페이드 → Gordon 3단**: 명시말기 고성장에서 영구성장률로 **급단절**하면 TV 가 왜곡되고 TV 비중이 치솟는다. `fade_years=5` 를 주면 마지막 명시연도의 **모든 비율(마진·세율·CAPEX/매출·D&A/매출·ΔWC/매출)이 동결**된 채 성장률만 `fade_growth`(기본 = AVERAGE(마지막 명시 성장률, PGR))로 수렴하는 구간이 붙는다. `terminal_from_last_fcff=True` 면 TV 를 **마지막 연도 FCFF×(1+g)** 로 잡아 그 해의 재투자 강도를 영구 승계한다(기본은 EBIT_T 재구축=D&A·CAPEX 상쇄).
> **실측(모델러스 Hugel, `tests/golden/test_modellers_hugel_fade.py`)**: 페이드 5년 → 주당 144,000원·**TV비중 57.8%(PASS)**. 동일 입력에 페이드를 빼면 주당 157,000원·**TV비중 84.6%(WARN)** — 9% 과대. **TV 비중이 75% 를 넘으면 페이드 구간을 먼저 검토**하라.

---

## 지식 참조 (사전 바인딩)

각 단계에 오면 위 표의 지식 파일(`scripts/vendor/reference/<파일>.md`)만 Read한다 — 통독·전량검색 금지. 단계에 안 잡히는 비정형 질문만 `book_search.py` 폴백(오프라인 lexical). 챕터 색인은 `references/index.md`.

**참고 모델 계열은 방법론 지식으로만** — 시트 복제 금지.

---

## 상태 규약 (`_VS_STATE` 시트)

세션은 무상태 → 워크북이 곧 상태. 숨김 시트 `_VS_STATE`에 기록: `skill_version·mode(A/B/C)·stage(W0·W1·W2·W2.5·W3~W9)·last_gate_passed·engine_tieout` + 가정 대장(provenance) + 계정 매핑 대장(W2 연도간 이관 이력 / W2.5 세분 대장 / W3 평가유형). 재진입 시 이 시트만 읽고 재개 지점 판별. 각 게이트 통과 시 갱신.

## 가정 출처(provenance)

모든 가정은 `_VS_STATE` 대장에 `가정명|값|출처유형|근거|승인상태|lookback|lookback사유`.
**과거평균 드라이버는 lookback 창과 그 사유가 필수**(R12) — `AVERAGE(과거 N년)` 은 좋은 기본값이지만 **N 자체가 판단**이다. 실측(모델러스 5.4 §2.2c): 같은 워크북에서 DSO=3년 평균, DIO·DPO=5년 평균으로 창이 달랐는데 시트에 근거가 없었다. 창을 달리했으면 이유를 쓴다(예: "2020 코로나 재고 이상치 제외 위해 DSO 만 3년"). 출처유형 = `user`(평가인) / `research`(URL·문서 병기) / `suggested`(근거 챕터 병기). **`suggested` 미승인 가정이 W6에 유입되면 WARN 표면화**, 출처 없는 가정은 진행 차단.

## 추천 모델·난이도 승격

단계 성격에 맞춰 권고(런타임별 실행력 다름 — Excel은 조언만, Claude Code/MAS는 서브에이전트 모델 지정 가능). W1·W3·W9=상위 모델·high, W2.5=medium(과립도·성격 판정 시 승격), W6·W8=결정론이라 저비용. **애매하면(계정분류 모호·재분류 다대다·세분 과립도 불명·peer uncertain·audit FAIL) 상위 모델/high로 승격하고 평가인에게 표면화.**

---

## 키·비밀 원칙

**스킬은 API 키가 필요 없다.** scripts/는 결정론 stdlib(키 무소요), 외부 데이터는 사용자 투입·MCP 커넥터(Claude 설정 인증). **API 키·토큰을 워크북 셀·`_VS_STATE`·스킬 파일·가정 대장 어디에도 기록 금지**(워크북은 공유·전달 산출물).

## 신뢰 원칙

- LLM은 평가인 판단의 **보조**(대체 아님). 규칙·근거 없어 애매하면 결론 강제 금지 — "XX는 ~해서 애매합니다"로 표면화.
- 계산은 항상 `scripts/`. 암산·추정 금지(재현·감사 불가).
- 숫자에 출처를 붙인다. audit 경고를 숨기지 않는다.
- 모르는 방법론은 references에서 확인 후 답한다(환각 금지).
- **참고 모델 시트를 복제하지 않는다** — 방법론만 차용, 자체 아키텍처 사용.
