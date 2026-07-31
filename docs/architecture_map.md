# 아키텍처 맵 (AI-소비용 전수 지도)

> 목적: 세션 시작 시 이 문서 하나로 코드베이스 전체의 정신 모델을 복원한다.
> 생성: 2026-08-01, 전 영역 병렬 탐사(엔진·API·엑셀/인제스트·프론트·스킬/테스트·문서) 결과 합성.
> 사람용 시각화 판은 아티팩트로 별도 존재(브라우저 열람용). 상세 근거 라인번호는 탐사 시점 실측값 — 코드 변경 시 어긋날 수 있으니 grep으로 재확인.

---

## 0. 한 문장 정의

**실무 DCF 엑셀 모델을 셀 단위로 재현하는 순수 결정론 엔진(calc_core)을 코어로, 앞단(공시 수집·주석 추출·가정 도출 = ingest→assemble)과 뒤단(살아있는 수식 xlsx·평가의견서 = excel·report)을 잇고, 웹(React)·Claude 스킬·Excel Task Pane 세 표면에서 소비하는 밸류에이션 워크벤치.**
핵심 사상: **판단은 사람, 계산·검증은 결정론 코드. 게이트는 경고가 아니라 실행 차단**(PGR≥WACC면 DCF를 아예 실행하지 않음).

## 1. 계층 지도

```
[원천] DART OpenAPI · ECOS · FinanceDataReader/pykrx · XBRL · PDF(OCR) · xlsx · 복붙/CSV
   ↓
backend/ingest/   (16모듈) 원천→값. 커넥터 + 파서 + 4종 검증 + provenance      "이 숫자는 어디서 왔나"
   ↓ 게이트 통과분만
backend/assemble/ (4모듈)  원천값→검증된 엔진입력. 커넥터 리포트 fold + 실행순서 게이트  "쓸 수 있는 가정인가"
   ↓
backend/calc_core/ (25모듈, 5,410 LOC, stdlib-only·IO 0) 순수 결정론 계산 + checks(L2 게이트) + analytical(L3)
   ↓
backend/excel/    (12모듈) 살아있는 수식 xlsx 4방향: export ⇄ import ⇄ diff/apply ⇄ 정적감사
backend/report/   language_guard(서사 린터, 렌더러 아님)
backend/rag/      searcher+embedder (북 검색, CLI 전용 — 웹 API 미노출)
   ↓
backend/api/main.py (단일 파일 2,100줄, 59라우트 + StaticFiles) — APIRouter 분리 없음, Pydantic 미사용(raw dict→dataclass 수동 변환)
   ↓
frontend/ (React 18 + Vite, 의존성 단 2개, 라우터·차트 라이브러리 0, 계산 로직 0줄) — 평가인 7stage/21sheet + 감사인 5stage/9sheet
.claude/skills/ 3종 (excel-valuation-workbook=vendored 자기완결 / valuation-analysis=레포 직결 / assumption-audit=SKILL.md 단독)
add-in/ Excel Task Pane manifest 3종 (본체 = 웹앱 ?embed=1)
docs/reference/ 지식층 (챕터 49 + smic 58케이스 + industry 13편 + 온톨로지) → checks.py 규칙으로 승격
tests/ 89파일 (root 71 + golden 4 + skill 13 + xlsx 1), fixtures/ viol·classys 골든
```

**검증 3층**: L1 tie-out(ingest/validators, 라운드트립) → L2 가정 게이트(calc_core/checks.py) → L3 시계열 연속성(calc_core/analytical.py, ISA 520 동형) + 워크북 정적감사(excel/model_audit.py).

## 2. calc_core — 엔진 25모듈

| 모듈 (LOC) | 역할 | 핵심 API |
|---|---|---|
| models.py (109) | 도메인 dataclass(단위=백만원) | `DcfSpineInput`(wacc·terminal_growth·6시계열·브리지 4종·mid_year·tax_override·terminal_* 오버라이드·**fade_years/fade_growth**) · `DcfResult` |
| dcf.py (237) | DCF 스파인(비올 1:1) + R1 페이드 | `run(inp)→DcfResult` · `resolve_fade_growth` · `_expand_fade`(입력확장 방식: 전 라인을 gf로 성장=비율 동결; gf 기본=AVERAGE(마지막 명시 성장률, PGR)) |
| tax.py (57) | 한국 법인세 구간세율(9/19/21/24%×1.1) | `corporate_tax` · `effective_rate` |
| wacc.py (136) | CAPM 빌드업(Hamada+Kroll decile) | `build_wacc(WaccInputs)→WaccResult` · `unlever/relever_beta` · `kroll_size_premium` |
| model.py (89) | E2E 오케스트레이터(가정→스파인) | `ModelConfig` · `build_spine` · `run_model` |
| checks.py (1,719) | **L2 룰엔진 — check_ 함수 29종** (§5) | `audit_dcf` 총괄 · `diagnose_dcf_gap` |
| analytical.py (542) | **L3 분석적 절차**(ISA 520) | `analytical_review` · `impact_ledger`(결함별 Δ주당 원장) · seam/spike/mix/derived/consensus/nwc 6검사 + opm_bridge·mix_decomposition |
| three_statement.py (418) | 3표 완전연결, 순환 3층(average 고정점반복 / opening 1패스 / Circuit-Switch OFF=R14 WARN) | `project_three_statements` |
| revenue.py (194) | 매출: top_down/bottom_up 트리/razor-blades + **아키타입 A~K 11종 라우터** | `bottom_up` · `validate_tree_sums` · `route_archetype` |
| ebit.py (46) / cost_build.py (96) | EBIT 라인 / 성격별 원가 6 method(growth·ratio·headcount·cpi·fa_dep·fixed) | `build_ebit_from_ratios` · `project_costs` |
| fa.py (137) / wc.py (114) | CAPEX 빈티지 상각 / 회전기일→ΔNWC | `project_fixed_assets` · `project_working_capital` · `turnover_days` |
| lease.py (77) | K-IFRS 1116 리스 상각표 | `lease_schedule` |
| scenario.py (80) / sotp.py (85) | 시나리오 가중 / 다개체·다통화 SOTP | `run_scenarios` · `run_sotp` |
| multiples.py (104) / relative.py (43) | 상대가치 PER·PBR·EV/EBITDA·PSR / LTM·계절성 | `relative_valuation` · `ltm` |
| viu.py (127) | IAS 36 사용가치(TV 없는 제약 DCF + 유효세전율 이분탐색 역산) | `compute_viu` |
| convertible.py (197) | CB/RCPS — CRR 격자 + TF 분리할인(콜캡→홀더 max, 풋-우선 캐스케이드 금지) | `price_convertible` · `with_without` |
| backsolve.py (227) | OPM(BSM 워터폴) backsolve + RCPS 이항격자 | `backsolve_equity` · `price_rcps` · `allocate_equity` |
| backlog.py (82) | 수주산업 잔고→매출 전환 | `project_backlog` · `to_spine_lines` |
| merger.py (58) | 자본시장법 합병가액(기준주가·본질가치 1:1.5) | `base_share_price` · `intrinsic_value` |
| method_selector.py (207) | 목적×거래유형×상장 → 기법 결정론 추천 | `recommend_method` · `recommend_by_business_nature` |
| data/industry_benchmarks.json | 산업 분포 prior(SMIC rigor=참고) — `check_metric_vs_industry` 전용 | — |

**DCF `_compute` 순서**: fade 확장 → EBIT → 세금(tax_override > effective_tax_rate > 구간세율) → NOPLAT → FCFF → mid-year PV → 터미널 FCFF(override > from_last_fcff > reinvestment_rate > D&A=CAPEX − terminal_wc_ratio) → TV=FCFF_T/(WACC−g), terminal_discount_period 할인 → EV → 지분=EV+비영업−순차입−NCI → 주당=(지분−희석FV)/주식수×1e6 → 3×3 민감도.

**내부 의존**: tax←dcf←{model,scenario,sotp}; checks→{models,wacc}+지연(relative·analytical); analytical→models+지연 dcf.run. 독립(의존 0): backlog·backsolve·convertible·cost_build·ebit·fa·lease·merger·method_selector·multiples·relative·revenue·tax·viu·wc.
**⚠️ 유일한 외부의존**: calc_core.{checks,analytical} → ingest.validators (Finding 타입 공유).

## 3. assemble — 게이트 fold 계층 (4모듈)

- `wacc_inputs.py` — 커넥터 3종(price/macro/manual_paste)→`WaccAssembly`. 필수값(rf/mrp/βu/Kd) 결측 FAIL=조립 차단. 복붙 문자열은 `paste_risk_free/paste_mrp`로 range 게이트 통과.
- `dcf_inputs.py` — **실행 순서 강제**: WACC fold → 실행 전 게이트(PGR≥WACC FAIL이면 `dcf_run` 미호출, blocked·result=None) → build_spine→run → 실행 후 게이트(TV비중·WC burn·YoY) → report.ok일 때만 result 채택.
- `history_inputs.py` — DART 응답→`FinancialHistory`(L3 입력). "있는 것만" 원칙(부분 시계열 금지, 매출 무매칭 연도 제외).

## 4. ingest — 16모듈

**공통 백본**: `parsers/base.py`(BaseParser.emit: raw→parse_number→ProvenancedValue) · `validators.py`(4종 게이트: ①parse_number 괄호음수·△·%·단위→백만원 ②classify_cell VALUE/ZERO/BLANK/DASH/MISSING ③reconcile_sum ④tie_out; ValidationReport.ok=FAIL 0) · `provenance.py`(SourceKind·ExtractMethod·Locator·char_span 불변식 `source[start:end]==raw_text`·merge_confidence=약한고리 최소값).

**파서**: `xbrl.py`(fact⋈context, 연결/별도·세그먼트, 한글라벨) · `pdf.py`(pdftotext -layout→garble 감지→숫자 우측끝 클러스터링 표 복원+LLM용 text_chunks) · `ocr.py`(Tesseract 폴백, smart_extract) · `xlsx.py`(**openpyxl 유일 사용처**, msoffcrypto 복호화+파일명 두벌식 자모 비번 자동복원 ㅁ→a) · `footnote_extractor.py`((주N) 위치규칙 POINTER/DEFINITION) · `router.py`(방식×유형 자동 라우팅→프로파일 적용).

**커넥터**: `dart_client.py`(재무제표·직원현황) · `dart_corp.py`(corpCode 인덱스·공시목록·원문 zip) · `dart_reports.py`(개황·감사의견/KAM·주식총수 발행vs유통 D7·최대주주·타법인출자 NOA·배당) · `dart_employee.py`(headcount 드라이버+급여 tie-out) · `macro_client.py`(ECOS + EIU 복붙 + **vintage 이중가드**: 기준일 후 실적/개정치 FAIL·staleness 180d WARN; `suggest_pgr_from_inflation` PGR 앵커) · `price_client.py`(FDR/pykrx, β 회귀 look-ahead 절단, 조정β=0.67raw+0.33) · `manual_paste.py`(**복붙 1급 경로**, confidence 0.9, range sanity: β 0~3/rate 0~30%/MRP 2~15%, Kd 등급×만기 매트릭스) · `damodaran.py`(CRP **정적 내장** vintage 2024-07) · `peer_selection.py`(4-step 퍼널, Step2만 LLM 판단·사유 필수) · `fs_mapper.py`(계정→버킷: 1단 taxonomy_store 표준요소명→2단 키워드 첫매칭 승리, 무매칭=uncertain·판단계정=judgment) · `taxonomy_store.py` · `ksic.py` · `footnote_costs.py`(성격별 비용+드라이버 제안).

**profiles/ = 문서 유형별**(산업별 아님): `business_report.py`(XBRL→핵심 10계정) · `opinion_template.py`(의견서 앵커 추출 — CID 깨져도 생존) · `research_brief.py`(Brief ②④⑩ 프리필).

## 5. 게이트 인벤토리 (checks.py 29종 + 분산 게이트)

**터미널·DCF**: pgr_vs_wacc(**FAIL 차단**·스프레드<1%p WARN) · pgr_vs_gdp(>2% WARN) · terminal_reinvestment(**F1**) · terminal_from_last_fcff(CAPEX<D&A WARN) · tv_weight(>75% WARN — 공식스킬 기준 채택) · pgr_provenance(**R2**) · terminal_discount_convention(**R15**, 대안영향 동봉) · dcf_gap_diagnosis(구조버그 가설 5종: 기말할인·TV미할인·TV누락·NOA누락·순부채미차감)
**시계열**: projection_smoothness(|YoY|>50%) · working_capital_burn(흑자도산)
**WACC**: beta_provenance(**F3**) · beta_mrp_consistency(**F3**) · wara_irr_wacc(PPA ±1%p) · Kroll size 룩업 provenance(**F2**)
**브리지**: cross_method_bridge + cross_method_shares(**R3**·**D7** 발행vs유통) · bridge_consistency
**3표**: ts_opening/balance/cash_tie/re_rollforward(전부 FAIL) · ts_circularity(**R14** OFF=WARN·미수렴=FAIL) · ts_vs_spine(FAIL — 대차가 D&A 오류를 흡수하는 맹점 보완) · fcff_vs_cashflow
**복합금융(S1)**: cb_distress · cb_offset_effect · cb_decomposition
**공정가치(S2)**: backsolve_anchor(Arm's Length+180d staleness) · fv_hierarchy · day_one_difference · market_price_eligibility
**SBC·희석(S4)**: dilution_bridge(TSM 한계) · sbc_treatment(valuation/viu 분기)
**계속기업·FCFE(S5)**: going_concern 4종(OCF 역설·유동비율·ICR·Debt/EBITDA≥8) · fcfe_discount_rate(**FAIL**: FCFE를 WACC로) · fcfe 4종
**VIU(S3)**: viu_discount_rate(gross-up 금지) · viu_cashflow_scope · impairment_trigger
**상대가치**: peer_seasonality(최대분기≥40% 연환산 금지) · 5-10 Rule
**산업 prior**: {opm|dso|dio|capex_sales}_vs_industry(p25~p75 PASS / min~max WARN / 밖 이상치; 단일 로더 mtime 무효화+결정론 매칭 — 세 표면 drift 해소 이력)
**ingest 층**: 4종 tie-out · vintage 이중가드 · 복붙 range sanity · footnote tie-out
**excel 층**: formula_pattern_lint(E-6·E-10) · hardcode_scan(T164 `*32`) · check_sensitivity_center(E-9) · workbook_diff 4버킷·row_uniformity · CHECK_TOL=0.001(D1 정확일치 함정) · promote per_share 불변 tie-out · vs_state 미승인 가정 게이트
**L3**: ratio_seam(±3%p) · spike_revert · mix_reconciliation(0.5%p) · derived_continuity(±10%) · consensus_anchor(±5%p) · nwc_growth_consistency — 전부 WARN-only, execution/judgment 층위 태깅
**report**: 표현 린트 5종(단정·순환·상투어·뭉뚱그림·허위정밀) — 전부 WARN

**룰 ID 계보**: R1~R16=모델러스 5.4 / D1~D7=모델러스 결함 / E·J=비올 리뷰노트 / F1~F3=지식→규칙 승격 / S1~S5=칼럼 코퍼스 승격(게이트 16종) / 공식 Anthropic 금융스킬에서 이식(TV 75%·5-10 Rule·audit-xls 버그 5종→diagnose_dcf_gap·변동분석 서사규격→린트).

## 6. API — main.py 단일 파일 59라우트

CORS=Vite dev 전용. 전역 BadZipFile→422. 응답·요청 전부 수제 dict(Pydantic 0).

| 그룹 | 라우트 | 백엔드 |
|---|---|---|
| 헬스·데모 | GET /api/health · GET /api/demo/cases(viol·classys 픽스처 직접, **키 없는 방문자 진입점**) | fixtures/ |
| DCF·시나리오 | POST /api/dcf(+claimed_per_share→gap_diagnosis, pgr_source/basis) · POST /api/scenario | calc_core.run·scenario |
| 어셈블리 | POST /api/wacc/assemble · POST /api/dcf/assemble · POST /api/three-statement | assemble.* · three_statement |
| 가정 상류 | POST /api/revenue/build · /api/assumptions/build(ebit·fa·wc) · /api/assumptions/costs-build · /api/assumptions/lease · /api/footnote/costs · /api/backlog · /api/fs/classify · /api/brief/from_xbrl | calc_core·ingest |
| xlsx 4방향 | POST /api/xlsx/export·import·diff(project_id 기준선 재생성)·audit · POST /api/upload/sheet | excel.* |
| DART 11종 | validate·financials·employee·corp-search(서버 캐시 var/dart_corpcode.json)·filings·document(zip)·company·audit-opinion·shares(D7)·investments·dividends | ingest.dart_* |
| 시세·거시 | POST /api/price/beta·marketcap·fx·multiples(pykrx 503 폴백) · POST /api/macro/series·pgr-suggest · GET /api/damodaran/crp(정적) · GET /api/ksic/search · GET /api/benchmarks/industry | ingest.* |
| 기법·peer·상대 | POST /api/method/recommend · GET /api/method/options · POST /api/method/recommend-legal · POST /api/peer/select(Step2 무근거 422) · POST /api/relative/value · POST /api/bridge/check | method_selector·peer_selection·multiples·checks |
| VIU·RCPS | POST /api/viu · POST /api/rcps | viu·backsolve |
| 감사인 | POST /api/opinion/extract(poppler pdftotext) · POST /api/report/lint | opinion_template·language_guard |
| L3 리뷰 | POST /api/review/analytical(dart_years→history_from_dart 서버 어셈블) · POST /api/review/ledger | analytical |
| 프로젝트 | GET/POST /api/projects · GET/PATCH/DELETE /api/projects/{12hex}(mode 불변·구용어 마이그레이션) | project_store |
| 키 검증 | POST /api/keys/validate(Gemini) · POST /api/dart/validate | 외부 1회 조회 |
| 정적 서빙 | `app.mount("/", StaticFiles(frontend/dist, html=True))` — 파일 최말미, 단일 컨테이너 동일 오리진 | — |

**BYOK**: DART/ECOS/Gemini 키는 요청별 헤더(X-Dart-Key·X-Ecos-Key·X-Gemini-Key)로만 통과, 서버 저장·로깅 0, 서버 시크릿 0개 설계. localStorage(byok_* 4종, Anthropic 키는 UI만 있고 미배선).
**영속화**: `project_store.py` — PROJECTS_GCS_BUCKET 설정 시 GCS SSOT(메타데이터 서버 토큰+JSON API, stdlib), 미설정 시 var/projects/{id}.json 휘발(Cloud Run 인메모리).

## 7. 외부 연동 전량

| 대상 | 인증 | 데이터 | 위치 |
|---|---|---|---|
| OpenDART (10개 엔드포인트) | X-Dart-Key(BYOK) | FS·직원·개황·공시·zip·주식총수·최대주주·출자·배당 | ingest/dart_* |
| 한국은행 ECOS | X-Ecos-Key(BYOK) | GDP·CPI·국고채10y·기준금리·환율 | macro_client |
| Google Gemini | X-Gemini-Key(검증) / GEMINI_API_KEY env(임베딩) | 키검증 + gemini-embedding-001 768d(RAG, CLI 전용) | main.py·rag/embedder |
| FinanceDataReader / pykrx | 무키 | 주가·β·시총·FX / PER·PBR 등 | price_client |
| GCS + 메타데이터 서버 | Cloud Run SA | 프로젝트 JSON | project_store |
| Damodaran CRP | 없음(정적 내장 2024-07) | 국가위험프리미엄 | damodaran.py |

LLM 호출은 Gemini뿐. Bloomberg β·한공회 MRP·KOFIABOND Kd는 **복붙 1급 경로**(manual_paste)로 대체(외부 API 봉쇄 대응).

## 8. 프론트 — React 18, 계산 0줄

- 의존성 react+react-dom 뿐. 라우팅=App.jsx 자체 상태(Home↔Workspace). nav.js가 모드별 stage×sheet 2축 SSOT. `?embed=1`=Excel Task Pane 모드.
- **평가인 7stage/21sheet**: cover(Dashboard) → materials(files·disclosure·brief) → mapping(pl·bs) → assumptions(macro·revenue·costs·fa·wc) → discount(peer·wacc) → valuation(dcf·assemble·model·review·scenario·relative) → output(report·export·diff·audit). 보조: MethodWizard·IndustryProfileCard.
- **감사인 5stage/9sheet**: cover(CoverSheet) → ingest(OpinionIngest) → recalc(IndependentRecalc — 같은 /api/dcf, audit_* 키로 데이터 격리) → diagnosis(GapDiagnosis — API 0, 저장본 소비) → findings(Findings+LintPanel).
- 모드는 생성 시 1회 확정·변경 불가(감사인 독립성). ReportSheet는 API 0(클라 순수 조합).
- **데이터 릴레이**: project.data 키 축적 — revenue_built→costs_built→fa_built/wc_built→wacc_result→dcf_input→scenario/review/export. ContextPanel이 wacc_provenance+4종 findings 집약.
- "PastePanel"이라는 단일 컴포넌트는 없음 — 복붙은 DiscountSheet(Rf·MRP·Kd 매트릭스)·MacroSheet(시계열)·CostsSheet(주석 표)·RelativeSheet(peer 배수)·OpinionIngest(의견서)에 분산. 원칙: 클라 파싱 없이 원문 문자열→서버 커넥터→range 게이트.
- 차트 전부 수제(CSS 막대·SVG Sparkline·CSS 밴드·HTML 민감도표). 미사용 예비 배선: /api/price/marketcap·fx.
- 컴포넌트→API 전수 매핑은 아티팩트/프론트 탐사 보고 참조.

## 9. excel — 4방향 인터페이스 (12모듈)

**openpyxl로 생성하지 않는다** — 자체 stdlib 라이터(zipfile+XML, 수식 `<f>`+캐시 `<v>`). openpyxl은 ingest/parsers/xlsx.py(읽기)뿐.

- `template_schema.py` = **셀 레이아웃 SSOT**(YEAR_COLS C..G, ASSUMP C3~C8, ROW 10~24, RESULT C27~C33, META C37~C39, CHECK_TOL=0.001). export/import/민감도/스킬 전부 이 파일 소비.
- 방향①생성: dcf_export.build_dcf_sheet(계단식 법인세 수식·TV 수식·브리지) + 스킬 scaffold/stage_sheets(W0~W6b 시트) + sensitivity_grid(5×5 셀마다 closed-form DCF 수식, 터미널 4갈래 미러) + scenario_sheet(SUMPRODUCT+CHOOSE 스위치).
- 방향②되읽기: dcf_import(tax_override 복원·NCI 호환) + vs_state.parse_vs_state(`_VS_STATE` 가정 대장 5열·미승인 게이트).
- 방향③diff·반영: workbook_diff 4버킷(입력/수식/구조/상태) → apply_policy.build_apply_plan(auto_apply/review_queue/blocked/state).
- 방향④정적감사: model_audit(formula_pattern_lint·hardcode_scan·sensitivity_center·audit_workbook) — 비올 리뷰 결함 귀납.
- **fade는 엔진 전용**: xlsx에 페이드 연도 열이 찍히지 않고 캐시된 terminal_fcff·결과 블록에만 반영. 3표 Excel 표현은 스킬 stage_sheets.build_model_3s(Circuit Switch 셀 C5). 셀 DAG는 자료구조가 아니라 규약(SKILL.md)+diff/audit이 집행.
- add-in/: manifest 3종(prod/dev/staging)만, 본체=웹앱 embed. Permissions ReadDocument(MVP L1).

## 10. 스킬 3종 — 결합 방식이 전부 다름

| 스킬 | 결합 | 요지 |
|---|---|---|
| excel-valuation-workbook | **vendored 자기완결**(_bootstrap.py→scripts/vendor/) | W0~W9 워크플로우, 도구 17종(scaffold·fs_clean·footnote_costs·fs_disagg·reclass·peer·wacc·dcf·promote·roundtrip·scenario·sensitivity·audit·lint_report·book_search·stage_sheets). vendor=calc_core 25 전체+excel 12 전체+ingest 선별(네트워크 커넥터 의도적 배제)+rag+reference 50편. `scripts/build_excel_skill.py`가 SSOT(SHA256+파일집합 매니페스트), vendor는 gitignore된 빌드 산출물 — tests/skill/conftest.py가 stale 시 자동 재빌드. dist/zip=Claude for Excel 배포용 |
| valuation-analysis | **레포 backend 직접 import**(_find_backend) | 리서치→인제스트→분류→가정→DCF→리포트 + 감사인 트랙. 도구 9종(brief·ingest·ksic·peer·wacc·dcf·audit·book_search). 지식=docs/reference 직접 Read |
| assumption-audit | **SKILL.md 단독**(자체 코드 0) | 남의 리포트/모델 가정 감사: 원장화→아키타입 분류→assumption_check.py 검산→산업 이상치→브리지→감사스캔 리포트 |

공통: 세 스킬 모두 HTTP API를 호출하지 않음(로컬 결정론 실행). "암산·추정 금지, 숫자는 scripts/로" 규약.

## 11. 지식층 → 규칙 승격 체인

- docs/reference/ 루트 = 공개 가능 증류 지식 49챕터(타이폴로지 6종·기법선택 로직·벤치마크 집계 5종·검증 문서·가정원장 방법론). smic/(58케이스+_fulltext 182+_extract 582+_ledger YAML)·industry/(13편+_fulltext 26+_extract 28)는 **gitignore 비공개**(3층: _fulltext=사료 / _extract=기계 추출 / 루트 md=증류).
- 온톨로지: docs/reference/ontology/ — build.py가 md frontmatter에서 rag_index.json(49챕터)·graph.json(엣지 228·개념 670)·CONCEPTS.md 자동 컴파일(직접 편집 금지). rag/searcher가 소비(canonical_questions bigram > 키워드 > topic > 그래프 1-hop 40%).
- **동기화 체인**: smic 케이스 md 수정 → .githooks/pre-commit → 빌드 스크립트 7종(build_segment_map→벤치마크 4종→산업프로파일→export_benchmarks_json) → 공개 MD + calc_core/data/industry_benchmarks.json 재생성·동반 커밋 → build_excel_skill.py로 스킬 vendoring.
- **rigor 2단**: 권위 골든(비올·클래시스·모델러스)=FAIL/WARN 규칙 승격 가능 / 학회리포트(SMIC)=분포 prior(WARN 참고)만.
- 매출 아키타입 A~K 11종(모든 매출=P×Q, Q를 뭘로): A 전방Capex연동 / B 전방생산량 / C 직접P×Q / D ARPU×유저 / E 점유율침투 / F 수주잔고 / G TAM탑다운 / H 구독ARR / I 캐파가동률 / J Take rate / K 규제요금.
- 공개원칙 3중 방어: .gitignore(코퍼스 원문 제외) + scripts/mask_names.py(fail-closed 마스킹, 규칙표는 로컬 전용) + public-main 브랜치.

## 12. 골든·테스트

| 골든 | 수치 | 검증 대상 |
|---|---|---|
| 비올(1차) | 주당 **8,413.380552원** rel_tol 1e-9 | 순수 스파인 셀단위(fixtures/viol) |
| 클래시스(2·3차) | 주당 **40,600원** ±5원 | tax_override+terminal_fcff_override(WACC 6.24%≈g 5% 폭발 정규화) |
| 모델러스 Hugel 5.4 | 주당 **144,000원**, TV비중 57.8% | 페이드 3단(명시5+페이드5+Gordon), 상수 인라인 |
| TF 워크북 3종 | 채록 상수 | CB 콜캡/풋 캐스케이드 교정 |
| E2E(scripts/) | 삼성(DART 라이브→간이 DCF) · 알테오젠(PSR 75,000~95,000) | 커넥터 실전 |

tests/ 89파일: root 71(엔진·API TestClient·인제스트·커넥터 mock·excel·인프라 — conftest가 skill vendor 오염 purge) + golden 4(stdlib 단독 실행 가능) + skill 13(vendored 사본 검증, test_skill_dcf_golden=격리 재현) + xlsx 1. `test_frontend_wiring`=죽은 참조 탐지, `test_benchmarks_shared`=3표면 단일 정본, `test_vendor_sync`=드리프트 6종.

## 13. 배포

- Dockerfile 2-stage: node:20 빌드(dist) → python:3.12-slim + poppler-utils + requirements → backend/ + dist + **fixtures/**(데모용 COPY 필수) 복사, 비root, PORT=8080, keep-alive 75s(>Cloud Run LB 60s).
- Cloud Run: `gcloud run deploy val-studio --source . --region asia-northeast3 --allow-unauthenticated --memory 1Gi`. cloudbuild.yaml/GH Actions 없음(deploy.md 수동/GitHub 연동 Cloud Build). 라이브: val-studio-789315789234.asia-northeast3.run.app.
- 브랜치: main(기본) / feat/excel-valuation-skill(작업) / public-main(공개 스냅샷). origin=gfdsstyu/val-studio.
- env: PORT(주입)·PROJECTS_GCS_BUCKET(영속화)·GEMINI_API_KEY(RAG CLI만). .env의 DART_API_KEY는 로컬 e2e 스크립트 전용 — 서버는 안 읽음.

## 14. 알려진 미해결·주의 지점

- 프로젝트 저장 비영속(GCS 버킷 미설정 시), corpCode 캐시 휘발.
- Anthropic 키 UI만 존재(미배선). /api/price/marketcap·fx 예비 배선(프론트 미소비).
- 벤치마크 prior n≥3 산업이 7개뿐(저신뢰 라벨로 표면화).
- 로드맵 잔여: NAV 순자산법·PPA/WARA · 감사인 트랙 심화(ISA 540) · RAG 고도화(웹 미노출) · Supabase/멀티유저.
- main.py 단일 2,100줄(라우터 분리 없음) — 확장 시 분리 후보. calc_core→ingest.validators 역참조 2건은 의도된 예외.

## 15. "어디를 보면 되나" 빠른 색인

| 궁금한 것 | 파일 |
|---|---|
| DCF 계산 순서·페이드 | backend/calc_core/dcf.py |
| 게이트 전체 | backend/calc_core/checks.py (+ §5 이 문서) |
| 실행 차단 로직 | backend/assemble/dcf_inputs.py |
| 셀 레이아웃 | backend/excel/template_schema.py |
| API 전체 | backend/api/main.py (단일 파일) |
| 화면·시트 구조 | frontend/src/nav.js + App.jsx |
| 시트별 API 소비 | frontend/src/pages/appraiser/*.jsx |
| 스킬 워크플로우 | .claude/skills/excel-valuation-workbook/SKILL.md |
| vendoring | scripts/build_excel_skill.py |
| 지식→규칙 승격 | docs/engine_spec.md §6-B + .githooks/pre-commit |
| 공개원칙 | .gitignore 주석 + scripts/mask_names.py |
| 골든 수치 | tests/golden/ + fixtures/ |
