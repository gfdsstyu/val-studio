# 회사 탐색·스크리너 고도화 — 구현 계획 (2026-08-04)

> **무엇을·왜**(동종 상용 툴 벤치마크)는 레포 밖 로컬 노트에 둔다. 이 문서는 **어떻게**(계약·모듈·테스트·게이트)만 적는다.
> 원칙: 각 Phase 종료 시 `py -3.12 -m pytest` 그린 유지(착수 시점 **863**), 프론트 `npm run build` 그린.

---

## 0. 착수 시점 사실 (실측)

| 항목 | 상태 |
|---|---|
| 개황 필드 | 백엔드 `dart_reports._COMPANY_FIELDS` **17종 수집** / 화면 6종 렌더 → **렌더 갭** |
| 회사 검색 | `dart_corp.search_corp_index` — 이름 부분일치만. limit 30 **절단 미표시** |
| 공시 주체 검증 | `POST /api/dart/company-check` 완료(89ce67e) |
| peer 퍼널 | `peer_selection.py` Step1a~Step4. **Step1 앞단(모집단 탐색) UI 없음** |
| 시가총액 | `price_client.marketcap`(pykrx) 보유 — 프론트 미소비 |
| 업종 | `ksic.py` 검색 보유 |
| 주요 제품 | **없음** — 사업보고서 '주요 제품 및 서비스' 표에 존재 |
| CB·주식매수선택권 | 엔진 `convertible.py`·`backsolve.py` 골든 검증 완료 / **화면 없음** |

---

## Phase 1 — 탐색 UX 이식 (백엔드 변경 최소)

### 1-1. 개황 전량 렌더 + 복사 (I1)
- **대상**: `frontend/src/pages/appraiser/DisclosureSheet.jsx` 개황 카드
- **작업**: `_COMPANY_FIELDS` 17종을 2열 정의형 표로 전량 표시.
  - 라벨은 `_COMPANY_FIELDS` 의 한글값을 그대로 쓴다(백엔드가 이미 라벨을 들고 있다).
  - `hm_url`·`ir_url` 은 `<a target="_blank" rel="noreferrer">` — **자료 수집 동선 직결**.
  - `acc_mt !== "12"` 경고는 현행 유지(DCF 기간 정합).
- **추가**: 우상단 복사 버튼 → `TableTransfer` 재사용(2열 격자를 rows 로).
- **주의**: 백엔드 응답이 이미 전량을 담으므로 **API 변경 없음**.

### 1-2. 용어 정정 (I3)
- `corp_code` 노출 지점 전량 → **"고유번호"** 병기(`고유번호(corp_code)`).
- 대상: `CompanyPicker`, `DisclosureSheet`, `MultiYearFsPanel`, `CostsSheet`.
- 근거: DART 공식 명칭. 회계 실무 표준어.

### 1-3. 검색 3-way 라우팅 (I2)
- **대상**: `CompanyPicker.search()`
- **규칙**(클라 판정, 서버 변경 없음):
  | 입력 | 처리 |
  |---|---|
  | 숫자 8자리 | 고유번호 직결 → 곧바로 `company-check` |
  | 숫자 6자리 | 종목코드 → corp 인덱스에서 `stock_code` 일치 검색 |
  | 그 외 | 현행 이름 부분일치 |
- **서버 보강 1건**: `POST /api/dart/corp-search` 에 `by` 파라미터(`name`|`stock`) 추가.
  `search_corp_index` 에 `stock_code` 정확일치 분기 신설(기본값은 현행 유지 → 회귀 없음).
- placeholder: `회사명 · 종목코드(6자리) · 고유번호(8자리)`

### 1-4. 결과 표기 (I6·I8)
- 후보 행: `이름 [종목코드]` / 아래 줄에 고유번호(muted).
- 하단 `총 N건` + **절단 표시**: `search_corp_index(limit=30)` 이므로
  서버가 `truncated: bool`·`total: int` 를 함께 반환하도록 `/api/dart/corp-search` 확장.
  → 지금은 30건에서 잘려도 화면이 침묵한다(정직 표기 위반).

### 1-5. 기간 프리셋 (I4)
- `DisclosureSheet` 공시목록: `오늘/1개월/3개월/6개월/1년/3년/5년` 칩 + 시작·종료 2칸.
- 현재는 '최근 1년' 하드코딩 → 사업보고서가 창 밖으로 나가면 안 보인다.

### 1-6. ⓘ 도움말 · 빈 상태 문구 (I5·I7)
- 공용 컴포넌트 `frontend/src/Hint.jsx` 신설: `<Hint>설명…</Hint>` → ⓘ 토글.
- 상시 노출 `muted` 설명문을 접는다. **Task Pane(~350px) 세로 확보가 주목적**.
- 빈 상태 문구 규약: *상태 + 다음 행동*. 예 `"조회 결과 없음 — 기간을 넓히거나 공시유형을 '전체'로 바꿔보세요."`

**Phase 1 게이트**: 863 그린 유지 · `test_frontend_wiring` 통과(신규 저장 키 없음) · 빌드 그린.

---

## Phase 2 — 기업 스크리너 (최대 격차)

### 2-1. 목표
peer **모집단 탐색**을 화면으로. `peer_selection` Step1 앞단에 꽂아
`스크리너 → Step2(LLM 유사성·사유 필수) → Step3·4` 로 흘린다.
동종 툴 대비 차별점 = **왜 이 peer 인가의 감사추적**.

### 2-2. 데이터 소스 — **정정(2026-08-04 실측)**

> ⚠️ 최초 계획은 "주요 제품을 사업보고서에서 추출"이었고, 비용을 상장사 2,600사 ×
> 2콜 = 5,000+ DART 콜 + 표 서식 제각각(실패율 높음)으로 추정했다. **틀렸다.**
> DART 에서 뽑을 생각만 했기 때문이다. FinanceDataReader 가 전량을 준다.

```
fdr.StockListing("KRX-DESC")  → 2,872행
  Code · Name · Market · Sector · Industry(세부업종) · Products(주요제품)
  · ListingDate · SettleMonth · Representative · HomePage · Region
fdr.StockListing("KRX")       → 2,872행
  Code · Name · Market · Marcap(시가총액) · Stocks(상장주식수) · Close
```
**총 2콜 · DART 쿼터 0 · 사업보고서 파싱 0.** `Products` 예시: `반도체 웨이퍼 캐리어`,
`렌탈(파렛트, OA장비, 건설장비)` — 동종 툴의 '제품' 필드와 동등하다.

| 항목 | 소스 | 상태 |
|---|---|---|
| 상장사 목록·시장·업종·**주요 제품** | `fdr.StockListing("KRX-DESC")` | **1콜** |
| 시가총액·상장주식수 | `fdr.StockListing("KRX")` | **1콜** |
| 고유번호(corp_code) 연결 | 기존 corp 인덱스 `stock_code` 조인 | 보유 |

**덤으로 얻는 것**(peer 퍼널에 직결):
- `ListingDate` → `peer_selection` **Step4 상장연수(베타 포인트)**
- `SettleMonth` → 결산월 정합(비교 대상이 12월 결산인지)
- `HomePage` → 자료 수집 동선

### 2-3. (삭제) 사업보고서 제품 추출
2-2 정정으로 **불필요**해졌다. 가장 비싸고 실패율이 높던 부분이 통째로 증발한다.
후일 비상장까지 모집단에 넣을 때만 다시 검토한다(비상장은 FDR 에 없다).

### 2-4. 인덱스 빌드·캐시
- **모듈**: `backend/ingest/screener.py` — 조회 함수는 **주입(DI)**, 코어는 stdlib·평문 dict
  (pandas 는 fetch 경계에서만. `calc_core` 무의존 철학과 동일).
- **캐시**: `var/screener_index.json` — 기존 `var/dart_corpcode.json`(corpCode 캐시)과 **같은 패턴**.
  최초 사용 시 lazy 빌드, 이후 재사용. **커밋하지 않는다**(시총이 시변이라 커밋하면 거짓이 된다).
- **vintage 필수**: `as_of` 기록 + staleness 경고. 시총은 날짜 없으면 비교가 거짓
  (`macro_client` 이중가드와 같은 사상). 기본 7일 초과 시 WARN, 갱신 버튼 노출.

### 2-5. API
```
POST /api/screener
  { q?, induty_code?, market?: ["KOSPI","KOSDAQ","KONEX"],
    mcap_min?, mcap_max?, include_unlisted?: false, sort?, limit?: 100 }
→ { rows: [{corp_code, corp_name, stock_code, market, induty_nm, sub_induty,
             products, marketcap}],
    total, truncated, as_of, notes[] }
```
- `q` 검색 범위 = **명칭 · 종목코드 · 세부업종 · 주요 제품**(동종 툴 규약 채택).
- `include_unlisted` 기본 false지만 **옵션으로 존재**해야 한다 — 우리 주 고객은 비상장 평가.
  (동종 툴은 상장사 한정 — 여기가 우리 차별점)

### 2-6. 화면
- `frontend/src/pages/appraiser/ScreenerSheet.jsx` (discount 단계, PeerSheet 앞)
- 컨트롤: 검색어 · 업종 드롭다운 · **시총 범위 슬라이더**(로그 눈금 `0/100억/500억/1천억/5천억/1조/∞`)
  · 시장 토글 · 정렬 4종 · 리셋
- 결과 행: `순번 | 회사(종목코드│시장) | 업종/세목/제품 3줄 | 시가총액` + `총 N건`
- **인계**: 선택 후보 → `project.data.peer_candidates` → `PeerSheet` 의 Step2 입력으로.

**Phase 2 게이트**: 스크리너 필터 결정론 테스트(픽스처 인덱스) · `as_of` staleness WARN 테스트 ·
제품 추출 실패가 예외가 아니라 빈 결과임을 고정.

---

## Phase 3 — 엔진 노출 (CB · 주식매수선택권) — **보류 중(2026-08-04)**

> MVP 범위를 **기업공시 · 스크리너**로 좁히기로 해 전환사채 화면은 `nav.js` 에서
> `soon: true`(준비중)로 두었다. **코드는 살아 있다** — 엔진·`/api/convertible`·
> `ConvertibleSheet.jsx` 모두 완성·테스트 통과 상태이고, `soon` 한 줄만 지우면 열린다.
> 부수 산출물인 **DCF 의 '희석 청구권 FV' 입력은 남긴다** — CB 와 무관하게 필요한 값인데
> 엔진 필드에 화면이 없어 항상 0 으로 나가고 있었다(그 탓에 `check_dilution_bridge` 가
> 발동할 수 없었다). 주식매수선택권 화면은 착수 전.

정직 표기 2축(available/ui)에서 **"엔진 有 · UI 無"** 로 남은 대표 사례.

| 화면 | 소비 엔진 | 이미 있는 것 |
|---|---|---|
| 전환사채 평가 | `convertible.price_convertible` · `with_without` | CRR 격자, TF 분리할인(콜캡→홀더 max, 풋-우선 캐스케이드 금지), 게이트 S1 3종 |
| 주식매수선택권 평가 | `backsolve.backsolve_equity` · `allocate_equity` · `price_rcps` | OPM 워터폴, 이항격자, 게이트 S2·S4 |

- API는 `/api/rcps` 가 이미 있음 → CB용 `/api/convertible` 신설 필요 여부 확인 후 결정.
- 화면은 **입력 → 게이트 findings → 결과** 3단(기존 `DcfSheet` 패턴 재사용).

---

## Phase 4 — 후순위

### 4-1. 사업자 등록정보(국세청 사업자상태) — N2
- `docs/plan.md` 에 이미 "신규 가치 있음(계속기업가정 체크)" 로 기재.
- `checks.going_concern` 4종과 직결. 폐업·휴업이면 계속기업가정 자체가 흔들린다.

### 4-2. 비동기 변환 잡 큐 — N3
- 트리거: **다건 배치**(peer 10사 × 3개년 원문 파싱). 단건은 현행 동기로 충분.
- ⚠️ 동종 툴의 "결과 24시간 보관"은 **채택하지 않는다** — BYOK·서버 미저장 원칙.
  큐는 진행 상태만 들고, 산출물은 즉시 스트리밍한다.

---

## 후퇴 방지 목록 (이식 중 훼손 금지)

1. 항등식 10종 SSOT — 화면 판정과 워크북 체크행이 같은 규칙에서 나온다
2. `note_map`(계정↔주석) — 재무 API로는 원리적으로 불가능
3. 재작성/부호규약/중복 의심 3분류
4. `company-check` 공시 주체 검증 — 동명 후보 함정
5. rFS/H_FS 살아있는 수식 + key-in 금지
6. BYOK·서버 미저장
7. **Task Pane(~350px) 대응** — 3단 레이아웃을 베끼지 않는 이유

---

## 순서·의존

```
Phase 1 (1-1 → 1-2 → 1-3 → 1-4 → 1-5 → 1-6)   백엔드 변경 2건뿐(corp-search 확장)
   └→ Phase 2 (2-3 제품추출 → 2-4 인덱스 → 2-5 API → 2-6 화면)
Phase 3 (독립)
Phase 4 (Phase 2 이후)
```
Phase 1은 서로 독립이라 부분 착수 가능. Phase 2는 2-3이 선행(제품 없으면 스크리너의
판별력이 동종 툴 이하로 떨어진다).
