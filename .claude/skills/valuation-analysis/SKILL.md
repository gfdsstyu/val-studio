---
name: valuation-analysis
description: 기업가치평가(DCF) 수행·검증·해석. 재무제표/사업보고서(XBRL)/외부평가의견서/증권사
  리서치로 DCF 밸류에이션, WACC·영구성장률 산정, 가정 타당성 검증, 평가의견서 분석을 요청할 때
  사용. 판단(계정분류·가정)은 스스로, 계산·검증은 scripts/ 결정론 도구 호출.
---

# 밸류에이션 분석 (DCF)

**원칙: 판단은 LLM, 계산·검증은 코드.** 계정 분류·가정 도출·해석은 당신이 하되, 숫자 계산과
가정 타당성 검증은 반드시 `scripts/` 결정론 도구를 호출한다(재현·감사 가능). 방법론이 헷갈리면
`references/` 밸류에이션 북의 해당 챕터를 그때 읽는다(전부 미리 읽지 말 것).

## 워크플로우

### 1. 문서 인제스트 (재무제표·의견서 등을 받은 경우)
```
python scripts/ingest.py <파일경로>
```
- `.xbrl`(사업보고서) → 핵심 재무계정 자동 추출(매출·영업이익·자산…). **DART 정형공시는 XBRL 우선.**
- `.pdf`(외부평가의견서) → SOTP·영구성장률·통화 프로파일. ⚠️ DART PDF 한글은 CID폰트라 깨짐
  → `gate_ok`·`extract_method` 확인, 한글 필요 시 OCR(references/파서_아키텍처 참조).
- `.xlsx`(DCF 모델) → 셀 추출. 우리 모델 포맷이면 왕복 import 가능.

### 2. 계정 분류 (LLM 판단)
재무제표 각 계정을 **계정유형**과 **분석방법**으로 태깅한다(references/xdcf_계정분류 참조):
- 손익: Sales / COGS / SGA / NO(영업외)
- 재무상태표: WC / FA / NOA / IBD / OAL / EQU
- 분석방법: 매출성장률·시장점유율·단가×판매량 / 비용은 인건비·변동비·고정비·상각비
> ⚠️ 매출(Sales) 분석방법은 특히 신중히 — 무조건 "매출성장률"로 몰지 말 것(경쟁사 LLM의 약점).

### 3. 가정 산정 (LLM 판단 + 북 근거)
- **WACC**: CAPM 빌드업(Rf+β·ERP+size). β 출처(Bloomberg=글로벌 / KICPA=한국)와 ERP 시장을
  일치시킬 것. references/베타, references/deloitte_감사인검토 참조.
- **영구성장률(PGR)**: 한국 관행 0~1%(실측 DART 의견서 다수 1.00%), 글로벌 2~4%.
  **철칙: PGR ≤ 장기 GDP.** references/영구성장률 참조.

### 4. DCF 계산 + 검증 (결정론 도구 — 필수)
```
echo '{"wacc":0.09,"terminal_growth":0.01,"revenue":[...],"cogs":[...],"sga":[...],
"dep_amort":[...],"capex":[...],"delta_nwc_cash_adj":[...],"non_operating_assets":0,
"net_debt":0,"shares_outstanding":1000000}' | python scripts/dcf.py
```
- 반환: 주당가치·EV·**TV비중** + **audit 경고**(PGR≤GDP·TV과다·재투자·β/ERP정합).
- **audit 경고를 반드시 사용자에게 해석해 전달**(예: "TV비중 95% → 터미널 과의존, 재검토 권장").
- 세금 override·터미널 정규화가 필요하면 입력에 `tax_override`·`terminal_fcff_override` 추가.

### 5. 해석·리포트 (LLM)
- 결과를 밸류에이션 북 근거와 함께 설명. audit 경고는 리스크로 명시.
- 외부평가의견서 검증 시: 의견서의 가정(WACC·PGR)을 추출 → dcf.py로 **독립 재계산** → 차이 리포트
  (감사인 트랙). references/deloitte_감사인검토 체크리스트 활용.

## 신뢰 원칙
- 계산 결과는 **항상 scripts/dcf.py**로. 암산·추정 금지(재현·감사 불가).
- 숫자에 출처를 붙인다(어느 문서·어느 가정). audit 경고를 숨기지 않는다.
- 모르는 방법론은 references/ 북에서 확인 후 답한다(환각 금지).

## 참조
`references/index.md` — 밸류에이션 북(방법론·계정분류·의견서 양식·파서) 챕터 색인.
헷갈리는 주제만 골라 그때 읽는다.
