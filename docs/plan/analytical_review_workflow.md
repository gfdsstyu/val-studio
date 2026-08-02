# 분석적 절차 계층 (Analytical Review Layer) — 탑다운 모델 리뷰 워크플로우

**작성 2026-07-31** | 근거: `D:\Valuation\DCF_비올\portfolio_final\리뷰노트_모델검토.md` (비올 DCF 결함 8건 전수 검토 조서)
**상태: P1~P4 구현 완료(2026-07-31), 747 그린 + vite 빌드 클린** — 전 단계 종료
- P4: ReviewPanel(4.밸류에이션 › 분석적 리뷰 — DART 다개년 자동 수급→층위별 판정·수제 SVG 스파크라인(접합부 점선)·마진 브리지 표·영향 원장 JSON 실행기) + AuditSheet(5.산출물 › 모델 정적 감사 — 업로드→패턴 린트·하드코딩·중심셀) + impact_ledger 엔진·`/api/review/ledger` + BadZipFile→422 전역 핸들러. review_findings→ContextPanel·Dashboard 합류(배선 테스트 4/4).
- ✅ 이월분 완료(가정 조립 사이클): AssembleSheet(4.밸류에이션 › 가정 조립) — 2.가정·3.할인율 저장 산출물→ops 계약 매핑(`cogs_pct`=costs_built÷revenue_built 파생 / 자산·WC 정의는 입력 키 fa_input·wc_input에서 재구성 / WACC 서브바디는 wacc_input 폼 스냅샷 재조립+CRP 재조회 / 연도 수 프리플라이트) + `/api/dcf/assemble` 응답 spine 동봉 → "DCF 입력으로 반영"으로 왕복 루프 폐합. 747 그린+빌드 클린
- P1: calc_core/analytical.py(체크 6종+브리지 2종) + tests/test_analytical.py(비올 골든 22건) + audit_dcf `history=` 배선
- P2: `/api/review/analytical` + assemble/history_inputs.py(DART financials/employee→FinancialHistory, fs_mapper 분류 재사용) + tests/test_api_review.py 10건
- P3: excel/model_audit.py(R1C1 패턴 린트 행/열·하드코딩 스캔·중심셀 검산) + `/api/xlsx/audit`(표준 레이아웃이면 import→재계산→Sens!F7 대조) + tests/test_model_audit.py 12건. ⚠️ §4.1 초안 정정: **균일 밀림(E-3형)은 패턴 린트 사각지대**(이웃도 같이 틀림) — L3 성장-운전자본 정합이 담당, 테스트로 계층 분담 문서화
- 지식 승격: docs/reference/모델감사_분석적절차.md (원 조서 비공개 유지, 패턴·임계값만 증류)
선행: checks.py 33종·CHECK행·excel 트랙(dcf_import/workbook_diff/sensitivity_grid) 가동 중

---

## 0. 한 줄 요약

플랫폼의 검증은 현재 **항등식 축**(tie-out: ingest/validators + 가정 게이트: checks.py)만 있다.
비올 리뷰에서 결함 8건 중 5건을 실제로 잡아낸 도구는 **연속성 축**(비율 시계열을 늘어놓고 튀는
지점을 분해 역추적)이었고, 이 축이 플랫폼에 없다. 감사론 용어로 전자는 세부테스트, 후자는
**분석적 절차(ISA 520)** — 두 축은 상호 대체 불가다(항등식은 잘못된 비율로도 성립한다.
리뷰노트 원문: *"자기정합성 검산만으로는 E-6가 잡히지 않는다 — 원가율 자체가 잘못된 것이므로
항등식은 성립"*).

```
[기존] 모델 내부가 스스로와 정합한가?   → ingest/validators(tie-out) + checks.py(가정 게이트)
[신규] 시계열이 스스로의 과거와 정합한가? → calc_core/analytical.py (이 문서)
```

## 1. 검증 인프라 3층 구조 (관심사 분리)

checks.py 도입부의 기존 선언("tie-out과 판단 게이트의 분리")을 3층으로 확장한다.

| 층 | 모듈 | 질문 | 예 |
|---|---|---|---|
| L1 tie-out | ingest/validators | 데이터가 원본과 일치하나 | 라운드트립 정합 |
| L2 가정 게이트 | calc_core/checks.py | 가정이 경제적으로 말이 되나 | PGR≥WACC, TV 비중 |
| **L3 분석적 절차** | **calc_core/analytical.py (신규)** | **시계열·파생지표가 과거·구성요소와 정합하나** | 접합부 연속성, 마진 브리지 |

Finding/Severity/ValidationReport 인프라는 그대로 재사용. checks.py가 1,700줄이라 신규 모듈로
분리하되, `audit_dcf`가 옵션 인자로 L3를 호출해 단일 리포트로 합류시킨다.

## 2. 데이터 모델 — 실적 시계열의 부재가 유일한 구조 변경

`DcfSpineInput`은 추정 전용(명시연도)이라 실적이 없다. 접합부 검사는 실적↔추정 경계를 보는
검사이므로 실적 컨테이너가 필요하다.

```python
# calc_core/analytical.py
@dataclass(frozen=True)
class FinancialHistory:
    """실적 연도별 시계열(오래된→최신). 전부 optional — 있는 것만 검사한다.

    출처: /api/dart/financials(재무)·/api/dart/employee(인원·급여) 커넥터가 이미 수급.
    세그먼트는 사업보고서 부문정보(수동 복붙 or LLM 추출) — provenance 필수.
    """
    years: list[int]
    revenue: list[float] | None = None
    cogs: list[float] | None = None
    sga: list[float] | None = None
    headcount: list[float] | None = None
    labor_cost: list[float] | None = None      # 원가 노무비 + 판관 인건비 합
    nwc: list[float] | None = None
    segments: list[SegmentSeries] | None = None # 믹스 분해용

@dataclass(frozen=True)
class SegmentSeries:
    name: str                    # '제품' | '상품' | ...
    revenue: list[float]
    cogs: list[float]
    provenance: str | None = None
```

**설계 원칙**: 실적은 게이트가 아니라 **prior** — 없으면 해당 검사는 PASS(정보)로 강등하고
절대 차단하지 않는다(check_metric_vs_industry의 "벤치마크 없음 — 대조 생략" 패턴과 동일).

## 3. 신규 체크 스펙 (P1 — 순수 엔진, 외부 의존 0)

### 3.1 `check_ratio_seam` — 실적↔추정 접합부 비율 연속성 ⭐

비올에서 E-6·J-1·E-10 세 건의 **진입점**이 된 검사. 기존 `check_projection_smoothness`와
축이 다르다: smoothness는 **레벨**의 상대 YoY·**추정 구간만** / seam은 **비율**의 %p 이탈·
**실적↔추정 경계**.

```python
def check_ratio_seam(actuals, forecast, *, name, tol_pp=0.03, report=None) -> Finding
```

| 비율 | 산출 | tol 기본 | 근거 |
|---|---|---|---|
| 원가율·GPM·판관비율·OPM | cogs/rev 등 | ±3%p | 리뷰노트 E-6 검증법 "직전 실적 대비 ±3%p" 명시 |
| 회전기일(DSO·DIO·DPO) | 표준식 | 상대 ±20% | %p 개념 없음. J-3(재고 130~225일 변동) 참고, WARN only |

**[구현 확정 변경]** NWC/매출 seam(위 표 초안)은 별도 검사
`check_nwc_growth_consistency`로 분리 구현했다 — `delta_nwc_cash_adj`가 현금조정
부호 규약(원본 row24 = −ΔWC)이라 NWC 레벨 재구성에 부호 해석 리스크가 있어,
|ΔNWC| 기반(부호 무관)으로 "매출 YoY > 10% 인데 |ΔNWC| < Δ매출×2%" 를 직접
감지한다(E-1·E-3 현상). check_working_capital_burn(유출 과다)의 반대 방향 짝 검사.

판정: `|forecast[0] − actuals[-1]| > tol` → WARN. detail에 양쪽 값·Δ·전체 시계열 동봉
(프론트 스파크라인 소재). 실적 3개년 미만이면 PASS(정보).

**비올 실측**: 원가율 22.2%(2023) → 28.8%(2024E) = +6.6%p → WARN 발화 ✓

### 3.2 `check_spike_revert` — V자(스파이크-복귀) 시그니처 ⭐

한 해만 이탈 후 트렌드 복귀 = **참조 밀림의 시그니처**. 사업 이벤트는 지속되고(레벨 시프트),
참조 오류는 한 해만 튄다 — 리뷰노트가 E-6를 "의도된 가정이 아니라 참조 실수"로 판정한 논리를
그대로 코드화한 것. "오류 vs 가정" 구분 휴리스틱이라 메시지도 다르게 낸다.

```python
def check_spike_revert(series, *, name, spike_pp=0.02, neighbor_pp=0.01, report=None) -> Finding
# 내부점 i에 대해: |x[i] − (x[i-1]+x[i+1])/2| > spike_pp AND |x[i+1] − x[i-1]| < neighbor_pp
```

- 실적+추정 결합 시계열에 적용(접합부 스파이크·추정 중간 스파이크 모두 커버).
- WARN 메시지: *"t=N만 이탈 후 복귀 — 참조 밀림(복사 시 시작참조 미고정) 시그니처.
  사업 이벤트라면 근거 기재"* — 리뷰노트 §9 ①계열 병리 문구 승계.
- **비올 실측**: 재료비율 [12.90(실적)] → 15.32 → 11.77 → 11.77: 이탈 +3.55%p, 이웃차 0 → 발화 ✓.
  J-2의 연구개발비율 7.11 → 13.10 점프(복귀 없음)는 이 검사가 아닌 3.1 계열로 잡힘 — 두 검사의
  역할 분담이 맞다(J-2는 "가정일 수도 있는" 항목).

### 3.3 `margin_bridge` — 마진 브리지 분해 (검사 + 리포트 소재 이중 목적) ⭐

리뷰어의 첫 질문 *"마진이 왜 들쭉날쭉한가"*에 자동으로 답하는 모듈. 비올 §3.5가 실적 변동을
"전부 정상"으로, 추정 1차연도만 "결함"으로 가른 근거 절차다. PASS/WARN보다 **설명 가능한 표**가
주 산출물이므로 report/ 계층에서도 소비한다.

```python
def opm_bridge(gpm, sga_ratio) -> list[dict]
# ΔOPM_t = ΔGPM_t − Δ판관비율_t  — 연도별 기여 분해 (§3.5(b) 표 재현)

def mix_decomposition(segments: list[SegmentSeries]) -> dict
# Δ전체원가율 = Σ Δw_s·c̄_s (믹스 효과) + Σ w̄_s·Δc_s (세그먼트 원가율 효과)
# 가중치는 양연도 평균(midpoint) — 잔차 0으로 완전 분해

def check_mix_reconciliation(segments, total_cogs_ratio, *, tol=0.005, report=None) -> Finding
# Σ(비중×세그먼트 원가율) ≟ 전체 원가율  — 가중평균 재현 검산 (§3.5(a))
```

**비올 실측**: `0.870×26.9% + 0.130×75.8% = 33.3% ≈ 33.1%` ✓ 재현 / 상품 원가율
68.4%→41.1% 접합부는 3.1이 세그먼트 단위로도 돌면 잡힘(E-10) → segments가 있으면
**세그먼트별 원가율에도 check_ratio_seam 자동 적용**.

### 3.4 `check_derived_continuity` — 단위경제 파생지표 연속성

*"각 셀은 맞는데 결합했을 때만 틀리는 유형은 파생지표 검산으로만 잡힌다"* (J-1 교훈).
분자·분모가 각각 자연스러워도 나눗셈이 튀면 경고.

```python
def check_derived_continuity(numerator, denominator, *, name, tol=0.10, report=None) -> Finding
# 파생 = num/den, YoY ±10% 초과 → WARN  (리뷰노트 검증장치 문구 그대로)
```

1차 적용: 인당 인건비(labor_cost/headcount — DART employee 커넥터가 데이터 보유),
인당 매출액. 범용 시그니처라 향후 대당 소모품매출(razor-and-blades)·평당 매출 등 확장.
**비올 실측**: 46.0 → 64.5 (+40%) → WARN ✓ (J-1 적발)

### 3.5 `check_consensus_anchor` — 컨센서스 크로스체크

`check_metric_vs_industry`(산업 분포 prior)와 별개인 **회사별 앵커**. 비올 건의 뼈아픈 지점:
같은 파일 research 탭에 컨센서스 GPM 78%가 있었는데 자기 추정 71.2%와 대조가 안 됐다.

```python
def check_consensus_anchor(metric, own, consensus, *, source, tol_pp=0.05, report=None) -> Finding
```

- 입력은 manual_paste 커넥터 패턴 재사용(복붙 + range sanity + provenance 강제, confidence 0.9).
- source 없는 컨센서스는 받지 않는다(가정 provenance 원칙과 동일).
- **비올 실측**: |71.2 − 78| = 6.8%p > 5%p → WARN ✓

## 4. Excel 감사 트랙 (P3 — excel/model_audit.py 신규)

플랫폼 네이티브 엔진은 참조 밀림·민감도 축 오류가 **구조적으로 불가능**하다(수식 복사가 없고,
민감도는 dcf.run이 셀마다 재계산). 따라서 이 트랙의 대상은 **외부 xlsx**(유저 업로드·연수
산출물·인수 실사 대상 모델)다. xlsx_reader가 이미 `cell.formula`를 노출하므로 재계산 없이
정적 분석 가능.

### 4.1 수식 패턴 동질성 린트 — ①계열(참조 밀림 6건) 전부의 예방책

리뷰노트 §7.1 "이웃 패턴을 깨는 수식" 항목의 자동화. **레이아웃 지식이 필요 없는** 범용
검사라는 점이 핵심 — 비올처럼 표준 템플릿이 아닌 모델에도 작동한다.

```
알고리즘:
1. 각 수식을 R1C1 정규화 (A1 참조 → 호스트 셀 기준 상대 오프셋)
2. 행 단위로 연속 수식 구간의 정규화 패턴 최빈값(mode) 산출
3. 최빈 패턴과 다른 셀 → WARN [셀주소, 자기 패턴, 이웃 패턴, 원문 수식]
```

**비올 소급 적발**: `M162=J162`(이웃 `$G$162`) ✓ E-6 / `M199=M130`(실적열 `K127` 패턴과
행 오프셋 상이) ✓ E-10① / `SUM(M199:M202)`(이웃 `K198=H_FS참조` — 구조 자체가 다름) ✓ E-10② /
`Q184`(무형자산 항 누락 — 같은 행 M~P와 항 개수 다름) ✓ E-8 보조 / E-3·E-5(열 밀림 — 상대
오프셋이 이웃과 상이) ✓. **①계열 + ③계열 전량 커버.**

### 4.2 하드코딩 스캔 (R4)

수식 내 숫자 리터럴(`=M165*32`) + 수식 영역 안의 상수 셀 검출. 비올의 조용한 버그 1위
(`32` 하나가 인건비 +2,435백만원의 진원지). 화이트리스트: 0·1·12·365·단위환산(10^6).

### 4.3 민감도 중심셀 검산 — "한 줄로 4개 결함 유형" (E-9)

```
import_dcf_model(xlsx) → dcf.run 재계산 → 워크북에 기록된 민감도 중심셀 값과 대조
|중심셀 − 재계산 주당가치| > tol → WARN
```
축 이동(E-9)·stale 테이블(2차 리포트 파손 유형)·연결 끊김을 재계산 대조 하나로 동시
적발 — COM 불필요, Cloud Run에서 작동. 리뷰노트 §7.5 "비용 대비 효과 최대" 검사의 이식.

### 4.4 오류 영향 분리 원장 (fix ledger)

*"순 효과 −3.0%가 개별 −111/+26의 상쇄를 가린다 — 분리 측정하지 않으면 보이지 않는다"*
(§6.5(a)). 파이썬 엔진에서는 자명하게 구현된다:

```python
def impact_ledger(base: DcfSpineInput, patches: list[Patch]) -> list[LedgerRow]
# 패치를 한 건씩 누적 적용 → dcf.run → 주당가치 Δ 기록 (비올 §6.5(a) 표 포맷)
```
scenario.py의 시나리오 실행 패턴 재사용. Excel 원본 수정은 COM 필수라 플랫폼 밖(로컬 스킬,
§7)에 남긴다.

## 5. 판정 프레임 — [방법론/실행/판단] 3분류를 리포트 상단에

리뷰노트 §9의 결정적 판정: *"방법론 선택은 전부 표준, 결함은 전부 실행"* — 이 구분이 처방을
가른다(방법론 오류=학습, 실행 오류=검산 장치). 리뷰 리포트 표준 헤더로 승격:

| 층위 | 판정 소스 |
|---|---|
| 방법론 선택 | method_selector 타이폴로지 매핑 (매출 P×Q/top-down, 마진 M1/M2, WC W1…) — 기존 |
| 구조 설계 | 잔차 배분 여부·SSOT 경로 단일성 — cost_build 기존 + 패턴 린트 |
| 실행 | L3 분석적 절차 + 패턴 린트 findings |
| 검산 장치 | CHECK행 유무 — *"검산 행이 있던 H_FS에서는 결함 0건"* 상관 그대로 |

구현: Finding.detail에 `{"layer": "execution"}` 태그(공유 인프라 Finding 클래스는 불변),
report/ 계층에서 4층 집계.

## 6. 배선 (API·audit_dcf·프론트)

```
P1  audit_dcf(inp, res, *, history: FinancialHistory | None = None, ...)
    — history 주어지면 L3 자동 합류. 기존 호출부 무변경(하위호환).

P2  POST /api/review/analytical
    { history, forecast(DcfSpineInput | 시계열), segments?, consensus? }
    → { findings, opm_bridge 표, mix_decomposition 표 }
    데이터 자동 수급: /api/dart/financials(실적) + /api/dart/employee(인원·급여) → history 어댑터

P3  POST /api/xlsx/audit   (또는 /api/xlsx/import 응답 확장)
    → 패턴 린트 + 하드코딩 스캔 + 중심셀 검산 findings

P4  val-studio ReviewPanel: 비율 시계열 스파크라인(접합부 하이라이트) + 브리지 표 + 4층 판정표
    — PastePanel/DcfSheet 배선(기존 백로그)과 같은 사이클에 묶기
```

## 7. 로컬 리뷰 스킬 (플랫폼 밖 — 선택)

실제 비올 리뷰의 실행 환경은 Excel COM(배열수식·데이터테이블 보존)이었고 Cloud Run에서는
불가능. 리뷰노트 §6 작업 규율(COM 필수 / 수정 순서 = 상류부터 / 단계마다 주당가치 기록 /
상쇄 유의)을 `.claude/skills/model-review` 런북으로 포장하면, 임의 xlsx에 대한 "수정까지
하는" 풀 리뷰는 로컬 스킬이, "진단까지"는 플랫폼이 담당하는 이원 구조가 된다.

## 8. 골든 테스트 — 비올 픽스처로 "있었다면 잡혔다"를 증명

리뷰노트 §2·§3.5·§6.5의 실측 수치를 그대로 픽스처화. **결함 8건 중 6건 소급 적발**이 통과
기준(E-4·E-5 상각 스케줄 세부는 L3 범위 밖 — tie-out 계층 기존 커버).

| 픽스처 | 기대 발화 | 소급 대상 |
|---|---|---|
| 원가율 [25.6,29.4,33.1,26.7,22.2] → [28.8,24.5,23.8,23.5,23.4] | seam WARN +6.6%p | E-6·J-1 진입점 |
| 재료비율 [.., 10.60, 12.90] → [15.32, 11.77, 11.77, ..] | spike_revert WARN | E-6 |
| 상품 원가율 68.4% → 41.1% | 세그먼트 seam WARN | E-10 |
| 믹스 0.870×26.9+0.130×75.8 vs 33.1 | mix_reconciliation PASS | §3.5(a) 재현 |
| OPM 브리지 §3.5(b) 4개년 기여값 | 표 일치 assert | 분해 정확성 |
| 인당 인건비 46.0 → 64.5 | derived_continuity WARN +40% | J-1 |
| GPM 71.2 vs 컨센서스 78 (source 有) | consensus WARN 6.8%p | §2-3 |
| ΔNWC/매출 ≈ 0, 매출 +33.5% | seam(nwc_to_revenue) WARN | E-1·E-3 현상 |
| 패턴 린트: M162=J162 vs 이웃 $G$162 (합성 워크북) | pattern WARN | E-6 수식층 |
| 중심셀 8,634.7 vs 재계산 8,413.4 | center WARN | E-9 |

## 9. 공개원칙 처리 (귀납지식 승격)

- 리뷰노트 자체는 비공개 원자료(D:\Valuation). 패턴만 증류해
  `docs/reference/모델감사_분석적절차.md` 신설 — 회사명·금액 제거, ①참조밀림 ②경로중복
  ③연산자 3계열 병리 + V자 시그니처 + 접합부 ±3%p + 인당 ±10% 임계와 그 실측 근거를
  귀납지식으로 기재. checks 규칙 승격(F1~F3 전례)과 동일 절차.
- 임계값 provenance: 코드 상수에 근거 주석(기존 TV_WEIGHT_WARN 스타일).

## 10. 페이징·미결정

| 단계 | 내용 | 규모 |
|---|---|---|
| P1 | analytical.py 5종 + 골든 테스트 + audit_dcf 배선 | 반나절~1일 |
| P2 | /api/review/analytical + DART→history 어댑터 + 컨센서스 페이스트 | 1일 |
| P3 | excel/model_audit.py (R1C1 린트·하드코딩·중심셀) | 1~2일 (R1C1 정규화가 유일 난제) |
| P4 | 리포트 4층 판정표 + 원장 + ReviewPanel | UI 사이클에 합류 |

**미결정 (착수 전 확인)**
1. SegmentSeries 수급: 사업보고서 부문정보 자동 추출(LLM) vs 수동 복붙 — P1은 수동으로 시작 권장.
2. 회전기일 tol ±20%의 근거 보강 — 산업 벤치마크 분포(benchmarks) 연동 여부.
3. P3 패턴 린트의 스코프: 전 시트 전수 vs 수식 밀도 높은 영역 자동 탐지(성능).
