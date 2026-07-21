# PRD — Excel Office Add-in MVP (로컬 HTML → 웹 Excel / MS Excel 연동)

| 항목 | 내용 |
|------|------|
| **문서 ID** | PRD-EXCEL-ADDIN-001 |
| **버전** | 1.0 |
| **작성일** | 2026-07-17 |
| **상태** | Draft → 구현 착수 대기 |
| **관련 문서** | [plan.md](plan.md) · [ia_ux_architecture.md](ia_ux_architecture.md) · [engine_spec.md](engine_spec.md) · [앤트로픽_금융스킬_벤치마크](reference/앤트로픽_금융스킬_벤치마크.md) |

---

## 1. 배경 및 목적

### 1.1 왜 이 PRD인가

Val-Studio(valuation-platform)는 참고 모델 기업가치평가 DCF 워크플로우를 **결정론적 Python 엔진(`calc_core`)** + **로컬 FastAPI/React SPA**로 구현 중이다. 실무자의 작업 환경은 **Excel(데스크톱·웹 Excel)** 이며, “웹에 올린다”와 “Excel과 연동한다”는 서로 다른 목표로 자주 혼동된다.

본 PRD는 **현재 로컬 HTML MVP에서 Excel Office Web Add-in을 배포 가능한 수준까지 올리는** 범위·아키텍처·일정·검증 기준을 한 문서로 고정한다.

### 1.2 제품 목표 (한 문장)

> **Excel Online 및 Microsoft 365 Excel(데스크톱) 안에서 Task Pane Add-in으로 DCF 계산·검증을 수행하고, 기존 FastAPI `calc_core`를 SSOT(단일 진실 원천)로 유지한다.**

### 1.3 비목표 (본 PRD 범위 밖)

- VSTO/COM 기반 Windows 전용 플러그인
- AppSource(Office Store) 공개 출시 및 Microsoft 상용 심사
- DART/RAG/LLM 전 단계 UI (Phase 2~3)
- Office.js 없이도 불가능한 **Named Range 양방향 동기화·왕복 diff UI** (v2)
- 로컬 파일 경로 기반 인제스트 (Excel Online 샌드박스와 불가)

---

## 2. 용어 정리 — “웹” 세 가지

혼동 방지를 위해 본 PRD에서 사용하는 용어를 고정한다.

| 용어 | 정의 | 본 프로젝트에서의 역할 |
|------|------|------------------------|
| **① 우리 웹앱** | Vercel 등 HTTPS에 호스팅된 React SPA | DCF UI·BYOK·(후일) 프로젝트 허브 |
| **② 웹 Excel** | `excel.office.com` — Microsoft가 제공하는 브라우저 Excel | Add-in **호스트(容器)** |
| **③ Office Add-in** | ②(또는 PC Excel) **내부 Task Pane**에 ①을 임베드 | **“Excel 연동”의 정식 의미** |

```
[Level 0 — 현재 로컬 MVP]
  브라우저 localhost:5173 → Vite React → /api/dcf → calc_core
  Excel과 무관 (수동 복붙·xlsx 파일)

[Level 1 — 본 PRD MVP Must]
  Excel 창 = MS 시트 + Task Pane(①과 동일 URL)
  패널에서 입력·계산·결과 표시 — 시트 자동 연동 없음

[Level 2 — PRD Should / v1.1]
  Office.js: 선택 Range 읽기 → API, (선택) 결과 Range 쓰기

[Level 3 — v2]
  xlsx export/import API, workbook_diff, template_schema Named Range
```

**결론:** “웹에 올리기(① HTTPS 배포)”는 “Excel 연동(③)”의 **선행 조건**이다. 둘 다 필요하지만 동일하지 않다.

---

## 3. 현재 상태 (As-Is)

### 3.1 구현 완료 ✅

| 레이어 | 경로 | 상태 |
|--------|------|------|
| DCF 스파인 | `backend/calc_core/dcf.py` 등 | ✅ 비올 골든 검증 |
| 상류 엔진 | `revenue`, `wacc`, `fa`, `wc` … | ✅ 단위 테스트 |
| Excel export/import | `backend/excel/dcf_export.py`, `dcf_import.py` | ✅ stdlib, 수식 live |
| Workbook diff | `backend/excel/workbook_diff.py` | ✅ 3버킷 분류 |
| 로컬 API | `backend/api/main.py` | ✅ `/api/dcf`, `/api/scenario`, `/api/projects`, BYOK |
| React UI | `frontend/src/App.jsx` | ✅ DCF 계산기, BYOK, 민감도·audit findings |
| Dev 프록시 | `frontend/vite.config.js` | ✅ `/api` → `:8000` |

### 3.2 미구현 ⬜ (Add-in 관련)

| 항목 | 비고 |
|------|------|
| `manifest.xml` | Office Add-in 등록 파일 |
| `add-in/` 디렉터리 | (선택) 전용 빌드; MVP는 기존 `frontend` URL 재사용 가능 |
| HTTPS 프로덕션 배포 | Vercel + Railway/Render |
| `/api/xlsx/export` | `export_dcf` Python 함수는 있으나 API 미노출 |
| Office.js 연동 | Range 읽기/쓰기 |
| Task Pane 레이아웃 (`?embed=1`) | ~350px 폭 대응 |
| M365 중앙 집중식 배포 | 관리센터 sideload |

### 3.3 로컬 실행 방법 (기준선)

```bash
# 터미널 1 — API
py -3.12 -m uvicorn backend.api.main:app --reload

# 터미널 2 — 프론트 (또는 dist 빌드 후 API 정적 서빙)
cd frontend && npm run dev
```

- DCF 화면: `http://localhost:5173` (DCF 탭)
- API 문서: `http://127.0.0.1:8000/api/docs`

---

## 4. 목표 상태 (To-Be) — 연동 수준

### 4.1 MVP Must (v1.0) — **Level 1**

**Excel 안에 우리 DCF 화면이 Task Pane으로 뜨고, `/api/dcf`로 계산·검증 결과를 본다.**

| 기능 | 설명 |
|------|------|
| Add-in sideload / M365 배포 | Excel Online + Desktop Excel에서 실행 |
| Task Pane UI | 기존 `DcfCalculator` (WACC, FCFF 시리즈, EV, 주당가치, findings, 민감도) |
| API 호출 | HTTPS FastAPI `/api/dcf` |
| BYOK | localStorage + `X-Gemini-Key` 헤더 (LLM 단계 전까지 DCF만으로도 동작) |

**시트 연동:** 없음. 사용자는 Excel 시트와 Task Pane을 **수동**으로 맞춘다.

### 4.2 MVP Should (v1.1) — **Level 1.5**

| 기능 | 설명 |
|------|------|
| `GET/POST /api/xlsx/export` | `export_dcf` → `.xlsx` 다운로드 (수식 live) |
| 시나리오 UI | `/api/scenario` (API 존재, UI `soon`) |
| `?embed=1` 레이아웃 | LNB 축소·Task Pane 폭 최적화 |

### 4.3 v1.2 — **Level 2** (Office.js 최소)

| 기능 | 설명 |
|------|------|
| “선택 영역 읽기” | `getSelectedRange().values` → JSON → `/api/dcf` |
| “결과 쓰기” (1개 Range) | API 응답 KPI → 지정 셀 (예: `Summary!B2:B5`) |
| Named Range (고정 5~10개) | WACC, PGR 등 — `template_schema.py` 도입 시 |

### 4.4 v2 — **Level 3**

| 기능 | 설명 |
|------|------|
| xlsx 재업로드 + `workbook_diff` | 3버킷 diff UI |
| Skills 단계별 LLM (Brief, WACC, peer…) | Task Pane 우측 패널 |
| 감사인 트랙 | claimed_per_share gap 진단 UI |
| AppSource 출시 | (선택) |

---

## 5. 사용자 및 시나리오

### 5.1 페르소나

| 페르소나 | 목표 | MVP Must에서의 가치 |
|----------|------|---------------------|
| **평가 실무자** | Excel 옆에서 DCF sanity check | Task Pane 계산·TV WARN·민감도 |
| **참고 모델 수강생** | 연수 모델과 숫자 대조 | 비올 골든 입력 → 주당가치 검증 |
| **감사인 (후일)** | 의견서 주장 vs 독립 재계산 | `claimed_per_share` + gap_diagnosis |

### 5.2 Must MVP 사용자 스토리

1. **US-01** Excel Online에서 “Val-Studio DCF” Add-in을 연다.
2. **US-02** Task Pane에 WACC·5년 FCFF 등을 입력하고 “DCF 계산”을 누른다.
3. **US-03** 주당가치·EV·TV 비중·audit findings(WARN/FAIL)를 확인한다.
4. **US-04** 3×3 민감도표(WACC×g, 엔진 내장)에서 base 셀(중앙)이 base 가정과 일치함을 확인한다.
5. **US-05** (Should) “xlsx 내보내기”로 수식 live 파일을 받아 같은 워크북 또는 새 파일에서 연다.

### 5.3 v1.2 사용자 스토리 (Office.js)

6. **US-06** 시트에서 매출 5년 Range를 선택 → “가져와서 계산” → Task Pane에 반영.
7. **US-07** 계산 후 “요약 셀에 쓰기” → Cover 시트 B2:B5에 KPI 기록.

---

## 6. 시스템 아키텍처

### 6.1 MVP Must 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│ Microsoft 365 Excel (Web excel.office.com / Desktop)        │
│  ┌──────────────────────┐  ┌─────────────────────────────┐  │
│  │ 워크시트 (MS)         │  │ Task Pane (Chromium WebView)│  │
│  │ 사용자 DCF 모델       │  │ https://app.valstudio.example│  │
│  │ (수동 편집)           │  │  /?embed=1  → React SPA     │  │
│  └──────────────────────┘  └──────────────┬──────────────┘  │
└──────────────────────────────────────────│──────────────────┘
                                           │ HTTPS fetch
                                           ▼
                              ┌────────────────────────────┐
                              │ FastAPI (Railway/Render)    │
                              │ POST /api/dcf               │
                              │ POST /api/scenario          │
                              │ GET  /api/health            │
                              └──────────────┬─────────────┘
                                             │
                                             ▼
                              ┌────────────────────────────┐
                              │ calc_core (결정론, SSOT)    │
                              │ audit_dcf · run · scenario  │
                              └────────────────────────────┘
```

### 6.2 manifest.xml 역할

Excel에 **“Task Pane URL = 우리 HTTPS 앱”** 을 등록한다. Add-in 본체는 **별도 바이너리가 아니라 웹 페이지**이다.

필수 manifest 요소 (개략):

- `<Id>` — GUID (배포 후 변경 금지)
- `<ProviderName>`, `<DisplayName>`, `<Description>`
- `<AppDomains>` — API 도메인 (CORS·iframe 정책)
- `<DefaultSettings>` → `<SourceLocation DefaultValue="https://.../?embed=1"/>`
- `<Permissions>ReadWriteDocument</Permissions>` — Level 1만이면 `ReadDocument`로 시작 가능, Level 2부터 ReadWrite

### 6.3 SSOT 원칙

| 계층 | SSOT | Excel의 역할 |
|------|------|--------------|
| 숫자 계산 | Python `calc_core` | 표시·(선택) 입력 소스 |
| 수식 live 모델 | `export_dcf` xlsx | 감사 추적 산출물 |
| LLM 가정 제안 | (후일) RAG + Skill | 제안만; 검증은 validators |

**금지:** Task Pane JavaScript에서 FCFF·EV를 직접 계산하지 않는다.

---

## 7. 기능 요구사항

### 7.1 FR-M1 — Add-in 등록 및 실행

| ID | 요구사항 | 우선순위 |
|----|----------|----------|
| FR-M1.1 | `manifest.xml`이 Excel Online·Desktop Excel 2016+에서 sideload 가능 | Must |
| FR-M1.2 | M365 관리 센터 “통합 앱”으로 테넌트 배포 가능 | Must |
| FR-M1.3 | Add-in 아이콘·표시명 “Val-Studio DCF” (가칭) | Must |
| FR-M1.4 | `/api/health` 실패 시 Task Pane에 연결 오류 배너 | Must |

### 7.2 FR-M2 — DCF Task Pane

| ID | 요구사항 | 우선순위 |
|----|----------|----------|
| FR-M2.1 | `DcfSpineInput` 필드 전부 입력 가능 (App.jsx `DEMO`/`FIELD_LABELS` 동일) | Must |
| FR-M2.2 | 연도 수 불일치 클라이언트 검증 | Must |
| FR-M2.3 | 결과: `per_share`, `enterprise_value`, `equity_value`, `tv_weight` | Must |
| FR-M2.4 | `findings[]` severity별 표시 (pass 제외 또는 접기) | Must |
| FR-M2.5 | 민감도 3×3(WACC×g, 엔진 `dcf.run` 내장, step ±1%p), 중앙 셀 base 하이라이트 (`center-cell` CSS) | Must |
| FR-M2.6 | `claimed_per_share` 입력 시 `gap_diagnosis` 표시 | Must |

> **민감도 3×3 vs 5×5 (엔진 내장 ≠ 워크북 리포트)**: 엔진 `dcf.run`의 내장 민감도는 **3×3(WACC×g)** — 중심셀 == base 자기일관성 검증용(내부 앵커). 반면 `excel-valuation-workbook` 스킬이 워크북에 만드는 리포트 그리드는 **5×5(WACC×PGR) 살아있는 수식**으로, 외곽 셀은 Excel recalc가 검증한다. Add-in Task Pane은 엔진 3×3을 표시. 상세: [skill_excel_workflow_spec.md](skill_excel_workflow_spec.md) §1.4c.
| FR-M2.7 | `?embed=1` 시 LNB/헤더 축소, min-width ~320px | Should |

### 7.3 FR-M3 — API 및 배포

| ID | 요구사항 | 우선순위 |
|----|----------|----------|
| FR-M3.1 | 프론트 HTTPS (Vercel 등) | Must |
| FR-M3.2 | API HTTPS (Railway/Render) | Must |
| FR-M3.3 | CORS: manifest `<AppDomains>` + API `allow_origins` | Must |
| FR-M3.4 | 프론트 `VITE_API_BASE` env로 API 베이스 URL 분리 | Must |
| FR-M3.5 | `POST /api/xlsx/export` — body: DcfSpineInput 또는 계산 결과 포함 | Should |

### 7.4 FR-M4 — Office.js (v1.2, Must 아님)

| ID | 요구사항 | 우선순위 |
|----|----------|----------|
| FR-M4.1 | `Office.onReady` 초기화 | v1.2 |
| FR-M4.2 | 선택 Range → 2D array → API | v1.2 |
| FR-M4.3 | KPI → Named Range 또는 고정 Address | v1.2 |
| FR-M4.4 | merged cell·빈 선택 예외 메시지 | v1.2 |

### 7.5 비기능 요구사항

| ID | 요구사항 |
|----|----------|
| NFR-1 | API 키(BYOK) 서버 디스크·로그 저장 금지 (현행 유지) |
| NFR-2 | Add-in 첫 로드 3초 이내 (Task Pane HTML, gzip) |
| NFR-3 | `/api/dcf` p95 < 500ms (로컬 calc_core, LLM 없음) |
| NFR-4 | 골든 회귀: `test_viol_spine`, `test_xlsx_export` CI PASS 유지 |

---

## 8. API 명세 (Add-in MVP 추가·노출)

### 8.1 기존 (변경 없음)

#### `POST /api/dcf`

Request body: `DcfSpineInput` JSON (+ optional `claimed_per_share`)

Response: `per_share`, `enterprise_value`, `findings`, `sensitivity`, optional `gap_diagnosis`

#### `POST /api/scenario`

Request: `{ "cases": { "Base": {...}, ... }, "weights": {...}? }`

#### `GET /api/health`

Response: `{ "ok": true, "engine": "calc_core" }`

### 8.2 신규 (Should — v1.1)

#### `POST /api/xlsx/export`

**Request:** 동일 `DcfSpineInput` (서버에서 `run()` 후 export)

**Response:** `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`  
`Content-Disposition: attachment; filename="valstudio_dcf.xlsx"`

**구현:** `calc_core.run` → `excel.export_dcf(inp, res, tmp_path)` → `FileResponse`

#### `POST /api/xlsx/diff` (v2)

**Request:** multipart — `before.xlsx`, `after.xlsx`  
**Response:** `workbook_diff.diff_workbooks` JSON (3버킷)

---

## 9. UI/UX — Task Pane (`embed` 모드)

### 9.1 레이아웃 (Should)

`?embed=1` 쿼리 시:

- LNB 숨김 또는 아이콘-only
- 헤더: 로고 + “DCF” + 연결 상태 점
- 본문: 입력 카드 → 결과 KPI → findings → 민감도 (세로 스크롤)
- 하단 시트탭 숨김

### 9.2 디자인 토큰

[design_system.md](design_system.md), [brand_color_palette.md](brand_color_palette.md) 준수.  
Task Pane은 **액션 버튼·활성·KPI hero**에만 버건디 — 기존 웹과 동일.

### 9.3 Excel 메타포 유지

[ia_ux_architecture.md](ia_ux_architecture.md) §0 “프로젝트=워크북, 화면=시트” — Add-in v1은 **단일 화면(DCF)** 만.  
v2에서 LNB 단계를 Task Pane 탭으로 확장.

---

## 10. 배포 및 운영

### 10.1 환경

| 환경 | 프론트 | API | manifest |
|------|--------|-----|----------|
| **Local dev** | `https://localhost:5173` (Office dev certs) | `:8000` | sideload `manifest.xml` |
| **Staging** | `https://staging.valstudio.example` | `https://api-staging...` | 테스트 테넌트 |
| **Prod** | Vercel | Railway/Render | M365 관리 센터 |

### 10.2 Excel Add-in 배포 경로 (MVP)

1. **개발:** `npx office-addin-debugging start manifest.xml` (sideload)
2. **사내 MVP:** Microsoft 365 관리 센터 → 설정 → 통합 앱 → 사용자 지정 앱 추가 → manifest URL
3. **공개 (v2+):** Partner Center → AppSource (본 PRD 비범위)

### 10.3 CORS 설정 (FastAPI)

```python
# 프로덕션 예시 — 프론트 origin(=SourceLocation 도메인)
# 주의: Task Pane fetch 의 Origin 은 SourceLocation URL(우리 앱 도메인)이지 excel.office.com 이 아니다.
#   → allow_origins 의 핵심은 자기 프론트 origin. excel.office.com/outlook.office.com 은 보통 불필요
#   (무해하나 오해 소지). manifest <AppDomains> 는 CORS 가 아니라 Task Pane 내 내비게이션 허용 목록.
allow_origins=[
    "https://app.valstudio.example",   # ← 우리 앱(SourceLocation) — 필수
    # "https://excel.office.com",      # 대개 불필요(호스트가 fetch Origin 아님)
]
allow_headers=["*", "X-Gemini-Key", "X-Anthropic-Key"]
```

로컬 sideload 시 `https://localhost:5173` 추가.

### 10.4 디렉터리 구조 (권장)

```
valuation-platform/
├── backend/                 # FastAPI + calc_core + excel (기존)
├── frontend/                # React SPA — embed 모드 추가
├── add-in/                  # (신규, v1.0)
│   ├── manifest.xml         # SSOT for Office registration
│   ├── manifest.staging.xml
│   └── README.md            # sideload·배포 runbook
└── docs/
    └── prd_excel_addin.md   # 본 문서
```

**MVP 단순화:** `add-in/manifest.xml`만 추가하고 Task Pane URL은 `frontend` 배포 URL을 가리켜도 됨. 별도 `add-in/src`는 v1.2 이후 검토.

---

## 11. Skills · Claude Code 워크플로우 (구현 순서)

한 번에 “플러그인 전체”를 요청하지 않고 **아래 Phase를 순서대로** 진행한다.  
(Anthropic financial-services / dcf-model 스킬의 “단계별 confirm”과 동형)

| Phase | 산출물 | Claude Code / Skill 역할 | 사람 필수 |
|-------|--------|--------------------------|-----------|
| **P0** | 본 PRD 리뷰·범위 확정 | — | ✅ |
| **P1** | `manifest.xml` + sideload 성공 | GUID·XML·`<AppDomains>` 생성 | Excel에서 띄워보기 |
| **P2** | Vercel/Railway 배포 + CORS | Dockerfile, env, vite `VITE_API_BASE` | 계정·도메인 |
| **P3** | `?embed=1` Task Pane UI | CSS·조건부 LNB | Excel Online 폭 확인 |
| **P4** | `/api/xlsx/export` | FastAPI 라우트 + 테스트 | xlsx Excel에서 열기 |
| **P5** | M365 관리 센터 배포 runbook | 문서화 | IT 관리자 |
| **P6** | Office.js Range 읽기/쓰기 | `Excel.run` 보일러플ate | v1.2 |
| **P7** | diff API + UI | workbook_diff 래핑 | v2 |

### 11.1 Phase별 프롬프트 템플릿 (P1 예시)

```
[역할] Excel Web Add-in manifest 전문가.
[컨텍스트] FastAPI https://api.example.com, Task Pane URL https://app.example.com/?embed=1
[요청] Excel Online sideload용 manifest.xml만 작성. Permissions=ReadDocument(MVP).
[제약] 다음 Phase는 sideload 확인 후 진행.
```

---

## 12. 일정 및 리소스

### 12.1 Must MVP (Level 1)

| 역할 | AI 적극 활용 | 1명 단독 (AI 보조) |
|------|:------------:|:------------------:|
| P1 manifest + sideload | 0.5일 | 1일 |
| P2 HTTPS 배포 | 0.5~1일 | 1~2일 |
| P3 embed UI | 0.5일 | 1일 |
| Excel Online 검증 | 0.5~1일 | 1~2일 |
| **합계** | **1.5~2.5일** | **3~5일** |

### 12.2 Should (+ xlsx export, 시나리오 UI)

| | AI 적극 | 1명 |
|--|:-------:|:---:|
| 추가 | +1~2일 | +2~3일 |
| **Must+Should** | **4~6일** | **1~2주** |

### 12.3 AI가 단축하지 못하는 항목

- M365 관리 센터 클릭·권한
- Excel Online manifest 캐시 갱신 대기
- 실제 테넌트 sideload 디버깅
- AppSource 심사 (v2+)

---

## 13. 검증 및 완료 기준

### 13.1 Must MVP Definition of Done

- [ ] Excel **Online**에서 Add-in Task Pane 로드
- [ ] Excel **Desktop** (Microsoft 365)에서 동일 manifest 동작
- [ ] 데모 입력 → `/api/dcf` → 주당가치·EV·findings·민감도 표시
- [ ] `fixtures/viol/inputs.json` 동등 입력 시 주당가치 **8,413.38원** (rel_tol 1e-6) — 수동 또는 E2E
- [ ] TV 비중 WARN 등 `audit_dcf` findings 노출
- [ ] BYOK 키가 서버 로그에 남지 않음 (코드 리뷰)
- [ ] `pytest -q` + `test_viol_spine` PASS

### 13.2 Should 추가 DoD

- [ ] `/api/xlsx/export` 파일이 Excel에서 열리고 DCF 시트 수식 존재 (`<f>` 태그)
- [ ] `test_xlsx_export.py` PASS 유지

### 13.3 v1.2 DoD (Office.js)

- [ ] 선택 5×1 숫자 Range → Task Pane 폼 채움
- [ ] “요약 쓰기” → 지정 4셀 KPI 기록
- [ ] 빈 선택·문자열 혼입 시 사용자 메시지

---

## 14. 리스크 및 완화

| 리스크 | 영향 | 완화 |
|--------|------|------|
| manifest/AppDomains 오타 → Add-in blank | 높음 | P1에서 sideload만 먼저; health 배너 |
| CORS 차단 | 높음 | Staging에서 fetch 테스트; AppDomains 이중 등록 |
| Excel Online merged cell | 중 | MVP Must는 Office.js 미사용 |
| localhost sideload vs prod URL 불일치 | 중 | manifest 환경별 파일 분리 |
| `{=TABLE}` 민감도 | 낮 (export) | stdlib writer는 고정 그리드; TABLE 미사용 |
| 외부링크 xlsx `#REF!` | 중 | import 시 경고 ([plan.md](plan.md) §xlsx 규약) |
| 로컬 경로 인제스트 기대 | 중 | PRD·UI에 “Add-in은 업로드만” 명시 |

---

## 15. 보안 및 개인정보

- BYOK: 클라이언트 localStorage, 헤더 전달만 ([backend/api/main.py](../backend/api/main.py))
- MVP: 사용자 재무 데이터는 **요청 body**로 API 전송 — HTTPS 필수
- 로그: request body 전체 로깅 **금지**
- AppSource (후일): 개인정보 처리방침 URL, 데이터 보관 기간 명시

---

## 16. 로드맵 요약

```
v1.0 Must  ──► Task Pane DCF + HTTPS + M365 sideload     [본 PRD]
v1.1 Should ─► xlsx export + embed UI + 시나리오 탭
v1.2       ──► Office.js Range read/write (최소)
v2.0       ──► xlsx diff, template_schema, Skills LLM 단계
v3.0       ──► AppSource, 감사인 full track, RAG ingest in Add-in
```

---

## 17. 오픈 질문

| # | 질문 | 결정 필요 시점 |
|---|------|----------------|
| OQ-1 | Add-in 표시명·아이콘 최종 (Val-Studio vs 참고 모델 연수 브랜드) | P1 전 |
| OQ-2 | API/앱 도메인 (`valstudio.*` vs 임시 Vercel URL) | P2 전 |
| OQ-3 | MVP 배포: 개인 sideload vs 특정 M365 테넌트 | P5 전 |
| OQ-4 | Level 1 Must 출시 후 바로 Office.js(v1.2) vs xlsx export(v1.1) 우선 | Must 완료 후 |
| OQ-5 | `ReadDocument` vs `ReadWriteDocument` manifest 권한 | P1 (Must=ReadDocument 가능) |

---

## 18. 참고 · 벤치마크

| 자료 | 활용 |
|------|------|
| [Microsoft Office Add-ins docs](https://learn.microsoft.com/en-us/office/dev/add-ins/) | manifest, sideload, Excel JS API |
| [앤트로픽_금융스킬_벤치마크](reference/앤트로픽_금융스킬_벤치마크.md) | Office.js vs openpyxl 이중 환경, audit-xls |
| [계정분류_모델아키텍처](reference/계정분류_모델아키텍처.md) | 경쟁 서비스(이메일 xlsx) — 우리는 Add-in+API |
| [모델링_워크플로우_기초](reference/모델링_워크플로우_기초.md) | 입력셀 1곳·색상 규약 → template_schema |
| [excel-valuation-workbook 스킬](skill_excel_workflow_spec.md) | **Claude for Excel 공존·스킬 브리지** — 범용 AI 조작(Claude for Excel) + Val-Studio 결정론 검증(스킬)은 경쟁 아닌 보완. 스킬이 워크북을 결정론 게이트로 감사하고, "미검증" 워크북을 로컬 import→재검증(페이즈2) |
| Yeoman `generator-office` | P1 스캐폴드 (선택) |

---

## 19. 부록 A — manifest.xml 스켈레톤 (P1 시작용)

> **GUID는 배포 전 `uuidgen` 등으로 교체.** URL은 환경별로 치환.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<OfficeApp xmlns="http://schemas.microsoft.com/office/appforoffice/1.1"
           xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
           xsi:type="TaskPaneApp">
  <Id>00000000-0000-0000-0000-000000000000</Id>
  <Version>1.0.0.0</Version>
  <ProviderName>Val-Studio</ProviderName>
  <DefaultLocale>ko-KR</DefaultLocale>
  <DisplayName DefaultValue="Val-Studio DCF"/>
  <Description DefaultValue="DCF 결정론 엔진 · 가정 타당성 검증"/>
  <IconUrl DefaultValue="https://app.example.com/logo.png"/>
  <HighResolutionIconUrl DefaultValue="https://app.example.com/logo@2x.png"/>
  <SupportUrl DefaultValue="https://github.com/your-org/valuation-platform"/>
  <AppDomains>
    <AppDomain>https://app.example.com</AppDomain>
    <AppDomain>https://api.example.com</AppDomain>
  </AppDomains>
  <Hosts>
    <Host Name="Workbook"/>
  </Hosts>
  <DefaultSettings>
    <SourceLocation DefaultValue="https://app.example.com/?embed=1"/>
  </DefaultSettings>
  <Permissions>ReadDocument</Permissions>
</OfficeApp>
```

Level 2(Office.js 쓰기)부터 `ReadWriteDocument`로 상향.

---

## 20. 부록 B — embed 모드 프론트 변경 체크리스트

- [ ] `App.jsx`: `const embed = new URLSearchParams(location.search).has('embed')`
- [ ] `embed === true` → LNB·sheettabs·mode 배지 축소
- [ ] `frontend/src/api.js`: `const API = import.meta.env.VITE_API_BASE ?? ''`
- [ ] `index.html`: (v1.2) `office.js` script defer
- [ ] `styles.css`: `@media (max-width: 400px)` 패드·grid1열

---

## 21. 부록 C — Gemini 대화 vs 본 PRD 정합

| 주제 | 외부 조언 (Gemini 등) | 본 PRD |
|------|----------------------|--------|
| 기술 | Office Web Add-in | ✅ 동일 |
| FastAPI+HTML 재사용 | 가능 | ✅ 동일 |
| Office.js 즉시 양방향 | 1~2일 가정 | **v1.2** (Must 아님) |
| MVP 범위 | 셀 read/write 포함 가능 | **Must = Task Pane only** |
| Skills 워크플로우 분할 | 4단계 프롬프트 | §11 Phase P0~P7 |

**같은 길(Office Add-in), MVP 깊이만 Level 1로 좁힘.**

---

## 변경 이력

| 버전 | 날짜 | 변경 |
|------|------|------|
| 1.0 | 2026-07-17 | 초안 — 로컬 MVP → Excel Add-in MVP PRD |
