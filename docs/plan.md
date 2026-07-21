# DCF 모델 자동화 플랫폼 — 구현 플랜

## Context (왜 만드는가)

참고 모델 기업가치평가연수 과제(정종범 _비올_ DCF Model)는 손으로 만든 엑셀 DCF다. 목표는 이 엑셀의 **로직을 1:1로 재현**하되, 앞단(가정 도출·리서치·컨텍스트 관리)을 **DART API + RAG + LLM**으로 자동화하고, 뒷단(산출물)을 **감사인이 셀 수식을 추적할 수 있는 살아있는 xlsx**로 내보내는 웹 플랫폼을 새 GitHub 레포로 구축하는 것.

두 개의 화이트보드 해석(제미나이·챗지피티 계획.md)이 공통으로 그리는 파이프라인:
`데이터 수집 → 파싱/매핑 → 재무DB → Assumption 생성(AI) → DCF 엔진 → Reporting`.

**운영은 투트랙:**
- **평가자(전문가) 트랙 [먼저 구축]**: FS·기초자료 → (RAG·챗으로 가정 도출) → DCF 모델 → 평가의견서.
- **감사인 트랙 [이후]**: *제공된* 평가의견서를 FS 등과 대조하여 유의적 가정·방법·데이터를 **테스트**하거나, 감사인의 **독립적 점/범위 추정치**를 도출 (ISA 540 회계추정치 감사에 대응).

## 목표 산출물 (확정된 결정)

| 항목 | 결정 |
|---|---|
| 산출물 형태 | 웹앱 UI + **수식이 살아있는 .xlsx export** (2차 리포트 구조 동일) |
| 첫 마일스톤 | **결정론적 DCF 코어 + 비올 1:1 재현** (AI 없이, 골든 테스트) |
| 스택 | **Python(FastAPI) 백엔드 + React+Vite SPA + Postgres(Supabase)** |
| 배포(MVP) | 프론트=**Vercel** · 백엔드=**Railway/Render 컨테이너** · DB/Auth/Storage/벡터=**Supabase(pgvector)** |
| 외부 데이터 | **OpenDART API** + IR/교육 PDF + 외부평가의견서 |
| LLM | **실서비스=Claude 작업별 티어링(Sonnet 5 기본/Opus 정밀)** + Gemini(검색그라운딩·임베딩)+Groq 폴백 — §LLM 모델 전략 |

## 원본 엑셀에서 확인된 실제 로직 (재현 대상)

핵심 엔진 파일: `DCF_비올/(DCF연수1기)정종범_비올_DCF Model_최종본.xlsx` (외부링크 0 = 자기완결). 시트 의존 그래프:

```
H_FS (과거 재무제표, 하드 입력)
  │
  ├─► EBIT 시트: 매출(제품별 P×Q 빌드) → 매출원가(COGS%) → 매출총이익
  │              → 판관비(인건비/지급수수료/감가상각…) → EBIT
  │              (드라이버는 Assumption 시트에서: 성장률·마진·segment)
  ├─► FA 시트:   기존자산 감가상각 스케줄 + 신규 CAPEX 감가상각 → D&A, CAPEX
  └─► WC 시트:   매출채권/재고/매입채무 회전율(365/회전율) → ΔNWC
        │
        ▼
   DCF 시트 (계산 spine):
     매출 → 매출원가 → 매출총이익 → 판관비 → EBIT
     → 법인세(구간세율 IF: <200 9%, 계단식) → NOPLAT
     → (+)D&A(FA!7) (−)CAPEX(FA!10) (−)ΔNWC(WC!15) → FCFF
     → PV(중간연도 할인, YEARFRAC 반기 컨벤션, 1/(1+WACC)^t)
     → 명시적기간 PV합 + Terminal[R26/(WACC−g)×PVfactor]
     → 기업가치(EV) (+)비영업자산(H_FS) (−)순차입부채(H_FS)
     → 주식가치 ÷ 발행주식수(BackData!G94) → 주당가치
     + 2-way 민감도표 (WACC × 영구성장률)

   WACC 시트 (할인율 서식_정종범.xlsx 로직):
     신용등급×만기 채권수익률 매트릭스
     → CAPM 빌드업: Unlevered β → D/E·tax로 relever → Ke = RF + β·MRP
       + Size premium + Country risk + Company-specific risk
     → Kd(pre-tax) → after-tax Kd → WACC = E/V·Ke + D/V·Kd(1−t)
     (유사회사 β·자본구조는 peer/유사회사재무 데이터에서)
```

**핵심 가정(비올, Assumption 시트):** 추정기간 5년, 영구성장률 2%, WACC ~11.3%. 매출은 제품군(RF/HIFU 소모품 등) segment별 성장률로 빌드.

> ⚠️ `2차 리포트` 엑셀은 externalLinks 8개 = 다른 파일 의존이 끊겨 있음. 그래서 재현 기준은 자기완결인 `DCF Model_최종본.xlsx`로 삼는다.

---

## 아키텍처 (모노레포)

```
valuation-platform/               # 새 GitHub 레포
├── backend/                      # Python · FastAPI
│   ├── calc_core/                # ★ Milestone 1: 결정론적 DCF 엔진 (순수 함수)
│   │   ├── models.py             #   Assumption/FS/DCF 도메인 dataclass (Pydantic)
│   │   ├── revenue.py            #   ★ 매출추정 전략: top_down(산업 CAGR) | bottom_up(P×Q)
│   │   ├── ebit.py               #   매출벡터 수신 → COGS·판관비 빌드 → EBIT
│   │   ├── fa.py                 #   감가상각·CAPEX 스케줄
│   │   ├── wc.py                 #   운전자본 회전율
│   │   ├── wacc.py               #   CAPM 빌드업 + 자본구조
│   │   ├── dcf.py                #   FCFF→EV→주당가치 + 민감도
│   │   └── tax.py                #   한국 법인세 구간세율
│   ├── ingest/                   # Phase 2: DART API·주석·IR PDF·외부평가의견서 수집
│   │   ├── dart_client.py        #   OpenDART: 정형 계정 API(fnlttSinglAcntAll, BS/IS/CF 값)
│   │   ├── macro_client.py       #   ★ 거시가정: GDP·CPI·임금성장률 (EIU 복붙 / 한국은행 ECOS API / IMF WEO)
│   │   ├── dart_document.py      #   사업보고서 원본(document API) → 주석 HTML/XBRL
│   │   ├── footnote_extractor.py #   ★ 주석 테이블 추출: 유형·무형 증감표(내용연수),
│   │   │                         #     판관비 성격별 분류 — classifyJu 위치규칙 포팅
│   │   ├── validators.py         #   ★ 4종 검증: 정합성·숫자형·공백·합계 (tie-out 엔진)
│   │   ├── peer_fs.py           #   ★ 유사기업 FS DART 적재 + 계정매핑 (unlever beta·자본구조용)
│   │   ├── price_client.py       #   ★ 주가·시총 (FinanceDataReader/pykrx) — E, 베타회귀, peer 시총
│   │   ├── pdf_parser.py         #   IR/의견서 PDF → text+table (영업보고서 fallback)
│   │   ├── manual_paste.py       #   ★ 복붙→전처리→파싱→검증 (Bloomberg 채권수익률·베타, NICE-bizline 신용등급)
│   │   └── fs_mapper.py          #   계정과목 매핑 + ★NOA/IBD 구분(영업/비영업·이자부부채) → EV→Equity bridge
│   ├── rag/                      # Phase 3: 3-코퍼스 벡터 검색 (감린이 RAG 포팅)
│   │   ├── chunker.py            #   build_chunks.mjs subsplit 포팅(window/overlap/표-atomic)
│   │   ├── ingest.py             #   contextual-prefix + Qdrant dense+sparse RRF (ingest.mjs)
│   │   ├── corpora.py            #   기초/경영진자료/지식원천(전문가 자료) 분리 + authority tier
│   │   ├── retrieve.py           #   hybrid+rerank+parent확장+citation검증 (chatHandler 포팅)
│   │   └── eval_metrics.py       #   nDCG/Recall/MRR 회귀 게이트 (eval_metrics.mjs)
│   ├── rag_inference/            # embed/rerank 마이크로서비스 (services/rag-inference 직접 복사)
│   │   └── main.py · models.py   #   env-swappable(EMBED_MODEL/RERANK_MODEL) FastAPI
│   ├── llm/                      # LLM 라우터 (gradingRouter.js 포팅)
│   │   └── router.py             #   OpenAI 호환 멀티프로바이더 + RPM 페일오버(Gemini/Groq)
│   ├── assist/                   # Phase 3: 가정도출 챗 오케스트레이터
│   │   ├── chat.py               #   가정 제안 + "경영진 자료 필요" 요청 루프
│   │   └── provenance.py         #   각 가정에 출처(공개/경영진/대형 회계법인) 태깅
│   ├── auditor/                  # Phase 5: 감사인 트랙
│   │   ├── ingest_opinion.py     #   제공된 평가의견서 파싱
│   │   ├── tests.py              #   유의적 가정·방법·데이터 대조 테스트
│   │   └── independent.py        #   독립적 점/범위 추정 재계산
│   ├── excel/                    # Phase 4: 살아있는 xlsx ↔ 웹 양방향 동기화
│   │   ├── template_schema.py    #   ★ 고정 입력셀 맵 + named range + 템플릿 버전 태그(SSOT)
│   │   ├── xlsx_writer.py        #   export: openpyxl 수식 그대로 기록(값X, =EBIT!H13 유지)
│   │   └── xlsx_reader.py        #   ★ import(업로드→자동반영): 셀맵 역방향 읽기→validators→calc_core 재계산
│   └── api/                      # FastAPI 라우터
├── frontend/                     # 경량 웹 (React+Vite 권장, 또는 HTMX)
│   ├── 컨텍스트 관리(3-코퍼스 뷰)
│   ├── 가정 챗 패널 + provenance 표시
│   ├── DCF 결과·민감도 인터랙티브
│   └── xlsx 다운로드
├── tests/
│   └── golden/                   # ★ 비올 1:1 재현 골든 테스트
├── fixtures/viol/               # 비올 입력(H_FS/Assumption) + 기대 출력 스냅샷
└── pyproject.toml / README.md
```

---

## 현 단계 운영 형태 — 로컬 모드 (사용자 확정, 2026-07-17)

**실사용급 배포 전까지는 전부 로컬에서 돌린다.** 아래 클라우드 스택(Vercel·Railway·
Supabase)은 그대로 목표로 두되 **착수를 연기** — 지금 가치는 엔진·워크플로우 검증.

- **구성**: `uvicorn backend.api:app` 1프로세스(localhost) + **React+Vite 프론트**
  (dev 서버 또는 빌드 정적파일을 FastAPI 가 서빙). 프레임워크는 계획 스택 그대로 —
  후일 Vercel/컨테이너 전환 시 코드 불변.
- **BYOK(Bring Your Own Key)**: Gemini/Anthropic 키를 **클라이언트에서 입력** →
  localStorage 저장 → 요청 헤더로 로컬 백엔드에 전달, 백엔드는 통과만(디스크 저장
  금지). 감린이 검증 패턴 재사용(키 검증·손상키 방어 경험 이식).
- **로컬 강점 활용**: 원자료(엑셀·PDF·XBRL)가 로컬 디스크 — 업로드 없이 **경로
  기반 인제스트**(파일 피커→절대경로). 저작권 자료가 클라우드에 올라가지 않아
  지식 취급 정책과도 정합.
- **저장**: Supabase 대신 로컬 파일(JSON)·SQLite. 모델 버전·감사로그도 로컬.
- 첫 화면 후보: ①Brief 프리필+딥서치 실행 ②DCF 입력→결과·민감도·시나리오
  ③peer 4-step 퍼널(⚖️ 애매 큐 포함) ④xlsx 왕복 diff 뷰 — 단계별 모델 뱃지·추천
  표시(§LLM 모델 전략 UX)를 이 로컬 UI 에서 먼저 구현.

## 배포·스택 확정 (실사용급 전환 시 — 개인 포폴, 빠른 배관 최소화)

| 레이어 | 선택 | 근거 |
|---|---|---|
| 프론트 | React + Vite SPA → **Vercel** | 정적 빌드, 트리편집·히트맵·챗 인터랙션 최적, 무료티어 |
| 백엔드 | FastAPI(Docker) → **Railway 또는 Render** | 장수명 Python(RAG·xlsx·Arelle)에 서버리스보다 컨테이너 적합 |
| DB/Auth/Storage | **Supabase** | Postgres(모델 버전·감사로그) + Auth + Storage(업로드 PDF/xlsx) 한 서비스 |
| 벡터검색 | **Supabase pgvector** (MVP) | 관계형+벡터 한 DB=배관 최소. `retrieve.py` 인터페이스 추상화로 후일 Qdrant 스왑 |
| 임베딩/리랭크 | **Gemini 임베딩 API**(MVP) | self-host rag-inference 생략; 스케일 필요 시 감린이 `services/rag-inference` 포팅 |
| LLM | **Claude 작업별 티어링**(아래 §LLM 모델 전략) + Gemini/Groq | `llm/router.py` 멀티프로바이더(Anthropic 추가) |
> 기밀성 낮은 MVP라 매니지드 우선. 후일 기밀 요구 생기면 전부 Docker Compose로 셀프호스트 이전(앱은 불변).

## LLM 모델 전략 — Claude 작업별 티어링 (실서비스, "Claude in Excel" UX)

**⭐ 대원칙(사용자 확정): LLM 은 유저 판단의 보조다 — 대체가 아니다.** 명확한 규칙·근거가
없어 애매하면 결론을 강제하지 않고 **"XX회사는 ~해서 애매합니다"를 표면화**해 유저 결정
큐로 보낸다(uncertain 3-상태 — peer Step2 에 구현됨, 계정분류 모호 케이스 등 전 판단
작업에 동일 적용). UI 는 애매 항목을 ⚖️ 별도 섹션으로 노출.

**모델 배치 원칙: 판단 품질이 돈이 되는 곳에 상위 모델, 대량·기계적인 곳에 하위 모델.** UX 는
Claude in Excel 처럼 **작업(단계)별로 모델을 나눠 쓰고 사용자가 오버라이드** 가능하게
— 이미 SKILL 의 "단계↔도구↔지식" 사전 바인딩 표가 있으므로 **모델 컬럼을 추가해
3중 바인딩(도구·지식·모델)**으로 확장하면 된다.

| 작업(단계) | 기본 모델 | 근거 |
|---|---|---|
| 0단계 기업·산업 이해(Brief 완성) | **Sonnet 5** | 판단+종합. 검색 그라운딩은 Gemini 병행(딥서치 실증됨) |
| 2 계정 분류(대량 태깅) | Sonnet 5 (Haiku 검토중) | 문항수 많음·스키마 고정 — 하향 후보 1순위 |
| 3b-pre 유사회사 선정 Step2(사업 유사성) | **Sonnet 5** | 판단 + 회사별 선정/탈락 사유(감사 방어). Step1·3·4는 결정론 |
| 3a 매출·원가 가정 도출 | **Sonnet 5** | Brief+북 근거 종합 판단 |
| 3b~4 WACC·DCF | (LLM 아님 — 결정론 scripts) | 계산은 모델 무관, 코드가 담당 |
| 5 리포트·평가의견서 서술 | **Sonnet 5**, "정밀 모드"=**Opus** | 고객 제출물 — 품질이 곧 상품 |
| 감사인 트랙(독립 재수행·반박) | **Opus** | 최고난도 추론 + generator(Sonnet)↔critic(Opus) 모델 분리 = 관점 다양성 보너스 |
| 파서 LLM 보조 변형(스키마 매핑) | Sonnet 5 (Haiku 검토중) | 검증 게이트가 뒤에 있어 모델 리스크 흡수 |
| 챗 폴백·요약 등 경량 | Gemini Flash/Groq | 기존 폴백 체인 유지 |
| 임베딩/검색 그라운딩 | **Gemini**(고정) | Anthropic 은 임베딩 API 없음. 검색 그라운딩도 Gemini 실증 |

- **UX**: 각 단계 패널에 모델 뱃지 + 드롭다운(기본값=위 표). 프리셋 2개 — "표준"(전부
  Sonnet 5) / "정밀"(리포트·감사인=Opus). 비용 표시(단계별 예상 토큰×단가).
- **UX 추천 표시(확정)**: 작업 **난이도에 따른 추천 모델을 UI 에 상시 표시** — 단계마다
  난이도 등급(예: ●○○ 기계적 / ●●○ 판단 / ●●● 고난도 추론)과 그에 매핑된 "추천"
  뱃지를 드롭다운 옵션 옆에 노출. 사용자가 추천보다 하위 모델을 고르면 품질 경고,
  상위를 고르면 비용 차이를 표시(informed override). 난이도·추천 매핑의 SSOT 는
  위 티어링 표(= task→model 설정 파일) — UI 는 이를 읽어 렌더만 한다.
- **라우터**: `llm/router.py` 는 OpenAI 호환 멀티프로바이더 설계 그대로 — Anthropic
  프로바이더 1개 추가 + `task→model` 매핑 테이블(설정 파일, SKILL 바인딩 표와 동기).
  Claude 429/장애 시 Gemini 폴백(기존 체인 재사용).
- **Haiku 는 검토중(미확정)**: 계정분류·파서변형이 후보지만, 분류 오류는 하류(DCF 입력)
  오염 비용이 커서 Sonnet 5 대비 오류율·비용 실측 후 결정(골든 분류셋으로 A/B).
- **프롬프트 캐싱**: 단계별 고정 컨텍스트(북 챕터+Brief)가 반복 투입되므로 Anthropic
  prompt caching 으로 비용 절감 — 단계 바인딩 구조와 정확히 맞물림.

## 파서 인프라 (범용 인제스트 백본 — 사용자 강조)

업로드(PDF/xlsx/HTML/XBRL/복붙)가 다양하므로 **공통 파서 파이프라인**으로 일반화. 개별 추출기(footnote_extractor·pdf_parser·manual_paste·peer_fs)는 이 백본의 어댑터.

```
[소스 어댑터] → [원시 추출] → [LLM 보조 변형] → [결정론적 검증 게이트] → [import]
 PDF(pdftotext/                구조화 후보    LLM이 지저분한 파싱을      validators.py 4종
   PyMuPDF/pdfplumber)                        타깃 스키마로 매핑·정규화   (숫자형·공백·합계·정합성)
 xlsx(openpyxl)                               *제안*만, 신뢰는 검증이      + charIndex provenance
 HTML(DART 주석)                              책임                        불변식
 XBRL(Arelle)                                                            ↓ 통과분만
 복붙(TSV/텍스트)                                                        calc_core/DB 반영
```
- **원칙**: LLM은 **변형/매핑 제안**만(예: OCR 깨진 표를 스키마로 정리). **검증은 결정론적**(clean-truth 라운드트립 오라클, runbook:85-96) — LLM 출력을 절대 무검증 신뢰 안 함. 저신뢰는 사람 검토 큐로.
- **provenance**: 모든 import 값에 `{source_file, page/table, char_span, raw, method: 'auto'|'llm'|'paste', confidence}`. 감사인이 출처·변형이력 추적 가능.
- **재사용**: 감린이 구조화메타의 `classifyJu`·charIndex 불변식·typed-extractor 뱅크·confidence tiering을 이 백본에 이식.

## `backend/parsers/` 모듈 (위 어댑터 집약)
```
parsers/
├── base.py          # 공통 파이프라인(어댑터→추출→LLM변형→검증→import) + Provenance 스키마
├── pdf.py           # pdftotext/PyMuPDF/pdfplumber 어댑터
├── xlsx.py          # openpyxl 어댑터 (업로드 중간엑셀 포함)
├── dart_html.py     # DART 주석 HTML 테이블
├── xbrl.py          # Arelle 어댑터 (주석 태깅 fact + calc-linkbase 합계검증)
├── paste.py         # 복붙 TSV/텍스트
└── llm_transform.py # LLM 보조 변형(스키마 매핑 제안) — 검증 전 단계
```

---

## Milestone 1 — 결정론적 DCF 코어 + 비올 1:1 재현 (AI 없음)

**목적:** "계산은 정확하다"의 바닥을 먼저 확보. 이후 모든 AI는 이 위에 얹는다.

1. **골든 픽스처 추출** (읽기 스크립트): `DCF Model_최종본.xlsx`에서
   - 입력: H_FS(과거 재무제표), Assumption(드라이버 5년치, WACC/g), WACC 빌드업 입력, BackData 발행주식수 → `fixtures/viol/inputs.json`
   - 기대 출력: DCF 시트의 FCFF·PV·EV·주식가치·주당가치·민감도표 셀 값 → `fixtures/viol/expected.json`
   - (이번 세션에서 검증한 파서를 재사용: `zipfile`+`xml` 로 shared strings·formula 추출)
2. **calc_core 구현**: 위 의존 그래프대로 순수 함수 모듈. `dcf.run(inputs) -> DcfResult`.
   - 반기 할인 컨벤션(YEARFRAC), 구간 법인세, Terminal `FCFF_T/(WACC−g)`, 2-way 민감도 정확 재현.
   - **매출추정 전략 선택**(`revenue.py`, `revenue_method` 토글, 하류 EBIT→FCFF 불변):
     - `top_down` (**기본·구현 쉬움**): `산업 TAM × 산업 CAGR^t × 점유율(share)` → 연도별 매출. CAGR은 지식원천(리서치·외부평가의견서) RAG에서 주입, 입력 3파라미터. 비올 Assumption 시트의 시장규모 CAGR(Precedence Research/Medical Insight) 데이터가 실제 사례.
     - `bottom_up`: `Σ(세그먼트 P×Q)` 제품군별 가격·수량. 검증(세그먼트 합계=총매출) 추가.
     - 비올 원본은 세그먼트 성장률(bottom-up 근사)을 썼으므로 골든 테스트는 bottom_up 경로로 1:1 재현, top_down은 별도 단위테스트로 검증.
3. **골든 테스트**: `pytest tests/golden/test_viol.py` — calc_core 출력이 `expected.json`과 **셀 단위 허용오차 내 일치**(부동소수 rel_tol 1e-6). 주당가치·EV·민감도 셀 전부 대조.
4. **xlsx export 스텁(초기)**: calc_core 결과를 원본과 동일 시트/셀 배치로 기록하되 **수식 문자열 유지**(감사 추적성). export 결과를 엑셀에서 열어 원본과 수치 대조.

**완료 기준:** 비올 입력 → calc_core → 원본 엑셀과 주당가치·EV·민감도 일치, 그리고 export xlsx가 엑셀에서 재계산해도 동일.

## Phase 2 — Ingestion + DART 주석 추출·검증 (핵심 신규 설계)

DART는 재무 데이터를 **2층위**로 노출하며, ingestion은 이 둘의 **조인**이다:
- **정형 계정 API**(`fnlttSinglAcntAll`): BS/IS/CF 계정 *값* → H_FS 숫자 골격 자동 적재.
- **사업보고서 원본 주석**(document API의 XBRL/HTML, 없으면 영업보고서 PDF): FA·판관비의 *구조*가 여기 있음. 정형 API엔 없다.

### 주석에서 반드시 가져와야 하는 항목 (사용자 지정)
| 대상 | 주석 위치 | calc_core 소비처 | 검증 |
|---|---|---|---|
| 유형자산 감가상각 내용연수 | 유형자산 증감표/회계정책 주석 | `fa.py` 감가상각 스케줄 | 취득원가−감가상각누계=장부금액; 내용연수 숫자형/범위 |
| 무형자산 상각 내용연수 | 무형자산 주석 | `fa.py` | 동일 |
| 판관비 성격별 분류 | 비용의 성격별 분류 주석 | `ebit.py` 판관비 분해 | 성격별 합계 = IS 판관비 합계 |

### 주석 추출 엔진 — 감린이 구조화메타 파이프라인 포팅
`footnote_extractor.py`는 감린이 `scripts/extract_structured_meta_regex.js`를 그대로 이식:
1. **`classifyJu` 위치규칙**(원 코드 `:131-135`): `(주N)` 마커가 줄머리/헤더셀 뒤면 **정의블록(추출)**, 표 셀 숫자 뒤 인라인이면 **본문포인터(비추출)**. → 증감표 셀을 통째로 삼키는 over-capture 방지. 한글 negative-lookahead `(?![가-힣])`로 `참고하여` 같은 오탐 차단.
2. **원문불변 + charIndex 불변식**: 각 추출값을 `{table_id, char_start, char_end, raw_text, unit}` 로 저장하고 `source[start:end]==raw` 를 추출·머지·테스트 3층에서 assert. → "내용연수 5년 = 주석21 char 1240–1245" 감사추적 provenance (감린이 `tests/structuredMetaIntegrity.test.mjs:17-39` 방식).
3. **typed-regex 추출기 뱅크**(감린이 `standard_refs` 슬롯 구조): 각 패턴이 타입드 span 방출 — `{type:'krw'|'pct'|'years', value:Decimal, span}`. 단위(천원/백만원)·콤마·괄호음수 정규화.
4. **SURGICAL 제외 오버레이**: 주석 *설명문*에서 딸려온 라벨/숫자는 실제 데이터 셀에 없을 때만 제외(감린이 `expand_keyword_exclusions_from_annotations.js:44-54` 규칙). 재추출에도 살아남는 큐레이션 레이어.

### 4종 검증 = 감사 tie-out 엔진 (`validators.py`)
> 철학: 감린이 **clean-truth 오라클**(runbook:85-96) — 검증은 *재구성/라운드트립 일치*로, "이전 추출과의 상관"으로 하지 않는다(추출기·소비처가 같은 오염 공유하므로).

- **① 숫자형(numeric-typing)**: 단위 정규화(천원/백만원/억), 천단위 콤마 제거, `(1,234)`→−1234, `%`→비율, `N년`→내용연수 int. Decimal 강제, 비숫자 셀은 `fail`. (감린이 `norm()` Unicode-property 스트립 재사용)
- **② 공백유무(blank detection)**: 진짜 0 / 공백 / `-` / null 구분. 합계에 구멍 내는 결측 셀 `warn` 플래그. (감린이 `tidy()` `deriveCleanBody.js:57-64` 공백 정규화)
- **③ 합계검증(sum reconciliation)**: 표의 소계·총계 = 구성요소 합(허용오차). 예: 판관비 성격별 Σ = 표기 합계, 유형자산 취득원가Σ−감가상각누계Σ=장부금액Σ.
- **④ 정합성(cross-statement tie-out)**: 주석↔재무제표 교차. 유형자산 주석 기말장부금액 = BS 유형자산; 감가상각비(주석) = CF D&A = IS 반영; 판관비 성격별 합계 = IS 판관비.
- 산출: **검증 리포트**(규칙별 pass/warn/fail + 근거 span). `fail` 있으면 ingestion 게이트가 막고 사람에게 에스컬레이트. **이 리포트는 그대로 감사인 트랙의 원재료**(tie-out 실패 = 감사 발견사항).

### 수동 인제스트 경로 — 복붙→전처리→파싱→검증 (`manual_paste.py`)
API가 없는 소스(Bloomberg 채권수익률 매트릭스·베타, 한공회 제공 베타 등 — 원본 WACC 시트의 "Source: Bloomberg" 데이터)를 위한 1급 경로:
1. **복붙 입력**: 사이트/터미널에서 복사한 표(TSV/공백정렬/지저분한 텍스트)를 그대로 받음. 원본 스냅샷 보존(감사추적).
2. **전처리**: 단위·콤마·괄호음수·`-`/공백 정규화 — `validators.py` 숫자형·공백 로직 **공유**.
3. **파싱**: 신용등급×만기 매트릭스, 베타(회사·산업·relever 입력) 등 타깃 스키마로 구조화. `wacc.py`가 소비.
4. **검증**: 동일 4종(특히 합계·정합성 — 예: relever 베타 = unlever×(1+(1−t)D/E)) + 값 범위 sanity(베타 0~3, 금리 0~30%).
5. **provenance 태깅**: "Bloomberg 수기 붙여넣기 @날짜/사용자" 로 신뢰수준 별도(경영진 코퍼스와 동급). 감사인이 출처 물으면 붙여넣은 원본까지 추적.
> 원칙: **자동(DART)든 수동(복붙)이든 동일한 검증 게이트를 통과**해야 calc_core에 입력된다. 소스만 다르고 규율은 하나.

## 밸류에이션 입력 데이터 출처 (SSOT) — 회계법인·한공회 교육자료 기준

원본 WACC·Assumption 시트의 각 입력이 어디서 오는지 확정(교육 PDF에서 방법론 확인). 모든 입력은 자동/수동 무관 `validators.py` 게이트 통과 + provenance 태깅.

### 표준 Assumption 항목 (비올·2강 템플릿에서 확정 → `models.py` 스키마)
1. **거시**: Country, 평가기준일, Real GDP·CPI·명목임금 성장률.
2. **기본가정**: 추정기간(5년), 영구성장률(2%), WACC, 유사회사 자본구조.
3. **매출 가정**: 세그먼트별 성장률 or P×Q (아래 트리).
4. **매출원가 가정**: 구성·증가율 — 원재료 / 노무비(인원수×인당급여·상여·퇴직급여) / 경비(driver 연동) / 외주비(CPI 연동) / 감가상각(FA 연동).
5. **판관비 가정**: 인건비 / 외주비 / 경비 / 감가상각.
6. **감가상각·CAPEX 가정**: 자산 구성, 기존자산 상각 스케줄, 신규자산 상각, 신규투자 CAPEX, 유지보수 CAPEX.
7. **WC 가정**: 항목 구성, 회전율(365/회전율).

### 매출 세분화 계층 트리 (LLM 제안 → 유저 승인, 사용자 요청)
`revenue.py`의 bottom_up 경로는 **디렉토리형 상-하위 트리**(깊이·차원 순서 자유): 예 `지역 > 제품군 > 제품 > 상품`, 또는 `제품군(장비/소모품) > 모델`.
- **축 순서 선택**: 트리 생성 시 "**지역 우선 vs 제품 우선?**"을 유저에게 질의(또는 LLM 추천) → 최상위 차원 결정. 비즈니스모델 반영(예: **장비/소모품** razor-and-blades — 비올 HIFU 장비 + RF 소모품).
- **LLM 제안**: `assist/chat`가 사업보고서의 매출/제품/사업개요 섹션(RAG)을 읽고 세분 트리를 **초안 제안** + 각 노드에 근거 provenance(어느 사업보고서 문단).
- **유저 워크플로우**: 트리 UI에서 **+/− 버튼으로 노드 추가·삭제·수정**, 축 재정렬, **승인**(human-in-the-loop). 승인된 트리만 calc_core에 입력.
- **각 리프 노드**: 판매량(Q)×판매단가(P) or 성장률. 상위 노드 = 하위 합계(합계검증). top_down 선택 시 트리 없이 산업 CAGR×점유율.

### 거시가정 (Assumption 시트 상단)
| 입력 | 출처 | 경로 |
|---|---|---|
| Real GDP·CPI·명목임금 성장률 | **EIU**(비올 원본 출처) / 한국은행 ECOS API / IMF WEO / OECD | `macro_client.py` (EIU 구독無 시 ECOS 자동 or 복붙) |

#### ⭐ 거시 데이터 = 프리페치 캐시 + vintage 가드 (사용자 착안 2026-07-18)
거시 예측치는 느리게 변하고 프로젝트 간 공유 → **미리 받아 로컬 캐시**(var/macro/)에 저장.
단 **"평가기준일 맞나?"를 프롬프트로만 확인하면 약함** — 우리 "판단은 LLM, 검증은 코드" 원칙대로
**vintage 결정론 가드**로 승격:
- **각 시리즈에 vintage(발표·as-of 일자) 태깅** 저장(예: IMF WEO 2024-04판, ECOS 조회일).
  같은 GDP 전망도 4월판/10월판이 다르므로 값만이 아니라 vintage 가 provenance 의 일부.
- **가드 규칙(`check_macro_vintage`)**:
  - 🔴 **look-ahead**: vintage > 평가기준일 → FAIL(그 시점 없던 데이터 = 미래정보 유입,
    소급평가·감사인 트랙에서 치명적).
  - 🟡 **staleness**: vintage 가 평가기준일보다 과도히 이전(예: >12개월) → WARN.
  - ✅ vintage 가 평가기준일 직전 최신판 → PASS(그 시점 이용가능 최신).
- **LLM 프롬프트는 2차 레이어**(권고): "이 거시치는 {vintage} 기준 — 평가기준일 {date}에
  적합한지 확인" 안내. 하지만 강제는 가드가, 프롬프트는 보조(판단보조 원칙과 동일).
- 교육 정본의 "Rf 가정과 위험프리미엄 가정 일관성"([[DCF_교육_정본]] §3.2)의 시간축 판.
  → 거시뿐 아니라 Rf·MRP·베타 vintage 도 같은 평가기준일 창에 정렬돼야 함(확장 적용).

### WACC 입력 (할인율 서식 로직 — 교육자료 근거)
| 입력 | 방법론(교육자료) | 출처 |
|---|---|---|
| **Rf 무위험이자율** | 국고채 수익률 | Bloomberg / 금융투자협회 KOFIABOND / ECOS |
| **MRP(시장위험프리미엄)** | **한공회 「시장위험프리미엄 가이던스」 권고 7~9%** (사용자 확정) | 한공회 가이던스 PDF; Damodaran MRP 교차검증 |
| **CRP(국가위험프리미엄)** | 국가별 프리미엄 | Damodaran (stern.nyu.edu) |
| **Beta** | 유사기업 60개월 월간 회귀 → unlever → **relever(D/E·tax)**; Marshall Blume 조정 | Barra/Kisline; **각 peer FS 필요**(아래) |
| **Size premium(CSRP)** | Deciles 1–10 | Duff&Phelps/Kroll(현 Kroll Cost of Capital) 복붙 |
| **Kd 타인자본비용** | **신용등급×만기 회사채 수익률 매트릭스**; BBB-=최저투자등급; Moody's Baa proxy | KOFIABOND 등급별 민평수익률 / 신용등급=KIS·NICE·한기평, DART 사업보고서, **NICE-bizline(복붙)** |
| **자본구조 D/E** | minority=현행 유지 / controlling=산업표준·최적 | peer 시총·부채 |
> **검증(정합성)**: WARA ↔ IRR ↔ WACC reconciliation(PPA calibration, ±1% 이내) — 감사인 검토 방법론 자료 강조. 감사인 트랙 테스트 항목으로도 재사용.

### ⭐ 외부 데이터 조달 갭·우선순위 (2026-07-18, 참고 모델 DCF 교육 정본 대조)
설계(macro_client·price_client·manual_paste)는 있으나 **커넥터는 아직 0개 구축**. 로컬 BYOK
도구라 4대법인의 **Bloomberg(유료·API無)는 배제**, 무료 소스로 대체 — 교육 정본이 "평가인 직접
계산 Daily beta(자산평가사·Local 법인)" 를 정당한 실무로 인정하므로 **β도 우리가 직접 계산 가능**.

| 입력 | 우리 현실적 소스 | 조달 방식 | 지금 닫을 수 있나 | 현 상태 |
|---|---|---|---|---|
| 대상·peer 재무제표 | **OpenDART API** | 무료(키) | ✅ | dart_client 설계·부분 |
| peer 주가·시총·**β 회귀** | **FinanceDataReader/pykrx** | 무료(Python) | ✅ **핵심 갭** | ✅ **price_client 구축**(β OLS·조정·시총·look-ahead 가드, 6테스트. fdr 커넥터=lazy) |
| Rf 국고채(10년) | **한국은행 ECOS API** / KOFIABOND | 무료(키) | ✅ | ✅ EcosProvider(817Y002/D/item)+일별 look-ahead 가드. **잔여: item코드 ECOS 확정**(관용후보 배선) |
| 거시 GDP·CPI·임금 | **ECOS** / IMF WEO / OECD | 무료(키) | ✅ | ✅ **macro_client 구축**(vintage 이중가드·EIU 복붙·as-of 선택·EcosProvider, 12테스트) |
| **MRP(국내)** | **한공회 시장위험프리미엄 가이던스** | 무료 PDF(연간) | 🔶 수치 수기 | ✅ paste_mrp(복붙→2~15% sanity게이트·provenance). 값 확보=유저 복붙 |
| CRP·글로벌 MRP 교차검증 | **Damodaran**(stern.nyu.edu) | 무료 다운로드 | ✅ | ⬜ |
| Size premium(CSRP) | **Kroll** deciles | 유료(연간표) | 🔶 2023 하드코딩 有 | ✅ wacc.py 테이블(갱신 필요) |
| Kd 신용등급×만기 | **KOFIABOND 등급별 민평** + 신용등급(DART 사업보고서·KIS/NICE) | 반무료·수기 | 🔶 복붙 경로 | ✅ **manual_paste 구축**(parse_bond_matrix→BondYieldMatrix·셀별 range게이트, 9테스트) |
| 산업 CAGR·시장규모 | **Gemini 검색 그라운딩**(구축됨) + 증권사 리포트 | BYOK | ✅ | ✅ 딥서치 |

**결론**: WACC 트랙 데이터의 ~80%가 무료 Python(FinanceDataReader/pykrx)+ECOS+Damodaran 으로
**지금 닫힌다**(Bloomberg 불요). ✅ price_client(주가→β 회귀)·✅ macro_client(거시 + vintage
이중가드 + Rf ECOS)·✅ manual_paste(Kd 매트릭스·MRP·β 복붙 게이트) 완료 — WACC·Assumption
트랙 데이터 조달 커넥터 3종 완비. 잔여: Rf ECOS item코드 실확정(관용후보 배선됨)·Damodaran
CRP 다운로드. 모든 값은 provenance 태깅 — **자동(DART/ECOS)이든 수동(복붙)이든 동일 validators
게이트**, 복붙은 confidence=0.9(merge_confidence 약한고리로 파생 WACC 신뢰도 자동 하향) + 도메인
범위 sanity(β 0~3·금리 0~30%·MRP 2~15%, hard=FAIL·soft=WARN).

**✅ WACC 어셈블리(`backend/assemble/wacc_inputs.py`)** — 커넥터 원천값 → 검증된 WaccInputs →
build_wacc 를 잇는 오케스트레이션 계층(calc_core 순수 엔진과 ingest 커넥터 사이의 다리).
`assemble_wacc_inputs`: Rf(paste/ECOS)·MRP(paste)·βu(peers 무부채화, price_client β 또는 Bloomberg
복붙)·Kd(BondYieldMatrix 등급×만기 룩업)·Size(Kroll decile, price_client 시총)를 모아 조립하되,
**모든 커넥터 ValidationReport 를 하나로 fold** → FAIL 하나라도 있으면 blocked(조립 차단, result=None).
checks 의 β provenance·β/MRP 시장정합 게이트도 통합. 실측 검증: Rf 3.45%+MRP 8%+peer βu+BBB 5Y Kd
→ **WACC ≈11.1%(비올 골든 11.3% 대역 일치)**. 7테스트. calc_core/model.py(엔드투엔드)가 이 WaccInputs 를 소비.

**vintage(look-ahead) 이중가드**(macro_client — 사용자 요청 "llm이 사용할 때 평가기준일 기준인지
확인"의 결정론 구현): 거시값은 날짜가 둘 — ①참조기간 ②vintage(공표시점). (a) 실적인데 참조기간이
기준일 이후 = FAIL(미확정 실적), (b) vintage 가 기준일 이후 = FAIL(나중 개정치), (c) staleness = WARN.
⚠️ ECOS 는 최신 개정치만 주므로(as-of 아님) 예측치·최근연도는 **EIU 복붙 스냅샷**(parse_paste_table,
vintage 고정)으로 받는 게 규칙. price_client 의 주가 look-ahead 가드와 동일 원칙의 거시판.

#### ⭐ 조달 방식 2분기 — 자동 커넥터 vs 복붙 UX (사용자 확정 2026-07-18)
- **자동 커넥터**(API/Python): DART·price_client(주가·β)·ECOS(Rf·거시)·Damodaran. 프리페치+
  vintage 가드.
- **복붙 UX**(무료 API 없음): **Bloomberg 베타·채권수익률, 한공회 베타·MRP** 등 4대법인이 유료
  터미널로 받는 값 → **사용자가 화면에서 원본 표/수치를 붙여넣기** → 전처리·파싱·validators
  검증게이트 → provenance("수기 @날짜/사용자", 신뢰수준 별도) → wacc.py 소비. 설계 = plan
  §manual_paste. **UI 컴포넌트: PastePanel**(WACC 화면 내 — 붙여넣기→미리보기 파싱→검증 결과→
  확정). 자동 소스가 있으면 커넥터 우선, 없거나 사용자가 Bloomberg 값을 신뢰하면 복붙으로 대체.
- 원칙: **자동이든 복붙이든 동일 validators 게이트 통과**해야 엔진 투입(소스만 다르고 규율은 하나).

### 유사기업(peer) — WACC 정확도의 핵심 (사용자 강조)

**선정 로직 = 할인율 서식 4-step 정본**(서식 `유사기업선정 Step0~3` + 클래시스
리포트 실측 83→11→9→6사; 북 리포트예시 §E·wacc_할인율서식 §1):

| Step | 기준 | 담당 | 구현 |
|---|---|---|---|
| 0 대상 리서치 | 평가대상 사업·재무 파악 | — | **Company Brief 재사용**(0단계 산출물) |
| 1a 코드 확정 | rough 유사회사 시드 → 그들의 KSIC 역산(**2~3개 union**) | **판단+역산** | `codes_from_seed_peers()`(Brief ⑦⑨=시드 후보) |
| 1b 모집단 필터 | 확정 코드들로 상장사 풀 필터 | 결정론 | FinanceDataReader 산업분류 필터 |
| 2 사업 유사성 | 사업보고서·홈피로 주요사업 유사 판단 | **LLM** | Brief ⑤⑦⑧ 근거 + 회사별 선정/탈락 사유 provenance, **애매→uncertain**(유저 결정 큐) |
| 3 매출 비중 | DART 매출비중 임계(관련사업 ~70%) | 결정론 | 사업보고서 부문매출(research_brief ④ 로직 재사용) |
| 4 기타 | 상장일(베타포인트 충족)·거래정지 | 결정론 | pykrx 상장일·거래상태 체크 |

⚠️ **Step1 실무 교정(사용자)**: KSIC 코드만으로 업종이 완전히 안 갈려 **코드 2~3개**를
가져오는 게 실무 표준. 어떤 코드를 쓸지 자체가 반복 과정 — 먼저 유사회사를 rough 하게
조사하고 걔네 KSIC 를 역산해 모집단 코드로 삼는다(1a). 코드 선택 근거도 기록.

LLM 은 Step1a(시드 역산)·Step2(유사성 판단)에 관여하되 — 나머지는 결정론이라
재현·감사 가능. 감사인 트랙에서 "왜 이 peer 인가"가 단골 질문이므로 회사별 사유가
필수 산출물. 최종 peer 셋은 **유저 승인**(human-in-the-loop) 후 확정.

**구현됨**: `backend/ingest/peer_selection.py`(select_peers 퍼널 엔진 + Step2Judgment
스키마 + 무사유 판정 거부 게이트 + to_markdown 감사리포트, 테스트 10) +
Skill 도구 `scripts/peer.py`(--seeds 역산 / --judgments 퍼널 실행).

`peer_fs.py`: 확정된 peer 의 **재무제표를 DART로 적재 → 계정매핑(가치평가 목적)** → unlever beta에 필요한 D/E·유효세율, 자본구조 산출. (2강 강의자료 `유사회사FS` 시트가 근거 구조.) 주가·시총은 `price_client.py`(FinanceDataReader/pykrx).

> **⭐ 이중 소비자 설계(사용자 확정)**: peer 선정·FS 적재 모듈은 WACC(β·자본구조)
> 전용이 아니라 **상대가치평가(⏳나중 구현)의 peer 배수(PER·EV/EBITDA 등) 산출에도
> 재사용**된다. 선정 파이프라인은 `peer_selection`(공유) ← {`wacc`(β·D/E),
> `relative_valuation`(배수)} 구조로 — Brief ⑨(경쟁사 밸류 비교)가 초기 후보군 힌트.

### NOA/IBD 계정 분류 — EV→Equity bridge
`fs_mapper.py`가 계정을 **영업/비영업(NOA)** 과 **이자부부채(IBD)** 로 분류 → DCF의 `(+)비영업자산 (−)순차입부채`(원본 H_FS D53-67) 정확 매핑. 참고: `NOA IBD 구분 참고자료.pdf` + 회계법인 교육자료.

### 참고자료 (docs/reference/로 색인)
- `(참고 모델) 2강 강의자료(배포용).xlsx` — STEP0-5 모델링 튜토리얼 + `유사회사FS`·`감가상각`·`BackData` 시트(구현 레퍼런스).
- `외부평가검토 자료 외부평가보고서 검토 유의사항` — **감사인 트랙 직결**(외부평가 검토 체크리스트, WACC/beta/MRP/Kd 유의사항).
- `밸류에이션 방법론 자료` — 할인율·CGU·Size premium 방법론.
- `NOA IBD 구분 참고자료.pdf`, 한공회 MRP 가이던스.

## Phase 3 — RAG + 가정 챗 (감린이 RAG 서버 포팅)

3-코퍼스(기초/경영진자료/지식원천대형 회계법인) 분리 벡터DB. 챗이 매출추정·마진·WACC 가정을 제안하고, 부족 시 "경영진으로부터 ~자료 필요" 발화 → 답을 넣으면 **경영진 코퍼스에 별도 저장**(신뢰수준 태깅). 외부평가의견서(로컬 13건: CJ·아모레퍼시픽·다산네트웍스·롯데케미칼…)에서 산업별 방법론·가정 선례 검색. 모든 가정에 **provenance 태그**.

## Phase 4 — Reporting + 웹↔엑셀 양방향 동기화

> **Excel Add-in MVP 상세 PRD:** [prd_excel_addin.md](prd_excel_addin.md) — Level 1(Task Pane) Must/Should,
> manifest·HTTPS 배포·Office.js v1.2·일정·DoD.
- 웹 인터랙티브 결과 + 살아있는 xlsx export + 평가의견서 초안 렌더.
- **중간엑셀 왕복(사용자 요청)**: 웹에서 export → 사용자가 엑셀에서 손봄 → **재업로드 시 웹 자동반영**. `template_schema.py` 고정 셀맵/named range로 `xlsx_reader.py`가 입력셀을 역방향 파싱 → `validators.py` 재검증 → calc_core 재계산 → 웹 상태 갱신. 템플릿 **버전 태그**로 구조 변경 감지(불일치 시 사용자에 경고). 난이도 中(입력셀 스키마만 고정하면 견고).
- **✅ 왕복 diff 엔진 구현됨**(`excel/workbook_diff.py`, 사용자 설계): 재업로드 시 블랙박스
  변화를 셀 단위 3버킷 분류 — ①입력 변경(수식無 셀 값, 정상·자동 반영) ②수식 변경(로직
  변경, 리뷰) ③구조 변경(시트 추가삭제·앵커 고정셀 이동, 위험). R1C1 상대 정규화로
  **행 내 수식 균일성 검사**(외딴 편집 감지), 같은 수식의 캐시값 차이는 무시(재계산 몫).
  `safe` 판정이 자동반영/리뷰 분기 게이트.

### 공식 anthropics/skills xlsx 규약 채택 (2026-07-17 원문 감사)
"dcf-model" 독립 스킬은 공식 레포에 없음(skills 17종·finance 플러그인 전수 확인) —
실재하는 정본은 **xlsx 스킬의 Financial models 절**. 채택 목록:
- **색상 5색**(우리 북 3색의 슈퍼셋): blue=hard 입력·시나리오 lever / black=수식 /
  green=타시트 링크 / **red=타파일 링크 / yellow fill=핵심가정·유저 입력칸**.
- **recalc 검증 게이트**: LibreOffice headless 재계산 → `errors_found` JSON, 0 에러
  전까지 출고 금지. pycel(GPL) 대신 **1차 검증기로 채택**(pycel 은 외부 CI 보조).
  단 "green recalc ≠ 옳은 숫자" — 골든 셀 대조(우리 기존 방식)와 병행.
- **함수 화이트리스트**: Excel-2007 세대(SUMIFS·INDEX/MATCH·IFERROR·SUMPRODUCT) 우선,
  post-2007 6종은 `_xlfn.` 접두 필수, XLOOKUP/FILTER/SORT 계열 금지(스필 메타 없음).
  → export 수식 생성 규칙.
- **외부링크 함정**: `[1]` 참조는 별도 파일 — 재저장 시 캐시값 소실→#NAME?(우리 2차
  리포트 externalLinks 8개 끊김 실측과 동일 이슈). import 시 외부참조 감지+경고 규칙.
- **서식**: % 는 fraction 저장(0.15→15.0%), 연도는 텍스트, 0 → '-', 음수 괄호, 배수 0.0x.
- **편집 원칙**: 기존 파일의 규약이 모든 지침에 우선 — 입력셀(색으로 표시된)만 쓰고
  기존 수식 불가침. 가정은 셀 분리+참조(=B5*(1+$B$6), 하드코딩 금지)·출처 주석.
> 유저 제공 "dcf-model 스킬 기능 목록" 판정: 색상코드·서식·수식원칙·오류검증 = 공식
> 규약과 일치(단 5색 중 3색만 언급). 4시트 구조·TV 이중계산·5×5 {=TABLE}·mid-year
> 토글·WACC 순환참조 격리 = 공식 스킬 명세에 **없음**(IB 관행 서술로 추정 — 특히
> {=TABLE} 데이터테이블은 openpyxl 미지원이라 공식 방식과 상충). Check Row 도 명세엔
> 없으나 우리 checks/validators 가 이미 상회.

## Phase 5 — 감사인 트랙
제공된 의견서 파싱 → 유의적 가정/방법/데이터를 FS·calc_core·주석검증리포트와 대조 테스트, 또는 독립적 점/범위 추정(감사인 자체 가정으로 calc_core 재실행 → 차이 리포트). Phase 2의 tie-out 엔진을 그대로 감사 절차로 재사용.

---

## 감린이 RAG 벤치마킹 매핑 (사용자 지시: 최대한 벤치마킹)

브랜치 `feat/rag-server-rebuild`에 이미 서버사이드 RAG가 스캐폴딩돼 있음. 최고가치 복사 대상:

| 감린이 원본 (repo-relative) | 무엇 | 밸류에이션 포팅 대상 |
|---|---|---|
| `services/rag-inference/main.py`,`models.py` | **이미 Python** FastAPI embed/rerank, `EMBED_MODEL`/`RERANK_MODEL` env 스왑, bge-m3 dense+sparse, scale-to-zero | `rag_inference/` **거의 직접 복사** |
| `functions/chat/chatHandler.js:181-248` | 8단계 오케스트레이터: 쿼리변환→임베드→하이브리드+RRF→리랭크→(confusion gate)→**parent 확장**→grounded gen→**citation 검증(Self-RAG)** | `rag/retrieve.py` — parent확장·citation검증이 감사추적 핵심 |
| `scripts/rag/build_chunks.mjs` | 통합 청크 스키마(authority tier=`gun`, `parent_id`, version, `clause_id` provenance) + `subsplit`(MAX 1100/WINDOW 900/OVERLAP 150, **표 atomic**) | `rag/chunker.py` — 외부평가의견서를 방법론/할인율/성장률 섹션 provenance로 청킹 |
| `scripts/rag/ingest.mjs` | **contextual-prefix**(LLM 없이 결정론적 온톨로지 문맥 프리픽스) + Qdrant dense+sparse RRF upsert | `rag/ingest.py` |
| `scripts/lib/gradingRouter.js` | OpenAI 호환 멀티프로바이더 레지스트리 + RPM 슬라이딩윈도우 + 429/5xx 페일오버 | `llm/router.py` (Gemini→Groq) |
| `js/services/ragService.js:558-685` | 결정론적 리랭크 부스트(정확 조항매치 +0.4, 타입 prior) 뉴럴점수와 블렌드 | `rag/retrieve.py` stage-b — 번호매긴 규제/조항에 고정밀 |
| `scripts/rag/eval_metrics.mjs` | nDCG@k·Recall·MRR + 도메인지표, 회귀 게이트 | `rag/eval_metrics.py` — 골든셋 회귀 |
| `js/services/geminiApi.js:48-73` | 4-레이어 캐스케이드 폴백(flash-lite→Groq→gemma), 타임아웃 즉시폴백 | `llm/router.py` 폴백 체인 |

**핵심 원칙 이식(감사추적):** 작게 검색·작은 단위로 인용하되 parent 전문으로 grounding → 두 번째 LLM 패스가 각 인용을 근거와 대조해 미지원 인용 제거(faithfulness 0.95). 밸류에이션에선 "이 가정은 [회계법인 CJ의견서 §할인율]에 근거" 식 감사방어 인용으로 직결.

**골든 스냅샷 습관**: 감린이 Phase 0.3.5 "출력 0변경 증명" 방식 그대로 DCF 재현(Milestone 1)에 적용.

---

## 참고 오픈소스 (기존 프로젝트 벤치마킹, 사용자 지시)

라이선스 안전(MIT/Apache-2.0)한 것 우선 벤더링, copyleft/무라이선스는 외부 CI 도구로만.

### DART 데이터·주석·스크리닝
| 프로젝트 | 무엇 | 우리 모듈 매핑 |
|---|---|---|
| **josw123/dart-fss** (MIT, 활발) | `extract_fs()` → BS/IS/CIS/CF DataFrame, XBRL 파서, arelle 의존 | `dart_client.py` — H_FS 자동적재 주력 |
| **FinanceData/OpenDartReader** (MIT) | rcept_no로 사업보고서 섹션·첨부·`finstate_xml()`(XBRL zip) 내비 | `dart_document.py` — 주석 원본 zip 취득 |
| **OpenDART 주석 일괄다운로드 TSV** | K-IFRS **주석** XBRL을 TSV로 배포(작성도구 제출인) | `footnote_extractor.py` **1차 소스** (내용연수·성격별) |
| **Arelle** (`arelle-release`, dart-fss 의존) | note-XBRL 태깅 fact + **calculation-linkbase 합계검증** | `footnote_extractor.py`+`validators.py` — 표준 합계검증 |
| **chrisryugj/korean-dart-mcp** (MIT, 83★) | 15-tool MCP, XBRL summation validation, `kordoc`(HWP/PDF→md) | validators 합계검증 로직 포팅 / MCP 레이어 설계 참고 / kordoc=첨부주석 |
| **FinanceDataReader + sharebook-kr/pykrx** | 유니버스·섹터·시총 / PER·PBR·DIV·재무비율 | (향후)기업 스크리닝 파이프라인 |
> ⚠️ **주석 테이블 구조화 추출은 모든 OSS의 공백** = 우리 차별점. dart-fss(FS)+Arelle(주석 파싱) 조합하고 **4종 검증 레이어는 자체 구축**. XBRL 미제출인은 HTML 주석 스크레이핑 fallback.

### DCF 엔진·xlsx·LLM
| 프로젝트 | 무엇 | 우리 모듈 매핑 |
|---|---|---|
| **Damodaran `fcffsimpleginzu.xlsx`** | 정본 FCFF DCF 스프레드시트 | calc_core **정확성 오라클**(비올 골든과 병행 diff) |
| **JerBouma/FinanceToolkit** (MIT, 5.1k★) | WACC·EV·200+지표를 재무제표에서 자동, "모든 계산=검사가능 함수" | calc_core 함수 분해 ethos + WACC/EV API 시그니처 참고 |
| **modeleonai/modeleon** (Apache-2.0) | Python 작성→**살아있는 엑셀 수식** 방출(`=A1*B2`), 의존그래프 추적 | `xlsx_writer.py` **핵심 블루프린트**(fork/study) |
| **anthropics/skills xlsx** | openpyxl 규약(input=파랑/formula=검정/링크=초록, `$B$6` 절대참조), recalc→0에러 검증 | `xlsx_writer.py` 규약 + CI 게이트 |
| **dgorissen/pycel** (GPL-3.0) / **bradbase/xlcalculator** | 방출 xlsx 헤드리스 재평가(수식↔파이썬 일치 검증) | export 왕복검증 — **pycel은 외부 CI 전용**(copyleft) |
| **AI4Finance/FinRobot** (Apache-2.0, 7.6k★) | 순수 Python operator(계산) vs LLM(서사) **하드 분리** + bull/bear/judge | 우리 "결정론 엔진→AI 얹기" 논지의 검증된 선례; assist/auditor 설계 |
| **EmanueleSturzo/DCF-Valuation-Model** (Streamlit) | 민감도 히트맵 + valuation-bridge 차트 | frontend 민감도·EV→equity 시각화 |
> ⚠️ 라이선스: **pycel GPL-3.0**(제품 링크 금지, 외부 도구만), **halessi/DCF 무라이선스**(사용 불가). 안전 벤더링 코어 = FinanceToolkit·modeleon·FinRobot.

## 검증 (Verification)

1. **Milestone 1**: `pytest tests/golden/` — 비올 셀 단위 일치. 실패 시 어느 시트/셀에서 갈라지는지 진단. **이중 오라클**: 비올 원본 엑셀 + Damodaran `fcffsimpleginzu` 로직 diff로 terminal value·reinvestment 링크 교차검증.
2. **Export 왕복 검증**: 방출 xlsx를 pycel/xlcalculator(외부 CI)로 헤드리스 재계산 → 파이썬 엔진 수치와 일치 + anthropics xlsx skill식 `#REF!/#DIV0!` 0에러 assert.
3. **Ingestion(정형)**: 비올 DART 정형 API로 적재된 H_FS 계정값이 수작업 H_FS와 일치.
4. **주석 추출·검증(핵심)**: 비올 사업보고서 주석에서 뽑은 유형·무형 내용연수·판관비 성격별이 원본 엑셀 FA/EBIT 입력과 일치. `validators.py` 4종이 실제로 물리는지 —
   - 숫자형: 콤마·괄호음수·단위 정규화 라운드트립.
   - 공백: 결측 셀이 `warn`으로 잡히는지.
   - 합계: 성격별 Σ ≠ 표기합계인 조작 케이스가 `fail`.
   - 정합성: 주석 감가상각비 ≠ CF D&A 인 조작 케이스가 `fail`.
   - provenance: 각 추출값 `source[start:end]==raw` 불변식 테스트 통과.
5. **감사인 트랙**: 의도적으로 왜곡한 가정(예: g=2%→4%, 내용연수 축소)을 넣은 의견서를 통과시켜 "유의적 차이"·tie-out 실패가 탐지되는지 확인.

## 열린 항목 (구현 착수 시 확정)

- ✅ 확정: 프론트=React+Vite/Vercel, 백엔드=FastAPI/Railway·Render, DB=Supabase Postgres, 벡터=pgvector(MVP), 임베딩=Gemini API.
- Railway vs Render 최종 택1(무료티어·콜드스타트 비교) — 배포 착수 시.
- OpenDART API 키 발급 및 rate-limit 정책; 비올이 주석 XBRL 제출인인지 확인(아니면 HTML 스크레이핑 fallback).
- `xlsx_writer.py`: modeleon fork vs openpyxl 직접(수식 문자열 관리) — modeleon 성숙도 평가 후.
- 주석 검증 합계로직: Arelle calculation-linkbase 재사용 vs 자체 구현 — 비올 XBRL 구조 확인 후.
- pgvector 스케일 한계 도달 시 Qdrant 이전(`retrieve.py` 추상화로 대비).
