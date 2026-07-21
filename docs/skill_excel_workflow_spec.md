# Excel 밸류에이션 워크플로우 스킬 — 명세서 (Spec)

| 항목 | 내용 |
|------|------|
| **문서 ID** | SPEC-EXCEL-SKILL-001 |
| **버전** | 1.0 |
| **작성일** | 2026-07-18 |
| **상태** | Draft → 구현 착수 대기 (0-c 리뷰) |
| **구현 계획** | [plan_excel_skill.md](plan_excel_skill.md) |
| **관련 문서** | [prd_excel_addin.md](prd_excel_addin.md) · [engine_spec.md](engine_spec.md) · [plan.md](plan.md) · [reference/앤트로픽_금융스킬_벤치마크.md](reference/앤트로픽_금융스킬_벤치마크.md) |

---

## 0. 개요

### 0.1 목적

Val-Studio(valuation-platform)의 **결정론 DCF 엔진(`calc_core`)**을 **Claude for Excel 커스텀 스킬**로 재포장하여, 평가 실무자가 Excel 워크북 위에서 기업가치평가 전 과정 — 템플릿 인식/생성 → 리서치 → 과거 재무제표 정합성 검증·이관 → 계정재분류 → 추정 → WACC → DCF → 시나리오 → 민감도 → 리포트 — 을 **단계별 확인 게이트**와 함께 수행하도록 한다.

### 0.2 3페이즈 구도

| 페이즈 | 내용 | 본 명세 범위 |
|--------|------|--------------|
| **페이즈1** | Claude for Excel 커스텀 스킬 (`excel-valuation-workbook`) | ✅ 상세 명세 (1장) |
| **페이즈2** | 로컬 xlsx 왕복 diff 루프 (FastAPI+React) | 명세만 (2장) |
| **페이즈3** | 자체 Office Add-in (기존 PRD) | 정정사항만 (3장) |

### 0.3 핵심 철학 — 역할 3분할

| 주체 | 담당 | 예시 |
|------|------|------|
| **Claude (스킬)** | 기계적 작업 + 지식기반 제안·리서치 | FS 정규화, 계정재분류 매핑안, 추정 로직 수식 구현, 가정 후보 제시(근거 포함), 산업 리서치 |
| **평가인 (사용자)** | 판단·확정 | 재분류 승인, 매출 드라이버 선택, 가정값 확정, 경영진 자료 투입 |
| **calc_core / checks (결정론)** | 검증 | 골든 재현, F1 재투자·F2 Kroll·F3 β/MRP 룰, 민감도 base 셀 정합 |

이는 감사 구조 그 자체다: **제안(LLM) → 판단(사람) → 검증(결정론 룰)**. 기존 `.claude/skills/valuation-analysis`의 "판단은 LLM, 계산·검증은 코드" 원칙과 Anthropic dcf-model 스킬의 "단계별 confirm" 패턴의 결합이다.

> **원칙: 가정은 추천만, 판단은 평가인.** 매출추정의 드라이버 선택, 계정의 영업/비영업 판정, 가정값 확정은 전부 평가인 몫이다. Claude는 후보를 제시하고 근거를 리서치하고 선택된 로직을 수식으로 구현할 뿐, 애매하면 단정하지 않고 표면화한다.

### 0.4 기존 자산 재사용 (재구현 아님)

DCF 엔진 로직은 **이미 구현·골든 검증 완료**다. 본 스킬은 이를 vendoring(복사)하여 재사용한다.

| 자산 | 경로 | 상태 |
|------|------|------|
| DCF 스파인·audit·scenario·wacc | `backend/calc_core/` | ✅ 비올(8,413.38)·클래시스 골든 |
| Excel export/import/diff | `backend/excel/` | ✅ stdlib zipfile·수식 live |
| RAG 검색기 | `backend/rag/` | ✅ stdlib lexical |
| 온톨로지 빌드 | `docs/reference/ontology/build.py` | ✅ 29챕터·439개념 |
| Claude Code용 스킬 | `.claude/skills/valuation-analysis/` | ✅ 참조 원형 |

**샌드박스 호환성**(실사 확정): `calc_core` + `ingest/validators.py` + `backend/excel/` + `backend/rag/`는 모두 **100% 표준 라이브러리(Python 3.11+)**. Claude for Excel 스킬 샌드박스(네트워크 불가·사전설치 라이브러리만)에서 그대로 동작한다.

---

## 1. 페이즈1 — 스킬 패키지 명세

### 1.1 패키지 구조 (자기완결)

Claude for Excel은 레포가 없는 환경이므로 스킬 패키지가 **자기완결적**이어야 한다 — 레포 상대경로 참조 금지, 지식은 실물 복사, 엔진은 vendoring.

```
.claude/skills/excel-valuation-workbook/     # 소스 (커밋)
├── SKILL.md                    # 워크플로우 정본 (1.9 골격)
├── references/                 # 지식 파일 (빌드가 docs/reference에서 복사, 커밋)
│   ├── index.md                # 단계↔지식 바인딩 색인
│   ├── template_conventions.md # 신규 저술: Val-Studio 시트 아키텍처 정본 (1.3b)
│   ├── account_dictionary.md   # 신규: 표준 계정 사전·동의어 (fs_clean 근거)
│   └── (1.5 표의 원문 복사본들)
├── scripts/
│   ├── dcf.py wacc.py audit.py        # valuation-analysis 원형 이식 (경로해결만 수정)
│   ├── scenario.py                    # 신규: run_scenarios 얇은 래퍼
│   ├── scaffold.py                    # 신규: 백지→DCF 스파인 생성 (1.3 B모드)
│   ├── fs_clean.py                    # 신규: FS 무결성 파이프라인 (1.4b)
│   ├── roundtrip.py                   # 신규: import_dcf_model + diff 대조
│   ├── book_search.py                 # 신규: BookSearcher lexical 폴백 (1.5b)
│   └── vendor/                        # 빌드 산출 (gitignore)
│       ├── calc_core/  validators.py  excel/  rag/
│       └── ontology/{graph,rag_index}.json + reference/*.md
└── dist/excel-valuation-workbook.zip  # 업로드 패키지 (빌드 산출, gitignore)
```

- **빌드**: `scripts/build_excel_skill.py`(레포 루트) — vendor 복사 + references 복사 + zip 생성 + **SHA256 동기 해시 검사**(vendor ↔ backend 원본 drift 방지).
- **스크립트 경로 해결**: 각 래퍼 첫머리 `sys.path.insert(0, str(Path(__file__).parent / "vendor"))` — 기존 `_find_backend()` 패턴 제거(자기완결).

### 1.2 이중 환경 지침

Anthropic 금융스킬의 Office.js↔openpyxl 이중환경 패턴 채택.

| 환경 | 계산·검증 | 워크북 반영 |
|------|-----------|-------------|
| **Claude for Excel** (열린 워크북 조작) | scripts/ 실행 가능하면 사용, 불가하면 지시문-only 폴백 | 셀 직접 기입 (색상·수식 규약 준수) |
| **Claude Code / claude.ai** (파일 경로) | scripts/ 실행 (필수) | xlsx 파일 생성·수정 (`scaffold.py`, xlsx_writer) |

**지시문-only 폴백**: 스크립트 실행이 안 되는 환경에서는 references의 계산 규약(engine_spec 컨벤션)으로 워크북 수식을 검산하되, **"결정론 미검증" 라벨**을 게이트 산출물에 명시하고 로컬 검증(페이즈2)을 권고한다.

#### 1.2.1 리서치 데이터 경로 (런타임 의존 — W1 핵심 제약)

- **Claude for Excel**: **범용 웹검색 없음**(접근이 현재 워크북으로 한정, 2026-07 확인). 외부 실데이터는 ① **MCP 커넥터**(S&P Global·LSEG·Daloopa·Pitchbook·Moody's·FactSet + Claude 설정 커스텀 커넥터) ② **사용자 붙여넣기·업로드 자료**로만 확보. 방법론 지식(온톨로지·references)은 오프라인 번들이라 검색 불요.
- **Claude Code / claude.ai**: 웹검색 도구 사용 가능.
- **provenance 정합(1.6)**: 출처유형 `research`의 소스가 런타임에 갈림(Excel=MCP/사용자자료, Claude Code=웹검색) — 어느 쪽이든 URL·출처 병기 규칙 동일.
- **MCP 커넥터 인증**: Claude 설정에서 관리 — 키를 워크북·스킬에 넣지 않음(1.8과 정합).

### 1.3 시작 모드 판별 (W0)

워크북을 읽고 3분기한다.

| 모드 | 감지 조건 | 동작 |
|------|-----------|------|
| **A. 자기 템플릿** | `_VS_STATE` 시트 존재 또는 Val-Studio DCF 시트 레이아웃 일치 | 상태 읽고 중단 지점부터 재개 |
| **B. 백지** | 시트가 비었거나 Sheet1만 | 평가인 입력 수집 → `scaffold.py`로 수식 live DCF 스파인 생성 |
| **C. 타 템플릿(기존 모델)** | 임의 구조의 기존 모델 | 구조 파악(시트 그래프·입력셀 식별) → 셀맵 작성·확인 후 그 규약에 맞춰 진행. 원본 수식 변경 금지, `_A/_F` 조정 레이어 원칙 |

**B모드 스캐폴딩(v1)**: 시작점은 `build_dcf_sheet(inp, res)` 재사용 — 가정 블록 + 5개년 스파인 + 계단식 법인세 수식 + 결과 블록, 전부 살아있는 수식. `scaffold.py` 모드 2종:
- `--xlsx out.xlsx`: 파일 생성 (Claude Code 경로)
- `--emit-cells`: `{sheet, ref, value|formula}` JSON 덤프 출력 → Claude for Excel이 열린 워크북에 그대로 기입 (파일 생성 불가 환경 대응)

두 모드 모두 `_VS_STATE` 시트(1.7)를 함께 생성.

### 1.3b 점진 성장 풀모델 + 자체 시트 아키텍처 (참고 모델 비복제)

스킬을 끝까지 따라가면 **풀모델이 완성**된다 — 처음부터 멀티시트를 찍어내는 게 아니라, **각 단계가 자기 시트를 만들며 워크북이 자란다**(리서치하면서 Research 시트, CapEx·상각 계산하면서 Capex_Dep 시트를 만드는 식).

#### Val-Studio 표준 시트 아키텍처 (template_conventions.md 정본)

| 단계 | 생성 시트 | 생성 주체 |
|------|-----------|-----------|
| W0 | `DCF`(스파인) + `_VS_STATE` | 결정론(`scaffold.py`) |
| W1 | `Research`(Company Brief 요약 + 출처) | Claude(규약 기반) |
| W2 | `FS_Hist`(Raw/Normalized/Map 3영역) | Claude + `fs_clean.py` |
| **W2.5** | **`FS_Disagg`(손익 계정 세분 + 합보존·구성비)** | **Claude + `fs_disagg.py`** |
| W3 | `Reclass`(계정 태깅 + `_A/_F` 조정 레이어) | Claude |
| W4 | `Fcst_Rev`·`Fcst_Cost`(FS_Disagg 세분 라인 롤업 배선)·`Capex_Dep`·`WC` (선택 드라이버별) | Claude |
| W5 | `Peer`(유사회사 4-step 퍼널 + Hamada 무부채화)·`WACC`(CAPM 빌드업) | Claude + `peer.py`(웹 미러) |
| W6~W8 | `DCF` 가정 블록을 상류 시트 참조로 전환, `Scenario`·`Sens` | Claude + 결정론 검증 |

#### 정체성 원칙 (참고 모델 비복제)

시트명·레이아웃·색상 규약은 **위 자체 정의**를 따른다. 참고 모델 시트명(H_FS/EBIT/BackData 등)·레이아웃을 복제하지 않는다. 참고 모델·타사 문서는 **방법론 지식**(무엇을 계산·검증할지)으로만 쓰고, viol/클래시스 픽스처는 **수치 검증 골든**으로만 쓴다.

- 참조 방향은 **단방향**(`뒤 시트 → 앞 시트`, 순환 금지).
- 색상 3색: Blue(직접 입력 hard) / Black(해당 시트 계산) / Green(타시트 참조) + 핵심가정 yellow fill.

#### hard number 승격 규칙

스파인 단독 단계에서는 DCF 시트 가정 블록이 Blue 입력셀이지만, 상류 시트가 생기면 해당 가정 셀을 상류 참조 수식(Green)으로 교체한다 — "hard number는 최초 1곳만"의 절차적 구현. **교체 시점마다 tie-out**(교체 전후 per_share 불변)을 `promote.py`(W6, 매출/원가/판관비 스파인 셀→`Fcst_*!계` 참조 승격 + per_share 불변 검증; 불일치 시 라인·연도 델타 표면화)로 확인. 셀 주소는 `template_schema`(ROW·FCST) SSOT.

### 1.3c 리서치 산출물 표현 (`Research` 시트 = SSOT, MD = 파생뷰)

붙여넣은 자료는 **`Research` 시트에 보기 좋게 정리**하고, 그걸 기반으로 이후 단계가 작업한다. MD와 **이중 유지하지 않는다**(drift 방지·SSOT).

**두 내용 유형 분리**:
- **숫자**(시장 CAGR·목표 점유율·회전일·peer 목록·거시가정): `Research`/`Assumption` 시트 **셀**에 저장 → 하류 시트가 **수식 참조**(Green). "hard number 1곳" 대상.
- **서사**(사업모델·경쟁구도·원가구조·투자포인트): `Research` 시트 텍스트 블록 → AI가 드라이버 선택·계정분류 판단 시 읽는 맥락. 사람도 열람.

**`Research` 시트 = 단일 SSOT**: 숫자+서사를 정리해 담고, 사람·AI(워크북 네이티브 읽기)·하류 수식이 모두 이걸 소비. Claude for Excel은 워크북을 직접 읽으므로 별도 MD 불요.

**MD Brief = on-demand 파생뷰**(별도 SSOT 아님, `Research`에서 생성): ① Claude Code 컨텍스트 경제성 ② W9 리포트 재료 ③ 이식성. 포맷 = `docs/examples/brief_삼성전자_2026Q1.md`(기업리서치_양식 10섹션) 재사용. 생성 후에도 SSOT는 `Research` 시트 — MD는 스냅샷.

#### 레이아웃 참조 양식 (복제 아님·구조 참조)

Research 시트·template_conventions 저술 시 아래 실무 양식의 항목 구성·레이아웃을 참조해 **자체 아키텍처로 정제**:
- `D:\Valuation\pe양식\(티XXX)기업리서치_20231220V2*.xlsx` — 기업리서치 양식(빈 템플릿)
- `D:\Valuation\pe양식\티에스이_리서치_20231220.xlsx` — 채워진 실례
- `D:\Valuation\DCF_비올\` — 비올 DCF Model 최종본 + (참고 모델) 2차 리포트(사용자 제작 러프 예시)
- (참고) `금융권_컨설팅_리서치바이블*.xlsb`, `Simplified_DCF_솔루엠*.xlsx`
- **열람 암호**: 파일명 "비번"/구분자 뒤 문자열(`1a2a3a4a5a`, `1ㅁ2ㅁ3ㅁ`→`1a2a3a`). 0단계에서 복호화·열람해 레이아웃 참조(구현 참조용, 산출물엔 암호 미기록).

### 1.4 워크플로우 단계 정의 (W0~W9)

각 단계 = **입력 → Claude 작업 → 결정론 체크 → 평가인 confirm 게이트**. **end-to-end 일괄 빌드 금지**(anthropic dcf-model 정본). 뒤 단계에서 발견된 앞 단계 오류는 전부 재작업임을 명시.

| 단계 | 내용 (산출 시트) | Claude | 평가인 | 결정론 게이트 |
|------|------------------|--------|--------|---------------|
| **W0 시작** | 모드 판별·템플릿 준비 (`DCF`+`_VS_STATE`) | 워크북 구조 보고, B모드 scaffold | 모드·셀맵 승인 | scaffold 산출을 `roundtrip.py`로 왕복 재검증 |
| **W1 리서치** | 기업·산업 이해 → Company Brief (`Research`) | Brief 초안, 리서치(가용 소스만, 출처·추정치 표기) | 사업모델 이해 확인, 자료 보강 | Brief 필수 슬롯 공란·출처 누락 검사, 미가용 소스 가정 금지 |
| **W2 과거 FS 정합성·무결성 + 이관** | 무결성 검증 파이프라인(1.4b) → `FS_Hist` | `fs_clean.py`로 정규화·교차검증·재분류 추적 | 원천 데이터·재분류 이관·매핑 확정 | FAIL 0건·재분류 미해결 0건, 당기/전기 교차, B/S 대차, 합계 tie-out, hard number 1곳 |
| **W2.5 손익 계정 세분화** | 러프한 IS 라인을 성격별·유형별로 분해 (1.4e) → `FS_Disagg` | 주석·세그먼트·원가명세서·W1 리서치 근거로 세분 매핑안 제시(모호는 표면화) | 세분 과립도·성격 판정(변동/고정) 승인, 자료 보강 | `fs_disagg.py` **세분합 = 원계정(합보존) FAIL 0건**, 구성비 YoY 급변 WARN 표면화 |
| **W3 계정재분류** | PL 4유형·BS 6유형 + 분석방법 태깅 (`Reclass`, `_A/_F`) — `reclass.py` 파티션 검증 | 분류안 제시(모호는 표면화) | 재분류 승인(현금·NOA/IBD 경계) | **분류합 = 원본 FS합(FAIL 게이트)**, 누락·중복·유형오류 0 |
| **W4 추정** | 매출·원가·판관비·CapEx상각·WC 로직 구축 (`Fcst_*`·`Capex_Dep`·`WC`). **`Fcst_Rev`·`Fcst_Cost`는 `template_schema.ROLLUP` SSOT로 FS_Disagg 세분 라인과 동일 성격 행 생성 + `계=Σ세분` 살아있는 SUM 롤업 → DCF 스파인** | 드라이버 후보 제시, 선택분 수식 구현, 근거 리서치 | 드라이버 선택·가정값 확정·자료 투입 | `check_projection_smoothness`·`check_working_capital_burn`, 가정 출처 태그 완비(1.6), 세분 계=원계정 롤업 | 
| **W5 WACC** | 유사회사 4-step 퍼널(`peer.py`, 웹 미러) → `Peer` Hamada 무부채화 → CAPM 빌드업(`WACC`) | `peer.py` 퍼널(Step2만 판단), `wacc.py` 빌드업·Kroll 제안·peer 근거 | β 출처·peer 선정·WACC 승인 | 퍼널 게이트(무근거 판정 거부·uncertain→⚖️큐·5-10 rule)·`check_beta_mrp_consistency`(F3)·`check_beta_provenance`, 8~14% |
| **W6 DCF 완성** | 스파인 입력셀→Fcst 계 참조 승격(`promote.py`) + 독립 재계산 | `promote.py`(승격+tie-out)·`dcf.py` 재계산 → 워크북 셀 단위 대조 | 결과 확정(승격 델타 검토) | **승격 tie-out(per_share 불변; 불일치=라인·연도 델타 표면화)**, **워크북 vs 엔진 per_share (rel_tol 1e-6)**, `audit_dcf` 전 규칙, 필요 시 `gap_diagnosis` |
| **W7 시나리오** | upside/base/downside (`Scenario`) | 케이스 구성안, `scenario.py` 실행 → Scenario 시트(가중 SUMPRODUCT·합=1 게이트 살아있는 수식) | 케이스·**가중치 승인(합=1)** | weights 완전일치·합=1 아니면 엔진 거부 |
| **W8 민감도** | `sensitivity.py`로 WACC×PGR **5×5 살아있는 수식**(closed-form, FCFF 고정·할인·터미널만 축 반응) + (선택)2중 그리드 | Excel 수식 생성, 엔진 3×3 중심 대조 | 그리드 범위·스텝 확정 | **워크북 중심 == 엔진 3×3 중심 == base**, 내부 3×3 == 엔진 민감도, 외곽은 recalc 게이트 |
| **W9 리포트(선택)** | 주요가정 표·차이 서사 | 리포트 초안(출처 표) | 최종 검토 | audit findings 요약 누락 없이 반영 |

### 1.4a 단계별 자료 요청 프로토콜 (guided intake — just-in-time)

웹검색이 없는 환경(Claude for Excel)에서 리서치는 **능동 요청**이되 **just-in-time(단계별 AI 판단)**이다 — 앞에서 체크리스트를 통째로 던지지 않는다. **각 단계에서 AI가 "지금 이 작업에 무엇이 빠졌다"를 판단하면 그때 필요한 것만 콕 집어 요청**한다. 출처가 전부 사용자 제공이라 provenance가 깨끗하고(1.6 `user`) 환각 위험이 낮다.

**동작 방식**: 단계 진입 → AI가 워크북·`Research`에 이미 있는 자료 점검 → 이 단계 작업에 결핍이 있으면 → **그 결핍만 지목해 요청**(무엇을·왜). 결핍 없으면 요청 없이 진행. 아래 표는 사용자용 폼이 아니라 **AI의 결핍 판단 기준(내부 참조표)**이다.

**수집 채널(런타임 무관)**: ① 붙여넣기(항상) ② 파일 업로드(가능 환경) ③ `Research`/`FS_Hist!Raw` 시트 직접 붙여넣기.

**단계별 자료 참조표 (AI 내부용)**:

| 단계 | 필요할 수 있는 자료 |
|------|---------------------|
| W1 | 사업보고서 ①사업의 개요 ②주요 제품·서비스 ③원재료·생산설비 ④매출·수주상황 / 최근 3개년 재무제표+주석 / (있으면) IR·실적발표 / 신용등급 |
| W2 | 과거 FS 원문(당기·전기 포함), 회계정책 변경 주석(재분류 있으면) |
| W2.5 | 매출 세그먼트·품목별 주석(제품/상품/용역), 제조원가명세서(재료·노무·경비), 판관비 명세 주석(성격별), 영업외손익 명세 |
| W3 | 세그먼트·부문 정보, 원가명세서(제조원가·판관비 성격별) |
| W4 | 매출 드라이버 실데이터(제품별 물량·단가·점유율), CapEx 계획, 경영진 추정치(있으면) |
| W5 | peer 후보 시드, 목표자본구조, 신용스프레드(Kd) |
| 감사인 | 외부평가의견서 PDF, 주장 주당가치 |

**규칙**: 미가용 소스로 가정을 지어내지 않는다. 자료가 없으면 "X가 필요합니다 — 없으면 Y 가정으로 진행하되 추정치 표기"로 표면화. 요청→수령→`Research` 정리(1.3c)→다음 단계 순환.

### 1.4b W2 과거 FS 정합성·무결성 체크 파이프라인 (`fs_clean.py`)

W2는 **과거 재무제표의 정합성·무결성을 검증하는 절차**이고, 아래 전처리·교차검증·재분류 추적은 모두 그 하위 구성요소다. 복붙한 FS 원문은 손이 많이 가고(문자·공백·콤마·괄호음수), 연도 간 재분류·재작성이 섞여 있어 시계열 정합성을 결정론 스크립트로 검증하고 감사 추적을 남긴다.

**`FS_Hist` 시트 구조**: `Raw`(붙여넣기 원문 불변) / `Normalized`(정규화 결과) / `Map`(계정 이관·매핑 대장) 3영역 — 원본 불변 원칙.

**`fs_clean.py`** (stdin: 붙여넣기 텍스트 또는 셀 배열 JSON → stdout: 정규화 결과 + 이슈 리포트 JSON). 결정론 처리 5단계:

1. **값 정규화**: 천단위 콤마·통화기호·괄호(음수)·공백·비수치 문자 제거, 문자열→숫자, `-`/공백/`N/A`→0 또는 결측 구분, 단위 감지(원/천원/백만원 → 백만원 정규화).
2. **당기/전기 구조 파싱**: "당기·전기" 2열 또는 연도 헤더 감지 → `{year: {account: value}}` 구조화.
3. **당기/전기 교차 대조 (재분류 탐지의 핵심)**: 25년 자료의 전기 == 24년 자료의 당기(원본)를 계정별 대조. **불일치 = 회사의 회계처리방법·원칙 변경에 따른 계정 재분류 흔적**(재작성/재분류로 전기 비교치가 바뀜). 불일치 셀·금액차 전량 리포트. 여러 파일 투입 시 겹치는 연도 전부 tie-out.
4. **계정 정합성**: BS 대차(자산 == 부채+자본), 소계=구성항목 합, PL 단계 합계 검산.
5. **계정 연속성 추적 후보 (reclassification tracing)**: 교차 불일치가 뜬 계정에 대해 **"어느 계정이 어디로 이관·병합·분할됐는가" 후보 제시** — 사라진 계정 금액 ≈ 새로 생기거나 증가한 계정 금액 매칭(금액 보존·합계 불변 기반 결정론 후보). `account_dictionary.md`의 상하위·흡수 관계로 후보 보강. 신뢰도 낮거나 다대다 재분류는 **미해결로 표면화**.

**이슈 리포트**: `{정규화된값, 이슈[]}`. severity — FAIL(대차 불일치) / WARN(교차 불일치=재분류 의심·단위 추정) / INFO(자동 정규화). **게이트: FAIL 0건 + 재분류 추적 미해결 0건**이어야 W3 진행.

재분류 "추적 후보 생성"은 결정론(금액 보존 매칭), "확정"은 평가인 판단 — 역할 3분할 유지. `fs_clean.py`는 판정하지 않고 표면화만.

#### ⚠️ W2·W3 두 계정 작업은 다른 층위다 (혼동 금지)

- **W2 계정 연속성 추적**: 같은 회사가 **사업연도 사이에 회계처리방법·원칙을 바꿔** 계정 재분류가 일어났을 때, **어떤 계정이 어디로 이관됐는지 추적**해 과거 시계열의 비교가능성 확보. 탐지 신호 = 당기/전기 교차 불일치. 판단 대상 = "24년 A계정이 25년 재작성에서 B로 옮겨갔는가". 근거 = 금액 보존 매칭 + `account_dictionary.md`.
- **W3 평가목적 재분류**: 정합성 확보된 시계열을 **WC/NOA(OA)/OAL(OL)/FA/IBD/EQU**로 밸류에이션 관점 재분류(유동성기준 B/S → 사업연관성기준 Valuation B/S). 판단 대상 = 영업성·현금성·자본성. 근거 = `타사 §2 taxonomy`.
- `_VS_STATE` 매핑 대장도 두 층 분리 기록(연도간 계정 이관 이력 / 표준계정→평가유형).

### 1.4b·2 W2.5 손익 계정 세분화 파이프라인 (`fs_disagg.py`)

**문제의식(Claude for Excel 실사용에서 발견)**: 공시 포괄손익계산서는 러프하다 — `매출액`·`매출원가`·`판관비`·`영업외손익`이 한 줄씩 뭉쳐 있다. 이 상태로는 W4 추정에서 **P×Q·세그먼트 드라이버를 걸 대상이 없고**, 원가를 변동/고정으로 나눌 수도 없다. 따라서 **평가목적 재분류(W3) 이전에**, 과거 IS를 성격별·유형별로 **세분(disaggregation)**하는 단계가 필요하다.

**세 연산의 구분(같은 과거 IS, 다른 목적)**:
- **W2 무결성**: 합이 맞나(tie-out·교차검증). 러프한 계정을 **그대로 검증**.
- **W2.5 세분화(여기)**: 한 줄 → 여러 성격으로 **분해**. `매출액`→제품/상품/용역/기타, `매출원가`→재료비/노무비/경비, `판관비`→급여/감가상각비/광고선전비/…, `영업외`→경상/일회성. 방향 = **분해(coarse→fine)**.
- **W3 평가재분류**: 성격 → 평가유형으로 **집계**(Sales/COGS/SGA/NO). 방향 = **집계(fine→type)**.

즉 W2.5는 리서치(W1의 제품·매출 구성)와 추정(W4의 드라이버)을 잇는 **다리**다. W1이 정성적으로 파악한 사업부문·품목이 여기서 IS 숫자에 매핑되어야, W4가 그 위에 드라이버를 얹는다.

**과립도 원칙(사용자 확정: 원천자료 지지 범위)**: 세분은 **주석·세그먼트·제조원가명세서가 실제로 지지하는 만큼, 그리고 W4 드라이버에 연관되는 만큼만** 한다. 원천자료가 없으면 총액을 유지하고 `[성격별 미확보]`로 표면화(억지 분해 금지 — 환각·과분해 위험 차단). 고정 표준 세분을 강제하지 않는다.

**`fs_disagg.py`** (stdin: 세분안 JSON → stdout: 세분 결과 + 이슈 리포트 JSON). 결정론 처리:

1. **값 정규화**: `fs_clean.py`의 `normalize_value`·`detect_unit` 재사용(콤마·통화·괄호음수·단위 스케일 — DRY, 둘 다 stdlib).
2. **합보존 검증(within-year 게이트)**: 각 블록 `parent`에 대해 `Σchildren == total`(연도별). 잔차 `residual = total − Σchildren`, `|residual| > tol` → **FAIL(누수)**. 이것이 세분의 핵심 불변식(부모-자식 롤업).
3. **구성비(mix) 산출 + 교차연도 추이(cross-year)**: `child/total` 비율을 연도별로 계산, **YoY 구성비 절대변화 > 임계(기본 15%p)** → **WARN(구성 급변 — 재검토·재분류 신호)**. 사용자가 말한 "다른 연도들끼리 정합성"이 이 체크.
4. **결측 자식 처리**: `null` 자식은 롤업에서 제외하되 잔차에 반영(누락 표면화).

**게이트: 합보존 FAIL 0건**이어야 W3 진행. 구성비 급변(WARN)은 차단하지 않고 표면화(실제 사업의 믹스 변화일 수 있음 — 판단은 평가인).

**역할 3분할**: 세분 매핑안 제시·구성비 계산은 Claude(제안)·`fs_disagg.py`(검증), 과립도·성격(변동/고정) 판정은 평가인(판단). `fs_disagg.py`는 판정하지 않고 합보존·믹스만 검증한다.

**`FS_Disagg` 시트**: 원계정별 블록(자식 행 + `계(=FS_Hist 원계정)` 롤업 행 + 구성비 행). 참조는 `FS_Disagg → FS_Hist`(뒤→앞) 단방향. 하류의 `Fcst_Rev`·`Fcst_Cost`가 이 세분 라인을 드라이버 대상으로 참조한다.

**자료구조 함의(template_schema 연결)**: 러프함의 뿌리는 `DcfSpineInput.revenue[]`가 통짜 시계열인 것. W2.5는 **부모-자식 롤업 구조**를 도입하므로, 향후 `template_schema.py`(셀 레이아웃 SSOT)는 단순 셀맵을 넘어 **롤업 위계**(자식 셀 → 부모 셀, 합보존)까지 선언해야 한다. 세분화와 `template_schema`는 상보(경쟁 아님).

### 1.4c 민감도 2층 구조 (엔진 검증 ≠ 워크북 산출물)

- **엔진 3×3** (`dcf.run` sensitivity): WACC×g, step ±1%p, 중심 [1][1]==base. **내부 self-consistency 앵커만** — 리포트용 아님. 엔진 변경 없음.
- **워크북 그리드** (W8 산출물): WACC×PGR **5×5 살아있는 Excel 수식**(셀마다 독립 DCF 재계산). `scripts/sensitivity.py`(→`backend/excel/sensitivity_grid.py`)가 생성 — **명시연도 FCFF 는 WACC·g 무관(고정)이라 `DCF!FCFF` 행 참조, 할인·터미널만 축값 반응하는 closed-form**(엔진 `_compute` 대수 1:1). 셀 캐시=엔진 재계산값, 수식은 그 closed-form 에서 생성. 내부 3×3 == 엔진 자체 민감도로 교차검증, Excel 문법은 recalc 게이트가 확인. 참고 모델 리포트 관행(부록F) 그리드 크기 계승.
- **연결**: 워크북 그리드 중심 == 엔진 3×3 중심 == base per_share (3자 일치 게이트). 외곽 셀은 Excel recalc 게이트(LibreOffice headless, `scripts/recalc_gate.py`)가 검증.

**recalc 게이트(`scripts/recalc_gate.py`) — 수식 정확성 CI 도구**: 우리 export 는 `<f>수식</f><v>엔진캐시값</v>` 를 함께 쓰므로 지금까지 테스트는 캐시(엔진값)만 봤다. 이 게이트는 **cached 를 제거한 '수식만' xlsx** 를 LibreOffice 로 recalc-on-load(OOXMLRecalcMode=0) 시켜, 계산된 값을 엔진값과 대조 → `<f>` 수식(셀참조·중첩 IF 구간세율·`^`·크로스시트 참조)이 진짜 Calc 엔진에서 우리 엔진과 동일하게 계산되는지 확인한다. cached 제거가 핵심(안 하면 recalc 미동작 시 캐시 echo 로 false pass). `soffice` 미설치면 skip(오탐 아님). W6 승격 셀(`=Fcst_*!계`)·W8 그리드 외곽 셀의 수식 검증에 사용. `tests/skill/test_recalc_gate.py`.
- **(선택) 시나리오×민감도 2중 그리드**: 부록F의 `CHOOSE` 드라이버 토글로 시나리오 전환 + 각 시나리오별 민감도. W7·W8 합성. v1은 단일 시나리오 5×5 우선, 2중 그리드는 Should.

### 1.4d 단계별 추천 모델·effort·난이도 기반 선택

스킬이 각 단계 성격에 맞춰 **모델·사고깊이(effort)를 권고**한다. 기존 valuation-analysis "컨텍스트 경제학(0단계만 고투자)"의 일반화. SKILL.md 단계표에 `추천` 메타 병기.

#### ⚠️ 런타임별 "추천"의 실행력

- **Claude for Excel**: 밑단 모델 = 사용자 구독 모델. 스킬은 **자동 전환 불가 → 조언만**("이 단계는 고난도, 상위 모델·깊은 사고 권장"을 산출물에 표기). 사용자가 모델·thinking 선택.
- **Claude Code / MAS**: 단계별 서브에이전트에 **모델 실제 지정 가능**. 결정론 스크립트 단계는 저비용, 판단·저술 단계는 상위 모델.
- **API 앱(향후)**: `output_config.effort`·모델 라우팅으로 단계별 실제 적용.

#### 단계별 기본 권고

| 단계 | 성격 | 추천 effort |
|------|------|-------------|
| W0 | 기계(모드판별·scaffold) | 저 |
| W1 | 고투자(리서치·종합·Brief) | 상위 모델·high |
| W2 | `fs_clean.py` 주도, 재분류 판단만 사고 | medium(재분류 케이스 승격) |
| W2.5 | `fs_disagg.py` 합보존 주도 + 세분 매핑 판단 | medium(과립도·성격 판정 승격) |
| W3 | 판단 집약(영업/비영업 모호) | 상위 모델·high |
| W4 | 드라이버 판단(high)+수식 구현(medium) | 혼합 |
| W5 | `wacc.py` 주도 | medium |
| W6 | `dcf.py` 재계산 검증 | 저~medium |
| W7 | 케이스 구성 판단 | medium |
| W8 | 그리드 생성(기계) | 저 |
| W9 | 종합 저술·차이 서사 | 상위 모델·high |

**난이도 기반 동적 승격 규칙(SKILL.md 인코딩)**: 케이스가 애매하면(계정분류 모호·재분류 다대다·peer 판정 uncertain·audit FAIL) → **상위 모델/high effort로 승격하고 평가인에게 표면화**; 명확·결정론 통과면 저비용 유지. 판단보조 원칙과 결합 — "애매함"이 곧 승격 트리거.

### 1.5 지식 주입 사전 바인딩 (스킬북 — 단계↔지식 매핑)

기존 valuation-analysis의 "사전 바인딩" 패턴 계승: **그 단계에 오면 해당 파일만 Read, 통독·검색 금지.** references/로 복사할 원본:

| 단계 | references/ 파일 (원본: docs/reference/ 또는 docs/) |
|------|------------------------------------------------------|
| W0 템플릿 | `template_conventions.md`(**Val-Studio 자체 시트 아키텍처 정본** + 모델링_워크플로우_기초 §6 색상·hard number 1곳 + plan.md anthropic xlsx 5색·함수 화이트리스트·recalc 게이트) |
| W1 리서치 | `기업리서치_양식.md`(Brief 10섹션) + `참고보고서_활용.md`(산업 CAGR·컨센서스 출처) |
| W2 이관 | `모델링_실무_2강4강.md`(§3 Finalize 연결 체크) + `account_dictionary.md`(표준 계정 사전·동의어) |
| W2.5 세분화 | `account_dictionary.md`(성격별 원가·매출 항목 사전) + `모델링_실무_2강4강.md`(제조원가명세서·판관비 성격별 구조) |
| W3 재분류 | `계정분류_모델아키텍처.md`(§2 유형·§3 방법) + `DCF_교육_정본.md`(§1.4 Valuation B/S 재분류 이론) |
| W4 추정 | `리포트예시_클래시스.md`(§2 주요가정·부록A~D 실측 비율) + 모델링_실무 P×Q 사전 |
| W5 WACC | `wacc_할인율서식.md` + `베타_Bloomberg_vs_KICPA.md` + `감사인검토_WACC방법론.md` + `영구성장률_PGR_적합성.md` |
| W6 DCF | `engine_spec.md`(§0 컨벤션·§4 절차·§6 검증) + `검증_클래시스_DCF.md`(tax_override·terminal_fcff_override 선례) |
| W7 시나리오 | `리포트예시_클래시스.md` 부록F(Driver 3개+CHOOSE 토글) |
| W8 민감도 | `앤트로픽_금융스킬_벤치마크.md` §1(중심셀=base 검증) |
| 게이트 공통 | `앤트로픽_금융스킬_벤치마크.md` §2 audit-xls(BS부터·하드코딩 오버라이드·DCF 버그 5종) |

`references/index.md`에 이 표 수록(자기완결 색인). **참고 모델 계열 문서는 방법론 지식으로만 주입** — 시트명·레이아웃 복제 금지를 index.md에 명시.

### 1.5b 온톨로지 참조 구조

`docs/reference/ontology/`는 **SSOT(md frontmatter+`[[링크]]`) → build.py 컴파일 → 3산출물** 파이프라인이며 **stdlib only·임베딩 프리라 샌드박스에서 그대로 동작**한다(29챕터·439개념·54엣지·0미해소).

**중요 판정**: 엣지는 **타입 없는 문서 참조**(`[[wikilink]]`)일 뿐 — "베타→WACC", "PGR≤GDP" 같은 **도메인 규칙은 그래프에 없다**. 규칙은 `checks.py`(코드)에 하드코딩되고 온톨로지는 "규칙의 출처 문서"만 제공하는 **느슨한 문서-코드 결합**. 규칙 강제는 온톨로지가 아니라 vendored `checks.py`가 담당.

**스킬 채택안 — (c) 사전바인딩 뼈대 + (a) lexical 검색 폴백**:
1. **1차 = 단계별 사전 바인딩**(1.5 표): 그 단계에 오면 해당 md만 Read. 결정론·컨텍스트 효율·샌드박스 100%.
2. **폴백 = `book_search.py` + rag 3파일**: 단계에 안 잡히는 비정형 질문만. `BookSearcher()`를 embedder 없이 = 순수 lexical(문자 bigram Jaccard + 키워드 + graph 1-hop 확장), 네트워크·임베딩 불요.
3. **동봉물**(빌드가 vendor로 복사): `ontology/{graph,rag_index}.json`, `docs/reference/*.md`, `backend/rag/*.py`, `book_search.py`. Gemini 임베딩 하이브리드만 미동봉(부가신호).
4. **frontmatter `canonical_questions`**: 각 챕터가 "답하는 질문" — index.md 단계 매핑 검증용.

**금지**: 감린이(gamlini)의 "127 엔티티 개념그래프/KSA 혼동 온톨로지"를 끌어오지 말 것 — 별개 프로젝트 자산이며 valuation-platform 온톨로지(29챕터)와 무관.

### 1.6 가정 출처(provenance) 규약

모든 가정은 `_VS_STATE`의 가정 대장에 기록: `가정명 | 값 | 출처유형 | 근거 | 승인상태`.
- 출처유형 ∈ `user`(평가인 제공) / `research`(리서치, URL·문서 병기) / `suggested`(지식기반 제안, 근거 챕터 병기)
- **게이트 규칙**: `suggested` 상태로 승인 안 된 가정이 W6에 유입되면 WARN 표면화. 출처 없는 가정은 진행 차단(평가인 질의).
- 리서치 소스는 런타임 의존(1.2.1)하되, 기준(수치는 추정치 표기·출처 URL 필수)을 SKILL.md에 명시.

### 1.7 워크북 상태 규약 (`_VS_STATE` 시트)

스킬 세션은 무상태 → **워크북이 곧 상태**. 숨김 시트 `_VS_STATE`:
- A열 키/B열 값: `skill_version`, `mode`(A/B/C), `stage`(W0·W1·W2·**W2.5**·W3~W9), `last_gate_passed`, `engine_tieout`(per_share·검증시각)
- 가정 대장 블록(1.6), 계정 매핑 대장(W2 이관 이력 / W2.5 세분 대장 / W3 평가유형, 1.4b·1.4b·2), 셀맵 블록(C모드)
- W0에서 생성(scaffold 포함), 각 게이트 통과 시 갱신. 재진입 시 Claude가 이 시트만 읽고 재개 지점 판별.

### 1.8 API 키·비밀 관리 원칙

**스킬은 API 키가 필요 없다** — 설계 원칙이다:
- **추론**: Claude for Excel 안에서는 사용자 Claude 구독으로 동작 — 별도 LLM 키 불요.
- **계산·검증**: scripts/는 전부 결정론 stdlib — 키 무소요.
- **외부 데이터**: 스킬 샌드박스는 네트워크 불가라 키가 있어도 쓸 곳 없음. 원천 데이터는 사용자 투입(파일/붙여넣기) 또는 MCP 커넥터(Claude 설정 인증)가 정본.
- **금지 규칙**: API 키·토큰을 워크북 셀·`_VS_STATE`·스킬 파일·가정 대장 어디에도 기록 금지(워크북은 공유·전달 산출물).
- **페이즈2 경계**: BYOK(X-Gemini-Key, localStorage·헤더 전달·서버 미저장)는 웹앱/FastAPI 트랙 메커니즘으로 현행 유지 — 스킬과 무관.

### 1.9 SKILL.md 골격

frontmatter(name: excel-valuation-workbook, description: Excel 워크북 위 DCF 밸류에이션 워크플로우 — 템플릿 인식/생성·리서치·FS 이관·계정재분류·추정·WACC·DCF·시나리오·민감도; 판단은 평가인, 계산·검증은 결정론 도구) → 원칙(역할 3분할·판단보조) → 이중 환경(1.2) → 시작 모드·성장 아키텍처(1.3·1.3b) → 단계표+게이트(1.4) → 자료 요청 프로토콜(1.4a) → 지식 바인딩(1.5) → 추천 모델(1.4d) → provenance(1.6) → 상태 규약(1.7) → 키 원칙(1.8) → 도구 사용법(stdin JSON 예시) → 신뢰 원칙(암산 금지·audit 은폐 금지·모호하면 표면화·참고 모델 복제 금지).

---

## 2. 페이즈2 — 로컬 diff 루프 (명세)

현행 FastAPI+React 수준 유지. 핵심은 **엑셀 왕복이 로컬 평가모델에 즉시 diff 반영**되는 루프.

```
로컬 모델(프로젝트 JSON, var/projects/) ⇄ xlsx
  export: POST /api/xlsx/export  (DcfSpineInput → 수식 live xlsx, FileResponse)   [dcf_export 기존]
  import: POST /api/xlsx/import  (xlsx 업로드 → import_dcf_model → DcfSpineInput)  [dcf_import 기존]
  diff:   POST /api/xlsx/diff    (before/after 또는 프로젝트 저장본 대비 → 3버킷)  [workbook_diff 기존]
```

**적용 정책 (diff 3버킷 → 모델 반영)**:
- ① `input_changes`(.safe) → 자동 반영 + 재계산 (로직만, LLM 불요)
- ② `formula_changes` → 리뷰 큐: LLM이 수식 변경 의미 해설 → 평가인 승인 후 반영
- ③ `structure_changes` → 차단 + 경고 (템플릿 불일치, 앵커 이동)

**React**: diff 리뷰 패널(3버킷 표시, `to_markdown` 재사용) + "적용" 버튼 + formula 리뷰 UI.

**API 명세**:

| 엔드포인트 | Request | Response |
|-----------|---------|----------|
| `POST /api/xlsx/export` | `DcfSpineInput` JSON | `.xlsx` (application/vnd...sheet), `Content-Disposition: attachment` |
| `POST /api/xlsx/import` | multipart xlsx | `DcfSpineInput` JSON (+ 재계산 결과 검증) |
| `POST /api/xlsx/diff` | multipart before.xlsx·after.xlsx (또는 프로젝트 저장본 대비) | `WorkbookDiff` 3버킷 JSON + `.safe` |

**스킬(페이즈1)과의 접점**: Claude for Excel에서 "결정론 미검증" 라벨이 붙은 워크북을 로컬 import → 게이트 재검증하는 보완 루프.

---

## 3. 페이즈3 — PRD 정정사항

`docs/prd_excel_addin.md`:
- FR-M2.5·US-04·§13.3의 "5×5" → **3×3** 정정 (엔진 내장 민감도 실측). 단 워크북 리포트 그리드는 5×5(1.4c) — 명세 문서에 두 개념 구분 병기.
- §10.3 CORS: fetch origin은 SourceLocation 도메인 — `excel.office.com`은 불필요, `<AppDomains>`는 CORS 아닌 Task Pane 내비게이션 허용 목록임을 주석.
- §18 벤치마크 표에 "Claude for Excel 공존·스킬 브리지"(범용 AI 조작 + Val-Studio 결정론 검증 보완) 행 추가.

---

## 4. 로드맵 (MVP 이후 — 아이디어 차원)

> **원칙: 지금은 페이즈1 MVP 스킬에 집중.** 아래는 방향 기록용.

| 아이디어 | 요지 | 스킬/엔진 접점 |
|----------|------|----------------|
| **산업별 평가방법 지식 구축** | 산업별 밸류에이션 관행·드라이버·배수를 온톨로지 챕터로 정교화 | `docs/reference/` 신규 챕터 → build.py 자동 반영, W1·W4 바인딩 확장 |
| **상대가치법 트랙** | comps(peer 배수) 정식 트랙 — `peer.py`·`relative.py`·`check_peer_seasonality` 활용 | 신규 W단계군 + `calc_core.relative` |
| **상증세법상 평가** | 상속·증여세법상 평가 방법 트랙 | 신규 `method_selector` 카탈로그 항목 |
| **상증세법상 비상장주식평가** | 세법상 계정 재분류(순손익·순자산가액) — **IS/BS 로직 신규 구축 필요** | 신규 엔진 모듈(DCF 스파인과 별개 수학) + 세법 재분류 taxonomy |
| **감사인 트랙 신설** | 평가자↔감사자 분리 독립 재계산(generator+critic) — `audit.py`·`diagnose_dcf_gap` 기반 | 별도 스킬 또는 본 스킬 트랙 확장, MAS |
| **공유 워크스페이스 환경** | 팀 협업(프로젝트 허브·산출물 공유) | 페이즈3 웹앱/애드인 + 조직 스킬 배포 |

교차 링크: [plan.md](plan.md)(전체 로드맵) · [reference/밸류에이션_스코프_로드맵.md](reference/밸류에이션_스코프_로드맵.md)(트랙 지도).

---

## 변경 이력

| 버전 | 날짜 | 변경 |
|------|------|------|
| 1.0 | 2026-07-18 | 초안 — 페이즈1 스킬 명세 + 페이즈2·3 요약 |
| 1.1 | 2026-07-18 | **W2.5 손익 계정 세분화 단계 신설**(`fs_disagg.py`·`FS_Disagg` 시트). Claude for Excel 실사용에서 발견 — 러프한 IS를 성격별로 분해해야 W4 드라이버가 성립. 세 연산 구분(W2 무결성/W2.5 세분/W3 집계), 합보존 게이트 + 구성비 추이. 과립도=원천자료 지지 범위. 1.3b·1.4·1.4a·1.4b·2(신규)·1.4d·1.5·1.7 반영 |
