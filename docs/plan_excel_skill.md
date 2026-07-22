# Excel 밸류에이션 워크플로우 스킬 — 구현 계획 (Implementation Plan)

| 항목 | 내용 |
|------|------|
| **문서 ID** | PLAN-EXCEL-SKILL-001 |
| **버전** | 1.0 |
| **작성일** | 2026-07-18 |
| **상태** | 문서 확정 대기 (착수 게이트) |
| **명세** | [skill_excel_workflow_spec.md](skill_excel_workflow_spec.md) |
| **관련** | [plan.md](plan.md) · [prd_excel_addin.md](prd_excel_addin.md) |

---

## 0. 착수 순서 원칙

> **문서 먼저, 코드 나중.** 명세([skill_excel_workflow_spec.md](skill_excel_workflow_spec.md))와 본 계획을 사용자가 리뷰·확정한 뒤에야 §2 코드에 착수한다. 문서가 구현의 게이트다.

**리스크 우선 착수 순서**: `fs_clean.py`+테스트(유일 실질 신규 알고리즘) → 나머지 래퍼·빌드 → 문서(SKILL/references) → PRD 정정.

---

## 1. 대상 레포·전제

- **작업 레포**: `D:\valuation-platform` (현재 CWD인 gfdsstyu.github.io와 별개).
- **엔진은 재구현 아님**: `calc_core`·`backend/excel`·`backend/rag`는 완성·골든 검증 상태 → **vendoring(복사) 재사용**.
- **샌드박스 호환 확정**: 위 3모듈 + `ingest/validators.py` 전부 표준 라이브러리(Python 3.11+).
- **민감도**: 엔진 3×3(내부 앵커) 유지, 워크북 리포트 그리드는 5×5(살아있는 수식) — 두 개념 분리(명세 1.4c).

---

## 2. 파일별 작업

### 2.0 상세 MD 문서화 (완료 — 착수 게이트)

- ✅ `docs/skill_excel_workflow_spec.md` — 정식 명세 (1~4장)
- ✅ `docs/plan_excel_skill.md` — 본 문서
- ⬜ **0-c 사용자 리뷰·확정** → 확정 후 2.1 착수

### 2.1 빌드 스크립트

**`scripts/build_excel_skill.py`** (레포 루트):
- 빌드 전 `docs/reference/ontology/build.py` 재실행 (온톨로지 drift 방지).
- **vendor 복사**: `backend/calc_core/` → `scripts/vendor/calc_core/`, `ingest/validators.py`, `excel/{xlsx_writer,xlsx_reader,dcf_export,dcf_import,workbook_diff}.py`, `backend/rag/{searcher,embedder,__init__}.py`, `docs/reference/ontology/{graph,rag_index}.json` + `docs/reference/*.md`.
- **references 복사**: 1.5 표 매핑대로 `docs/reference/*.md` → 스킬 `references/`. `account_dictionary.md` 생성(타사 §2 taxonomy 기반 표준 계정 사전·동의어). `template_conventions.md` 편집 생성(Val-Studio 시트 아키텍처 1.3b 정본 + 색상 규약 + 함수 화이트리스트).
- **패키징**: `dist/excel-valuation-workbook.zip`.
- **SHA256 동기 매니페스트**: vendor ↔ backend 원본 해시 기록(테스트에서 drift 검사).

### 2.2 스킬 래퍼 (`.claude/skills/excel-valuation-workbook/scripts/`)

| 스크립트 | 출처 | 작업 |
|----------|------|------|
| `dcf.py`·`wacc.py`·`audit.py` | valuation-analysis 원형 복사 | `_find_backend()` → `sys.path.insert(0, vendor)` 교체 |
| `scenario.py` | 신규 | stdin `{"cases":{...},"weights":{...}?}` → `run_scenarios` → rows·spread·weighted_per_share JSON |
| `scaffold.py` | 신규 | stdin `DcfSpineInput` → `run()` → `build_dcf_sheet` → `--xlsx` 파일 또는 `--emit-cells` JSON + `_VS_STATE` 생성 |
| `fs_clean.py` ⚠️ | 신규 | stdin FS 원문 → 정규화·당기/전기 교차검증·BS대차·연도간 재분류 추적 후보 → 무결성 이슈 리포트 JSON (명세 1.4b) |
| `roundtrip.py` | 신규 | xlsx 경로 → `import_dcf_model` → 재계산 → 원 입력/결과 대조 JSON (+ 옵션 `diff_workbooks` 3버킷) |
| `book_search.py` | valuation-analysis 원형 복사 | vendor/rag `BookSearcher()` lexical 폴백 (명세 1.5b) |

**`fs_clean.py` 알고리즘 상세**(리스크 집중):
1. 값 정규화(콤마·통화·괄호음수·공백·단위 감지)
2. 당기/전기 구조 파싱 → `{year: {account: value}}`
3. 당기/전기 교차 대조(불일치=재분류 흔적)
4. BS 대차·소계·PL 합계 검산
5. 재분류 추적 후보(금액 보존 매칭) — **1:1·1:다까지만 결정론 후보, 다대다는 미해결 표면화**(시간·정확도 균형)

### 2.3 SKILL.md

명세 1.9 골격대로 저술. 역할 3분할·이중 환경·시작 모드·성장 아키텍처·단계표+게이트·자료 요청 프로토콜·지식 바인딩·추천 모델·provenance·상태 규약·키 원칙·도구 사용법·신뢰 원칙.

### 2.4 references/

- `index.md` — 단계↔지식 바인딩 색인(1.5 표), 참고 모델 복제 금지 명시.
- `template_conventions.md` — 2.1 빌드가 생성(소스는 build 스크립트 내 문자열/편집 로직).
- `account_dictionary.md` — 2.1 빌드가 생성.
- 1.5 표 원본 md 복사(기업리서치_양식·참고보고서_활용 등 포함).

### 2.5 테스트 (`tests/skill/`)

| 테스트 | 검증 |
|--------|------|
| `test_skill_dcf_golden.py` | fixtures/viol/inputs.json → 스킬 `dcf.py` 서브프로세스 → per_share **8413.380552** (rel_tol 1e-6), 레포 backend 임포트 없이(환경 격리) 동작 |
| `test_skill_scaffold_roundtrip.py` | scaffold `--xlsx` → `roundtrip.py` → 입력 복원·per_share 일치, `_VS_STATE` 존재 |
| `test_vendor_sync.py` | vendor 해시 == backend 원본 해시 (drift 감지) |
| `test_fs_clean.py` | 재분류 섞인 다연도 FS 샘플 → 당기/전기 교차 불일치·재분류 추적 후보 정상 출력 |

### 2.6 PRD 정정

`docs/prd_excel_addin.md`: 명세 3장 3건(5×5→3×3 병기·CORS 주석·벤치마크 행).

### 2.7 .gitignore

`scripts/vendor/`, `.claude/skills/excel-valuation-workbook/dist/` 추가.

---

## 3. 검증 (Verification)

1. `python scripts/build_excel_skill.py` → vendor·references·zip 생성 확인.
2. **레포 격리 실행**(임시 디렉터리에 스킬만 복사): `type fixtures\viol\inputs.json | py -3.12 .claude/skills/excel-valuation-workbook/scripts/dcf.py` → per_share 8413.380552…, findings에 terminal_reinvestment 등.
3. `py -3.12 -m pytest tests/skill -q` 전체 PASS + 기존 골든(`tests/golden/`) 회귀 PASS.
4. scaffold 산출 xlsx를 실제 Excel에서 열어 수식(`<f>`) 살아있음 확인 (수동).
5. dist zip을 Claude for Excel(조직 스킬) 업로드 → 백지 워크북에서 `/excel-valuation-workbook` → B모드 스캐폴딩·W0 게이트 동작 (수동, 사용자).
6. 스크립트 실행 불가 환경 폴백: SKILL.md 지시문만으로 W6 DCF tie-out이 "미검증" 라벨 남기는지 시나리오 리뷰.
7. `fs_clean.py` 단위 검증(2.5 `test_fs_clean`).

---

## 4. 소요시간 추정 (클로드 코드 기준)

### 페이즈1 (이번 구현)

| 워크스트림 | 예상 |
|-----------|------|
| 빌드·번들링 + `.gitignore` | 2~3h |
| 래퍼 복사형(dcf/wacc/audit/book_search) | 1~2h |
| `scaffold.py` | 2~3h |
| **`fs_clean.py`** ⚠️ 유일 실질 알고리즘 | 4~6h |
| `roundtrip.py`·`scenario.py` | 2h |
| 문서 저술(SKILL·template_conventions·account_dictionary·index) | 3~5h |
| 테스트 | 2~3h |
| PRD 정정 | 1~2h |
| **합계** | **≈ 1.5~2.5 집중일** |

### 페이즈2 (다음 사이클)

| 워크스트림 | 예상 |
|-----------|------|
| API 라우트 3종(export/import/diff) | 3~4h |
| **apply-정책 엔진** ⚠️ (diff 3버킷 → 모델 반영) | 4~6h |
| React diff 리뷰 패널 | 4~6h |
| 프로젝트 왕복 통합 + 테스트 | 3~4h |
| **합계** | **≈ 2~3.5 집중일** |

### 종합

| | AI 집중 | 실전 검증(달력) |
|---|---|---|
| 페이즈1 | 1.5~2.5일 | +사람검증 며칠 |
| 페이즈2 | 2~3.5일 | +왕복 E2E 며칠 |
| **코어** | **≈ 4~6일** | |

**사람·환경 의존**(AI 실작업 아님): Claude for Excel 조직 스킬 업로드·E2E, recalc 게이트(LibreOffice) 셋업, 애드인 내 스크립트 실행 가부 확인, 풀모델 성장 프롬프트 튜닝, 실제 xlsx 왕복 E2E(외부 파일·병합셀·외부링크 함정).

---

## 변경 이력

| 버전 | 날짜 | 변경 |
|------|------|------|
| 1.0 | 2026-07-18 | 초안 — 구현 로드맵·파일별 작업·검증·소요시간 |
