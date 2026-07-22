# 스킬 재조정 명세 — 유사회사 선정 풀 배선 + 시트 상세화 + 웹 UX

| 항목 | 내용 |
|------|------|
| **문서 ID** | SPEC-EXCEL-SKILL-002 (재조정) |
| **상위 명세** | [skill_excel_workflow_spec.md](../skill_excel_workflow_spec.md) |
| **레퍼런스 정본** | `reference/wacc_할인율서식.md` §1~2 · `reference/리포트예시_클래시스.md` §E · `backend/ingest/peer_selection.py` |
| **작성일** | 2026-07-19 |
| **상태** | Draft → 구현 착수 대기(명세 커밋 후) |

---

## 0. 배경 — 재조정 근거 (검토 결과)

Claude for Excel 실사용 피드백: 스킬 시트가 **모델링 기초 대비 얕고**, 특히 **유사회사 선정**이 참고 모델 강의자료의 다단계 퍼널에 비해 빈약(3행 placeholder). 검토로 확인된 사실:

| 계층 | 유사회사 선정 상태 |
|------|--------------------|
| 백엔드 `ingest/peer_selection.py` | ✅ 4-step 퍼널 정본(stdlib) — 83→11→9→6 실측 재현, Step2만 LLM, uncertain→⚖️큐, 전 후보 감사추적, Step1a KSIC 역산, 5-10 rule |
| 웹 `PeerSheet.jsx` | ✅ 4-step + 판정(유사/비유사/애매)·⚖️큐·퍼널 생존수 (`/api/peer/select` 소비) |
| **스킬 W5** | ❌ 3행 placeholder + Hamada만 — **퍼널 전체 누락(skill↔web 패리티 갭)** |

**근본 원인**: `peer_selection.py`가 stdlib이라 벤더링만 하면 스킬에서도 웹과 동일 퍼널을 돌릴 수 있는데, 이를 안 쓰고 얕은 테이블을 새로 그림. `dcf.py`/`wacc.py`처럼 **`peer.py` 얇은 래퍼**로 미러하면 즉시 패리티.

**3단계 로드맵** (순차, 각 단계 커밋):
1. **① 유사회사 선정 풀 배선(스킬)** — 본 명세 §1 (이번 구현)
2. **② 전체 시트 참고 모델 상세화** — 본 명세 §2 (①완료 후)
3. **③ 웹 UX 강화** — 본 명세 §3 (②완료 후)

---

## 1. ① 유사회사 선정 풀 배선 (이번 구현)

### 1.1 방법론 정본 (두 레퍼런스 병합)

**할인율 서식 §1 (Step0~3)** + **참고 모델 §E (4-step 실측)** + **peer_selection.py (실행 엔진)**:

| Step | 기준 | 주체 | 게이트 | 클래시스 실측 |
|------|------|------|--------|---------------|
| **Step0** 대상 리서치 | 대상 사업·재무 파악 | W1 Company Brief 재사용 | — | — |
| **Step1a** 코드 확정 | rough 유사회사 시드 → KSIC 역산(2~3개 union) | LLM+역산 | 코드 근거 기록 | 의료용기기+의료용품 제조업 |
| **Step1b** 모집단 필터 | 확정 코드로 KRX 상장사 필터 | 결정론 | 코드 매칭 | **83사** |
| **Step2** 사업 유사성 | 홈페이지·DART 사업보고서로 '피부/미용' 관련 | **LLM만**(사유 필수, uncertain→⚖️큐) | 판정 완비·무사유 거부 | **11사** |
| **Step3** 매출 비중 | 관련사업 매출비중 임계(기본 70%) | 결정론 | 비중 ≥ threshold | **9사** |
| **Step4** 기타 | 상장연수(베타포인트 ≥2년)·거래정지 | 결정론 | 상장≥2Y·미정지 | **6사** |

- **Step1 실무 교정**: KSIC 코드만으로 업종이 완전히 안 갈려 **코드 2~3개**가 실무 표준. 어떤 코드를 쓸지 자체가 "rough 유사회사 조사 → KSIC 역산" 반복(Brief ⑦⑨ 경쟁사가 시드). `codes_from_seed_peers()`가 역산 지원.
- **5-10 Rule**: 확정 peer 5개 미만=통계 취약, 10개 초과=유사성 희석 → `size_note()` 표면화.

### 1.2 `peer.py` 스킬 도구 (웹 `/api/peer/select` 미러)

- **벤더링**: `ingest/peer_selection.py`를 vendor 대상에 추가(stdlib, 자기완결). `dcf.py`/`wacc.py`와 동일 `_bootstrap` 패턴.
- **I/O 계약 (웹과 동일)**:
  ```
  stdin: {
    "candidates": [{ticker, name, industry_code, revenue_share_related, listed_years, suspended}],
    "target_industry_codes": ["2710", ...]  또는  "seed_peers": [{ticker,industry_code}]  (역산),
    "judgments": [{ticker, similar, uncertain, reason}],   # Step2(선택; 없으면 결정론 1·3·4만)
    "revenue_share_threshold": 0.70, "min_listed_years": 2.0
  }
  stdout: {
    "funnel": {step→생존수}, "selected": [{ticker,name}], "needs_review": [{ticker,name,reason}],
    "dropped": [{ticker,name,dropped_at,reason}], "warnings": [...], "size_note": ..., "markdown": ...
  }
  ```
- **게이트**: Step2 판정이 생존 후보 전원분 없거나 사유 비면 거부(무근거 판정 금지 — 감사 방어). uncertain은 자동 탈락 금지, ⚖️큐로.
- `to_markdown()`로 감사 방어 리포트(퍼널+최종+탈락사유 전량) 출력.

### 1.3 `Peer` 시트 (`build_peer`) — 4-step 퍼널 + 무부채화

**§1 4-step 퍼널 표** (후보 → 생존; peer.py 게이트):
- 컬럼: `회사 · Ticker · KSIC · 관련매출% · 상장연수 · 거래정지 · 판정(유사/비유사/애매) · 사유 · 생존스텝`
- 게이트 노트: `peer.py — Step1 코드매칭·Step2 판정완비(사유)·Step3 비중≥70%·Step4 상장≥2Y/거래정지, uncertain→⚖️큐, 5-10 rule`

**§2 확정 peer 무부채화(Hamada) 테이블** (할인율서식 §2 컬럼 정본):
- 컬럼: `회사 · 세율t · D/Cap · E/Cap · D/E · Levered β · Unlevered β`
- 살아있는 수식: `D/E = D/Cap ÷ E/Cap`, `Unlevered β = Levered β / (1+(1-t)·D/E)` (Hamada)
- 평균 행: `AVERAGE(D/Cap, E/Cap, Unlevered β)`
- **베타 옵션 노트**: 2Y weekly 조정베타(Bloomberg adj=⅔·raw+⅓) 관행.

**연결(절차적, 크로스시트 수식 아님)**: 확정 peer → WACC 무부채β·목표자본구조(D/Cap·E/Cap 평균). 참고 모델 11.유사회사 → 12.WACC 분리 구조 계승.

### 1.4 W5 스테이지 재구성

`build_stage("W5")` = `[build_peer, build_wacc]` (2시트). `build_wacc`는 기존(Hamada 재부채화 + CAPM 빌드업 살아있는 수식) 유지하되 무부채β·목표D/E는 `[입력]`(Peer 평균에서 옮김). β·MRP provenance 행 유지(β/MRP 시장 정합).

### 1.5 서브태스크 게이트 (task 쪼개기)

퍼널 자체가 4 서브태스크이며 각각 생존수·감사추적:
- **Step1** 산업코드 매칭(모집단 확정) — 코드 근거
- **Step2** 사업유사성 판정 완비·사유 필수 — LLM 산출, 원출처 재확인
- **Step3** 매출비중 ≥ 임계 — DART 근거
- **Step4** 베타포인트(상장≥2Y)·거래정지 — 상장일·정지 스크리닝

### 1.6 테스트

- `test_peer.py`: 웹 시나리오 재현 — 모집단(코드 불일치 탈락)·Step2(비유사 탈락·uncertain→needs_review·무사유 거부)·Step3(저비중 탈락)·Step4(신규상장·거래정지 탈락), funnel 생존수, size_note(5-10).
- `test_skill_scaffold_roundtrip`: W5=[Peer, WACC] 생성, Peer 퍼널 컬럼·Hamada 수식·WACC 빌드업 수식.

---

## 2. ② 전체 시트 참고 모델 상세화 (①완료 후)

참고 모델 모델 시트(모델링_실무 §2: `Assumption · DCF · EBIT · FA · WC · WACC · H_FS · BackData · 상각비계산 · 유사회사FS`) 대비 현 스켈레톤 갭을 매핑해 세분:

| 현 스켈레톤 | 참고 모델 상세화 방향 |
|-------------|---------------------|
| W1 Research | 10섹션 하위필드·소비처(기업리서치_양식 정본; 착수분 반영) |
| W2 FS_Hist | 전체 IS(매출~당기순이익)+BS(유동/비유동/총계) + Finalize 연결맵(착수분 반영) |
| W4 Fcst/Capex/WC | EBIT(원가 성격별)·FA(상각비계산 스케줄)·WC(회전율 방향) 세분 |
| 신규 | `Assumption` 시트(가정 SSOT)·`BackData` 관행 검토 |

> 원칙: 참고 모델 **방법론·시트 골격 참조**, 시트명·레이아웃 **비복제**(자체 아키텍처). 살아있는 수식 우선.

---

## 3. ③ 웹 UX 강화 (②완료 후)

`PeerSheet.jsx` 등 웹을 스킬과 동일 상세도로:
- **Step1a KSIC 역산**: seed_peers 입력 → codes_from_seed_peers 배선(현재 코드 직접입력만).
- **완전 peer 테이블**: unlever 컬럼(D/Cap·E/Cap·Levered β·Unlevered β)을 PeerSheet에 통합(현재 DiscountSheet 분리).
- **베타포인트 수 표시**·거래정지 근거.
- skill↔web **동일 방법론**(peer_selection.py 단일 엔진) 유지 — 두 표면이 같은 결과.

---

## 4. 설계 원칙 (전 단계 공통)

- **벤더 SSOT**: `peer_selection.py` 미러(스킬)·`/api/peer/select`(웹)·`build_peer`(시트)가 **같은 엔진**. 로직 중복 금지.
- **참고 모델 비복제**: 방법론·시트 골격만 차용, 셀 레이아웃 자체 정의.
- **살아있는 수식**: Hamada 무부채화·D/E·평균 = live formula.
- **판단=평가인**: Step2 사업유사성·uncertain 표면화, 결정론(코드·비중·베타포인트)은 자동.
- **감사 방어**: 전 후보 탈락사유·퍼널·5-10 rule 산출(peer.py `to_markdown`).

---

## 5. 변경 이력

| 버전 | 날짜 | 변경 |
|------|------|------|
| 1.0 | 2026-07-19 | 재조정 명세 초안 — 유사회사 풀 배선(peer.py 미러·Peer 시트 4-step) + ②전체시트·③웹UX 로드맵 |
