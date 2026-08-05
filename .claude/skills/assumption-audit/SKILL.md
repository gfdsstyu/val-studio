---
name: assumption-audit
description: 밸류에이션 리포트·엑셀모델의 가정을 감사·검증. 증권사 리서치/DCF 모델/외부평가의견서를
  받아 각 가정을 원장화하고, (1) 산문 논리가 자기 숫자를 재현하는지 자기정합성 검산, (2) 동종 산업
  분포 대비 이상치, (3) EV→목표주가 브리지 누락(비지배지분·이중계상), (4) provenance 결측을 감사
  리포트로 출력할 때 사용. 판단은 LLM, 검산·이상치는 결정론 도구.
---

# 가정 감사 (Assumption Audit)

밸류에이션 분석([[valuation-analysis]])이 모델을 *만든다면*, 이 스킬은 남이 만든 모델·리포트를
*감사*한다. **핵심 질문 = "이 가정이 말이 되나, 그리고 저자의 서술이 자기 숫자와 일치하나?"**

**원칙: 판단은 LLM, 검산·대조는 코드.** 가정 해석·gap 원인 진단은 당신이, 자기정합성 검산·산업
이상치 판정은 `scripts/`·`calc_core` 결정론 도구가.

## 워크플로 ↔ 도구 ↔ 지식

| 단계 | 도구 | 📖 지식 (docs/reference/) |
|---|---|---|
| **0 가정 추출·원장화** ⭐ | (LLM) 리포트/모델에서 가정 → `smic/_ledger/*.yaml` 스키마 | **가정원장_방법론** (claim·formula·value·basis·provenance) |
| 1 매출동인 분류 | (LLM) driver_type 판정 | **매출추정_논리_타이폴로지** (A~K) + `calc_core.revenue.route_archetype` |
| 2 자기정합성 검산 | `scripts/assumption_check.py <ledger.yaml>` | 가정원장_방법론 (claimed↔applied gap) |
| 3 산업 이상치 대조 | `calc_core.checks.check_metric_vs_industry(산업, opm/dso/dio/capex_sales, 값)` | **산업_프로파일** + 벤치마크_{마진,운전자본,CAPEX} |
| 4 마진/CAPEX/WC 방식 점검 | (LLM) M/X/W 아키타입 적정성 | 마진·CAPEX·운전자본_드라이버_타이폴로지 |
| 5 기법 적정성 | `calc_core.method_selector.recommend_by_business_nature` | **밸류에이션_기법선택_로직** |
| 6 EV→목표주가 브리지 | (LLM) Br1~Br6 체크 + `calc_core.checks.check_bridge_consistency` | **밸류에이션_브리지_타이폴로지** (비지배지분 누락·이중계상) |
| 7 시나리오 점검 | (LLM) range 이중계상 함정 | **시나리오_구축_타이폴로지** |
| 8 코퍼스 배치 감사 | `scripts/audit_scan.py` | (gap·provenance·산술이상치 집계) |

## 감사 체크리스트 (red flag 우선순위)
1. **자기정합성 gap** (2단계): 서술한 방식(예 "5년 평균 0.436%")이 자기 표 숫자(예 실제 0.30%)를
   재현하나? 안 되면 `finding`에 claimed↔applied 병기. → 케이씨 파일럿 사례.
2. **산업 이상치** (3단계): OPM/DSO/DIO/CAPEX가 동종 min~max 밖이면 WARN. "필러사 DIO 60일
   (동종 219일)" 같은 이례 = 사업모델 질문.
3. **브리지 누락** (6단계): **비지배지분 미차감**(연결 SOTP 과대 = 최빈 오류), 지분법 자회사
   이중계상, 지주 할인 근거 부재.
4. **provenance 결측** (8단계): 전방 컨센서스·회전기일 출처 미기재 = 감사 추적 불가.
5. **시나리오 이중계상** (7단계): 운영가정 + exit 배수를 같은 방향 동시 조정 = range 과장.

## 출력
`감사스캔_리포트.md` 형식: A.내러티브↔숫자 gap · B.provenance 결측 · C.산술/이상치. 각 항목에
근거(원문 span·산업 분포)와 심각도(FAIL/WARN/PASS). rigor=학회리포트는 참고 prior임을 명시.

## 데이터 갱신
케이스 doc·산업 태그 변경 시 `python scripts/refresh_all.py` → MD(RAG) + `calc_core/data/
industry_benchmarks.json`(엔진 게이트) 동기화.

## 관련 지식
[[가정원장_방법론]] · [[산업_프로파일]] · [[밸류에이션_브리지_타이폴로지]] · [[매출추정_논리_타이폴로지]] · [[밸류에이션_기법선택_로직]] · [[시나리오_구축_타이폴로지]]
