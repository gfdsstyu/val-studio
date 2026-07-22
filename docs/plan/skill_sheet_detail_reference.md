# ② 전체 시트 참고 모델 상세화 — 명세

| 항목 | 내용 |
|------|------|
| **문서 ID** | SPEC-EXCEL-SKILL-002-② |
| **상위 명세** | [skill_peer_selection_and_sheet_detail.md](skill_peer_selection_and_sheet_detail.md) §2 |
| **정본** | `reference/모델링_실무_2강4강.md` §2·§3 · `reference/기업리서치_양식.md` · `reference/wacc_할인율서식.md` |
| **작성일** | 2026-07-19 |
| **상태** | Draft → 구현 착수 대기(명세 커밋 후) |

---

## 0. 목표

참고 모델 4강 모델 시트 골격(`Assumption · DCF · EBIT · FA · WC · WACC · H_FS · BackData · 상각비계산 · 유사회사FS`)에 맞춰 스킬 스켈레톤을 **모델링 기초 수준으로 세분**. 결정론 부분(상각 스케줄·WC 회전율·EBIT 롤업)은 **살아있는 수식**. 참고 모델 시트명·레이아웃은 **비복제**(방법론·골격만 차용, 자체 아키텍처).

**참고 모델 시트 ↔ 우리 시트 매핑**:

| 참고 모델 시트 | 우리 시트 | ① 상태 | ② 상세화 |
|---|---|---|---|
| Assumption | **`Assumption`(신규)** | ❌ | 가정 SSOT 블록(성장·마진·회전일·CAPEX%) |
| H_FS(과거 FS) | `FS_Hist`(W2) | 🔶 IS/BS(①착수) | 검증·보완 |
| 유사회사FS | `Peer`(W5) | ✅ ① | — |
| EBIT(매출·원가·판관비) | `Fcst_Rev`+`Fcst_Cost`(W4) | 🔶 세분·롤업 | 영업이익 롤업행·상각비 유입 |
| FA·상각비계산 | `Capex_Dep`(W4) | ❌ 얕음 | CAPEX 신규/유지 분리·상각 스케줄 살아있는 수식 |
| WC | `WC`(W4) | ❌ 얕음 | 회전율→잔액·ΔNWC 살아있는 수식 |
| DCF | `DCF`(W0 스파인) | ✅ | — |
| WACC | `WACC`(W5) | ✅ ① | — |
| Research | `Research`(W1) | 🔶 10섹션(①착수) | 검증·보완 |
| BackData | (주석/근거) | — | 각 시트 근거 노트 |

---

## 1. `Assumption` 시트 (신규) — 가정 SSOT

참고 모델 Assumption 시트 = 모든 가정의 단일 소스. 하류 시트가 **Green 참조**("hard number 1곳"). 스캐폴딩은 라벨+placeholder, 값은 Claude/평가인이 Research 근거로 채움.

**블록 구조**(연도=열, C..G):
- **매출 드라이버**: 성장률 or 시장CAGR·목표점유율(방식=평가인). → `Fcst_Rev`
- **마진**: GP%(=1−원가율)·EBIT%(판관비 후). → `Fcst_Cost` 검산
- **원가 성격**: 변동비율(매출연동)·고정비 증가율(CPI)·인건비 상승률. → `Fcst_Cost`
- **CAPEX·상각**: CAPEX(% of sales) 신규·유지보수, 상각연수(정액). → `Capex_Dep`
- **운전자본**: 매출채권·재고·매입채무 회전일. → `WC`
- **거시·할인**: Rf·MRP·목표 t. → `WACC`·세금

> 클래시스 벤치마크(peer_dcf): GP% 79.8%·EBIT% 51.6% 고정, 성장 +20% flat — sanity 앵커(주석).

---

## 2. `EBIT` 관점 (W4 `Fcst_Rev`+`Fcst_Cost`) — 영업이익 롤업

이미 세분·롤업(① 이전 배선). ② 보완:
- **영업이익 롤업행**: `Fcst_Cost`에 `영업이익 = 매출 − 매출원가계 − 판관비계` 살아있는 수식행 추가(EBIT = DCF!EBIT 검산).
- **상각비 유입**: 원가 상각비·판관비 상각비는 `Capex_Dep`에서 Green 참조(모델링_실무 §3: EBIT ← FA 상각비). 성격별 원가에 상각비 라인 명시.
- **마진 검산행**: GP%·EBIT% = Assumption 대비 편차(살아있는 수식) — 클래시스류 마진 sanity.

---

## 3. `Capex_Dep`(FA·상각비계산) — 상각 스케줄 살아있는 수식

참고 모델 FA+상각비계산 시트 정본. **기존자산 잔여상각 + 신규 CAPEX 상각 분리**(모델링_실무 §1 원가추정: "기존자산 vs 신규 CAPEX 분리, 절세효과").

**살아있는 수식 구조**(연도 t):
```
기초 유형자산_t   = 기말_{t-1}
CAPEX_t           = 신규 + 유지보수  (Assumption % of sales × 매출_t; 또는 [입력])
당기상각_t        = 기존자산 잔여상각_t + Σ(신규자산 정액상각)   [상각 스케줄]
기말 유형자산_t   = 기초_t + CAPEX_t − 당기상각_t
```
- 상각 스케줄: 신규 CAPEX는 상각연수(Assumption) 정액 → 향후 연도 상각 배분(삼각 스케줄). 살아있는 수식.
- **연결**: `당기상각 → DCF!(+)D&A` · `CAPEX → DCF!(−)CAPEX` · `상각비(원가/판관비 배분) → EBIT`(Green).
- CAPEX 정의(솔루엠): `유형자산취득 − 처분`, % of sales.

---

## 4. `WC` — 회전율 → 잔액 → ΔNWC 살아있는 수식

참고 모델 WC 시트(1주차 회전율 방향 오류수정 주의). 회전일 기반 잔액(모델링_실무 §3: WC ← Driver 매출·원가).

**살아있는 수식**(연도 t):
```
매출채권_t = 매출_t   × 매출채권회전일 / 365      (Green: Fcst_Rev·Assumption)
재고자산_t = 매출원가_t × 재고회전일 / 365          (Green: Fcst_Cost)
매입채무_t = 매출원가_t × 매입채무회전일 / 365
순운전자본(NWC)_t = 매출채권_t + 재고_t − 매입채무_t
ΔNWC_t = NWC_t − NWC_{t-1}                          (→ DCF!(−)ΔNWC, 현금조정 부호)
```
- 회전일 = Assumption/Research 참조(Green).
- 부호: `delta_nwc_cash_adj`는 DCF 현금조정 부호(원본 row24 = −ΔWC) — 증가시 현금유출.

---

## 5. `FS_Hist`(H_FS)·`Research` 보완 (①착수분 검증)

- `FS_Hist`: 전체 IS(매출~당기순이익)+BS(유동/비유동/총계) + Finalize 연결맵(①착수). ② = 소계 검산행(매출총이익=매출−원가 등) 살아있는 수식 추가.
- `Research`: 10섹션 하위필드·소비처(①착수). ② = 숫자가정 블록을 `Assumption` 시트로 이관(SSOT 단일화)하고 Research는 서사+출처 URL 중심.

---

## 6. Finalize 연결맵 (모델링_실무 §3) — 시트간 참조 규율

각 시트 하단에 **연결 노트**(어디서 오고 어디로 가나) 명시. 참조 방향 단방향(뒤→앞):
```
DCF   ← 매출/원가/판관비(EBIT) · (+)DEP/(−)CAPEX(Capex_Dep) · ΔNWC(WC) · 비영업자산/순차입부채(FS_Hist) · WACC
EBIT  ← 상각비(원가·판관비)(Capex_Dep)
WC    ← Driver 매출(Fcst_Rev)·원가(Fcst_Cost)
전부  ← 가정(Assumption)
```
- 향후 검증: 스캐폴딩이 이 연결을 노트로 강제(사람이 Green 참조 배선). W6 tie-out(promote.py)이 최종 정합 확인.

---

## 7. 구현 순서 (①완료 후, 각 커밋)

1. `Assumption` 시트 신규(build_assumption) + 스테이지 배선(W1 또는 신규 W0.5).
2. `Capex_Dep` 상각 스케줄 살아있는 수식(build_capex_dep 재작성).
3. `WC` 회전율→잔액→ΔNWC 살아있는 수식(build_wc 재작성).
4. `Fcst_Cost` 영업이익 롤업·상각비 유입행.
5. `FS_Hist`·`Research` 소계 검산·SSOT 이관.
6. 각 시트 Finalize 연결 노트.
7. 테스트: 상각 스케줄 합·WC 회전율 수식·연결 노트 구조. 스킬 회귀·골든 불변.

---

## 8. 원칙

- **참고 모델 비복제**: 방법론·시트 골격만, 셀 레이아웃 자체 정의.
- **살아있는 수식**: 상각 스케줄·WC 회전율·EBIT 롤업·마진 검산 = live formula.
- **Assumption SSOT**: 가정은 Assumption 시트 1곳, 하류 Green 참조(hard number 1곳 절차화).
- **판단=평가인**: 드라이버 방식·마진·회전일 값은 평가인, 수식 구조는 결정론.

---

## 9. 변경 이력

| 버전 | 날짜 | 변경 |
|------|------|------|
| 1.0 | 2026-07-19 | ② 상세화 명세 — 참고 모델 시트 매핑 + Assumption 신규·Capex_Dep 상각스케줄·WC 회전율 살아있는 수식·Finalize 연결맵 |
