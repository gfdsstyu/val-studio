---
topic: WACC 할인율 서식의 셀 수식 논리 (Hamada·규모별세율·베타옵션)
keywords: [WACC, 할인율, Hamada, unlever, relever, 베타, 규모별 유효세율, 빌드업, 자본구조, D/E]
canonical_questions:
  - "WACC는 어떻게 계산하나?"
  - "Hamada 언레버/리레버 공식은?"
  - "베타를 자본구조로 조정하는 법은?"
  - "규모별 유효세율은 어떻게 적용하나?"
doc_type: knowledge
---
# 할인율(WACC) 서식·강의자료 — 시트 논리 정본 명세

출처: `DCF_비올\강의자료\할인율 서식.xlsx`(빈 템플릿) · `할인율 강의자료_JYP.xlsx`(JYP엔터 예시).
**시트 셀 수식을 최대한 그대로 반영**. 우리 `calc_core/wacc.py`의 검증 근거.

시트 구성: `유사기업선정 >> (Step0 평가대상 리서치 · Step1 모집단 · Step2 사업유사성 · Step3 매출비중) → 할인율 >> WACC`.

---

## 1. 유사기업 선정 (Step0~3) — peer 선정 절차

| Step | 시트 | 내용 |
|---|---|---|
| Step0 | 평가대상회사 리서치 | 대상 사업·재무 파악 |
| Step1 | 모집단 선정 | KRX 상장 동일/유사 산업코드 |
| Step2 | 사업유사성 검토 | 홈페이지·DART 사업보고서로 주요사업 유사성 |
| Step3 | 매출비중 검토 | DART 매출비중으로 주요사업 영위사 확정 |

> 리포트 예시(클래시스)의 4-step과 동일 골격. Step4(베타포인트·거래정지)는 리포트에서 추가.

---

## 2. WACC 시트 — 유사회사 테이블 (rows 7~16)

컬럼: `# | 회사명 | Ticker | 국가(도시) | Tax rate | Debt to Capital | Equity to Capital | D/E | Levered beta | Unlevered beta | 2Y Weekly | 5Y Monthly`

### 셀 수식 (핵심)
| 셀 | 수식 | 의미 |
|---|---|---|
| **베타 옵션** | `J3` = 1(2년 주간) / 2(5년 월간) | 베타 산정 기간 토글 |
| **Tax rate** (F열) | `=IF(과표<20000·10^6, 20.9%, IF(과표<300000·10^6, 23.1%, 27.5%))` | **규모별 유효세율**(지방세 포함): 200억↓ 20.9%(19%×1.1) / 3000억↓ 23.1%(21%×1.1) / 초과 27.5%(25%×1.1) |
| **Levered beta** (J열) | `=IF($J$3=1, L열(2Y weekly), M열(5Y monthly))` | 옵션에 따라 베타 선택 |
| **Unlevered beta** (K열) | `=J/(1+(1-F)*I)` | **Hamada 무부채화**: βL/[1+(1−t)·D/E] |
| **Average** (row 16) | `=AVERAGE(...)` for Debt/Cap, Equity/Cap, Unlevered β | 유사회사 평균 |

> peer마다 **개별 세율**로 무부채화(F열이 회사별). 우리 `wacc.peer_unlevered_beta([(βL, D/E, tax), ...])` 가 이 구조.

---

## 3. WACC 빌드업 (rows 19~42) — 셀 참조 그대로

| 셀 | 항목 | 수식/출처 |
|---|---|---|
| F19 | Unlevered Beta | `=K16` (유사회사 평균 무부채 β) |
| F20 | Debt to Equity | `=G16/H16` (평균 D/Cap ÷ E/Cap) |
| F21 | Tax Rate | 대상회사 세율 |
| **F22** | **Relevered Equity Beta** | `= F19 × [1 + (1−F21)·F20]` (Hamada 재부채화) |
| F24 | Risk-Free Rate | 국고채 (Bloomberg) |
| F25 | Equity Risk Premium | 한공회(예시 8%) |
| F26 | ReLevered Equity Beta | `=F22` |
| F27 | Unsystematic Risk Factors | (0 or 조정) |
| F28 | Size Premium | Kroll deciles |
| F29 | Country risk premium | Damodaran |
| F30 | Company-Specific Risk | 판단 |
| **F32** | **Cost of Equity (Ke)** | `= F24 + (F26 × F25) [+ F28 + F29 + F30]` |
| F34 | Pre-Tax Cost of Debt | 신용등급 회사채 수익률 |
| F35 | Tax Rate | `=F21` |
| **F37** | **After-Tax Cost of Debt** | `= F34 × (1−F35)` |
| F39 | Debt to Capital | `=G16` |
| F40 | Equity to Capital | `=H16` |
| **F42** | **WACC** | `= (F39 × F34 × (1−F35)) + (F40 × F32)` |

### 공식 범례 (시트 하단 C44~48, 원문)
```
Unlevered Equity Beta = Levered Equity Beta / [1 + (1−Tax Rate) × Debt-to-Equity]
Levered Equity Beta   = Unlevered Equity Beta × [1 + (1−Tax Rate) × Debt-to-Equity]
Cost of Equity        = Risk-Free Rate + (Equity Beta × Equity Risk Premium)
Cost of Debt          = Pre-Tax Cost of Debt × (1−Tax Rate)
WACC = [(Debt to Capital × Cost of Debt) × (1−Tax Rate)] + (Equity to Capital × Cost of Equity)
```

---

## 4. `calc_core/wacc.py` 매핑 (셀↔코드)

| 서식 셀 | wacc.py |
|---|---|
| K열 `J/(1+(1-F)*I)` | `unlever_beta(levered, d_e, tax)` |
| F22 relever | `relever_beta(unlevered, d_e, tax)` |
| K16 평균 | `peer_unlevered_beta(peers)` (peers=[(βL,D/E,tax),…]) |
| F32 Ke | `Ke = risk_free + beta·ERP + size + CRP + CSRP` |
| F37 after-tax Kd | `pre_tax_cost_of_debt × (1−tax)` |
| F39/F40 weights | `we = 1/(1+D/E)`, `wd = D/E/(1+D/E)` (또는 G16/H16 직접) |
| F42 WACC | `we·Ke + wd·Kd_at` |

> 차이 주의: 서식은 D/Cap·E/Cap를 유사회사 **평균 자본구조**로 직접 사용(G16/H16). 우리 `build_wacc`는 `target_debt_to_equity`에서 weight를 유도 — 목표 자본구조를 D/E로 넘기면 동일. peer 평균 자본구조를 목표로 쓰는 게 리포트 예시 관행.

## 5. 재현 체크리스트 (WACC)
- [ ] peer 세율 = 규모별(20.9/23.1/27.5%) 개별 적용해 무부채화.
- [ ] 베타 옵션(2Y weekly vs 5Y monthly) 명시 — 리포트 예시는 **2년 주간 조정베타**(Bloomberg adjusted = ⅔·raw + ⅓·1).
- [ ] ERP = 한공회 가이던스(예시 8%).
- [ ] 목표 자본구조 = 유사회사 평균(D/Cap, E/Cap).
- [ ] Ke에 size/CRP/CSRP 반영 여부 문서화.
- [ ] WACC 재계산 = `wacc.build_wacc` 결과와 일치.
