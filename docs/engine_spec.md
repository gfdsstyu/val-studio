# calc_core 엔진 명세 — 임의 회사 DCF 재현 가이드

> 이 문서 하나로 **어떤 회사든** calc_core 로 DCF 평가를 재현할 수 있게 하는 것이 목표.
> 입력 규격·단위·컨벤션·데이터 출처·단계별 절차·검증 체크리스트를 정의한다.
> 검증 앵커: 비올(Viol) — `tests/golden/test_viol_spine.py` 가 주당가치 8,413.38원을 rel_tol 1e-9 로 재현.

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

```
calc_core/
  models.py   DcfSpineInput / DcfResult (도메인 dataclass)
  tax.py      한국 구간세율 (corporate_tax, effective_rate)
  dcf.py      스파인: EBIT→법인세→NOPLAT→FCFF→PV→EV→주당가치 + 민감도   ← 비올 골든 검증
  revenue.py  매출추정: top_down(산업CAGR) | bottom_up(계층트리 P×Q)
  wacc.py     CAPM 빌드업 (Hamada unlever/relever, Ke, Kd, WACC)
  fa.py       감가상각 스케줄 (기존자산 잔여상각 + 신규 CAPEX 빈티지)
  wc.py       운전자본 회전율 → ΔNWC
  ebit.py     매출+원가/판관비 드라이버 → EBIT 라인
  model.py    run_model: 가정 → 전체 DCF 오케스트레이터
```

두 가지 진입점:
- **스파인만**(`dcf.run`): 이미 투영된 라인아이템이 있을 때. 최소 입력.
- **전체 모델**(`model.run_model`): 가정(매출전략·마진·FA·WC·WACC)에서 전부 조립.

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

### 2-B. `WaccInputs` (wacc.build_wacc)
| 필드 | 설명 | 출처 (교육자료 근거) |
|---|---|---|
| `risk_free` | 무위험이자율(국고채) | Bloomberg / 금융투자협회 KOFIABOND / 한국은행 ECOS |
| `equity_risk_premium` | 시장위험프리미엄(MRP/ERP) | **한공회 「시장위험프리미엄 가이던스」 7~9%**; Damodaran 교차 |
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
   - top_down: 산업 리포트/Big4 의견서에서 TAM·CAGR·점유율.
   - bottom_up: 사업보고서 매출/제품 섹션 → 트리(LLM 제안+유저 승인). 합계검증.

STEP 4. 원가·판관비 가정
   - cogs_pct / sga_pct (매출연동) or 성격별(원재료/노무비/경비/외주비/감가상각) 빌드.

STEP 5. FA·WC 가정
   - fa: 기존자산 잔여상각 + 신규 CAPEX 계획(내용연수 정액).
   - wc: 회전율(매출채권/재고/매입채무 = driver/잔액, 회전기간 고정) → ΔNWC.

STEP 6. WACC 빌드업
   - 유사기업 FS(DART) 적재 → 각 peer βL·D/E·세율 → unlever → 평균 βu.
   - Rf·ERP(한공회)·size·CRP → Ke; 신용등급 회사채 수익률 → Kd; 자본구조 → WACC.
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
- [ ] **WACC 상식범위**: 8~14% (한공회 ERP 7~9% 기준). 민감도 중심셀=base 주당가치.
- [ ] **회귀**: `python tests/golden/test_viol_spine.py` + `tests/test_upstream.py` + `tests/test_xlsx_export.py` 전부 PASS.
- [ ] **export 추적성**: 결과 셀이 수식(<f>)으로 기록, 캐시값=calc_core.

---

## 7. 스코프·한계 (정직한 명세)

- **스파인·법인세**: 비올 원본과 셀단위 정확 일치(검증됨).
- **상류(revenue/fa/wc/wacc)**: 표준 방법론 일반 구현(단위테스트). 비올의 bespoke 세그먼트 977수식을 비트복제하지 않음 — 회사별 실제 구조로 파라미터화하는 게 설계 의도.
- **감가상각**: 정액법 기준(체감법 등 이후 확장). 월할 무시(연 단위).
- **xlsx export**: stdlib 최소 라이터(수식+캐시값). 정식 recalc 검증(pycel/xlcalculator)·서식·양방향 import 는 Phase 4.
- **미구현**: DART 인제스트·주석 추출·4종 검증·RAG/챗·감사인 트랙 (계획 `docs/plan.md` 참조).
```
