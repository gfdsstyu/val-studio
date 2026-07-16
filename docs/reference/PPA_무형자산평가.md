---
topic: PPA(매수가격배분) 무형자산 평가 — MEEM·RFRM·TAB
keywords: [PPA, 매수가격배분, 사업결합, 무형자산, MEEM, 다기간초과이익법, RFRM, 로열티면제법, contributory asset charge, 기여자산비용, CAC, TAB, 세금절감효과, 고객관계, 상표권, WARA]
canonical_questions:
  - "PPA(매수가격배분)에서 무형자산은 어떻게 평가하나?"
  - "MEEM(다기간초과이익법)의 절차와 기여자산비용은?"
  - "RFRM(로열티면제법)은 언제 어떻게 쓰나?"
  - "TAB(세금상각편익)는 무엇이고 왜 더하나?"
layer: methodology
parent: 밸류에이션_스코프_로드맵
doc_type: knowledge
---

# PPA 무형자산 평가 (MEEM·RFRM) — ⏳ 미래 트랙

> PPA(Purchase Price Allocation, 매수가격배분): 사업결합 취득원가를 식별가능 자산·부채에 공정가치로
> 배분. 무형자산(고객관계·상표·기술)을 **소득접근법**으로 평가. [[밸류에이션_스코프_로드맵]] FV/PPA 트랙.
> WARA↔IRR↔WACC 정합([[deloitte_감사인검토_WACC방법론]])이 여기 핵심.

## 1. MEEM (다기간초과이익법, Multi-period Excess Earnings Method)
무형자산 현금흐름에서 **다른 자산이 기여한 부분을 차감**한 초과이익. PPA **고객관계 평가 최표준**.

### 절차
1. **기존 고객 수익 추정** — 과거 이탈률 분석, 통계기법(Iowa Curve·보험통계 퇴직율법).
2. **EBITDA 추정** — 기존 고객 **유지 비용만**, 신규 고객 획득비용 제외.
3. **기여자산비용(CAC, Contributory Asset Charge) 차감** — 무형자산이 빌려쓴 다른 자산의 요구수익:
   - 순운전자본: 매출액 대비 비율 × 단기차입금 이자율
   - 유·무형자산: Gross Lease Method 또는 Return on Asset Method
   - 집합적 노동력(assembled workforce): 신규 채용·교육비
4. **세후 현금흐름** 계산.
5. **현재가치 할인** — 할인율 = **WACC + 1~5% 프리미엄**(무형자산 위험).
6. **TAB 가산** (아래).

## 2. RFRM (로열티면제법, Relief From Royalty Method)
자산을 **보유함으로써 절약한 로열티**의 현재가치. **상표권·기술** 등에 적합.

### 절차
- 매출 추정 × **시장 로열티율**(동종 라이선스 계약 비교, 자발적 licensor↔licensee 요율).
- **retention factor**(무형자산 가치 침식) 반영(내용연수 비한정이면 예외).
- **TAB 가산**.

### 적용 조건
분리가능 + 라이선스 가능 + 시장 로열티율 존재.

## 3. TAB (Tax Amortization Benefit, 세금상각편익)
무형자산 상각으로 인한 **절세효과(세금 방어)**의 현재가치. MEEM·RFRM 결과에 **가산**.
- TAB factor = f(상각 내용연수, 세율, 할인율). 취득자가 무형자산을 상각해 얻는 세금 이득을 자산가치에 포함.

## 4. 방법 선택
| 무형자산 | 주 방법 |
|---|---|
| 고객관계 | **MEEM** |
| 상표권·브랜드·기술(라이선스가능) | **RFRM** |
| 집합적 노동력 | Replacement Cost(CAC로만 반영, 별도 인식 안 함) |

## 5. 우리 플랫폼 (⏳ 미래)
- FV/PPA 모드: 소득접근 무형자산 평가(MEEM/RFRM) + CAC + TAB. market-participant 관점([[손상검사_impairment]] VIU와 대비).
- WARA↔IRR↔WACC reconciliation 검증(전체 무형자산 가중수익률 = IRR = WACC ±1%).
