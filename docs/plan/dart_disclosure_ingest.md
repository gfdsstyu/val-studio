# DART 공시자료 분석·가져오기 — 조사 및 설계 (2026-07-21)

> 출처: `D:\Valuation\dart` 자산 7종 전량 해부 + OpenDART 개발가이드 전수 확인 + xlwork 사이드카 역분석
> 대상: `D:\valuation-platform` (val.studio) 고도화

---

## 0. 결론 요약

| 항목 | 상태 |
|---|---|
| DART 백엔드 배관 | **이미 구축됨** — `ingest/dart_client.py`·`dart_corp.py`·`dart_employee.py`·`parsers/xbrl.py`, `/api/dart/*` 7종 |
| 프론트 노출 | **결손** — `MaterialsSheet`의 재무제표 패널 + `CostsSheet`의 직원현황뿐. `api.dartFilings`는 선언만 되고 호출처 0, `/api/dart/document`는 클라 래퍼 자체가 없음 |
| 계정 정규화 | **취약** — `fs_mapper.classify()`가 회사가 지어낸 **한글 계정명 문자열**에 의존. `account_id`(표준 택사노미 코드)는 `Locator`에 수집만 하고 **미사용** |
| 커버리지 | **좁음** — OpenDART 85종 중 3종만 사용(`fnlttSinglAcntAll`·`empSttus`·`list`). 감사의견·최대주주·주식총수·타법인출자·배당 전부 미연결 |

**핵심 개입점 3개**
1. `DART_Taxonomy_20260630_배포용.xlsx` → **`ingest/taxonomy_store.py` 신규**. `account_id` → 한/영 라벨·계산 weight·부호규약의 SSOT.
2. `fs_mapper`를 **2단 폴백**으로 개편 — 1단 `account_id` 정확일치(결정론, conf 0.95) → 2단 기존 한글 키워드(conf 0.85~0.9).
3. **DART 시트 신설** + 기존 미노출 백엔드(공시목록·원문 zip) 배선 + 신규 API 5종.

---

## 1. 자산 인벤토리 — `D:\Valuation\dart`

| 파일 | 정체 (실측) | 활용 |
|---|---|---|
| `1. DART_Taxonomy_20260630_배포용.xlsx` 13MB | **DART XBRL 택사노미 2026-01-31 전체 배포판.** 8시트 — Concepts 9,451 / RoleTypes 2,004 / Presentation 71,274 arc / Calculation 11,352 arc / Label(ko·en 41열) / Definition / Reference | ★★★★★ `taxonomy_store` 원천 |
| `주요 상장사 주석 작성 사례 예시_v8.9.ixd` 20MB | **ZIP.** 내부 `D*.frm` 176개 = DART 공시서류작성기 주석 서식 전체(XML, element↔한글라벨↔표 레이아웃) | ★★★☆☆ 주석 표 스키마 사전 |
| `XBRL2XLforDART_test.zip` 40MB | PyInstaller(py3.11) tkinter. 작성자 `kimdusik`/XBRL Korea, 2025-01-07. XBRL zip/ixd → Excel | ★★★★☆ 알고리즘 참조 |
| `XBRL_Downloader_v1.0.exe` 431KB | .NET/Costura. `https://filer.fss.or.kr/Resource/ifrsclient/install/` 에서 택사노미 zip 다운로드만 수행 | ★★☆☆☆ 택사노미 갱신 URL |
| `DartSetup.exe` 38MB | InstallShield+MSI+.NET = DART 공시서류작성기(제출용 편집기) | ☆ **설치 불요** — 제출 방향 도구, 소비 API 없음. 서식은 `.ixd`에서 전량 확보 |
| `xlwork-setup.exe` 22MB | Inno Setup → **MCP 사이드카 + FastAPI(:17845) + Excel COM**. 벤치마크 대상 | ★★★★☆ 기능 벤치마크 |
| `claude-excel-practical-cases.pdf` 4MB | (미해부) | — |

### 1-1. XBRL2XL에서 복원한 알고리즘

PyInstaller 아카이브 해부 → 메인 모듈 심볼 테이블로 파이프라인 복원:

```
zip/ixd → namelist()로 .xsd / *_pre / *_lab-ko / *_lab-en 식별
→ lxml: presentationLink / presentationArc / loc / label / labelArc
   ({%s}from · {%s}to · {%s}href 로 arc 결선)
→ role별 트리 (depth · order · preferredLabel 보존)
→ axis_1..axis_8 / member_1..member_8 로 차원 평탄화   ← 핵심
→ pandas → Concepts / Presentation 시트 to_excel
```

**axis/member 8단 평탄화**가 요체. `parsers/xbrl.py`의 `Context.dims`가 같은 문제를 풀고 있으므로,
차원 축을 컬럼으로 펴는 규약을 이 방식으로 통일할 것. (exe 자체는 GUI·단일스레드 → 서버 부적합, 참조만)

---

## 2. 택사노미 실측 — 무엇이 되고 무엇이 안 되는가

### 2-1. 되는 것: 라벨·부호·현금흐름 계층

주요재무제표 26개 role에서 **1,558 element** 추출, 조상경로 포함 압축 시 **369KB** (런타임 상주 가능).

```
문서 구성:  BS 527 · IS/CI 512 · CF 460 · SCE 55
루트 5개:   재무상태표[개요] · 당기손익[개요] · 포괄손익계산서[개요] ·
            현금흐름표[개요] · 자본변동표[개요]
```

손익계산서 트리 실제 복원 예:

```
당기손익 [개요]               ifrs-full_IncomeStatementAbstract
  수익                        ifrs-full_Revenue
    재화의 판매로 인한 수익     ifrs-full_RevenueFromSaleOfGoods
      제품매출액              dart_RevenueFromSaleOfGoodsProduct
      상품매출액              dart_RevenueFromSaleOfGoodsMerchandise
    용역의 제공으로 인한 수익   ifrs-full_RevenueFromRenderingOfServices
      게임매출액 / 임대수익 / 호텔매출액 / 물류매출액 ...
  매출원가                    ifrs-full_CostOfSales
```

**현금흐름표는 완전히 계층적** — 여기가 DCF 직결 노다지:

| 구간 | element 수 | 도출 가능 |
|---|---|---|
| 영업활동현금흐름 | 253 | 운전자본 증감·D&A 가산 |
| 투자활동현금흐름 | 149 | **CAPEX 후보 62** (`유형자산의 취득`·`토지/건물/구축물/기계장치/차량운반구/선박의 취득`…), **처분 65** |
| 재무활동현금흐름 | 44 | **차입 관련 27** (`단기/장기차입금의 증가·상환`, 사채, 리스부채) |

→ 현재 `assemble_dcf_inputs(new_capex_by_class=…)`로 **수기 입력받는 CAPEX를 공시 실측으로 대체 가능**.

### 2-2. 안 되는 것: BS/IS 계층 추론

depth 분포 `depth2=290 · depth3=709 · depth4=527 · depth≥5=11`.
**표준 택사노미의 BS/IS presentation은 의도적으로 얕다** — 실제 계층은 각 회사가 제출한 XBRL의 *자체* linkbase에 있다.
따라서 BS/IS는 계층 추론 불가, **`account_id` 정확일치 + 라벨 매칭**으로 가야 한다.

> ⚠️ 초기 시도에서 "계층만으로 버킷 도출 22.9%"가 나왔으나 이는 앵커 8개만 넣은 측정 오류.
> 올바른 결론은 위 2-1/2-2의 **구간별 상이**다.

### 2-3. 그래서 3층 하이브리드

| 층 | 대상 | 방법 | confidence |
|---|---|---|---|
| L1 | CF · SCE | 택사노미 조상경로 규칙 | 0.95 |
| L2 | BS · IS | `account_id` 정확일치 → 택사노미 한글라벨 | 0.9 |
| L3 | 회사 확장계정 (`-표준계정코드 미사용-`) | 기존 `fs_mapper` 한글 키워드 | 0.7~0.85 |
| L4 | 무매칭 | `uncertain=True` → 유저 분류 | 0.0 |

기존 `Classification(confidence, uncertain, rule)` 구조가 이미 이 4단을 표현할 수 있다. **`fs_mapper`는 대체가 아니라 하위 폴백으로 강등**된다.

### 2-4. 택사노미 SSOT 선택

OpenDART에 `xbrlTaxonomy.json`(sj_div별 `account_id`/`label_kor`/`label_eng`/`data_tp`/`ifrs_ref`) API가 있으나:

| | xlsx 배포판 | xbrlTaxonomy.json |
|---|---|---|
| 계산 weight(±) | ✅ 11,352 arc | ❌ |
| role 2,004개(주석 포함) | ✅ | ❌ (주요재무제표 sj_div만) |
| API 쿼터 소모 | ❌ 없음 | ✅ 소모 |
| 부호규약 `(X)` | 간접(balance) | ✅ `data_tp` |
| ifrs_ref 조문 | Reference 시트 | ✅ |

→ **xlsx를 SSOT로, `xbrlTaxonomy.json`은 연 1회 교차검증**. 갱신은 `filer.fss.or.kr/Resource/ifrsclient/install/`.

---

## 3. xlwork 벤치마크

Inno Setup → `app/xlwork-server.exe`(PyInstaller py3.11) + `.env` + `docs/사용법.html`.
스택: **MCP 1.28 + FastAPI 사이드카(:17845) + pywin32 COM(Excel 직접 제어) + openpyxl + bs4**.

### 3-1. 프로바이더 레지스트리 (`xlwork.providers.__init__`)

`ProviderSpec(kind, label, runner, required_keys, needs_selection, available)` — 미구현은 `available=False`로 등록해 `POST /jobs/{kind}` 시 **501 + 사유** 반환. (좋은 패턴: 기능 목록이 곧 능력 선언)

| kind | 라벨 | 필요 키 |
|---|---|---|
| `fx-series` | 환율 | KOREAEXIM |
| `biz-status` | 사업자 상태 | DATA_GO_KR |
| `stock-kr` / `stock-global` | 주가 | DATA_GO_KR / — |
| `beta` | 베타 | BETA_MCP_URL |
| `peer-population` · `valuation-data` · `peer-industry` | Peer 모집단·밸류에이션 데이터·업종검색 | — |
| **`dart-fin`** | **DART** | OPENDART_API_KEY |
| `unipass-cargo` / `unipass-export` | 수입통관/수출이행 | UNIPASS_*_API_KEY |
| `dsd-convert` / `dsd-verify` | DSD 변환 / 변환+검증 | — (`dsdfoot` 엔진 내장) |
| `realty` / `lawsuit` | 등기부 / 소송 | CODEF_* + IROS_* |
| `membership` | 회원권 시세 | — |
| `ai` | AI 검토 | — |

### 3-2. xlwork의 DART 기능 7종 (`xlwork.providers.dart`)

| # | 항목 | 엔드포인트 | 산출 |
|---|---|---|---|
| 1 | 재무제표 전체 | `fnlttSinglAcntAll.json` | 계정과목·당기·전기·전전기, OFS/CFS |
| 2 | 회사 개황 | `company.json` | 14필드(대표이사·설립일·**결산월**·법인등록번호·사업자번호·업종코드…) |
| 3 | 최근 1년 공시목록 | `list.json` | 접수일·보고서명·제출인·접수번호, 상위 300건 |
| 4 | **감사인** | `accnutAdtorNmNdAdtOpinion.json` | 3개년 감사인·**감사의견·강조사항·핵심감사사항(KAM)** |
| 5 | **최대주주 현황** | `hyslrSttus.json` | 성명·관계·주식종류·기초/기말 주식수·지분율 |
| 6 | **타법인 출자현황** | `otrCprInvstmntSttus.json` | 법인명·취득일·출자목적·기말 장부가액·당기순손익·총자산 |
| 7 | **배당에 관한 사항** | `alotMatter.json` | 당기/전기/전전기 |

캐싱: `corpCode.xml`(약 10만사) **일 1회**. 시트명 접두 `_DART_*`, 출처 문자열에 접수번호·파라미터 명시(우리 provenance와 동일 사상).

### 3-3. 우리 대비 격차

| 기능 | val.studio | xlwork | 조치 |
|---|---|---|---|
| 재무제표 전체 | ✅ `/api/dart/financials` | ✅ | — |
| corp 검색 | ✅ `/api/dart/corp-search` | ✅ | — |
| 공시목록 | 🔶 백엔드만 (`api.dartFilings` 호출처 0) | ✅ | **프론트 배선** |
| 공시원문 zip | 🔶 백엔드만 (클라 래퍼 없음) | ❌ | **프론트 배선 + ingest 파이프 연결** |
| 직원현황 | ✅ | ❌ | 우리 우위 |
| XBRL 파서·provenance·4종 검증 | ✅ | ❌ | 우리 우위 |
| 회사 개황 | ❌ | ✅ | **신규** |
| 감사인·감사의견·KAM | ❌ | ✅ | **신규 (감사인 트랙 직결)** |
| 최대주주 현황 | ❌ | ✅ | **신규 (D7 주식수 게이트)** |
| 타법인 출자현황 | ❌ | ✅ | **신규 (NOA 실측)** |
| 배당 | ❌ | ✅ | **신규** |
| 주식총수 | ❌ | ❌ | **신규 (D7 핵심)** |

---

## 4. OpenDART 사실관계 (검증 완료)

**한도·정책**
- 개인 **일 20,000건**(전 서비스 합산). 기업회원은 `list`/`company` 무제한 + IP 등록 필요.
- **분당 1,000회 초과 시 IP 1시간 차단.**
- **서버사이드 호출 시 `User-Agent` 필수** (없으면 404). TLS 1.2+.
- 상업적 이용 가능(공공데이터법). 금감원 정확성 무보증 → **최종사용자 고지 필요**.
- 상태코드: `013` 데이터없음 / `020` 한도초과 / `021` 조회회사수 초과(100) / `012` 미등록 IP.

**커버리지 한계 — 설계에 반드시 반영**
- 재무정보 API는 **2015년 사업보고서부터**. 그 이전은 `document.xml` 원문 파싱만이 유일 경로.
- **금융업 상장사는 2023년 3분기 이전 XBRL 없음.** K-GAAP 비상장은 아예 조회 불가.
- 분·반기 손익: `thstrm_amount`는 **3개월 값**, 누적은 `thstrm_add_amount` → **TTM 계산 시 혼동 금지**.
- `sj_div`가 `IS`+`CIS` 둘 다인 회사와 `CIS`만인 회사 공존 → **EBIT 추출은 IS 없으면 CIS 폴백**.
- `fs_div=OFS`가 비는 회사 존재 → **CFS↔OFS 양방향 폴백**.
- `currency`가 KRW가 아닌 회사 존재 → **통화 게이트 필수** (기존 단위규약 버그와 동일 계열 리스크).
- 금액은 콤마 포함 문자열 + `-` 단독/빈문자 혼재 → sanitize (기존 `emit_blank_aware`가 처리).
- `account_id`는 `ifrs-full_*` / `dart_*` 표준 요소명. 회사가 임의 계정 생성 시 **`-표준계정코드 미사용-`**.
  발생 빈도 공식 통계 없음 → **우리 유니버스로 직접 측정해 SSOT화**(피어 100사×3년 표본).

**주석(notes) 태깅 현황 (2026-07 기준)**
- 실제로 태깅된 주석이 존재하는 범위 = **비금융 자산 2천억↑ + 금융 자산 10조↑**.
  (2천억~5천억은 2026.03 제출분부터, 1천억~2천억 2027.03, 1천억 미만 2028.03)
- **OpenDART에 주석 조회 API는 없다.** 경로는 ① `fnlttXbrl.xml` 인스턴스를 XBRL 파싱, ② `document.xml` 텍스트 파싱, ③ 웹 스크레이핑.
  → **구조화 자동화는 ①이 유일**. `docs/plan.md:504`의 "주석 테이블 구조화 추출 = OSS 공백 = 우리 차별점" 판단은 여전히 유효.

**`document.xml` 함정**
- zip 안에 XML **여러 개**(본보고서 + 첨부). **인코딩 EUC-KR 우선, 실패 시 UTF-8.**
- 내용은 XBRL이 아니라 DSD 편집기 산출 SGML/XML — 표는 `<TABLE>` 마크업.

**라이브러리 판단**
- `OpenDartReader` 0.3.2 (2026-05, MIT) — **`requires_python >=3.13`**, 일부 기능이 DART 웹 스크레이핑 정규식 의존.
- `dart-fss` 0.4.17 (2026-07, MIT) — Arelle 의존, 강력하나 무겁고 크롤링 혼재.
- **결론: 라이브러리 통째 의존 금지.** 현행 stdlib `urllib`+`ElementTree` 얇은 자체 클라이언트 유지. XBRL 인스턴스 파싱이 필요해지면 그때만 Arelle 선택적 도입(Arelle은 "DART 규정 검증기"로는 부적합, "XBRL 리더"로는 적합).

---

## 5. 설계

### 5-1. 신규 — `backend/ingest/taxonomy_store.py`

```python
@dataclass(frozen=True)
class TaxonomyEntry:
    element_id: str          # 'ifrs-full_Revenue'
    label_ko: str
    label_en: str
    balance: str | None      # debit | credit
    period_type: str         # instant | duration
    statements: tuple[str, ...]   # ('IS','CIS')
    ancestors: tuple[str, ...]    # 조상 경로(루트→직상위)
    calc_weight: float | None     # ±1 (부모 대비)
    calc_parent: str | None

def load(path: Path = DATA / "dart_taxonomy_2026.json") -> TaxonomyStore
class TaxonomyStore:
    def get(self, element_id: str) -> TaxonomyEntry | None
    def label(self, element_id: str, lang="ko") -> str | None
    def under(self, element_id: str, ancestor: str) -> bool
    def bucket_hint(self, element_id: str) -> tuple[str | None, float, str]
```

빌드 스크립트 `scripts/build_taxonomy_store.py`: xlsx → 압축 JSON(≈370KB) → `backend/data/`.
xlsx 자체는 13MB라 레포에 넣지 않고 **산출 JSON만 커밋**(빌드는 재현 가능하게 스크립트 동봉).

### 5-2. 개편 — `fs_mapper.classify`

```python
def classify(account: str, statement: str, *, account_id: str | None = None) -> Classification
```
- `account_id`가 있고 `-표준계정코드 미사용-`이 아니면 → `TaxonomyStore.bucket_hint()` (L1/L2)
- 아니면 기존 키워드 규칙 (L3)
- `rule` 문자열에 `"taxonomy:ifrs-full_Revenue"` 형태로 근거 명시

**하위호환**: 기존 시그니처 유지(키워드 인자 추가만) → 기존 테스트 무영향.
`.claude/skills/*/vendor/ingest/` 벤더 사본 동기화 필요 여부 확인할 것.

### 5-3. 신규 API 5종 (`backend/api/main.py`)

기존 스타일 준수 — `Request` + `await request.json()`, `X-Dart-Key` 헤더 BYOK, Pydantic 미사용.

| 엔드포인트 | OpenDART | 용도 |
|---|---|---|
| `POST /api/dart/company` | `company.json` | 개황 + **`acc_mt` 결산월 → DCF 기간 정합 게이트** |
| `POST /api/dart/audit-opinion` | `accnutAdtorNmNdAdtOpinion.json` | 감사인·의견·**KAM** → 감사인 트랙 |
| `POST /api/dart/shares` | `stockTotqySttus.json` + `hyslrSttus.json` | **발행/유통 주식수 + 최대주주** → **D7 게이트 자동화** |
| `POST /api/dart/investments` | `otrCprInvstmntSttus.json` | 타법인 출자 → **NOA 실측** |
| `POST /api/dart/dividends` | `alotMatter.json` | 배당성향·배당수익률 |

### 5-4. 프론트

- `nav.js` — `materials` 다음에 **`disclosure` 시트 신설** ("0-2. 공시자료")
- `pages/appraiser/DisclosureSheet.jsx` 신규:
  - 회사 검색(기존 `dartCorpSearch` 재사용) → 개황 카드(결산월 강조)
  - **공시목록 브라우저** (`api.dartFilings`, `pblntf_detail_ty` 필터: A001 사업 / A002 반기 / A003 분기 / F001 감사보고서) → `rcept_no` 선택
  - 원문 zip 다운로드 (`/api/dart/document` — **`api.js`에 래퍼 신규 추가 필요**)
  - 탭: 재무제표 / 감사의견·KAM / 주식수·최대주주 / 타법인출자 / 배당
  - 각 값에 provenance 뱃지(`DART {rcept_no}/{account_id}`, `Locator.label()` 이미 존재)
- ⚠️ **`tests/test_frontend_wiring.py` 통과 필수** — 새로 저장하는 `dart_*` 키는 반드시 어딘가에서 **읽혀야** 한다 (`ALLOWED_UNREAD`가 빈 dict).

### 5-5. xlwork에서 가져올 패턴

1. **`ProviderSpec.available=False` + 사유 반환** — 미구현 기능을 침묵시키지 않고 501+이유로 표면화. `nav.js`의 `soon: true`와 같은 사상이나 서버까지 확장.
2. **`corpCode` 일 1회 캐시** — 현행 `_CORP_CACHE`는 one-shot. **TTL(24h) + 변경사항 익영업일 반영** 규칙 반영.
3. **출처 문자열에 파라미터 전문 기록** — `OpenDART fnlttSinglAcntAll (접수번호 …, corp_code …, 당기=…, 전기=…)`. 우리 `Provenance.note`에 동일 수준으로.

### 5-6. 안 가져올 것

- Excel COM(pywin32) 직접 제어 — 웹 플랫폼에 부적합. 기존 `excel/xlsx_writer.py` 유지.
- `DartSetup.exe` 설치 — 제출용 편집기, 소비 가치 없음.
- 라이브러리 통째 의존(OpenDartReader/dart-fss).

---

## 6. 작업 순서

| # | 작업 | 산출 | 선행 |
|---|---|---|---|
| 1 | `scripts/build_taxonomy_store.py` + `backend/data/dart_taxonomy_2026.json` | 370KB JSON | — |
| 2 | `ingest/taxonomy_store.py` + `tests/test_taxonomy_store.py` | | 1 |
| 3 | `fs_mapper` 2단 폴백 + 회귀 테스트(기존 분류 결과 불변 확인) | | 2 |
| 4 | `dart_client` 확장 5종 + `tests/test_dart_extra.py` (canned JSON, DI) | | — |
| 5 | `/api/dart/{company,audit-opinion,shares,investments,dividends}` | | 4 |
| 6 | `api.js` 래퍼 6종(+`dartDocument`) | | 5 |
| 7 | `DisclosureSheet.jsx` + `nav.js` 등록 | | 6 |
| 8 | **D7 게이트 자동화** — 발행/유통 주식수 공시 대조 → `dcf_inputs` 경고 | | 5 |
| 9 | CF 기반 CAPEX 자동제안 → `assemble_dcf_inputs(new_capex_by_class)` prefill | | 2 |
| 10 | `-표준계정코드 미사용-` 발생률 실측(피어 100사×3년) → 문서화 | 키 필요 | 4 |

**게이트**: 각 단계 `py -3.12 -m pytest` 그린 유지(현재 568). 커버리지 85% 하한.

---

## 7. 미검증 — 키 확보 후 실측할 것

1. `fnlttXbrl.xml` zip의 실제 `namelist()` — `.xbrl` 인스턴스 외 `.xsd`/링크베이스 동봉 여부(추론 상태).
2. `document.xml` zip 내부 파일명 규칙 및 DSD XML 태그 스키마(공개 DTD 스펙 없음).
3. `-표준계정코드 미사용-` 실제 발생률.
4. 기업회원 IP 등록 절차/등록 가능 IP 수.

---

## 8. 미연결 외부 API (별건, 후순위)

`data.go.kr` / `koreaexim` / `unipass` / 국세청 / 금융위 — **레포 전체 언급 0건**.
현행 외부 연결은 OpenDART · ECOS · Gemini · FinanceDataReader 4곳뿐.

- 수출입은행 환율 → **ECOS와 중복**
- 금융위 주식시세 → **FinanceDataReader와 중복**
- **국세청 사업자상태**(폐업·휴업 검증) → 신규 가치 있음 (계속기업가정 체크)
- **관세청 수출입실적** → 신규 가치 있음 (매출 추정 교차검증)
