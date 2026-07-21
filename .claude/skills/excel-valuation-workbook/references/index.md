# 밸류에이션 북 — 챕터 색인 (스킬 참조)

단계별 사전 바인딩: **그 단계에 오면 해당 파일만 Read**(통독·전량검색 금지). 지식 원문은
`scripts/vendor/reference/<파일>.md`(빌드가 docs/reference에서 복사). 단계에 안 잡히는
비정형 질문만 `scripts/book_search.py "질의"` 폴백(오프라인 lexical, 네트워크 불요).

## 단계 ↔ 지식 바인딩

| 단계 | 지식 파일 (vendor/reference/) |
|------|------------------------------|
| W0 템플릿 | `template_conventions.md`(자체 시트 아키텍처·색상·함수 화이트리스트 — 스킬 내 저술) |
| W1 리서치 | `기업리서치_양식.md` + `참고보고서_활용.md` |
| W2 과거 FS 무결성 | `모델링_실무_2강4강.md`(§3 Finalize) + `account_dictionary.md`(계정 사전 — 스킬 내 저술) |
| W3 계정재분류 | `계정분류_모델아키텍처.md`(§2 유형·§3 방법) + `DCF_교육_정본.md`(§1.4 Valuation B/S 재분류) |
| W4 추정 | `리포트예시_클래시스.md`(§2 주요가정·부록A~D) + `모델링_실무_2강4강.md`(P×Q) |
| W5 WACC | `wacc_할인율서식.md` + `베타_Bloomberg_vs_KICPA.md` + `감사인검토_WACC방법론.md` + `영구성장률_PGR_적합성.md` |
| W6 DCF | `engine_spec.md`(§0·§4·§6) + `검증_클래시스_DCF.md`(tax_override·terminal 정규화 선례) |
| W7 시나리오 | `리포트예시_클래시스.md`(부록F Driver+CHOOSE 토글) |
| W8 민감도 | `앤트로픽_금융스킬_벤치마크.md`(§1 중심셀=base 검증) |
| W9 리포트 | `리포트예시_클래시스.md` + `장표_작성법.md` |
| 게이트 공통 | `앤트로픽_금융스킬_벤치마크.md`(§2 audit-xls — BS부터·하드코딩 오버라이드·DCF 버그 5종) |
| 계정 모호 | `계정분류_모델아키텍처.md`(현금·NOA/IBD 경계 처리) |
| PGR·TV | `영구성장률_PGR_적합성.md`(0~1% 관행·PGR≤GDP) |
| 감사인 트랙 | `외부평가의견서_고정양식_구조.md` + `감사인검토_WACC방법론.md` |

## ⚠️ 참고 모델 복제 금지

`정본_*`·`계정분류_*` 문서는 **방법론 지식**(무엇을 계산·검증할지)으로만 쓴다. 시트명(H_FS/EBIT/
BackData)·레이아웃을 복제하지 않는다. 워크북은 `template_conventions.md`의 **자체 아키텍처**를 따른다.

## frontmatter 활용

각 vendor/reference md 상단 frontmatter `canonical_questions`로 "이 챕터가 답하는 질문"을
확인할 수 있다. 단계 매핑이 헷갈리면 그걸로 검증.
