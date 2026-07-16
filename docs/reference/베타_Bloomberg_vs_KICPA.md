---
topic: 베타(β) 산출: Bloomberg(S&P500) vs KICPA(KOSPI) + CAPM 한계
keywords: [베타, Bloomberg, KICPA, KOSPI, S&P500, Adjusted Beta, Raw Beta, CSRP, 체계적위험, MRP, 기준시장]
canonical_questions:
  - "Bloomberg 베타와 KICPA 베타의 차이는?"
  - "Adjusted Beta 공식(0.67·raw+0.33)은?"
  - "어느 베타를 써야 하나?"
  - "CAPM이 못 잡는 위험(비체계적)은?"
layer: foundation
parent: 밸류에이션_스코프_로드맵
doc_type: knowledge
---
# 베타(β) 산출: Bloomberg β vs KICPA β

출처: 회계업계 실무 이슈 노트(2023~24 KICPA 베타·MRP 조회서비스 도입). `deloitte_감사인검토_WACC방법론.md` Beta 절 심화.
**β는 숫자가 아니라 "어느 시장의 체계적위험인가"의 선택** — 우리 `wacc` 엔진의 필수 provenance.

---

## 0. 배경 (관행의 변화)
- 종래: **Bloomberg β 단독** 사용이 관행.
- 변화: **한국공인회계사회(KICPA)**가 **베타계수 조회서비스 + 시장위험프리미엄(MRP)** 정보 제공 → 현재 KICPA 이용 비중이 더 큼.
- **결론(원칙)**: "한국거래 = KICPA" 같은 단순결론 아님. **평가대상 회사에 더 적합한 β·MRP**를 선택.

## 1. 핵심 차이 — 기준시장(market proxy)
| | Bloomberg β | KICPA β |
|---|---|---|
| 시장대용치 | **S&P500 (Global market)** *(한국기업엔 KOSPI/KOSDAQ 적용 알려짐)* | **KOSPI (Korean market)** |
| 데이터 | 역사적 주가 + 회귀분석 | 한국시장 특정 데이터 |
| 빈도 | 주로 **2년·주단위**(20~25년 장기도) | **Daily/Weekly/Monthly 선택** |
| 조정 | **Raw + Adjusted 둘 다** | **Raw만** (현재 시장상황 중점) |
| 비용 | 유료(단말) | 무료(KICPA 회원) |

### 시장 선택 판단 (어느 시장 영향이 큰가)
- **글로벌 동조 산업 → Bloomberg**: 반도체·2차전지·AI·Bio 등 미래산업. 한국투자자도 매일 글로벌시장 주시 → 글로벌 변동성이 더 유의미.
- **내수 중심 산업 → KICPA**: 전통 제조·부동산·건설 등 한국 경제상황 민감.

## 2. Bloomberg β 계산방법
데이터: (1) 주가(historical) (2) 시장지수(S&P500 등) (3) 빈도(2주 간격 2년 기본, 장기 20~25년도).
```
단계: 데이터수집(배당·분할 조정) → 주간 수익률 계산(Pt/Pt-1 − 1)
    → 회귀분석: 시장수익률(x, 독립) vs 주식수익률(y, 종속), 기울기 = Raw Beta
```
Excel 3방법:
- `=SLOPE(stock_returns, market_returns)`
- `=COVARIANCE.P(stock, market) / VAR.P(market)`
- 회귀분석 Tool(Data Analysis) → X변수 계수 = Raw Beta

### Adjusted Beta (Bloomberg 고유, 미래 추정베타)
```
Adjusted β = 0.67 × Raw β + 0.33 × 1.0
```
- 근거: 개별 베타는 **종국적으로 시장평균(1.0)에 근접**(mean reversion, Marshall Blume).
- 장기·안정적 측정치 제공. → deloitte 문서 β절과 동일 원리.

## 3. CAPM의 한계 — 체계적위험만 (⚠️ 고성장 과대평가)
- β·MRP CAPM = **체계적위험(systematic)** 만 = 시장 대비 개별주 민감도. **비체계적(기업특유) 위험 미포함**.
- 이론: 비체계적위험은 분산투자로 소멸 → 투자자는 체계적위험만 보상 요구.
- **실무 함정**: 고성장 사업일수록 할인율이 **과소 적용** → 기업가치 **과대평가**.
- **CSRP (Company Specific Risk Premium)**: 모든 기업 고유위험 보유 → 중요.
  - 계량화 어려움 → **일반론: 현금흐름(CF)에 반영**.
  - 그러나 Bio·Game·AI·2차전지 등 고위험 신생산업: 과거실적 성장률 기반 CF에 기업특유위험이 다 포함됐다 단정 어려움.
  - 할인율에 특정위험 가산 = 논란 많고 국제적으로 널리 인정된 방식 아님.

## 4. `wacc` 엔진 반영
| 개념 | 구현 |
|---|---|
| β source 선택 | `WaccInputs.beta_source` ∈ {bloomberg, kicpa} + `beta_market` ∈ {SP500, KOSPI} — **필수 provenance** |
| Raw vs Adjusted | `beta_adjusted` 플래그 (Adjusted = 0.67·raw+0.33) |
| 빈도 | `beta_frequency` (daily/weekly/monthly) + `beta_period_years` |
| CSRP | `company_specific_risk_premium`(할인율) **또는** CF 반영 — 방식 명시 |
| 감사인 체크 | 시장선택 근거(산업 글로벌/내수), 고성장 과대평가 경고, CSRP 반영위치(CF vs 할인율) |

> 감사인 트랙 산출물: "β=1.2"가 아니라 **"KOSPI 기준 2년 주간 raw β 1.2 (KICPA), 내수 제조업이라 한국시장 채택"** — 시장선택 근거까지 추적.
