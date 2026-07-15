# Valuation Platform — DCF 모델 자동화

MSVALUE 기업가치평가 연수 과제(비올 DCF Model)의 로직을 **1:1로 재현**하는 결정론적 DCF 엔진을 코어로, 앞단(DART API·RAG·LLM 가정도출)을 자동화하고 **감사인이 셀 수식을 추적할 수 있는 살아있는 xlsx**를 내보내는 웹 플랫폼.

## 투트랙
- **평가자(전문가)**: FS·기초자료 → 가정도출(RAG·챗) → DCF 모델 → 평가의견서.
- **감사인**: 제공된 의견서를 FS·주석과 tie-out 테스트하거나 독립적 점/범위 추정.

## 스택
Python(FastAPI) 백엔드 · React+Vite SPA · Supabase(Postgres+Auth+Storage+pgvector) · Gemini(+Groq).
배포: 프론트=Vercel, 백엔드=Railway/Render.

## 현재 상태 — Milestone 1 (결정론적 DCF 코어) ✅
- ✅ **calc_core 스파인** (`dcf·tax·models`): 매출→EBIT→구간법인세→NOPLAT→FCFF→중간연도PV→EV→주당가치 + 2-way 민감도.
- ✅ **스파인 골든** (`tests/golden/test_viol_spine.py`): 비올 원본과 셀단위 일치(rel_tol 1e-9). 주당가치 8,413.38원 정확 재현.
- ✅ **상류 엔진** (`revenue·ebit·fa·wc·wacc·model`): 표준 방법론 일반 구현 + 단위테스트 9건. 법인세는 비올과 정확 일치로 앵커.
  - `revenue`: top_down(산업 CAGR) | bottom_up(계층 트리 P×Q, 합계검증)
  - `wacc`: CAPM 빌드업(Hamada unlever/relever, Ke=Rf+β·ERP+size+CRP+CSRP)
  - `fa`: 정액 감가상각 스케줄 · `wc`: 회전율 ΔNWC · `model`: 엔드투엔드 조립
- ⬜ xlsx export(수식 유지) · DART 인제스트 · 주석 추출·검증 · RAG/챗.

> 설계 선택: 비올의 bespoke 상류 시트(제품 세그먼트 977수식·messy WACC 연구시트)를 비트복제하지 않고 **표준 방법론 일반 엔진**으로 구현. 스파인·법인세는 비올로 정확 검증, 나머지는 표준식 단위테스트.

## 실행
```bash
python tests/golden/test_viol_spine.py     # 스파인 골든(stdlib)
python tests/test_upstream.py              # 상류 단위테스트 9건(stdlib)
pytest -q                                  # 또는 pytest 설치 시 전체
```

## 구조
```
backend/calc_core/
  models·tax·dcf        결정론적 스파인 (비올 골든 검증)
  revenue·ebit·fa·wc·wacc  상류 표준 엔진 (단위테스트)
  model                 가정→전체 DCF 오케스트레이터
tests/golden/           비올 1:1 재현 골든 테스트
tests/test_upstream.py  상류 엔진 단위테스트
fixtures/viol/          inputs.json·expected.json (원본에서 추출한 골든 SSOT)
scripts/                원본 엑셀 → 픽스처 추출 스크립트
docs/                   계획·참고자료 색인
```

> 원본 엑셀·PDF 등 저작권/기밀 자료는 레포에 포함하지 않는다(.gitignore). 골든 테스트에 필요한 최소 수치만 `fixtures/viol/*.json` 로 커밋.

## 문서
- `docs/engine_spec.md` — **임의 회사 DCF 재현 명세**(입력 규격·단위·컨벤션·데이터출처·단계별 절차·검증 체크리스트).
- `docs/plan.md` — 전체 계획(투트랙·인제스트·주석검증·RAG·감사인 트랙·배포).
