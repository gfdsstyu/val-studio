# 워크북 공유 메모리 + 사업설명 프리필 — 설계 · CS 리뷰 · 실행계획

> 2026-08-04. 질문: "Claude for Excel 은 대화 컨텍스트와 `Claude Log` 탭을 메모리로 쓰는데,
> val-studio 애드인과 **공통 메모리를 공유**할 수 없나?"
>
> **상태 표기**
> · §2 설계 = **미구현 제안**
> · §3 결함 P1-A/P1-B/P2-D/P3-E = **현행 코드에 실재**(라인 인용, 지금 고칠 수 있음)
> · §3 P3-F = 2026-08-04 신설된 `backend/agent/` 자기 리뷰
> · §4 프리필 = 미구현, 이 설계의 첫 소비자
>
> 선행: [agent_transplant_walkthrough.md](agent_transplant_walkthrough.md)(§0 3자 역할, §11 판정 배관) ·
> [addin_two_panel_ux.md](addin_two_panel_ux.md)(§0 애드인 간 통신 불가, §7-1 정본 분기)

---

## 0. 결론

| 질문 | 답 |
|---|---|
| 공유 메모리를 새로 만들 수 있나? | **만들 필요 없다.** 워크북이 이미 유일한 공유면이고 `_VS_STATE`/`Claude Log`가 그 위에 있다. 결손은 **단방향**(Claude→웹)이라는 것 — 웹만 아는 사실·판정이 메모리에 안 들어간다. |
| 그럼 무엇을 하나? | **반대 방향 채널 1개 신설**(`_VS_FACTS`, val-studio 소유) + 메모리를 종류별로 갈라 정책을 명시. |
| 자료구조는? | **표가 아니라 append-only 로그.** 조정 없는 다중 작성자 환경에서 갱신유실·인과성·멱등성·감사를 한 자료구조로 동시에 푼다(§2-2). |
| 먼저 할 일은? | **기존 코드 결함 2건(P1-A 원자성 · P1-B 파티션 미강제)이 선행**이다. 프리필이 첫 쓰기를 만드는 순간 위험이 실재화된다. |

한 줄: **공유 메모리 = 워크북 위의 소유자별 단방향 append-only 로그 3벌.** 새 매체도, 합의 알고리즘도 필요 없다 — 필요한 건 **쓰기 집합 분할을 규약이 아니라 불변식으로 만드는 것**.

---

## 1. 문제 정의

### 1-1. 공유 가능한 메모리 층은 하나뿐

| 층 | 매체 | Claude for Excel | val-studio | 공유 |
|---|---|---|---|---|
| 세션 | 대화 컨텍스트 / 브라우저 state | ✓ | ✓ | ❌ iframe 격리 — 구조적 불가 |
| **워크북** | 셀 + `_VS_STATE` + `Claude Log` | 읽기·쓰기 | **읽기만** | ✅ **유일** |
| 서버 | `project.data`(GCS/var) | ❌ | ✓ | ❌ 스킬은 BYOK 키도 네트워크도 없다 |

워크북 층이 유일 공유면이라는 사실은 **"워크북이 유일 정본"(§7-1)과 정합**한다 — 메모리도 정본을 따라가야 분기하지 않는다. 서버에 공유 메모리를 두면 정본이 둘이 되고, §7-1 이 경고한 fork 가 메모리 층에서 재현된다.

### 1-2. 현재의 결손 — 메모리가 단방향이다

`backend/excel/vs_state.py` 모듈 주석이 규약을 못 박아 뒀다:

> 두 시트 모두 **읽기 전용**으로 다룬다. 웹은 이관·표시만 하고 되쓰지 않는다
> (되쓰기는 스킬·평가인 몫 — 역할 3분할).

그래서 **웹만 아는 것이 메모리에 한 글자도 안 남는다**:

- DART/screener 에서 가져온 사실(사업 설명·주식수 D7·산업코드·타법인출자)
- 게이트 findings 와 그 규칙 계보
- Step2 판정 provenance(`model`·`prompt_sha256`·`approval=suggested`) — §11 에서 만들었는데 API 응답에만 있고 워크북엔 없다

결과: Claude 는 매번 "이 숫자 어디서 왔나"를 모르고 사람이 말로 옮긴다. **다리 1의 메모리 버전.**

### 1-3. CS 관점의 정확한 정의

**다중 작성자 · 공유 가변 저장소 · 잠금 없음 · 공통 시계 없음.** 합의(consensus)를 쓸 수 없는 환경이며, 표준 탈출구는 하나다:

> **쓰기 집합을 분할해 각 레지스터의 작성자를 1명으로 만든다(SWMR).**
> 작성자가 서로소인 키만 쓰면 조정이 필요 없다.

본 설계의 "소유권을 시트로 가른다"가 그 답이다. **단, 분할이 성립한다는 가정 자체가 현재는 강제되지 않는다** — §3 P1-B 가 그 지점이다.

---

## 2. 설계

### 2-1. 원장 3개와 소유권

| 원장 | 담는 것 | 소유자(쓰기) | 읽기 | 상태 |
|---|---|---|---|---|
| `_VS_STATE` 가정 대장 | **결정** — 승인된 가정 | 스킬·평가인 | 웹 | 기존 |
| **`_VS_FACTS`** | **사실·판정** — 원천 값 + 출처 | **val-studio** | Claude·웹 | **신설** |
| `Claude Log` | **서사** — 무슨 작업을 했나 | Claude | 웹 | 기존 |

⚠️ **양방향 시트를 만들지 않는다.** 잠금이 필요해지는데 iframe 격리에서 잠금은 불가능하다. 지금의 단방향 규율을 깨는 게 아니라 **채널을 하나 더 파서 각자 단방향을 유지**해 대칭으로 만드는 것이다.

### 2-2. 왜 표가 아니라 append-only 로그인가

| 문제 | 가변 표 | append-only 로그 |
|---|---|---|
| 갱신 유실 | 발생 | **구조적으로 불가** |
| 인과성 | 벽시계뿐 → happens-before 복원 불가 | `(writer, seq)` 로 부분순서 |
| 멱등성 | 재시도 시 중복/덮어씀 | 멱등 키로 dedupe |
| 감사(ISQM) | 최종 상태만 남음 | **이력 자체가 산출물** |
| 충돌 해소 | 정의되지 않음 | 읽기 시점 fold(키별 LWW) = **결정론** |

마지막 행이 결정적이다. **로그 + 읽기 시점 fold 는 연산 기반 CRDT 의 최소형**(키별 LWW 레지스터)이고, 조정 없이 두 독립 작성자가 같은 결론에 도달한다. 게다가 ISQM 요구가 "이력을 남겨라"이므로 **감사 요구와 동시성 해법이 같은 자료구조로 동시에 만족**된다.

대가는 무한 성장 → **소유자가 자기 로그만 compaction**(단일 작성자라 조정 불요). 보존 정책은 §2-4.

### 2-3. 행 스키마 — 새로 발명하지 않는다

`ingest/provenance.py` 의 `as_dict()` 가 이미 만드는 모양을 그대로 옮긴다:

```
seq | key                    | value            | method    | source_id  | locator      | as_of      | conf | approval
 17 | peer.145020.business   | 보툴리눔 톡신 제조 | structured| screener   | FDR/Products | 2026-08-04 | 0.8  | suggested
 18 | peer.145020.step2      | 유사              | llm       | claude-opus-5 | sha256:a3f… | 2026-08-04 | 0.6  | suggested
```

- `seq` = **작성자별 단조 증가**. 웹이 자기 시퀀스만 올린다(단일 작성자라 경합 없음).
- `key` = 네임스페이스 경로. 읽기 시 `key` 로 group → 최대 `seq` 채택(fold).
- `method` = `ExtractMethod`(`llm` 은 §11 에서 추가됨).
- `approval` = `suggested` 로 시작 → `_check_ledger` 의 미승인 경고가 **그대로 적용**된다.
  모델이 프리필한 사업 설명이 "확정 사실"로 둔갑하지 않는 것이 이 열 하나로 보장된다.

⚠️ **헤더 이름으로 파싱한다**(위치 아님) + `schema_version` 키를 둔다 — 근거는 §3 P2-D.

### 2-4. 종류별 정책 — "메모리"는 세 가지를 덮고 있다

| 종류 | 예 | 재도출 | 축출 | 일관성 요구 |
|---|---|---|---|---|
| **캐시** | screener 사업설명, DART 사실 | 가능 | **자유**(TTL·staleness) | 없음 |
| **로그** | 판정 provenance, 작업 이력 | **불가** | **금지** | append-only |
| **상태** | 승인된 가정 | 불가 | 금지 | **셀과 트랜잭션 정합** |

셋은 무효화 정책이 정반대다. 캐시 행을 로그처럼 영구 보존하면 워크북이 붓고, 로그 행을 캐시처럼 축출하면 조서가 증발한다. → **compaction 은 `method`/`key` 네임스페이스로 종류를 판별해 캐시 행만 대상으로 한다.**

캐시 쪽은 정직하게 이름 붙인다: **코히런스 프로토콜이 없는 stale-while-revalidate 캐시**. 상류(공시 재작성·주가)가 바뀌어도 무효화 신호가 없다. 허용 가능한 유일한 근거는 **값에 provenance 가 붙고 결정론 게이트가 하류에서 재검증**한다는 것 — 이 근거가 없으면 그냥 잘못된 캐시다.

### 2-5. 배관은 이미 다 있다 (신규 발명 0)

| 필요 | 이미 있는 것 |
|---|---|
| 시트 생성·기입 | `officeBridge.writeSheetPlan()` — H_FS 로 실전 검증 |
| 배치도 자료구조 | `excel/fs_sheet.py` 의 `WorkbookPlan` — Office.js·xlsx 두 소비처 보유 |
| 웹 쪽 읽기 | `vs_state.parse_vs_state` 에 파서 함수 추가 |
| Claude 쪽 읽기 | SKILL.md 에 "`_VS_FACTS` 가 있으면 먼저 읽는다" 한 문단 |
| 미승인 게이트 | `_check_ledger` 의 `suggested` 규약 재사용 |

---

## 3. CS 리뷰 — 결함 인벤토리

### P1-A. 되쓰기가 원자적이지 않다 (**현행 코드**)

`frontend/src/officeBridge.js:98-99`:

```js
if (existing.has(sp.name)) book.getItem(sp.name).delete();
const sh = book.add(sp.name);
```

**delete-then-add.** Office.js 는 배치를 큐에 넣고 `ctx.sync()` 에서 적용하지만 **트랜잭션 보장이 문서화돼 있지 않다** — 중간 실패(보호된 시트·이름 충돌·사용자 취소)면 **삭제만 적용된 상태**가 남을 수 있다.

H_FS 같은 재생성 가능한 데이터 시트에서는 감내할 만하다(재조회하면 된다). **메모리 시트에서는 치명적**이다 — 판정 provenance 는 유일본이고 재생성이 불가능하다. torn write 한 번에 조서가 사라진다.

> **수정**: ①임시 시트에 쓰고 이름 교체(원자에 가까움) 또는 ②애초에 삭제하지 않고 **append**. ②가 §2-2 와 같은 답으로 수렴하므로 `_VS_FACTS` 는 ② 로 간다. H_FS 같은 전체 재생성 시트는 ① 로.

### P1-B. 파티션이 강제되지 않는다 (**현행 설계**)

SWMR 논증은 "각 레지스터의 작성자가 정확히 1명"일 때만 성립한다. 실제로는 세 경로로 깨진다:

| 침해 경로 | 결과 |
|---|---|
| 사람이 `_VS_FACTS` 를 손으로 편집 | 웹의 다음 쓰기가 조용히 덮음 |
| 사용자가 Claude 에게 "이 시트도 고쳐줘" | 다중 작성자 |
| Excel 자체 연산(행 삽입·정렬·열 삭제) | 위치 기반 파싱이 깨짐(P2-D) |

**규약은 불변식이 아니다.** Office.js `sheet.protection.protect()` 로 소유자 아닌 주체의 쓰기를 물리적으로 막는 것이, "분할이 성립한다"는 가정을 실제 불변식으로 바꾸는 유일한 방법이다.

⚠️ **P1-A 와 맞물린다**: 보호된 시트는 `writeSheetPlan` 의 `delete()` 를 실패시켜 torn write 를 **실제로 유발**한다. 두 결함은 반드시 같이 고친다.

### P2-C. 표 → 로그 (설계 결함, §2-2 에서 해소)

초안에서 `_VS_FACTS` 를 가변 key-value 표로 잡았던 것은 오류다. "메모리는 요약이 아니라 원장이어야 한다"고 쓰면서 자료구조는 표로 잡은 불일치. §2-2 로 정정.

### P2-D. 위치 기반 파싱 = 스키마 진화 취약 (**현행 코드**)

`backend/excel/vs_state.py:96`:

```python
row = {k: cells.get((r, c)) for k, c in zip(_LEDGER_COLS, "ABCDE")}
```

**열 위치로** 파싱한다. 독립적으로 갱신되는 두 리더(SKILL.md 쪽 / 웹 파서 쪽)가 하나의 포맷을 읽는 전형적 **프로토콜 버전 문제**인데, 위치 결합은 최악의 선택이다 — 누군가 열을 하나 끼우면 오류가 아니라 **조용한 오독**(값이 다른 필드로 들어감)이 된다.

> **수정 3종**: ①헤더 이름으로 파싱 ②`schema_version` 키 ③전방 호환 규칙(모르는 열은 무시하되 절대 실패하지 않음). `_VS_FACTS` 신설과 **무관하게 이미 있는 부채**다.

### P2-E. 캐시 코히런스 없음 — 수용하되 명시

§2-4 참조. 수용 근거(provenance + 하류 결정론 재검증)를 문서에 남기는 것이 조건.

### P3-F. 열거(enumeration) vs 술어(predicate) (**현행 코드**)

`backend/excel/workbook_diff.py:30`:

```python
STATE_SHEETS = ("vsstate", "claudelog")
```

**열린 세계에 닫힌 가정**을 박아둔 것이다. 목록 밖 시트가 새로 생기면 구조 변경 → `blocked` 로 잡혀 **자동반영이 영구 차단**된다(같은 파일 27행 주석이 이를 "마찰 1호"라 부른다). 상태 시트가 늘 때마다 코드 수정이 필요한데, 그 코드는 Claude for Excel 쪽에 배포되지 않는다.

> **수정**: 접두 규약 술어(`name.startswith("_VS_") or name == "Claude Log"`) + **알려진 원장 레지스트리**. 미등록 `_VS_*` 는 state 버킷에 넣되 **"미등록 상태 시트" 경고**를 단다 — 차단하지도, 침묵하지도 않는 중간값(순수 술어는 게이트를 약화시킨다).

### P3-G. 판정 계층 자기 리뷰 (2026-08-04 신설분)

| # | 결함 | 수정 |
|---|---|---|
| G1 | `agent/judge.py check_shape` 가 **fail-open**("모르는 키워드는 조용히 통과") | 런타임은 관대하게 두되 **검증을 정적으로 이동** — 레포의 모든 선언 스키마를 순회해 "지원 키워드만 썼는가"를 단언하는 린트 테스트 추가 |
| G2 | `ProviderError.kind` 가 stringly-typed. `_AGENT_STATUS.get(kind, 502)` 가 fail-open → kind 추가 시 인증 오류가 502 로 둔갑(사용자에겐 "내 키 문제"가 "서버 장애"로 보임) | enum + 전수 매핑 단언 테스트 |
| G3 | `PROVIDERS` 전역 딕셔너리를 테스트가 변이 → 병렬 실행(xdist)에서 데이터 레이스 | 현재 xdist 미사용이라 잠복. **트레이드오프로 수용하되 기록**(프로덕션 시그니처 청결 우선) |

### 과잉 설계 경계 — 하지 않을 것

- **벡터 클록·합의 알고리즘** — 작성자 2명 + 파티션 성립이면 불필요. 작성자별 시퀀스로 충분.
- **알고리즘 복잡도 최적화** — N(계정·후보)이 수백 규모. 논점 아님.
- **가격 vintage 만료 테스트** — 벽시계를 읽는 테스트는 미래에 터지는 시한폭탄. UI 표기로 충분.

---

## 4. 사업설명 프리필 — 이 설계의 첫 소비자

### 4-1. 최단 경로는 DART 가 아니라 screener (키 불필요)

`backend/ingest/screener.py:47`:

```python
products: str = ""          # 주요 제품 — **판별력의 핵심**
```

이 인덱스는 **FDR 기반이라 DART 키가 필요 없다**(`:157` 검색 대상 = 명칭·종목코드·세부업종·주요제품). Step2 판정이 요구하는 "같은 사업으로 돈을 버는가"의 근거로 1차 충분하다. 부족하면 DART 개황으로 보강(키 필요, 선택).

### 4-2. 흐름

```
① screener.products  ──▶ ② PeerSheet '사업' 열 프리필(현재 손 입력)
                              │
                              ├──▶ ③ _VS_FACTS append: peer.<ticker>.business
                              │        (method=structured, source=screener, approval=suggested)
                              │
                              └──▶ ④ Step2 판정 → _VS_FACTS append: peer.<ticker>.step2
                                       (method=llm, source=model id, locator=prompt sha)
                                            │
                                            ▼
                                  Claude for Excel 이 Peer 시트를 만들 때
                                  같은 문자열·같은 출처를 쓴다(재조회 0)
```

④ 가 §11 에서 만든 `JudgeResult.provenance()` 를 워크북으로 흘려보내는 지점이다 — "무엇이 판정했고 사람이 무엇을 승인했나"가 조서에 남아 §10-1 ISQM 증적 요구와 맞물린다.

### 4-3. 반출 면적 통제

`_VS_FACTS` 에 클라이언트 자료가 쌓이므로 **워크북의 반출 면적이 커진다**. SKILL.md §키 규약이 이미 "API 키·토큰을 워크북 셀·`_VS_STATE`·가정 대장 어디에도 기록 금지 — 워크북은 공유·전달 산출물"이라고 규정하며, `_VS_FACTS` 는 그 적용 대상이 하나 느는 것이다.

여기에 더해 **"게이트가 좁힌 최소 조각" 원칙을 메모리에도 적용**한다: 원문을 옮기지 말고 **참조(접수번호·좌표)를 남긴다**. 사업 설명 같은 짧은 요약은 값으로, 주석 본문 같은 원문은 locator 로.

---

## 5. 실행 순서 (통합)

선행 관계가 있어 순서가 곧 안전 조건이다.

| # | 항목 | 왜 이 순서 | 규모 |
|---|---|---|---|
| **1** ✅ | **P3-F** `STATE_SHEETS` 술어화 + 미등록 경고 + 회귀 테스트 | 이걸 안 하면 `_VS_FACTS` 생성 순간 **왕복 루프가 죽는다** | 소 |
| **2** ✅ | **P1-A** `writeSheetPlan` 원자성(임시 시트 → 커밋 sync → 교체) | 프리필이 첫 쓰기를 만드는 순간 torn write 가 실재화 | 소 |
| **3** ✅ | **P1-B** 시트 보호로 파티션 강제(`readonly_hint` → protect) | 2 와 맞물림(보호가 delete 를 실패시킴) | 소 |
| **4** ✅ | **P2-D** 헤더 기반 파싱 + `state_schema`(기존 `_VS_STATE` 포함) | 로그 스키마를 굳히기 전에 파싱 규약부터 | 소 |
| **5** ✅ | screener → 사업설명 프리필 + PeerSheet 배선 | **첫 소비자를 손에 쥔다** | 중 |
| **6** ✅ | `_VS_FACTS` 로그 빌더 + Office.js append + 웹 파서 | 5 에서 실제 쌓일 행을 본 뒤 스키마 확정 | 중 |
| **7** ✅ | SKILL.md 읽기 규약 한 문단 | Claude 쪽 소비 개시 | 소 |
| **8** ✅ | **P3-G** 스키마 린트 테스트 + `kind` enum화 | 독립. 언제든 | 소 |

⭐ **5 를 6 보다 먼저 두는 이유**: 소비자 없이 스키마를 먼저 굳히면 대개 틀린다. 프리필이 만들어내는 실제 행 한 종류를 손에 쥔 뒤 로그 스키마를 확정한다.

⚠️ **1~4 는 전부 기존 코드 수정이며 신규 기능이 아니다.** 지금 `_VS_FACTS` 없이도 P1-A·P2-D·P3-F 는 실재하는 결함이므로, 이 계획이 무산돼도 1~4 는 독립적으로 가치가 있다.

### 5-1. 1~4 구현 기록 (2026-08-04)

| 항목 | 변경 | 비고 |
|---|---|---|
| 1 | `workbook_diff.py` — `KNOWN_STATE_SHEETS`(레지스트리) + `STATE_PREFIX="_VS_"` 술어, `is_known_state_sheet()` 신설, `WorkbookDiff.warnings` 추가 → `ApplyPlan.warnings` 로 전달 | 접두 판정은 **원본 이름**으로(정규화 후 `startswith("vs")` 는 'VS 분석' 오탐) |
| 1 | `vs_state.parse_vs_state` 가 **해석 가능한 원장만** 파싱 | 미등록 시트를 `_VS_STATE` 로 착각해 없는 키를 만드는 것을 차단. "해석 못 함"의 표면화는 diff 책임 |
| 2 | `officeBridge.writeSheetPlan` — 임시 시트 전량 기입 → `sync()`(**커밋 지점**) → 원본 삭제 → 이름 승격 | 시트를 **한 장씩 최종 이름까지 확정**하고 다음으로 간다(H_FS 가 rFS 를 이름으로 참조) |
| 3 | 같은 함수 — `readonly_hint` 시트는 기입 후 `protection.protect()`, 재기입 시 삭제 전 `unprotect()` | `readonly_hint` 는 이미 있던 **선언**이었고 집행만 없었다. 실 적용 대상은 `rFS` 1장 |
| 4 | `vs_state.py` — `_LEDGER_LABELS` 로 **열이름 파싱**, 모르는 열은 `x_<라벨>` 로 보존, 열이름 행 부재 시 위치 폴백 + 경고. `STATE_SCHEMA_VERSION`·`_check_schema` 신설, `scaffold.py` 가 `state_schema` 키 기록 | 상위 버전 워크북을 만나면 **경고만 하고 계속 읽는다**(하위 리더가 죽으면 안 됨) |

**계획과 다르게 한 것 1건**: 2번의 "로그=append 경로 신설"은 **하지 않았다.** 소비자
(`_VS_FACTS`)가 6번에 오는데 지금 만들면 쓰이지 않는 API 가 굳는다 — 이 문서 §5 의
"소비자 없이 스키마를 굳히면 틀린다" 원칙을 append 경로에도 적용했다. 6번과 함께 만든다.

### 5-2. 5번 구현 기록 (2026-08-04)

| 항목 | 변경 |
|---|---|
| 조회 | `screener.rows_by_code()` — 종목코드 → 행(반복 선형탐색 회피) |
| 도메인 | `ingest/peer_prefill.py` 신설 — `compose_business()` + `prefill_business()` → **`PrefillFact`**(ticker·name·business·key·as_of·method·source_id·locator·confidence 0.8·`approval="suggested"`) |
| API | `POST /api/peer/prefill` — `_load_screener()` 재사용, **DART 키 불필요** |
| 화면 | PeerSheet `① 사업 설명 자동 채움` → `② Step2 판정 초안` 2단 버튼. 프리필은 **빈 칸만** 채운다(사람 입력 우선) |
| 테스트 | `tests/test_peer_prefill.py` 12건(인덱스 직접 구성, 네트워크 0). 전체 **925 그린** |

**설계 결정 3가지**
- **산출물이 문자열이 아니라 레코드다.** `PrefillFact.key()` 가 `peer.<티커>.business` 를
  내므로 6번에서 `_VS_FACTS` 행으로 그대로 append 된다 — §2-3 행 스키마를 미리 맞췄다.
- **못 찾으면 채우지 않고 경고한다.** 빈 값을 사실로 기록하면 원장이 "조회했는데 없었다"와
  "조회하지 않았다"를 구분하지 못한다. 업종만 아는 회사는 `(주요제품 미상) 업종: …` 로
  **모른다는 사실까지 문장에 담는다** — 그게 Step2 판정에 영향을 주는 정보이기 때문.
- **staleness 게이트를 걸지 않는다.** `as_of` 는 기록하되 차단하지 않는다 — 시가총액과
  달리 제품 서술은 주 단위로 변하지 않는다. 시총용 `STALE_DAYS` 규율을 그대로 가져오면
  멀쩡한 프리필이 막힌다.

**⚠️ 티커 함정 재발 방지**: 조회는 `normalize_ticker` 로 하되 **되돌려주는 값은 원본
문자열**이다(`A145020` → `A145020`). 정규화된 값을 돌려주면 표·퍼널의 행과 어긋난다 —
`peer_judge` 와 동일한 함정이라 회귀 테스트를 양쪽에 뒀다.

### 5-3. 6~8번 구현 기록 (2026-08-04)

| 항목 | 변경 |
|---|---|
| 6 | `excel/facts_sheet.py` 신설 — `parse_facts`(열이름 기반) · `FactsLog.fold()`(키별 최대 seq = LWW) · `FactsLog.next_seq(writer)` · `build_append`(멱등·차단). 헤더는 `_VS_STATE` 배치를 미러 |
| 6 | `workbook_diff.KNOWN_STATE_SHEETS` 에 `vsfacts` 등재. `parse_vs_state` 는 소유자별로 분기해 **`_VS_FACTS` 를 읽지 않는다**(아는 원장이라고 같은 파서에 넣으면 없는 키가 생긴다) |
| 6 | `POST /api/facts/append-plan` — 클라가 읽은 격자를 서버가 fold 해 **바뀐 것만** 새 행으로 |
| 6 | `officeBridge.readSheetGrid()` + `appendFactRows()` — **지우지 않는다**. 쓰기 전 unprotect, 쓴 뒤 protect |
| 6 | PeerSheet `③ 워크북 원장에 기록`(Task Pane 전용). 판정 키는 서버가 만든다(`/api/peer/judge` 응답에 `key` 추가 — 티커 정규화 규칙이 JS 에 복제되면 드리프트) |
| 7 | SKILL.md 에 `공유 원장 (_VS_FACTS 시트) — 읽기 전용` 절 신설: 레이아웃·열이름 기반 읽기·**최대 순번이 현재 값**·쓰기 금지·`suggested` 미승인 규율 |
| 8 | `ErrorKind` enum 신설(9종) — `ProviderError` 가 생성 시점에 미등록 kind 를 거부. `_AGENT_STATUS` 전수 매핑을 테스트가 강제 |
| 8 | `tests/test_schema_lint.py` — 선언 스키마의 키워드·`additionalProperties:false`·`required` 전수 검사 + **미등록 `*_SCHEMA` 발견 가드** |
| 테스트 | `test_facts_sheet.py` 13 + `test_schema_lint.py` 7. 전체 **945 그린** |

**설계 결정 2가지**
- **모르는 내용은 덮지 않는다.** 시트에 내용이 있는데 원장 열이름이 없으면 `blocked` 로
  돌려주고 기록하지 않는다 — 공유면에서 정체 모를 내용을 헤더로 갈아엎으면 남의 기록이
  소리 없이 사라진다. 첫 기록(빈 시트)일 때만 헤더를 쓴다.
- **fail-open 을 정적 검사로 옮겼다.** `check_shape` 의 "모르는 키워드는 통과"는 런타임
  관대함으로 남기되, 레포가 선언한 스키마가 지원 부분집합 안에 있는지는 CI 가 본다.
  검증을 없애는 게 아니라 **시점을 옮기는 것**이 정공법이다.

**행위 변화 1건**: `rFS` 가 이제 **보호된다**. 지금까지 "수정금지"는 주석뿐이었고, 사람이
`rFS` 를 고치면 H_FS 의 `원본자료 Refer Check` 행이 **바뀐 기준선과 비교**해 조용히
무의미해졌다. 재기입은 도구가 보호를 해제하고 진행하므로 왕복은 그대로다.

---

## 6. 수용 기준 (DoD)

- [ ] `_VS_FACTS` 를 만든 뒤에도 `workbook_diff` 가 **blocked 0** 을 유지한다(1 의 회귀 테스트)
- [ ] 시트를 보호한 상태에서 재기입해도 **기존 행이 소실되지 않는다**(2·3)
- [ ] 열을 하나 끼운 구버전 `_VS_STATE` 를 파싱해도 **필드가 밀리지 않는다**(4)
- [ ] 같은 프리필을 2회 실행하면 로그에 **중복 행이 생기지 않는다**(멱등 키)
- [ ] 프리필 값이 `approval=suggested` 로 기록되고, 미승인 상태에서 `_check_ledger` **경고가 뜬다**
- [ ] 워크북 어디에도 **API 키가 기록되지 않는다**(SKILL.md 키 규약 회귀)
- [ ] 전체 스위트 그린(현 기준선 **902**)

---

## 7. 근거 파일 색인

| 주장 | 파일·라인 |
|---|---|
| 메모리 단방향 규약 | `backend/excel/vs_state.py` 모듈 docstring |
| 가정 대장 5열·미승인 게이트 | `backend/excel/vs_state.py:26·28·122` |
| **위치 기반 파싱(P2-D)** | `backend/excel/vs_state.py:96` |
| **STATE_SHEETS 열거(P3-F)** | `backend/excel/workbook_diff.py:30·33` (+27행 "마찰 1호" 주석) |
| 상태 시트 추가/삭제 → state 버킷 | `backend/excel/workbook_diff.py:142·148` |
| **delete-then-add(P1-A)** | `frontend/src/officeBridge.js:98-99` |
| 시트 플랜 두 소비처 | `backend/excel/fs_sheet.py` (`WorkbookPlan`) |
| provenance 직렬화 모양 | `backend/ingest/provenance.py:124` (`as_dict`) |
| **주요 제품 필드(프리필 원천)** | `backend/ingest/screener.py:47·157` |
| 워크북=상태 규약 / 키 기록 금지 | `.claude/skills/excel-valuation-workbook/SKILL.md` §상태 규약 |
| 판정 provenance 산출 | `backend/agent/judge.py` (`JudgeResult.provenance()`) |
| 애드인 간 통신 불가 | `docs/plan/addin_two_panel_ux.md` §0 |
