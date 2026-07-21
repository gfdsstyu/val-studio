# 밸류에이션 북 — 챕터 색인 (Skill 참조)

실제 지식은 레포의 `docs/reference/` 에 있다(이 Skill과 같은 저장소). 아래 표에서 필요한
챕터만 골라 `docs/reference/<파일>` 을 그때 읽는다. 전부 미리 읽지 말 것(progressive disclosure).

각 문서 상단 frontmatter(`canonical_questions`)로 "이 챕터가 답하는 질문"을 확인할 수 있다.

| 주제 | 파일 (docs/reference/) | 언제 읽나 |
|---|---|---|
| **계정 분류·모델 구조** | 계정분류_모델아키텍처.md | 계정유형/분석방법 태깅, 매출추정 방법 |
| **영구성장률(PGR)** | 영구성장률_PGR_적합성.md | PGR 몇 %? PGR≤GDP, TV비중 |
| **베타(β)** | 베타_Bloomberg_vs_KICPA.md | β 출처 선택(글로벌/한국), Adjusted β |
| **WACC·감사인 검토** | 감사인검토_WACC방법론.md | Modified CAPM·size premium·WARA↔IRR↔WACC·검토 체크리스트 |
| **WACC 서식 수식** | wacc_할인율서식.md | Hamada 언레버/리레버, 규모별 세율 |
| **매출추정 실무** | 모델링_실무_2강4강.md | P×Q(ARPU·ARPPU), 구분 실익, Finalize |
| **외부평가의견서 활용** | 외부평가의견서_활용.md | 방법론 taxonomy, 정형문구, 감사인 트랙 |
| **의견서 고정양식** | 외부평가의견서_고정양식_구조.md | 고정부/가변부, 섹션 앵커, SOTP |
| **합병·주식교환** | 합병_주식교환_방법론.md | 상장=기준주가/비상장=본질가치 |
| **리포트 양식·peer** | 리포트예시_클래시스.md | 리포트 구조, 유사회사 선정 |
| **동종 DCF 가정** | peer_dcf_클래시스_솔루엠.md | 실무 DCF 가정·CAPM |
| **참고보고서(리서치)** | 참고보고서_활용.md | 산업 CAGR·컨센서스 출처 |
| **파서 아키텍처** | 파서_아키텍처_매트릭스.md | 방식×유형, XBRL 우선/PDF OCR |
| **검증 사례** | 검증_클래시스_DCF.md | 세금주입·터미널정규화 실사례 |
| **손상검사** | 손상검사_impairment.md | VIU vs FV·CGU·영업권·손상DCF (⏳미래 트랙) |
| **스코프 로드맵** | 밸류에이션_스코프_로드맵.md | 거래·손상·FV·복합금융상품(RCPS) 트랙 지도 |

## 도구 (scripts/)
- `scripts/dcf.py` — DCF 결정론 계산 + 가정 audit(PGR·TV비중·재투자·β/MRP). **계산은 항상 이것으로.**
- `scripts/ingest.py` — 파일(xbrl/pdf/xlsx) → 방식·유형 라우팅 + 구조화 + 프로파일.
- 더 깊은 로직은 레포 `backend/`(calc_core·ingest) 직접 호출 가능.
