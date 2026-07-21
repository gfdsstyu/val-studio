---
topic: 감사인 관점 WACC 방법론·검토 체크리스트 (Modified CAPM·Kroll size premium)
keywords: [감사인검토, Modified CAPM, Kroll, Duff Phelps, size premium, CSRP, WARA, IRR, kd, BBB-, 감사인 검토, ERP, beta]
canonical_questions:
  - "감사인은 WACC를 어떻게 검토하나?"
  - "size premium(규모프리미엄)은 어떻게 정하나?"
  - "WARA·IRR·WACC 정합은 무엇인가?"
  - "cost of debt(kd)는 어떻게 산정하나?"
layer: methodology
parent: 밸류에이션_스코프_로드맵
doc_type: knowledge
---
# 감사인검토 외부평가보고서 검토 유의사항 + WACC 방법론 (감사인 트랙 정본)

출처: `외부평가검토 자료-외부평가보고서 검토 및 관련 유의사항_교육.pdf` (감사인검토 기준). 회계법인 자료 단편 병합.
**감사인 트랙의 방법론·체크리스트 정본**. 우리 `wacc.py` + `auditor/` 근거.

---

## 1. WACC 구조 (Modified CAPM)
```
WACC = D/(D+E)·(1−t)·kd + E/(D+E)·ke
ke   = rf + β·(rm − rf) + Size Premium + CRP + CSRP      (Modified CAPM)
kd   = pre-tax cost of debt
```

### Risk-Free Rate (rf)
- Bloomberg risk-free rate 사용(장기 국고채). 평가기준일 근접일자.

### Equity Risk Premium (rm − rf, ERP)
- 관행: 역사적 초과수익률 평균(stocks − 국채).
- **Historical ERP** = 과거 차이가 안정적이라 가정 / **Forecast ERP** = 현재 시장정보로 전망.
- 감사인검토: **forward-looking ERP** + **감사인검토 FAS ERP(월별 산정)** 사용 권장. Damodaran EMRP 교차.
- **COVID-19 시 ERP Normalization**("정상" ERP 사용) 유의.
- (한국 실무: 한공회 시장위험프리미엄 가이던스 7~9% — 리포트 예시 8%.)

### Beta (β) — 체계적위험
- 시장수익률 대비 회귀기울기. β=1 시장동행, >1 변동확대, <0 역행(드묾).
- **비상장회사**: 베타 부재 → guideline public companies(유사 상장사) 군의 베타 → 중심경향(median/mean/시총가중).
- **측정 주기**: daily/weekly/monthly 가능하나 **monthly 60개월 선호**(BV 모델 기본). 짧은 구간은 산업이벤트 식별 시.
- **Marshall Blume 조정**(Mean Reversion): β가 시간이 지나며 시장베타(1)로 회귀 → 조정. (Bloomberg adjusted β = ⅔·raw + ⅓·1.)
- 소스: Kisline(Local β), Barra, Capital IQ.

### Size Premium (CSRP) — Kroll(구 Duff & Phelps) Deciles
2019 CSRP Deciles Size Premium (Valuation Handbook, CAPM 기반):
| Decile | 시총 범위(백만$) | Size Premium |
|---|---|--:|
| 1 (Largest) | 13,513~29,023 | 0.52% |
| 2 | 7,276~13,456 | 0.81% |
| 3 | 4,504~7,254 | 0.85% |
| 4 (Mid 3-5) | 2,996~4,504 | 1.28% |
| 5 | 1,962~2,992 | 1.50% |
| 6 (Low 6-8) | 1,293~1,960 | 1.58% |
| 7 | ~1,292 | 1.80% |
| 8 | 730~ | 2.46% |
| 9 (Micro 9-10) | 325~ | 5.22% |
| 10 (Smallest) | 2.46~727 | (최대) |
- Mid-Cap 3-5 / Low-Cap 6-8 / Micro-Cap 9-10 그룹. Modified CAPM에 가산.
> 소형사(비올)일수록 높은 size premium → 높은 ke·WACC. 클래시스(대형) 6.24% vs 비올 11.3% 격차의 정량 근거.

### Cost of Debt (kd)
- **최저 투자등급 = BBB-**. VKG: "Moody's Baa 등급 회사채 수익률"을 일반 사용, 신용도가 투자등급과 크게 다르면 조정.
- 신용등급×만기 회사채 수익률 매트릭스(KOFIABOND 등). 신용등급 = Bloomberg/Capital IQ, KIS/NICE/한기평.
- **소수지분(minority)** = 회사 현행 kd. **지배지분(controlling)** = 대상회사 신용도(선택 자본구조 기준) + guideline 신용등급 참고.

### 자본구조 (Capital Structure)
- **Minority**: 산업표준으로 조정 불필요(소수주주는 자본구조 변경 불가).
- **Controlling**: 산업표준(최적) 자본구조로 조정 가능(경쟁적 매수 시 최적구조 가치 반영).
- 목표 자본구조 = 유사회사 평균(리포트 예시 관행).

---

## 2. 감사인 검토 체크리스트 (핵심)

### WARA ↔ IRR ↔ WACC Reconciliation (PPA calibration)
- **WARA**(Weighted Average Return on Assets, 무형자산 등 자산별 요구수익률 가중) ↔ **IRR**(거래 내재수익률) ↔ **WACC** 3자 정합.
- 원칙: **WARA ≈ IRR ≈ WACC (약 ±1% 이내)**. 괴리 크면 가정·PPA 재검토.
- IRR>WACC: 저가매수/시너지 / IRR<WACC: 고가매수/리스크. calibration 필요.

### 유의사항 (Apple-to-Apple)
- 분자(현금흐름)와 분모(할인율)의 **일관성**: 명목 vs 실질, 세전 vs 세후, FCFF vs FCFE, 통화 일치.
- 비영업자산/부채는 FCF에서 제외 → 별도 가산/차감(이중계상 방지).

### 회계법인 자료 단편 (CGU·IFRS 16)
- **CGU**(현금창출단위) 단위 손상평가, IFRS 16 리스 반영이 CGU CF·WACC에 미치는 영향.
- Apple-to-Apple: 리스부채 반영 시 CF와 WACC(자본구조) 정합. R&Q(질의응답) 관점.
- (원본 PDF 한글이 CID폰트라 텍스트 추출 제한 — OCR 시 보강.)

---

## 3. `calc_core`·감사인 트랙 매핑

| 감사인검토 방법 | 우리 구현 |
|---|---|
| Modified CAPM ke | `wacc.build_wacc`(size_premium·CRP·company_specific 인자) |
| guideline β unlever/relever | `wacc.peer_unlevered_beta` + relever |
| Size premium deciles | `WaccInputs.size_premium`(Kroll decile 매핑 테이블 확장) |
| kd BBB-/Baa | `WaccInputs.pre_tax_cost_of_debt`(신용등급 매트릭스) |
| minority vs controlling | 자본구조·kd 분기(설정) |
| WARA↔IRR↔WACC | `auditor/tests.py` reconciliation 테스트 |
| Apple-to-Apple 정합 | `validators` 정합성(분자·분모 일관성) |

## 4. 감사인 검토 체크리스트 (실행)
- [ ] 할인율·현금흐름 정합(명목/실질, 세전/후, 통화).
- [ ] β: guideline 적정, 60개월 월간, Blume 조정 여부.
- [ ] ERP: forward-looking/한공회, 비정상기(COVID) normalization.
- [ ] Size premium: 적정 decile.
- [ ] kd: 신용등급 근거, minority/controlling 구분.
- [ ] 자본구조: 목표(유사회사 평균) 근거.
- [ ] WARA↔IRR↔WACC ±1% 정합.
- [ ] 비영업자산·이자부부채 이중계상/누락 없음.
