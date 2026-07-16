# 밸류에이션 북 온톨로지 + RAG 인덱스

**SSOT → 컴파일 단방향.** 사람은 `docs/reference/*.md`(frontmatter + `[[링크]]`)만 편집하고,
`build.py`가 온톨로지·RAG 인덱스를 **자동 생성**한다. 그래서 온톨로지가 문서와 절대 어긋나지 않는다
(감린이 [[unified_ontology_direction]] 패턴). 재생성: `python docs/reference/ontology/build.py`.

## 산출물 (자동생성 — 직접 편집 금지)
| 파일 | 용도 |
|---|---|
| `rag_index.json` | **RAG 검색 레코드** — 챕터별 {path·topic·keywords·canonical_questions·track·links} |
| `graph.json` | **개념 그래프** — nodes(챕터)·edges([[링크]])·concepts(keyword→챕터) |
| `CONCEPTS.md` | 사람용 — 트랙별 챕터·교차개념·미해소링크 |

## RAG 최적화 설계 (3층)
1. **frontmatter = 검색 메타** — `keywords`(필터·엔티티)·`canonical_questions`(쿼리 사전예측 매칭)·
   `topic`(요약). 사용자 "영구성장률 몇%?" → canonical_questions 직매칭으로 정확 청크 상위.
2. **[[링크]] = 관계 엣지** — 챕터 간 개념 연결(β→WACC, VIU↔FVLCD, TF모형→RCPS). 검색 시 **인접 챕터
   확장**(관련 지식 동반 회수). graph.json 의 edges.
3. **track = 라우팅** — 6트랙(거래평가·손상FV·복합금융상품·실사정상화·파서·검증)으로 질의 라우팅.

## RAG 파이프라인 권장
```
질의 → (1) canonical_questions 매칭 + keywords 필터(rag_index)
     → (2) 매칭 챕터 본문 청크 임베딩 검색
     → (3) graph.json 로 인접 챕터 1-hop 확장(관련 지식)
     → (4) track 다르면 재랭킹 downweight
     → LLM 컨텍스트(청크 + provenance)
```
- 청크 단위: 챕터 내 `## 섹션` 헤딩 기준 분할 권장(각 섹션이 자기완결). frontmatter는 각 청크에 메타로 부착.
- provenance: 답변 시 챕터 path + 섹션을 출처로.

## 개념 그래프 = 온톨로지
- **노드** = 챕터(19), **엣지** = [[링크]](21, 전부 해소), **개념** = keywords(220).
- **교차개념**(다중 챕터 등장) = 온톨로지의 허브: 클래시스·베타·WARA·PPA·RCPS 등이 챕터를 잇는다.
- 엔티티 해소: [[링크]] 미해소=0 → 모든 참조가 실제 문서로 연결(감린이의 "0/127 엔티티해소 난제"와
  달리 여기선 규모 작아 완전 해소). 저술 후보(미해소 링크)는 CONCEPTS.md 상단 경고.

## 유지
- 새 챕터 추가/링크 수정 후 `build.py` 재실행 → 3파일 갱신. CI 훅으로 자동화 가능.
- track 매핑은 build.py `_TRACK_HINTS`(키워드 기반 휴리스틱). 오분류 시 hint 조정.
