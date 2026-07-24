# 칼럼 코퍼스(62문서) 기반 플랫폼 보강·고도화 전략

> 작성 2026-07-24. 소스 = `D:\gfdsstyu.github.io\docs\book\research\corpus\` (ifrs 35 + val 27 = 62 md).
> 원본 = `D:\칼럼\ifrs`(IFRS Issue Paper 34편 + T-F 엑셀 워크북 3종 + FSS 질의회신) + `D:\칼럼\val`(밸류에이션 칼럼·상장사 실전평가 27편).
> 코퍼스 스키마 = `corpus/SCHEMA.md`(frontmatter에 `platform_refs` 필드 사전 설계), 인덱스 = `corpus/INDEX.md`(자동생성, §4에 게이트/모듈 연결 지도 이미 존재).

---

## 0. 한 줄 전략

**코퍼스의 4대 클러스터(복합금융·공정가치·손상 VIU·주식기준보상)가 현재 플랫폼에서 가장 얇은 트랙과 정확히 일치한다.**
거래평가 DCF 트랙이 3개 레퍼런스(비올·클래시스·모델러스)로 완주된 지금, 이 코퍼스는
"자본시장법 종합평가 → 손상 → 공정가치/복합금융"으로 이어지는 스코프 로드맵의 **다음 트랙 연료를 통째로 공급**한다.
특히 T-F 엑셀 워크북 3종은 `convertible.py`의 **첫 실무 골든 픽스처(4번째 교차검증 레퍼런스)** 후보다.

## 1. 자산–플랫폼 정합 지도 (왜 이 코퍼스인가)

| 코퍼스 클러스터 | 문서 수 | 현재 플랫폼 상태 | 격차 → 기회 |
|---|---|---|---|
| **복합금융(CB·TF·내재파생)** ifrs-218/221/407/408/8 + **TF 엑셀 3종** | 6 | `convertible.py` 구현됨(CRR+TF+RCPS accrual) — 그러나 **성질 테스트만 있고 실무 골든 0** | 엑셀 3종 → 골든 픽스처. 북 챕터 `복합금융상품_평가.md`는 ⏳ 스텁 → 정본 승격 |
| **공정가치 측정(IFRS 13)** ifrs-201/217/345/346/347/350/411/412/414 | 9 | FV 트랙 = 스코프 로드맵상 ⏳ 미래, 엔진·챕터 전무 | **Backsolve/OPM 신규 코어** + FV hierarchy·day-one·브로커가격 게이트 신설 |
| **손상 VIU(K-IFRS 1036)** ifrs-234/235/413/745/746/747 + fss-2020-33 | 7 | `손상검사_impairment.md` 블로그 기반 개론뿐, VIU 엔진 없음 | 손상 트랙 착수에 필요한 **기준서 논점 전량**(세전할인율·회수가능가액 비교대상·CGU·복구충당부채) 확보 |
| **주식기준보상·희석** ifrs-222/225/227/228/731 + 524/526 + 742/743 | 9 | 다모다란 SBC 반영·희석 주당가치 = 엔진 미반영 | `dcf.py` per-share 희석 브리지 + SBC 게이트. 이항 엑셀 구현편 = 엔진 검증 자료 |
| **실전 상장사 평가 사례** val-samsung/sk-hynix/hyundai-motor/doosan/glovis/hanwha-ocean/apr/alteogen/homeplus 등 | 10+ | 북 practice층 사례 = 비올·클래시스·Hugel 3건뿐 | **E2E 리허설 시나리오 10건**(우리 인프라로 독립 재현 → 칼럼 결론과 대조) + practice층 확충 |
| **방법론 칼럼** val-fcfe-vs-fcff/perpetual-growth-rate/beta/market-value-vs-dcf/analytical-review/현금흐름표 3부작/deferred-tax 등 | 10+ | 베타·PGR은 기존 챕터 존재(중복) | 기존 챕터 **보강 병합**(dedup) + FCFE 경고·분석적검토→FDD 연계 등 신규 승격 |

**역할 분리(중요)**: 코퍼스(`docs/book/research/corpus/`)는 **사료층**(원문 충실 추출, 책+플랫폼 공용 SSOT).
플랫폼 북(`docs/reference/`)은 **제품층**(자기완결 방법론 지식, RAG로 서빙). 코퍼스를 북에 **복붙하지 않고 증류**한다 —
북 1챕터가 코퍼스 N문서를 소화하고 frontmatter `source`로 역참조. 이중 저장이 아니라 계층이다.

## 2. 편입 대원칙 5

1. **증류, 복제 금지** — 북 챕터는 자기완결 방법론 지식으로 재작성. 코퍼스 원문(유료 칼럼 전문)은 플랫폼 레포에 이관하지 않는다.
2. **지식→로직 승격 우선순위** — "게이트화 가능한 규칙문"(코퍼스 §3 판단기준·규칙 절이 이미 추출해 둠)부터 checks/엔진으로 승격. 문서만 늘리는 편입은 후순위.
3. **골든 먼저** — 새 트랙(복합금융)은 챕터보다 골든 픽스처(TF 엑셀 3종)를 먼저 확보. 검증 불가능한 지식은 신뢰 백본이 아니다.
4. **기존 규약 준수** — 북 frontmatter(topic/keywords/canonical_questions/layer/parent) → `ontology/build.py` 재컴파일 → BookSearcher 자동 인덱싱 → vendor 재빌드(`build_excel_skill.py`, reference/*.md가 vendored됨).
5. **공개 경계** — 유료 프리미엄 칼럼·Issue Paper 원문은 공개 push 제외(기존 정책: docs/reference 비공개 + `mask_rules.json` fail-closed). 저자·매체명은 마스킹 규칙에 추가. 공개 표준출처(K-IFRS 조항번호·다모다란·상장사 공시 수치)는 유지.

## 3. 세부전략 S1~S5

### S1. 복합금융 트랙 완성 (최우선 — 엔진이 이미 살아있고 골든만 없다)

**목표**: `convertible.py`를 "성질 검증된 프로토타입"에서 "실무 재현 검증된 코어"로 승격.

1. **TF 엑셀 3종 골든화** — `D:\칼럼\ifrs\` 의 `CB_TF_Model_B2Formula.xlsx` · `TF_Model_CB_Valuation_Detailed_Steps.xlsx` · `TF_Model_Convertible_Bond_With_Put.xlsx`(단일 시트 'TF Model').
   - openpyxl 이중로드(formula+cached)로 입력셀·수식·산출값 채록(모델러스 5.4 방식 재사용) → `tests/golden/test_tf_model_*.py` — 워크북 캐시값을 `convertible.py`로 재현(rel_tol 게이트).
   - 코퍼스 `ifrs-tf-model-excels.md`에 구조·수식·입력셀이 이미 문서화되어 있음 → 채록 출발점.
   - 괴리 발생 시 = 비올/클래시스 때처럼 **설계차이 vs 결함 판별** 후 개선점 목록화(스텝 안분·스프레드 적용 노드·put 상환가 처리가 유력 괴리 후보).
2. **북 챕터 승격** — `복합금융상품_평가.md` ⏳ 스텁 → 정본: ifrs-218(TF 개요)·221(CB 기본논리)·407(with-without 내재파생)·408(신용악화 기업 CB)·8(제3자 지정 콜옵션 파생자산) 증류. put 가치=Put포함사채−일반사채, call 가치=CB전체−일반사채−put 등 **분해 공식을 수식 그대로** 수록.
3. **로직 승격 후보**
   - `convertible.with_without()` — 내재파생 평가 표준 인터페이스(407): 전체−host = 파생. 이미 있는 TF 분리와 별개의 감사인 교차검증 경로.
   - `check_distressed_cb`(408) — 신용스프레드가 임계 초과(신용악화)면 표준 TF 가정(채권성분 할인율) 경고 + 회수율 반영 여부 확인.
   - 제3자 콜옵션부 CB(8) — 파생상품**자산** 인식 케이스: 발행자/제3자 관점 분리 플래그.

### S2. 공정가치(FV) 트랙 신설 — Backsolve 엔진 + IFRS 13 게이트

**목표**: 비상장주식 FV 평가(Backsolve/OPM)를 새 calc_core 모듈로, IFRS 13 판단규칙을 checks로.

1. **`calc_core/backsolve.py` 신설**(ifrs-201/411/412) — 최근 투자 라운드 가격에서 기업가치 역산 → OPM(Black-Scholes 기반)으로 우선주 청산우선권·전환권 반영해 보통주 가치 배분. breakpoints(청산우선·전환·participation) 구조가 핵심. stdlib 폐형해(BSM)로 구현 가능 — 몬테카를로 불요.
2. **신규 챕터 `공정가치_측정_FV.md`** — ifrs-217(IFRS 13 프레임워크)·345/346(hierarchy)·347(day-one FV·calibration)·350(브로커 제공 가격의 Level 판정)·414(프리마켓/애프터마켓 주가) 증류. layer=methodology, parent=밸류에이션_스코프_로드맵.
3. **checks 승격**
   - `check_fv_hierarchy` — 평가에 쓴 인풋별 Level 판정 근거 요구(관측가능성), Level 3면 가치평가기법 공시 요건 WARN.
   - `check_day_one_calibration`(347) — 거래가격≠모델가치면 미실현 day-one 차이 이연 처리 확인.
   - `check_market_price_eligibility`(414+val-market-value-vs-dcf) — 활성시장 시가 존재 시 DCF 단독 채택 근거 요구(시가>모델이면 Level 1 우선 원칙).
   - `check_broker_price_source`(350) — 브로커 호가=구속력 없는 indicative면 Level 2/3 강등.
4. **기존 자산 재사용** — 온톨로지 씨앗(롯데 이항·신주인수권 OPM 공시사례), 외부평가의견서 taxonomy. Backsolve는 감린이 RAG 챗봇에도 고빈도 질의 주제(KIFRS1113/1109 계열)라 북 품질=답변 품질 직결.

### S3. 손상(VIU) 트랙 — 설계 스펙을 코퍼스로 완성

**목표**: 손상 트랙 착수 시 필요한 기준서 논점을 북에 정본화하고, VIU 엔진 설계 입력을 확정.

1. **`손상검사_impairment.md` 대폭 보강**(블로그 개론 → 기준서 논점 정본):
   - ifrs-234: **세전 할인율** — post-tax로 계산 후 iterative 환산이 실무 표준(단순 gross-up 아님). → VIU 엔진의 할인율 모듈 스펙.
   - ifrs-235: 회수가능가액과 **비교대상 장부가액의 범위 일치**(운전자본 포함 여부 등 Apple-to-Apple) — 기존 감사인 정합 원칙과 동일 계열.
   - ifrs-745/746: VIU 현금흐름 추정(성능개선 CAPEX 제외·구조조정 미확약분 제외) + 복구충당부채의 이중계상 방지(부채 차감 vs 현금흐름 반영 택일).
   - ifrs-747: 외부정보 기반 **기업전체 손상징후 → CGU 단위 손상방법**(시총<장부가 트리거).
   - ifrs-413 + fss-2020-33: 이연법인세→영업권 즉시손상 역설, 관리종목 관계기업주식 손상(실무 질의회신 = 공시 실측급 근거).
2. **로직 승격 후보**(엔진은 미래 트랙이지만 게이트는 지금 가능):
   - `check_viu_discount_rate` — 손상 목적 평가인데 세후 WACC 그대로 쓰면 WARN(세전 환산 요구).
   - `check_viu_cashflow_scope` — VIU에 성능개선 CAPEX·미확약 구조조정 포함 시 FAIL.
   - `check_impairment_trigger` — 시총<순자산 장부가(747) 감지(price_client 시총 재사용) → 손상징후 WARN. **기존 K-IFRS 1036.35 5년 상한 지식과 결합.**
3. **VIU 엔진 설계 결론(선언만)**: 손상 DCF = 기존 `dcf.py` 재사용 + 오버라이드 3종(TV 없음/내용연수 유한·세전 할인율·CAPEX 스코프 필터) — 새 엔진이 아니라 **기존 스파인의 제약 모드**로 설계(기존 판단 유지, 코퍼스가 제약 목록을 확정해 줌).

### S4. 주식기준보상(SBC)·희석 주당가치 — DCF 정밀화

**목표**: 이미 완성된 DCF 스파인의 두 가지 실무 정밀도 격차(SBC·희석)를 해소.

1. **신규 챕터 `주식기준보상_옵션평가.md`** — ifrs-222(모형 개관)·225(시장조건 반영)·227/228(**이항모형 엑셀 구현** — 검증 수치 포함)·731(변동성 영향) 증류. S1의 CRR 트리 코드(`convertible.py`)와 수학이 동일 — 코드 재사용 각주.
2. **`dcf.py` 희석 브리지**(ifrs-524/526) — 다모다란 주당가치: 전환가능증권 존재 시 (a) 옵션가치 차감 후 기본주식수 나눔 또는 (b) if-converted. 현재 엔진=발행주식수 단순 나눔 → `DcfSpineInput.dilutive_instruments`(옵션 FV 차감 방식 우선) + `check_dilution_bridge`(전환증권 감지 시 희석 미처리 WARN). **모델러스 D7(주식수 이원화 결함 게이트)과 같은 계열의 주당가치 정밀화.**
3. **SBC의 FCFF 반영**(ifrs-742/743) — 주식결제형 SBC: 비현금이지만 add-back 금지(다모다란: 실질 비용, 미래분은 비용으로·기발행분은 희석으로). → `check_sbc_treatment`: SBC 존재 표시 시 add-back 여부 확인 게이트. VIU 목적(742)과 계속기업 목적(743) 처리 차이를 챕터에 병기.

### S5. 실전 사례 practice층 + 재무분석 방법론

**목표**: 상장사 실전평가 10건을 practice층 사료 + E2E 리허설 시나리오로 전환.

1. **E2E 리허설 3건 선별 실행**(전 건 편입 아님 — 인프라 검증 가치가 있는 것만):
   - **삼성전자**(val-samsung-2025q2): XBRL 인제스트 실측 이미 보유 → DART XBRL→Brief→DCF 전 배관으로 독립 재현 후 칼럼 가정·결론과 대조. 괴리 = 가정 차이 설명 리포트(감사인 트랙 GapDiagnosis 실전 데이터).
   - **알테오젠**(val-alteogen-halozyme-psr): **PSR 상대가치** — `multiples.py`에 PSR 미구현이면 추가(적자 바이오 = PER/EV-EBITDA 불능 케이스의 정당한 PSR 사용례). 상대가치 트랙 실사례 1호.
   - **홈플러스**(val-homeplus): 부실 사례 — `check_going_concern` 신설 근거(영업CF 지속 음수·차입 롤오버 의존·이자보상배율<1). 계속기업 가정이 무너진 DCF는 무의미 → 실행 전 게이트 계열.
2. **practice층 사례 챕터 1개로 묶음** — `실전평가_상장사_사례집.md`(사례별 1~2절: 사용 방법론·핵심 가정·결론·우리 게이트로 본 논평). 개별 챕터 10개 남발 금지(북 비대화 방지).
3. **방법론 칼럼 병합(dedup)**
   - val-beta-bloomberg-kicpa + ifrs-730 → 기존 `베타_Bloomberg_vs_KICPA.md` 보강(신규 논점만).
   - val-perpetual-growth-rate → 기존 `영구성장률_PGR_적합성.md` 보강.
   - val-fcfe-vs-fcff → `DCF_교육_정본.md` FCFF/FCFE 절 보강 + `check_fcfe_usage`(FCFE 선택 시 차입 스케줄 정합 요구) 승격 후보.
   - 현금흐름표 3부작 + val-analytical-review → `three_statement.py` 검증 오라클(간접법 작성 원리 = CF 스파인 대사 게이트의 지식 근거) + FDD 챕터 연계.
   - val-deferred-tax → 개선 A(세금 주입) 문서 근거 보강. val-separate-consolidated → NCI 브리지(기구현) 지식 근거 보강.

## 4. 지식→로직 승격 후보 총괄표

| # | 승격 대상 | 근거 코퍼스 | 유형 | 트랙 |
|---|---|---|---|---|
| 1 | TF 골든 픽스처 3종 | ifrs-tf-model-excels + 엑셀 원본 | 골든 테스트 | S1 |
| 2 | `with_without()` 내재파생 | ifrs-407 | 엔진 | S1 |
| 3 | `check_distressed_cb` | ifrs-408 | 게이트 | S1 |
| 4 | `backsolve.py`(OPM breakpoints) | ifrs-201/411/412 | **신규 코어** | S2 |
| 5 | `check_fv_hierarchy` | ifrs-345/346/350 | 게이트 | S2 |
| 6 | `check_day_one_calibration` | ifrs-347 | 게이트 | S2 |
| 7 | `check_market_price_eligibility` | ifrs-414 + val-market-value-vs-dcf | 게이트 | S2 |
| 8 | `check_viu_discount_rate`(세전 환산) | ifrs-234 | 게이트 | S3 |
| 9 | `check_viu_cashflow_scope` | ifrs-745/746 | 게이트 | S3 |
| 10 | `check_impairment_trigger`(시총<장부가) | ifrs-747 | 게이트 | S3 |
| 11 | 희석 브리지 + `check_dilution_bridge` | ifrs-524/526 | 엔진+게이트 | S4 |
| 12 | `check_sbc_treatment` | ifrs-742/743 | 게이트 | S4 |
| 13 | PSR 배수 | val-alteogen | 엔진(multiples) | S5 |
| 14 | `check_going_concern` | val-homeplus | 게이트 | S5 |
| 15 | `check_fcfe_usage` | val-fcfe-vs-fcff | 게이트 | S5 |

## 5. 공통 편입 사이클 (기존 검증 프로세스 재사용)

```
코퍼스 md(§3 규칙문·§4 플랫폼 연결 이미 추출됨)
  → 북 챕터 증류(frontmatter 규약: topic/keywords/canonical_questions/layer/parent)
  → python docs/reference/ontology/build.py   # RAG 인덱스·그래프 재컴파일
  → 승격표(§4)에서 해당 항목 구현 + 테스트(골든/성질)
  → python scripts/build_excel_skill.py       # vendor 동기(reference/*.md vendored)
  → (공개 push 시) mask_names.py --check      # 칼럼 저자·매체 마스킹 규칙 추가
```

- 코퍼스 쪽 갱신: 승격 완료 시 해당 코퍼스 md의 `platform_refs`를 실제 심볼로 확정(`checks.py:check_viu_discount_rate` 형식) → `build_index.py` 재실행. INDEX §4가 살아있는 추적표가 된다.
- 현재 `platform_refs` 태깅 40/62 — Phase 착수 전 나머지 22건(빈 배열)을 훑어 승격 후보 누락 재확인.

## 6. 실행 순서 (마일스톤 정렬)

| 순서 | 내용 | 완료 판정 | 로드맵 정렬 |
|---|---|---|---|
| **P1** | S1 복합금융: TF 골든 3종 + 챕터 정본 + 승격 2~3 | TF 워크북 캐시값 재현 green | 복합금융 트랙 🔨→✅ 코어 검증 |

**P1 골든화 완료(2026-07-24)**: `tests/golden/test_tf_workbooks.py` 8건 green — 파일 B 121.0199893394989 재현(1e-12)·파일 A 격자+B2 이중구조 재현·파일 C as-written+교정판. **부수 성과: `convertible.py` 풋-우선 캐스케이드 결함 발견·수정**(홀더 선택 = max(계속(콜캡)·전환·풋), 기존 17테스트 유지). 교차검증: spread=0 붕괴 완전일치 + TF>단일위험할인 방향 실증. **워크북 3종 자체가 반면교사 4종 보유**(단일할인율을 TF로 명명·쿠폰 단위결함 2종·표시수식≠생성로직·이종가정 차감 분해) — 상세는 코퍼스 `ifrs-tf-model-excels.md` §4-0. 잔여 P1: 챕터 정본 승격(복합금융상품_평가.md) + 게이트 승격(§4 표 2·3번).
| **P2** | S2 공정가치: backsolve.py + 챕터 + 게이트 3~4 | Backsolve 수치예제(411/412 수록분) 재현 | FV 트랙 ⏳→🔨 |
| **P3** | S4 SBC·희석: 희석 브리지 + SBC 게이트 + 챕터 | 골든 8413.38 불변 + 희석 케이스 테스트 | DCF 정밀화(개선 A/B 계열) |
| **P4** | S3 손상: 챕터 정본 + 게이트 3 | VIU 제약모드 설계문서 확정 | 손상 트랙 착수 준비 완료 |
| **P5** | S5 사례: E2E 3건 + 사례집 + dedup 병합 | 삼성 독립재현 리포트 산출 | practice층 확충·상대가치 PSR |

P1이 첫 순서인 이유: **엔진이 이미 존재해 투자 대비 확실성이 가장 높고**(코드 0줄 신규여도 골든만으로 트랙 승격),
실패해도 얻는 것(설계차이 목록)이 비올/클래시스 패턴으로 검증된 작업 방식이기 때문.

## 7. 리스크·경계

- **저작권**: 유료 칼럼 전문은 어떤 형태로도 공개 레포에 넣지 않는다. 방법론·공식·기준서 조항·공시 수치만 증류. 마스킹 대상에 칼럼 매체·저자 추가(`mask_rules.json`).
- **북 비대화**: 62문서 → 신규 챕터는 **4개 이내**(복합금융 승격 1·FV 1·SBC 1·사례집 1) + 기존 챕터 보강. 문서 수가 아니라 승격된 게이트 수가 성과 지표.
- **사례의 시효성**: 상장사 평가 사례는 2025년 시점 수치 — practice층에 `기준일` 명기, RAG 답변 시 "해당 시점 사례" 프레이밍(frontmatter date).
- **이중 SSOT 방지**: 동일 주제(베타·PGR)는 기존 북 챕터가 SSOT 유지, 코퍼스는 source로 역참조만. 코퍼스→북 방향 단방향.
