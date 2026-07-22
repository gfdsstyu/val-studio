# calc_core 엔진 명세 — 임의 회사 DCF 재현 가이드

> 이 문서 하나로 **어떤 회사든** calc_core 로 DCF 평가를 재현할 수 있게 하는 것이 목표.
> 입력 규격·단위·컨벤션·데이터 출처·단계별 절차·검증 체크리스트를 정의한다.
> 검증 앵커: 비올(Viol) — `tests/golden/test_viol_spine.py` 가 주당가치 8,413.38원을 rel_tol 1e-9 로 재현.
>
> **현행화 2026-07-19** — 이 문서는 스킬 W6 단계에 지식 주입되는 정본이다(`excel-valuation-workbook`
> references/index.md 바인딩). 구현이 Milestone 1 을 크게 앞질러 확장되어 §1 모듈맵·§2 입력규격·
> §7 스코프를 전면 갱신했다. 검증 앵커는 2사례로 늘었다(비올 8,413.38 / 클래시스 40,600).

---

## 0. 공통 컨벤션 (반드시 준수)

| 항목 | 규칙 |
|---|---|
| **통화 단위** | 모든 금액 = **백만원(KRW mn)**. 주식수만 주(shares). 주당가치 산출 시 `×1e6`로 원 환산. |
| **추정기간** | 명시적 N년(기본 5년) + Terminal. 리스트 길이 = N 로 통일. |
| **할인 컨벤션** | **중간연도(mid-year)**: period = 0.5, 1.5, …, N−0.5. `PVfactor = 1/(1+WACC)^period`. |
| **Terminal 할인** | TV = `FCFF_T/(WACC−g)` 를 **마지막 명시연도 factor(N−0.5)** 로 할인(원본 모델 컨벤션). |
| **Terminal FCFF** | `EBIT_last×(1+g)` 로 성장 → **세금 재계산**(구간세율 비선형이라 NOPLAT 스케일 금지) → NOPLAT_T = FCFF_T (영구구간 D&A=CAPEX, ΔNWC=0). |
| **법인세** | 한국 구간세율(백만원): ≤200 9% / ~20000 19% / ~300000 21% / >300000 24%, ×1.1(지방소득세). `tax.corporate_tax`. |
| **부호** | capex = 양수 크기. `delta_nwc_cash_adj` = FCFF 현금조정 부호(운전자본 증가 시 −). |

---

## 1. 엔진 구조 (모듈 → 책임)

### 1-A. DCF 코어 (스파인 + 상류)

```
calc_core/
  models.py   DcfSpineInput / DcfResult (도메인 dataclass)
  tax.py      한국 구간세율 (corporate_tax, effective_rate)
  dcf.py      스파인: EBIT→법인세→NOPLAT→FCFF→PV→EV→주당가치 + 민감도   ← 비올 골든 검증
  revenue.py  매출추정: top_down(산업CAGR) | bottom_up(계층트리 P×Q) | razor-and-blades
  wacc.py     CAPM 빌드업 (Hamada unlever/relever, Ke, Kd, WACC, Kroll size decile)
  fa.py       감가상각 스케줄 (기존자산 잔여상각 + 신규/유지보수 CAPEX 빈티지)
  wc.py       운전자본 회전율 → ΔNWC + 정규화 WC비율
  ebit.py     매출+원가/판관비 드라이버 → EBIT 라인
  cost_build.py  성격별 원가·판관비 다중 드라이버(growth/ratio/headcount/cpi/fa_dep/fixed)
  model.py    run_model: 가정 → 전체 DCF 오케스트레이터
  checks.py   ★ 가정 타당성 게이트 (§6-B 규칙표 — 지식→로직 승격)
  scenario.py 시나리오(up/base/down) + 가중종합(합=1 강제)
```

### 1-B. 부가 트랙 (DCF 와 별개 수학)

```
calc_core/
  relative.py        상대가치 LTM·계절성(분기×4 연환산 왜곡 방어)
  multiples.py       peer 배수(PER/PBR/EV·EBITDA) → median → 내재가치, 5-10 Rule
  sotp.py            Sum-of-the-Parts 다개체·다통화(fx_to_base × ownership)
  merger.py          합병·주식교환: 자본시장법 기준주가(VWAP)·본질가치(자산1:수익1.5)
  convertible.py     CB/RCPS: CRR 이항트리 + TF 분리할인, 보장수익률 accrual
  lease.py           K-IFRS 1116 리스: 이자·원금 분리 + ROU 감가상각
  method_selector.py 평가방법 셀렉터: 목적×거래유형×상장여부 → 법제 기반 추천
```

### 1-C. 주변 레이어

```
ingest/    DART(재무·직원현황·corpCode·XBRL)·주석추출·PDF/OCR·검증 4종·provenance
           price_client(β회귀·시총)·macro_client(ECOS)·damodaran(CRP)·manual_paste
           peer_selection(4-step 퍼널)·ksic·fs_mapper
assemble/  커넥터 원천값 → 검증된 엔진입력(wacc_inputs·dcf_inputs, 게이트 fold)
excel/     살아있는 수식 xlsx: export/import/왕복 diff 4버킷·민감도 5×5·시나리오 시트
           vs_state(스킬 `_VS_STATE`·`Claude Log` 증적 파서)
rag/       밸류에이션 북 검색(BookSearcher: lexical + 온톨로지 그래프 1-hop, 임베딩 선택)
api/       FastAPI 로컬 단일프로세스 어댑터(BYOK — 키는 헤더 통과, 서버 미저장)
```

세 가지 진입점:
- **스파인만**(`dcf.run`): 이미 투영된 라인아이템이 있을 때. 최소 입력.
- **전체 모델**(`model.run_model`): 가정(매출전략·마진·FA·WC·WACC)에서 전부 조립.
- **어셈블리**(`assemble.assemble_dcf_inputs`): 커넥터 원천값(복붙·API)부터 게이트를 걸며 조립.
  실행 순서 게이트 — PGR≥WACC 면 `dcf_run` 전에 차단.

---

## 2. 입력 규격

### 2-A. `DcfSpineInput` (dcf.run) — 최소 스파인
| 필드 | 타입 | 설명 | 출처 |
|---|---|---|---|
| `wacc` | float | 가중평균자본비용 | `wacc.build_wacc` 결과 or 직접 |
| `terminal_growth` | float | 영구성장률 g | 가정(보통 1~2%, 물가·장기성장) |
| `revenue` | list[N] | 연도별 매출 | `revenue.top_down/bottom_up` |
| `cogs` | list[N] | 매출원가 | 매출×COGS% or 성격별 합 |
| `sga` | list[N] | 판매관리비 | 매출×SGA% or 성격별 합 |
| `dep_amort` | list[N] | 감가상각(양수) | `fa.project_fixed_assets` |
| `capex` | list[N] | CAPEX(양수 크기) | 투자계획 |
| `delta_nwc_cash_adj` | list[N] | ΔNWC 현금조정(증가 시 −) | `wc.project_working_capital` |
| `non_operating_assets` | float | 비영업자산(현금·투자자산 등) | FS + NOA/IBD 분류 |
| `net_debt` | float | 순차입부채 | FS + IBD 분류 |
| `shares_outstanding` | int | 발행주식수 | DART |
| `mid_year_periods` | list[N]? | 기본 0.5,1.5,… | 컨벤션 |
| `terminal_discount_period` | float? | 기본 N−0.5 | 컨벤션 |
| `non_controlling_interest` | float | 비지배지분(K-IFRS) 차감액, 기본 0 | FS 자본 |

**개선 A — 세금 주입** (클래시스 2차 골든에서 실증). 구간세율 대신 분석가 명시세금을 쓸 때:

| 필드 | 타입 | 설명 |
|---|---|---|
| `tax_override` | list[N]? | 연도별 세금(백만원, 양수 크기). 지정 시 구간세율 미사용 |
| `effective_tax_rate` | float? | EBIT 대비 유효세율(터미널 세금 재계산에 사용) |

**개선 B — 터미널 정규화** (WACC≈g 폭발·TV 과대계상 방어). 우선순위는 위→아래:

| 필드 | 타입 | 설명 |
|---|---|---|
| `terminal_fcff_override` | float? | 영구구간 FCFF_{n+1} 직접 주입(가장 투명) |
| `terminal_reinvestment_rate` | float? | NOPLAT_T×(1−rate), rate=g/ROIC (CAPEX+WC 번들) |
| `terminal_wc_ratio` | float? | 터미널 ΔWC = 추정말매출×g×비율 — **정본 공식**(참고 모델 §279-285). 미지정 시 ΔWC=0 이라 g>0 에서 과대계상 |

> 셋 다 미지정이면 터미널은 관례대로 D&A=CAPEX·ΔNWC=0(=골든 재현 경로).

### 2-B. `WaccInputs` (wacc.build_wacc)
| 필드 | 설명 | 출처 (교육자료 근거) |
|---|---|---|
| `risk_free` | 무위험이자율(국고채) | Bloomberg / 금융투자협회 KOFIABOND / 한국은행 ECOS |
| `market_risk_premium` | 시장위험프리미엄(MRP/MRP) | **한공회 「시장위험프리미엄 가이던스」 7~9%**; Damodaran 교차 |
| `unlevered_beta` | 유사기업 무부채 베타 | `wacc.peer_unlevered_beta` (peer FS 필요) |
| `target_debt_to_equity` | 대상회사 목표 D/E | peer 자본구조 or 대상 실제 |
| `tax_rate` | 유효세율 | FS or 법정세율 |
| `pre_tax_cost_of_debt` | 세전 타인자본비용 | 신용등급×만기 회사채 수익률(KOFIABOND); 신용등급=KIS/NICE/한기평, NICE-bizline |
| `size_premium` | 규모프리미엄 | Kroll(구 Duff&Phelps) deciles |
| `country_risk_premium` | 국가위험 | Damodaran |
| `company_specific_risk` | 기업특유위험 | 평가자 판단 |

### 2-C. `ModelConfig` (model.run_model) — 전체 조립
`DcfSpineInput` 필드 대부분 + 매출전략 결과(`revenue`) + `cogs_pct`/`sga_pct` + FA(`asset_classes`, `new_capex_by_class`) + WC(`wc_items`, `wc_driver_by_item`, `base_net_working_capital`) + `wacc_inputs`. (시그니처는 `model.py` 참조.)

---

## 3. 매출추정 전략 선택

| 전략 | 언제 | 입력 | API |
|---|---|---|---|
| **top_down** (쉬움·기본) | 산업 CAGR·점유율만 알 때 | market_size(TAM), share, cagr, years | `revenue.top_down(...)` |
| **bottom_up** | 제품/지역 세분 데이터 있을 때 | 계층 트리(지역>제품군>제품>상품; 리프=P×Q or base×growth) | `revenue.bottom_up(root, years)` |

**트리 규칙**: 축 순서 자유(지역우선/제품우선). 장비/소모품(razor-and-blades)도 표현. 상위노드=하위합계(`revenue.validate_tree_sums` 로 합계검증). LLM 이 사업보고서에서 제안 → 유저 +/− 편집·승인.

---

## 4. 임의 회사 평가 — 단계별 절차

```
STEP 0. 대상·기준일·추정기간(N) 확정. 통화=백만원.

STEP 1. 과거 재무제표(H_FS) 확보
   - DART 정형 계정 API(fnlttSinglAcntAll) → BS/IS/CF.
   - NOA/IBD 분류: 영업/비영업자산, 이자부부채 구분 → non_operating_assets, net_debt.

STEP 2. 주석에서 구조 데이터 확보 (정형 API에 없음)
   - 유형·무형자산 내용연수·증감표 → fa.AssetClass(remaining_life, useful_life)
   - 판관비 성격별 분류 → sga 성격별 빌드(선택)
   - 출처: OpenDART 주석 일괄다운로드 TSV + Arelle, or HTML 스크레이핑. 4종 검증 통과.

STEP 3. 매출추정
   - top_down: 산업 리포트/외부평가의견서에서 TAM·CAGR·점유율.
   - bottom_up: 사업보고서 매출/제품 섹션 → 트리(LLM 제안+유저 승인). 합계검증.

STEP 4. 원가·판관비 가정
   - cogs_pct / sga_pct (매출연동) or 성격별(원재료/노무비/경비/외주비/감가상각) 빌드.

STEP 5. FA·WC 가정
   - fa: 기존자산 잔여상각 + 신규 CAPEX 계획(내용연수 정액).
   - wc: 회전율(매출채권/재고/매입채무 = driver/잔액, 회전기간 고정) → ΔNWC.

STEP 6. WACC 빌드업
   - 유사기업 FS(DART) 적재 → 각 peer βL·D/E·세율 → unlever → 평균 βu.
   - Rf·MRP(한공회)·size·CRP → Ke; 신용등급 회사채 수익률 → Kd; 자본구조 → WACC.
   - peer 주가·시총: FinanceDataReader/pykrx.

STEP 7. 실행 & 산출
   - model.run_model(cfg) → DcfResult. or dcf.run(spine).
   - excel.export_dcf(inp, res, path) → 살아있는 수식 xlsx(감사 추적).

STEP 8. 검증 (§6 체크리스트).
```

---

## 5. 최소 재현 예시 (코드)

```python
import sys; sys.path.insert(0, "backend")
from calc_core import DcfSpineInput, run
from excel import export_dcf

inp = DcfSpineInput(
    wacc=0.113, terminal_growth=0.02,
    revenue=[56775.51, 70529.12, 85160.87, 97498.31, 109259.60],
    cogs=[16379.20, 17251.14, 20307.37, 22879.42, 25518.79],
    sga=[13699.82, 15779.52, 19897.31, 22313.97, 24964.06],
    dep_amort=[1500.09, 1308.42, 934.36, 599.43, 645.01],
    capex=[957.98, 1108.02, 1228.93, 1140.36, 1273.23],
    delta_nwc_cash_adj=[0.0, 43.41, -843.16, 264.05, -163.70],
    non_operating_assets=49462.98, net_debt=654.71,
    shares_outstanding=57656967,
)
res = run(inp)
print(res.per_share)          # → 8413.38 (비올 원본 일치)
export_dcf(inp, res, "out/dcf.xlsx")
```

`model.run_model` 전체 조립 예시는 `tests/test_upstream.py::test_run_model_end_to_end` 참조.

---

## 6. 검증 체크리스트 (재현 신뢰)

- [ ] **단위 일관성**: 전 금액 백만원, 주식수만 주. 주당가치 `×1e6` 확인.
- [ ] **리스트 길이**: revenue/cogs/sga/dep_amort/capex/delta_nwc = 모두 N.
- [ ] **부호**: capex 양수, ΔNWC 현금조정(증가 시 −).
- [ ] **합계검증**: 매출 트리 상위=하위합(`validate_tree_sums`). 판관비 성격별 합=IS 판관비.
- [ ] **정합성(tie-out)**: 주석 감가상각 = CF D&A; 주석 유형자산 기말 = BS; peer 무부채화 세율 일관.
- [ ] **WACC 상식범위**: 8~14% (한공회 MRP 7~9% 기준). 민감도 중심셀=base 주당가치.
- [ ] **회귀**: `py -3.12 -m pytest -q` 전량 PASS (스파인 골든·상류·API·스킬 포함).
- [ ] **export 추적성**: 결과 셀이 수식(<f>)으로 기록, 캐시값=calc_core.
- [ ] **스킬 vendor 동기**: backend 수정 시 `python scripts/build_excel_skill.py` 재실행
      (`tests/skill/test_vendor_sync.py` 가 SHA256 drift 를 잡는다).

### 6-B. 가정 타당성 게이트 (`checks.audit_dcf` — 지식→로직 승격)

| 규칙 | 판정 | 근거 문서 |
|---|---|---|
| PGR ≥ WACC (Gordon 발산) | **FAIL** | 영구성장률_PGR_적합성 |
| WACC−PGR < 1%p 스프레드 / PGR > 장기GDP(2%) | WARN | ″ |
| **F1** PGR>2% 인데 재투자 미반영(D&A=CAPEX, ΔWC=0) → TV 과대 | WARN | 참고 모델 정본 |
| TV 비중 > 75% 과다편중 | WARN | 앤트로픽 audit-xls 벤치마크 |
| **F3** β source·market 부재 / β시장 ≠ MRP시장 이중기준 | WARN | 베타_Bloomberg_vs_KICPA |
| **F2** Kroll size decile — 시총 룩업(자유입력 대신 provenance 강제) | 제안 | 감사인검토_WACC |
| 매출 YoY 급변 > 50% (key-in 오류) | WARN | 모델링_워크플로우_기초 |
| WARA ↔ IRR ↔ WACC ±1%p reconciliation | WARN | 감사인검토_WACC |
| peer 최대분기비중 ≥ 40% 연환산 금지 | WARN | 상대가치_계절성_LTM |
| 운전자본 현금유출 매년 악화 > 5% (흑자도산) | WARN | 참고 모델 정본 §2.4 |
| `diagnose_dcf_gap` — 주장값 vs 독립재계산 → 구조버그 5가설 지목 | WARN | 앤트로픽 벤치마크 §2 |

> **FAIL = 결과 무효, WARN = 통과시키되 감사인에게 노출.** 데이터 정합(주석↔FS tie-out·
> 합계·숫자형·공백)은 별도 관심사로 `ingest/validators.py` 4종이 담당한다.

---

## 7. 스코프·한계 (정직한 명세)

### 7-A. 검증된 것
- **스파인·법인세**: 비올 원본과 셀단위 정확 일치(rel_tol 1e-9, 주당 8,413.38원).
- **개선 A·B**: 클래시스 2차 골든에서 실증(`tax_override`·`terminal_fcff_override` → 40,600원 일치).
- **상류(revenue/fa/wc/wacc/cost_build)**: 표준 방법론 일반 구현(단위테스트). 비올의 bespoke
  세그먼트 977수식을 비트복제하지 않음 — 회사별 실제 구조로 파라미터화하는 게 설계 의도.
- **xlsx**: 수식 live export + 양방향 import + 왕복 diff 4버킷 + 민감도 5×5·시나리오 살아있는
  수식. recalc 게이트(`scripts/recalc_gate.py`)가 LibreOffice headless 로 수식 자체를 검증
  (캐시 제거 후 재계산 — 캐시 echo false-pass 차단). `soffice` 미설치면 skip.
- **인제스트·검증·RAG·감사인 트랙**: 전부 구현(§1-C). ※ 이전 판 "미구현" 기재는 오류였음.

### 7-B. 한계 (여전히)
- **감가상각**: 정액법 기준(체감법 미구현). 월할 무시(연 단위).
- **xlsx 서식**: 셀 색상·서식 미구현(값·수식만). 색상 3색 규약은 스킬 지시문 층에서 처리.
- **import 스코프**: 표준 Val-Studio DCF 스파인 레이아웃만 역파싱(비표준 템플릿 422).
  스킬이 만든 W-단계 시트(`Fcst_*`·`Peer` 등)가 자란 워크북의 왕복은 스파인 한정.

### 7-C. 미구현 (정직하게 표면화 중)
`method_selector` 가 `available=False` 로 표기하거나 ⏳ 트랙으로 남긴 것들 — "구현된 척"
하는 부분은 없다.
- **상증세법상 비상장주식 평가**(순손익·순자산가액 — IS/BS 로직 신규 필요)
- **손상 VIU 전용 트랙**(`dcf.py` TV=0 우회는 가능) · **PPA 무형자산**(MEEM/RFRM)
- **NAV 순자산법** · **리픽싱 조건부 CB**(몬테카를로 필요)

---

## 8. 변경 이력

| 날짜 | 변경 |
|---|---|
| Milestone 1 | 초판 — 비올 스파인 재현 명세(모듈 9개) |
| 2026-07-19 | **현행화** — §1 모듈맵 20개+주변 레이어, §2 개선 A·B 필드, §6-B 게이트 규칙표, §7 스코프 전면 갱신(구식 "미구현" 목록 정정), §8 신설 |
