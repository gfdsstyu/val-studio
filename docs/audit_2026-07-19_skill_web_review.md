# 감사보고서 — 3축 목표 대비 구현 검토 + 스킬·웹 병용 UX 트레이스

| 항목 | 내용 |
|------|------|
| **문서 ID** | AUDIT-20260719 |
| **작성일** | 2026-07-19 |
| **검토 방법** | 3계열 병렬 정독(스킬 구조 / 프론트 UX / 백엔드 엔진·한국화) + 직접 실측(전체 테스트 실행, 벤치마크 채택목록 코드 대조, xlsx 왕복 E2E 트레이스) |
| **검토 기준** | ① 클로드 스킬화(Anthropic dcf-model 대비 고도화) ② 한국 최적화 ③ 워크플로우 세분화 + 로컬 웹 UX ④ 최초 DCF 모델(비올) 대비 |
| **관련 문서** | [skill_excel_workflow_spec.md](skill_excel_workflow_spec.md) · [ia_ux_architecture.md](ia_ux_architecture.md) · [engine_spec.md](engine_spec.md) · [reference/앤트로픽_금융스킬_벤치마크.md](reference/앤트로픽_금융스킬_벤치마크.md) |

---

## 0. 요약 판정

| 축 | 판정 | 근거 요약 |
|----|------|-----------|
| 스킬 고도화 | ✅ **달성+초과** | 벤치마크 "즉시 채택 목록" 6/6 구현. 결정론 엔진 vendoring·`_VS_STATE`·provenance 대장·recalc 게이트는 Anthropic 원본 스킬에 없는 구조적 우위 |
| 한국 최적화 | ✅ **달성** | 세율·K-IFRS·데이터소스(ECOS/한공회/Kroll/DART/KSIC)·평가규정(자본시장법 합병) 4축 실측 반영. 상증법 보충적평가는 `available=False` 정직 표기 |
| 워크플로우 세분화 | ✅ **달성** | W0~W9(+W2.5) 11단계, 단계별 `제안→판단→검증` 게이트, end-to-end 금지 |
| 로컬 웹 UX | 🔶 **부분 달성** | 평가인 트랙 전 파이프라인 API 관통. 단 판단보조 레이어(§3.2)·감사인 UI·왕복 루프 닫기(§4) 미완 |
| 비올 원본 대비 | ✅ | 스파인 셀단위 재현(8,413.38원, rel_tol 1e-9) + 원본에 없는 감사 가능성(게이트 12룰·diff·provenance) 부가 |

**검토 중 조치**: `test_vendor_sync` 실패 1건 발견(커밋 ec80156의 `calc_core/model.py` 수정 후 스킬 재빌드 누락) → `scripts/build_excel_skill.py` 재실행으로 동기화, 스킬 테스트 69/69 전량 통과 확인. 백엔드 379/379 통과.

---

## 1. 축1 — Anthropic dcf-model 스킬 대비 고도화

[앤트로픽_금융스킬_벤치마크.md](reference/앤트로픽_금융스킬_벤치마크.md) §5 "즉시 채택 목록" 6건 전량 구현 확인:

| # | 채택 항목 | 구현 위치 | 상태 |
|---|-----------|-----------|------|
| 1 | 민감도 중심셀=base 3자일치 게이트 | `backend/excel/sensitivity_grid.py` + `tests/skill/test_sensitivity_grid.py` | ✅ |
| 2 | 수식 내 하드코딩 감지 | `backend/excel/workbook_diff.py` (R1C1 정규화 + 외딴 편집 감지) | ✅ |
| 3 | DCF 특화 버그 5종 감사 | `calc_core/checks.py` `diagnose_dcf_gap` (mid-year 미적용·TV 미할인·TV 누락·비영업 누락·순부채 무시) | ✅ |
| 4 | variance 서사 규격 | `valuation-analysis/SKILL.md` 감사인 트랙 (항목/Driver/Outlook/Action) | ✅ |
| 5 | 단계별 유저 confirm 명문화 | `excel-valuation-workbook/SKILL.md` W0~W9 게이트, end-to-end 빌드 금지 | ✅ |
| 6 | TV 경고 임계 75% 하향 | `calc_core/checks.py:29` `TV_WEIGHT_WARN = 0.75` | ✅ |

**구조적 우위(Anthropic 원본에 없는 것)**:
- **결정론 엔진 vendoring**: 골든 검증된 `calc_core`를 스킬 zip에 동봉(100% stdlib → Claude for Excel 샌드박스에서 실행). 그들 스킬은 지시문+수식 규약뿐 — "LLM이 검산" vs "코드가 검산"의 차이.
- **`_VS_STATE` 상태 규약**: 무상태 스킬 세션의 재개 지점·게이트 이력·가정 대장(provenance)을 워크북 자체에 기록.
- **recalc 게이트**(`scripts/recalc_gate.py`): 캐시 제거 후 LibreOffice 재계산으로 수식 자체를 검증(캐시 echo false-pass 차단).
- **W2 연도간 재분류 추적**(`fs_clean.py` 금액보존 매칭) + **W2.5 손익 세분화**(합보존 게이트) — 원본 스킬에 개념 자체가 없음.
- **SHA256 동기 매니페스트**: vendor drift를 테스트가 잡음(본 검토에서 실제 작동 확인 — §5).

**두 스킬의 역할 분리**(의도적 이원화, 타당): `valuation-analysis` = 레포 네이티브·분석/감사·판단=LLM ↔ `excel-valuation-workbook` = 자기완결 zip·워크북 성장·판단=평가인.

---

## 2. 축2 — 한국 최적화 (4축 전면 반영)

| 축 | 구현 |
|----|------|
| **세율** | `calc_core/tax.py` 구간세율(9/19/21/24%) ×1.1 지방소득세, 원본 DCF!M17 IF수식 그대로 export 이식 |
| **K-IFRS** | 1116 리스(`lease.py` ROU·이자/원금 분리), `fs_mapper.py` 한글계정 사전, 비지배지분 브리지, `account_dictionary.md` 1115/1116 이관 규칙 |
| **데이터** | OpenDART 전 파이프라인(재무·직원현황·XBRL·corpCode) + ECOS(vintage 이중가드) + 한공회 MRP + Kroll decile + Damodaran CRP + KSIC 로컬 2,000코드 + DART PDF 한글 CID→OCR 폴백 + 두벌식 자모 비번 복원 |
| **평가규정** | `merger.py` 자본시장법 기준주가(VWAP 산술평균)·본질가치(자산1:수익1.5)·±30% 밴드, `method_selector.py` 금감원 외부평가 가이드라인·상증세법(미구현은 `available=False` 정직 표기), PGR 한국관행 0~1% |

벤치마크 표의 "한국 규제·실무 정합 우위" 주장이 코드로 뒷받침됨.

---

## 3. 축3 — 워크플로우 세분화 + 로컬 웹 UX

### 3.1 잘 된 것
- 평가인 트랙: 홈 위저드(방법론 결정론 추천) → 0.자료/Brief → 1.계정분류 → 2.가정(4시트) → 3.할인율(peer→WACC 프리필) → 4.밸류에이션 → 5.산출물 **전 파이프라인 API 관통**.
- 세션 5종(footnote·employee·capex·razor·wc) 정위치 배선(CostsSheet·FaSheet·RevenueSheet·DcfSheet).
- 데이터 단방향 흐름(각 시트 → `dcf_input` push), 잠금 대신 게이트 — IA 명세 원칙 일치.

### 3.2 갭 (우선순위순)
1. **감사인 트랙 UI 전무** — nav 10개 시트 전부 `soon:true`. 백엔드(`diagnose_dcf_gap`·`audit.py`·의견서 앵커 추출)는 완비 → 최저비용·최고가치 다음 작업.
2. **IA 명세 §5 판단보조 레이어 미구현**: 필드 3상태 컬러코딩 / 가정별 근거 슬롯(비면 WARN) / LNB 진행표시(✓●○) / 헤더 게이트 요약 / 우측 패널 AI 제안→채택 반영(현재 읽기전용).
3. **DcfSheet hard-number 위반(자인)**: 가정 시트 push값과 DCF 직접 편집값 괴리 가능(단일소스 붕괴 지점). 스킬 쪽 `promote.py` 승격+tie-out에 상응하는 메커니즘이 웹에 없음.
4. 소소: `거시` 시트 누락(`macro_cpi` 입력 UI 없음), 시트 이탈 시 미저장 소실 경고 없음, `/api/dcf/assemble` 프론트 미소비, 구프로젝트 JSON `erp_*` 용어 잔재.

---

## 4. xlsx 왕복 루프 — 기능은 있으나 루프가 안 닫힘

되읽기(import) UI는 구현·라우팅되어 있음(`Roundtrip.jsx`: export + 되읽기 + diff 3버킷). 그러나 반복 루프가 4군데서 끊김:

1. **발견성**: 되읽기가 "xlsx **Export**" 탭 안에 숨어 있음(nav 라벨에 import 부재).
2. **before 수동 관리**: diff가 before/after 둘 다 업로드 요구. 명세 §2의 "**프로젝트 저장본 대비**" 미구현 — 서버가 `project.data.dcf_input`에서 before를 재생성하면 편집본 하나만 올리는 진짜 루프가 됨.
3. **루프 닫기 부재**: "로컬 모델에 반영" 후 변경버전 재-export 동선·왕복 버전 이력 없음.
4. **부분 반영 불가**: 수식 변경 1건이라도 있으면 `plan.safe=false` → 입력 변경분조차 반영 불가. 버킷① 선택 반영 필요. (수식 변경 LLM 해설·개별 승인 = `Roundtrip.jsx:205` "후속 배선" 자인.)

백엔드 `apply_policy.py` 3버킷 정책은 완성 — 프론트가 "전체 safe일 때만"으로 뭉뚱그려 소비하며 해상도가 죽는 구조. 최소 수선 = ⓐ 저장본 대비 단일 업로드 ⓑ 버킷① 선택 반영 ⓒ 반영 직후 "새 버전 export" 버튼(백엔드 신규 로직 거의 불요).

**스코프 주의**: import는 표준 DCF 스파인 레이아웃만 인식. W-단계 시트가 자란 워크북의 왕복은 스파인 한정.

---

## 5. 테스트 실측 및 조치 (2026-07-19)

| 항목 | 결과 |
|------|------|
| 백엔드 전체 | **379/379 통과** |
| 골든 스파인 | 비올 **8,413.38원** 정확 재현(라이브) |
| 스킬 스위트 | 최초 68/69 — `test_vendor_sync` 실패 |
| 원인 | ec80156에서 `backend/calc_core/model.py` 수정 후 스킬 재빌드 누락(vendor drift) |
| 조치 | `python scripts/build_excel_skill.py` 재실행 → **69/69 통과**. vendor/는 gitignore라 커밋 대상 아님 |
| 재발 방지 권고 | backend/ 수정 커밋 시 스킬 재빌드 강제(pre-commit 훅 또는 CI에 `test_vendor_sync` 편입) |

**문서 부채**: `engine_spec.md`가 Milestone 1 시점에 정지 — §7 "미구현" 목록(DART·4종 검증·RAG·감사인)이 전부 구현 완료, calc_core 9→20모듈. **스킬 references가 W6에서 이 문서를 지식 주입하므로 구식 명세가 스킬 컨텍스트로 들어감** → 현행화 우선순위 높음.

---

## 6. 병용 UX 트레이스 — Claude for Excel(스킬) + 로컬웹 (실측)

### 6.1 E2E 실측 (fixtures/viol 기반)

| # | 시나리오 | 결과 |
|---|----------|------|
| ① | 스킬 scaffold 워크북(`_VS_STATE` 포함) → 웹 `POST /api/xlsx/import` | ✅ **200, per_share 8413.38 재계산 일치** — 여분 시트가 import를 깨지 않음 |
| ② | 같은 입력의 웹 export본 ↔ 스킬 scaffold본 diff | 셀 차이 **0건**(템플릿 정체성 = template_schema SSOT 실증). 단 **`_VS_STATE` 시트 존재가 구조변경(blocked)으로 분류 → `safe=false` → 자동반영 차단** ← 병용 마찰 #1 |
| ③ | "엑셀에서 WACC 0.113→0.12 편집" 후 diff | ✅ 입력변경 2건(DCF!C3, _VS_STATE!B5 tie-out값) 정확 분류, safe=true, 재계산 7,863.09원 |

### 6.2 병용 마찰 지점과 수선

1. **`_VS_STATE`/`Claude Log` 시트 화이트리스트**: `workbook_diff`(또는 `apply_policy`)가 스킬 상태 시트·Claude for Excel 로그 시트를 구조변경에서 제외(또는 별도 `state_changes` 버킷)해야 스킬 워크북 ⇄ 웹 diff가 성립. 현재는 병용 시 항상 blocked.
2. **`_VS_STATE` 소비 미구현(웹)**: 웹 import가 `_VS_STATE`의 stage·게이트 이력·가정 대장을 읽지 않고 버림 — 스킬 세션의 감사증적이 웹 프로젝트로 이관되지 않음. import 시 파싱→`project.data.skill_state`로 보존 권고.
3. **"결정론 미검증" 라벨 재검증 루프**(명세 §2 접점): Claude for Excel에서 스크립트 실행 불가 환경의 산출물을 웹 import→게이트 재검증하는 흐름 — import는 재계산까지만 하고 audit findings를 `_VS_STATE`에 되써주는 역방향이 없음.

### 6.3 로그 자산 활용 설계 (제안)

**(a) Claude for Excel "Claude Log" 탭** — 설정의 세션 로깅을 켜면 워크북에 Claude Log 탭이 생성되어 턴별 작업 이력이 기록됨(공식 지원 기능). 활용:
- 웹 import 시 Claude Log 탭 파싱 → "누가(스킬) 언제 어떤 셀을 왜 바꿨나" 감사증적을 프로젝트에 첨부.
- diff 화이트리스트 대상(6.2-1)에 포함.
- 평가조서 관점: `_VS_STATE`(구조화 상태·가정 대장) + `Claude Log`(서술형 작업 이력) = 워크북 자체가 감사조서가 되는 구도.

**(b) Claude Code 세션 jsonl** — `C:\Users\<user>\.claude\projects\<시작디렉토리 슬러그>\<세션ID>.jsonl`에 도구 호출 단위 전체 이력 기록. 주의: 슬러그는 **세션 시작 워킹디렉토리** 기준 — valuation-platform 작업을 타 레포 세션에서 하면 그쪽 슬러그에 쌓임(현재 `d--valuation-platform`에는 jsonl 0건).
- 활용안: `scripts/mine_session_log.py`(신규) — jsonl에서 스킬 스크립트 실행(tool_use) 이벤트만 추출 → "실행한 결정론 검증과 결과" 부록을 감사보고서/W9 리포트에 자동 생성.
- 한계: jsonl은 로컬 개발 환경 전용(Claude for Excel 세션은 남지 않음) → Excel 경로의 증적은 (a)가 정본.

**참고 출처**: [Claude for Excel 공식 가이드](https://support.claude.com/en/articles/12650343-use-claude-for-excel) · [Houtini 실사용 리뷰](https://houtini.com/articles/claude-in-excel/)

---

## 7. 권고 우선순위

| 순위 | 작업 | 규모 | 근거 | 상태 |
|------|------|------|------|------|
| 1 | 왕복 루프 닫기(§4 ⓐⓑⓒ) + `_VS_STATE`/`Claude Log` diff 화이트리스트(§6.2-1) | 소 | 백엔드 로직 기존재, 프론트 소비 방식만 수정 | ✅ 완료 §8 |
| 2 | 감사인 트랙 UI 배선 | 중 | 백엔드 엔진 완비, UI만 부재 | ✅ 완료 §8 |
| 3 | `engine_spec.md` 현행화 | 소 | 구식 명세가 스킬 W6 컨텍스트로 주입되는 중 | ✅ 완료 §8 |
| 4 | 웹 import의 `_VS_STATE` 소비(§6.2-2) | 소~중 | 병용 감사증적 이관 | ✅ 완료 §8 |
| 5 | vendor 동기 재발 방지 | 소 | 본 검토에서 drift 실증 + §8 작업 중 재발 | ✅ 완료 §9 |
| 6 | 거시 시트 누락(`macro_cpi` 죽은 참조) | 중 | cpi 드라이버가 조용히 0% 계산 | ✅ 완료 §9 |
| 7 | `erp_*` 구용어 provenance 유실 | 소 | F3 게이트 근거 상실 | ✅ 완료 §9 |
| 8 | jsonl 세션 로그 마이너(§6.3-b) | 소 | 결정론 검증 부록 자동생성 | ⬜ |
| 9 | 미저장 편집 소실 경고 | 중 | 13개 시트 전체 배선 필요 — **부분 구현이 무구현보다 위험**(가드 신뢰 후 미배선 시트에서 유실) | ⬜ 의도적 보류 |
| 10 | 판단보조 UX 레이어(IA §5) | 대 | 명세 기존재, 전면 UI 작업 | ⬜ |

---

## 8. 조치 내역 (2026-07-19 후속 구현)

권고 1~4를 구현했다. 전체 회귀 **466/466 통과**(신규 24건 포함).

### 8.1 왕복 루프 닫기 + ④ state 버킷

| 변경 | 파일 |
|------|------|
| `_VS_STATE`·`Claude Log` 인식 + ④ `state_changes` 버킷 신설, `safe` 판정에서 제외 | `backend/excel/workbook_diff.py` |
| ApplyPlan 에 `state` 버킷·카운트 추가 | `backend/excel/apply_policy.py` |
| **저장본 기준선 재생성**(`project_id`) — 편집본 하나만 업로드하면 루프가 돔 | `backend/api/main.py` `_baseline_from_project` |
| **부분 반영** — 수식 변경이 섞여도 `auto_apply` 있으면 `new_input` 동봉 | 동 `/api/xlsx/diff` |
| 기준선 선택 UI(저장본/원본 업로드), 4버킷 표시, "입력 변경만 부분 반영", **↻ 새 버전 export**(루프 닫기) | `frontend/src/pages/appraiser/Roundtrip.jsx` |
| 발견성 — 시트명 "xlsx Export"→"xlsx 내보내기·되읽기", "왕복 diff"→"엑셀 왕복 diff" | `frontend/src/nav.js` |

`✔ E2E 실측`: 스킬 scaffold 워크북(WACC 편집본)을 저장본 대비 단일 업로드 → `baseline=project`,
`safe=true`, 입력변경 1건(`DCF!C3 0.113→0.12`), **`_VS_STATE`는 blocked 0 / state 1**,
재계산 7,863.09원. **마찰 1호 해소 확인.**

### 8.2 스킬 증적 이관 (`_VS_STATE`·`Claude Log`)

신규 `backend/excel/vs_state.py` — 상태 키(단계·게이트·tie-out)·가정 대장(가정명·값·출처유형·
근거·승인상태)·Claude Log 행을 파싱. **미승인 `suggested` 가정과 근거 공란을 WARN 으로 표면화**
(SKILL.md 1.6 게이트를 웹 이관 시에도 유지 — AI 제안이 조용히 확정 가정으로 둔갑하지 않도록).
`/api/xlsx/import`·`/diff` 응답에 `skill_state` 동봉, 반영 시 `project.data.skill_state` 로 저장,
Roundtrip 화면에 증적 패널 표시. 읽기 전용(되쓰기는 스킬·평가인 몫 — 역할 3분할).

### 8.3 감사인 트랙 UI (전 시트 `soon` 해제)

신규 `POST /api/opinion/extract` — 의견서 텍스트/PDF → 고정양식 앵커 추출(실측: 영구성장률
1.00%·Size Premium 2.75%·통화 KRW 정확 추출). pdftotext 부재 시 붙여넣기 안내로 폴백.

| 단계 | 화면 | 소비 엔진 |
|------|------|-----------|
| 1. 의견서 인제스트 | 투입(텍스트/PDF) · 추출 가정 확인 | `extract_opinion` |
| 2. 독립 재계산 | 입력 재구성(의견서 g 를 초기값 제안) · 재계산 vs 주장 | `/api/dcf` + `claimed_per_share` |
| 3. 괴리 진단 | 구조버그 5가설 표(주장값과 ±1% 일치 지목) · 민감도 역산(주장값 낳는 WACC×PGR ±2% 강조) | `diagnose_dcf_gap` |
| 4. 발견사항 | finding 리스트(게이트·진단 자동 수집 + 감사인 Driver·Action 기재) · 서사 리포트(variance 규격 조서 초안) | `audit_dcf` |

Cover 시트도 모드 인지로 수정(감사인은 독립 추정·주장값·다음 할 일 표시).

### 8.4 `engine_spec.md` 현행화

§1 모듈맵을 9→20개 + 주변 레이어(ingest/assemble/excel/rag/api)로 확장, §2 에 개선 A(세금 주입)·
B(터미널 정규화 3필드 우선순위)·NCI 추가, **§6-B 게이트 규칙표 신설**(11규칙 + 근거문서),
§7 스코프를 검증된 것/한계/미구현 3분할로 재작성(구식 "미구현: DART·검증·RAG·감사인" 정정),
§8 변경이력 신설. §5 예시 코드 재실행 검증(8,413.38 일치).

### 8.5 재발한 vendor drift

`backend/excel/` 수정 후 스킬 재빌드를 잊어 `test_vendor_sync` 가 **또** 실패했다(본 세션에서만
2회). 재빌드로 해소(38 파일 해시, `vs_state.py` 자동 포함)했으나, **권고 7(훅/CI)의 필요성이
실증**되었다 — 사람이 기억할 문제가 아니다.

---

## 9. 조치 내역 2차 — vendor 동기·거시·구용어 (2026-07-19)

전체 회귀 **477/477 통과**. 프론트 빌드 clean.

### 9.1 vendor 동기 — 훅이 아니라 **빌드 의존성**으로 해결

"git 훅을 만들까"가 첫 질문이었으나, 조사 결과 **훅은 틀린 도구**였다:

| 사실 | 함의 |
|------|------|
| `vendor/` 는 **gitignore**(추적 파일 0개) | drift 는 레포가 아니라 로컬 작업본 문제 — 커밋 시점 트리거는 무의미 |
| `.git/hooks` 는 버전관리 안 됨 | 공유 불가·설치 절차 필요·`--no-verify` 우회 가능 |
| 빌드 **1.1초** | 테스트마다 재생성해도 무해 |
| `_bootstrap.py` 가 vendor 를 `sys.path[0]` 에 올림 | **stale = 스킬 테스트 10개가 낡은 backend 를 검증하고 통과** ← 진짜 위험 |

즉 실패하던 테스트는 전령이었을 뿐, 위험은 "테스트가 빨개지는 것"이 아니라 **침묵**이었다.
그래서 make 식 의존성 재생성으로 전환:

- `tests/skill/conftest.py`(신규) — 세션 시작 시 stale 이면 **자동 재빌드**(zip·온톨로지 생략).
- `scripts/build_excel_skill.py` 재구성 — `vendor_plan()` 을 **빌드·검사 공용 SSOT** 로 두어
  둘이 갈라지지 않게 하고, `drift()`·`is_stale()`·`build(zip_package=, rebuild_ontology=)` 노출.
  CLI 에 `--check`(변경 없이 보고, exit 1)·`--no-zip` 추가.
- `test_vendor_sync.py` 의미 전환 — "낡았다"고 죽는 대신 **재생성이 동기를 달성했는지**와
  매니페스트 불변식을 검증.

**같이 드러난 구멍 2개도 메움**:
1. `_copy_reference()` 가 매니페스트에 **아무것도 기록하지 않아** 지식 md 30개·온톨로지
   drift 가 **완전 무검출**이었다 → 추적 대상 38 → **70 파일**. 스킬 단계별 지식 주입의
   정본이라 코드만큼 위험하다(§5 문서부채와 같은 종류의 사고).
2. 해시만 비교해 **파일 추가·삭제를 놓쳤다** — 신규 모듈을 vendoring 에 안 넣어도 조용히
   통과하고 런타임 import 실패. `drift()` 가 파일 집합(added/removed/missing)까지 대조.

`✔ 실측`: `backend/calc_core/tax.py` 에 주석 1줄 추가 → `--check` 가 정확히 지목(exit 1) →
스킬 테스트 실행 시 자동 재빌드 후 **72개 통과** → `--check` 재확인 exit 0. 프로브 원복.

### 9.2 거시 시트 신설 — `macro_cpi` 죽은 참조 해소

**결함의 실체**: `CostsSheet` 가 `project.data.macro_cpi` 를 읽는데 **쓰는 주체가 없었고**,
`cost_build.py:61` 이 `cpi_cumulative or [1.0]*years` 로 폴백해 **물가상승 0%로 조용히 계산**.
기본 DEMO 데이터부터 "외주비"가 `method: "cpi"` 라 첫 화면부터 해당됐다. 백엔드
`macro_client.py`(361줄, ECOS·vintage 이중가드)는 이미 있었고 **API 노출만 없던** 상태.

- `POST /api/macro/series`(신규) — 복붙(stdlib, 항상 가능) + ECOS(BYOK `X-Ecos-Key`).
  `base_date` 주면 look-ahead 가드, **탈락 기간을 `dropped_periods` 로 표면화**.
- `MacroSheet.jsx`(신규, 2.가정 › 거시) — 지표 3종(CPI·GDP·임금), vintage·예측시작연도·출처
  입력, 가드 findings 표시, 확정 시 `macro_cpi` 등에 연율 시리즈 + provenance 메타 저장.
- `CostsSheet` — cpi 드라이버가 있는데 CPI 가 없으면 **"물가상승 0%로 계산됩니다" 경고**.
- BYOK 에 ECOS 키 슬롯 추가.

`✔ 가드가 테스트보다 옳았던 사례`: `is_forecast_from` 없이 전망연도를 넣으면 "미래 실적"으로
간주돼 정당하게 탈락한다(2026-03-31 기준 2027 실적은 존재 불가). 테스트를 실제 의미대로
고치고, **UI 가 탈락을 침묵하지 않도록** `dropped_periods` 경고를 추가했다 — 조용히 사라지면
CPI 죽은 참조와 같은 종류의 사고가 반복되기 때문.

### 9.3 `erp_*` 구용어 provenance 유실

ERP→MRP 개명 이전 저장본은 `wacc_input.form.erp_source/erp_market` 을 갖는데,
`DiscountSheet` 가 `useState(saved?.form || DEMO)` 로 **DEMO 를 통째 대체**해 `mrp_source` 가
`undefined` 가 되고, 결국 **F3(β/MRP 시장 정합) 게이트가 판정 근거를 잃었다**.
`_load_project` 에서 읽기 시 정규화(`_migrate`) — 단일 choke point 라 모든 소비자가 한 번에
고쳐지고 다음 저장 때 영구 반영. 현행 키가 이미 있으면 구키는 버린다(현행 우선).

### 9.4 의도적 보류 — 미저장 편집 경고

13개 시트가 각자 로컬 편집 상태를 들고 있어 **일부만 배선하면 무배선보다 위험하다**
(사용자가 가드를 신뢰한 뒤 미배선 시트에서 유실). 전 시트 일괄 배선을 별도 작업으로 남긴다.
