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
- **결정론 도구(`scripts/`)**: 계산·검증. 골든 재현, audit 룰(PGR≤GDP·TV비중·β/ERP), tie-out. **암산·추정 금지** — 숫자는 반드시 scripts/ 로.

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
| W1 | `Research` |
| W2 | `FS_Hist`(Raw/Normalized/Map) |
| W3 | `Reclass`(`_A/_F` 레이어) |
| W4 | `Fcst_Rev`·`Fcst_Cost`·`Capex_Dep`·`WC` |
| W5 | `WACC` |
| W6~W8 | `DCF` 가정 상류참조 승격, `Scenario`·`Sens` |

**정체성 원칙(중요)**: 시트명·레이아웃은 위 **자체 정의**를 따른다. **MSVALUE(H_FS/EBIT/BackData 등) 시트명·레이아웃을 복제하지 않는다.** MSVALUE·xDCF 지식은 "무엇을 계산·검증할지"로만 쓴다. 규약은 `references/template_conventions.md`.

**단계 시트 뼈대 생성**: 각 단계에서 `scaffold.py --stage W1..W5`로 그 단계 시트의 뼈대(제목·범례·라벨·입력 placeholder·타시트 참조 스텁)를 결정론으로 찍고, 그 위에 값·수식·근거를 채운다. 뼈대가 색상·참조 규약을 강제하므로 손으로 시트를 그리는 것보다 일관되다. W1=Research, W2=FS_Hist, W3=Reclass, W4=Fcst_Rev·Fcst_Cost·Capex_Dep·WC, W5=WACC.

- 참조 단방향(`뒤→앞`, 순환 금지). 색상 3색: Blue(입력)/Black(수식)/Green(타시트) + 핵심가정 yellow.
- **hard number 승격**: 상류 시트가 생기면 DCF 가정 셀을 상류 참조(Green)로 교체하고, **교체 전후 per_share 불변(tie-out)**을 `roundtrip.py`로 확인.

**Research 시트 = SSOT**: 붙여넣은 자료를 여기 정리(숫자=하류 수식 참조 대상, 서사=판단 맥락). MD Brief는 필요 시 여기서 뽑는 파생뷰(이중 유지 금지).

---

## 워크플로우 단계 + 확인 게이트

**end-to-end 일괄 빌드 금지.** 각 단계 산출물을 평가인에게 보여주고 확인받은 뒤 다음으로. 뒤 단계에서 발견된 앞 단계 오류는 전부 재작업이다.

| 단계 | 작업 | 결정론 게이트 | 지식(references/) |
|------|------|---------------|-------------------|
| **W0 시작** | 모드 판별·`scaffold.py` | `roundtrip.py` 왕복 재검증 | template_conventions |
| **W1 리서치** | Company Brief 초안(가용 소스만) | 필수 슬롯·출처 누락 검사 | 기업리서치_양식·참고보고서_활용 |
| **W2 과거 FS 정합성·무결성 + 이관** | `fs_clean.py`로 정규화·교차검증·재분류 추적 | FAIL 0·재분류 미해결 0·대차·tie-out | 모델링_실무_2강4강·account_dictionary |
| **W3 계정재분류** | PL 4유형·BS 6유형 태깅(모호는 표면화) | 분류합=원본 FS합(누락·중복 0) | xDCF_계정분류·msvalue_DCF_교육_정본 |
| **W4 추정** | 드라이버 후보 제시→선택분 수식 구현 | projection_smoothness·wc_burn·가정 출처 완비 | msvalue_리포트예시·모델링_실무 |
| **W5 WACC** | `wacc.py`(Kroll 제안·peer 근거) | β/ERP 정합·provenance·8~14% | wacc_할인율서식·베타·deloitte·PGR |
| **W6 DCF** | 가정 상류참조 승격 + `dcf.py` 재계산 | tie-out(워크북 vs 엔진 rel_tol 1e-6)·audit 전규칙·gap_diagnosis | engine_spec·검증_클래시스 |
| **W7 시나리오** | `scenario.py`(구성=판단) | 가중치 완전일치·합=1 | msvalue_리포트예시 부록F |
| **W8 민감도** | WACC×PGR 5×5 살아있는 수식 | 워크북 중심 == 엔진 3×3 중심 == base | 앤트로픽_금융스킬_벤치마크 §1 |
| **W9 리포트(선택)** | 주요가정 표·차이 서사 | audit findings 누락 없이 반영 | msvalue_리포트예시·장표_작성법 |

**게이트 공통**: `앤트로픽_금융스킬_벤치마크.md §2`(audit-xls — BS부터·하드코딩 오버라이드·DCF 버그 5종).

---

## 자료 요청 (just-in-time)

체크리스트를 앞에서 통째로 던지지 않는다. **각 단계에서 "지금 이 작업에 무엇이 빠졌나" 판단해, 결핍이 있을 때만 그것만 콕 집어 요청.** 미가용 소스로 가정을 지어내지 않는다 — 없으면 "X가 필요합니다; 없으면 Y 가정으로 진행하되 추정치 표기"로 표면화.

단계별 필요 자료(내부 참조): W1=사업보고서(사업개요·주요제품·원재료/설비·매출/수주)+3개년 FS+주석 / W2=과거 FS 원문(당기·전기)+회계정책 변경 주석 / W3=세그먼트·원가명세서 / W4=드라이버 실데이터·CapEx 계획·경영진 추정 / W5=peer 시드·목표자본구조·Kd.

---

## 도구 (scripts/)

전부 stdin JSON(또는 파일인자) → stdout JSON. 계산·검증은 반드시 이걸로.

```bash
# W0 백지 스캐폴딩 (Claude Code)
echo '{...DcfSpineInput...}' | python scripts/scaffold.py --xlsx out.xlsx
# W0 백지 스캐폴딩 (Claude for Excel — 셀 JSON 받아 기입)
echo '{...}' | python scripts/scaffold.py --emit-cells
# W1~W5 단계 시트 뼈대(stdin 불요; 워크북 성장)
python scripts/scaffold.py --stage W4 --emit-cells     # Fcst_Rev·Fcst_Cost·Capex_Dep·WC

# W2 과거 FS 무결성 (정규화·교차검증·재분류 추적; 미해결엔 account_dictionary 이관 힌트)
echo '{"sources":[{"label":"FY2024","periods":{"2024":{"매출액":"1,234",...}}}]}' | python scripts/fs_clean.py

# W5 WACC (market_cap_musd 주면 Kroll 제안)
echo '{"risk_free":0.03,"equity_risk_premium":0.08,"unlevered_beta":1.0,...}' | python scripts/wacc.py

# W6 DCF 계산 + audit
echo '{"wacc":0.09,"terminal_growth":0.01,"revenue":[...],...}' | python scripts/dcf.py

# W0/W6 워크북 왕복 tie-out
python scripts/roundtrip.py model.xlsx --expect inputs.json
python scripts/roundtrip.py before.xlsx --diff after.xlsx      # 3버킷 diff

# W7 시나리오
echo '{"cases":{"Base":{...},"Up":{...}},"weights":{"Base":0.5,"Up":0.5}}' | python scripts/scenario.py

# 감사인 트랙 — 독립 재계산 + 주장값 대조
python scripts/audit.py inputs.json <주장주당가치>

# 지식 폴백(단계 바인딩에 없는 비정형 질문만)
python scripts/book_search.py "영구성장률 몇 퍼센트?"
```

**DcfSpineInput 필드**: `wacc, terminal_growth, revenue[], cogs[], sga[], dep_amort[], capex[], delta_nwc_cash_adj[], non_operating_assets, net_debt, shares_outstanding` (+ 선택: `mid_year_periods[], terminal_discount_period, tax_override[], effective_tax_rate, terminal_fcff_override, terminal_reinvestment_rate`). 단위 백만원, 주식수만 주.

---

## 지식 참조 (사전 바인딩)

각 단계에 오면 위 표의 지식 파일(`scripts/vendor/reference/<파일>.md`)만 Read한다 — 통독·전량검색 금지. 단계에 안 잡히는 비정형 질문만 `book_search.py` 폴백(오프라인 lexical). 챕터 색인은 `references/index.md`.

**MSVALUE 계열은 방법론 지식으로만** — 시트 복제 금지.

---

## 상태 규약 (`_VS_STATE` 시트)

세션은 무상태 → 워크북이 곧 상태. 숨김 시트 `_VS_STATE`에 기록: `skill_version·mode(A/B/C)·stage(W0~W9)·last_gate_passed·engine_tieout` + 가정 대장(provenance) + 계정 매핑 대장(W2 연도간 이관 이력 / W3 평가유형). 재진입 시 이 시트만 읽고 재개 지점 판별. 각 게이트 통과 시 갱신.

## 가정 출처(provenance)

모든 가정은 `_VS_STATE` 대장에 `가정명|값|출처유형|근거|승인상태`. 출처유형 = `user`(평가인) / `research`(URL·문서 병기) / `suggested`(근거 챕터 병기). **`suggested` 미승인 가정이 W6에 유입되면 WARN 표면화**, 출처 없는 가정은 진행 차단.

## 추천 모델·난이도 승격

단계 성격에 맞춰 권고(런타임별 실행력 다름 — Excel은 조언만, Claude Code/MAS는 서브에이전트 모델 지정 가능). W1·W3·W9=상위 모델·high, W6·W8=결정론이라 저비용. **애매하면(계정분류 모호·재분류 다대다·peer uncertain·audit FAIL) 상위 모델/high로 승격하고 평가인에게 표면화.**

---

## 키·비밀 원칙

**스킬은 API 키가 필요 없다.** scripts/는 결정론 stdlib(키 무소요), 외부 데이터는 사용자 투입·MCP 커넥터(Claude 설정 인증). **API 키·토큰을 워크북 셀·`_VS_STATE`·스킬 파일·가정 대장 어디에도 기록 금지**(워크북은 공유·전달 산출물).

## 신뢰 원칙

- LLM은 평가인 판단의 **보조**(대체 아님). 규칙·근거 없어 애매하면 결론 강제 금지 — "XX는 ~해서 애매합니다"로 표면화.
- 계산은 항상 `scripts/`. 암산·추정 금지(재현·감사 불가).
- 숫자에 출처를 붙인다. audit 경고를 숨기지 않는다.
- 모르는 방법론은 references에서 확인 후 답한다(환각 금지).
- **MSVALUE 시트를 복제하지 않는다** — 방법론만 차용, 자체 아키텍처 사용.
