# 밸류에이션 북 (Valuation Book) — LLM RAG 지식 코퍼스

**이 폴더는 제품의 핵심 자산이다.** 우리 서비스는 **LLM 중심** — AI가 이 북을 RAG로 먹고
고품질 밸류에이션 답변·분류·추천을 생성한다. **∴ 문서 품질 = AI 답변 품질.**

작성 원칙(RAG 최적화):
1. **도메인 지식 우선** — "우리 대비"가 아니라 "밸류에이션은 이렇게 한다"는 권위 지식으로.
2. **자기완결 청크** — 각 문서/섹션이 독립적으로 검색·인용 가능.
3. **검색용 frontmatter** — `topic/keywords/canonical_questions`(신규 문서부터 적용).
4. 결정론 `calc_core` 엔진은 이 LLM 서비스의 **신뢰 백본**(재현·출처·가드레일).

> 원본(엑셀·PDF·PPT)은 저작권/기밀·스캔이라 레포 미포함. **추출된 방법론·수치·지식만** MD로 보존.

## 지식 챕터
| 문서 | 내용 | 소스 |
|---|---|---|
| [계정분류_모델아키텍처](계정분류_모델아키텍처.md) | ⭐ **계정유형(Sales/COGS/SGA/NO·WC/FA/NOA/IBD/OAL/EQU) + 분석방법 taxonomy** + 28시트 자동화 파이프라인 + LLM 분류 기회 | 타사 매뉴얼+샘플 |
| [외부평가의견서_고정양식_구조](외부평가의견서_고정양식_구조.md) | ⭐ **고정부(섹션·방법론 골격·정형문구) vs 가변부(회사·수치·SOTP·통화)** — 파서 앵커·LLM·의견서 생성 | 외부평가의견서 13건 교차비교 |
| [파서_아키텍처_매트릭스](파서_아키텍처_매트릭스.md) | ⭐ **불러오기 방식(엑셀·PDF·XBRL·DART API) × 자료유형(사업보고서·IR·리서치·의견서)** 2층 구조 + DART PDF 한글 CID→XBRL우선/OCR폴백 | 삼성 XBRL·PDF 실측 |
| 문서 | 내용 | 소스 |
|---|---|---|
| [리포트예시_클래시스](리포트예시_클래시스.md) | ⭐ **2차 리포트 양식 정본** + 비올 peer 6사 + CAPM + 상세 가정(매출트리·원가/판관비 성격별·WC 회전기일·유사회사 4-step) | (참고 모델) 리포트 예시 |
| [peer_dcf_클래시스_솔루엠](peer_dcf_클래시스_솔루엠.md) | 클래시스(비올 동종)·솔루엠 실무 DCF 가정·로직·CAPM | pe양식(복호화) |
| [wacc_할인율서식](wacc_할인율서식.md) | WACC 서식 **셀 수식 논리**(Hamada·규모별세율·베타옵션·빌드업) | 할인율 서식·강의자료 |
| [외부평가의견서_활용](외부평가의견서_활용.md) | DART 공시 의견서 활용(감사인 트랙·report 양식·정형문구+슬롯·방법론 taxonomy) | 외부평가의견서 13건 + dcf공시사례.pptx |
| [참고보고서_활용](참고보고서_활용.md) | 증권사·산업 IR 리포트 → RAG 지식원천·산업 CAGR·컨센서스·provenance | 참고보고서 11건 |
| [감사인검토_WACC방법론](감사인검토_WACC방법론.md) | ⭐ **감사인 트랙 정본**: Modified CAPM·Kroll size premium deciles·kd(BBB-)·WARA↔IRR↔WACC·검토 체크리스트 | 감사인검토 교육 PDF + 회계법인 자료 |
| [합병_주식교환_방법론](합병_주식교환_방법론.md) | 상장=기준주가/비상장=본질가치(자산1:수익1.5), 두산 주식교환비율 사례 | 두산 합병 특강 |
| [모델링_실무_2강4강](모델링_실무_2강4강.md) | 매출 P×Q 사업유형 사전(구독ARPU·웹툰ARPPU)·구분실익·Finalize 연결체크 | 참고 모델 2강/4강 |
| [베타_Bloomberg_vs_KICPA](베타_Bloomberg_vs_KICPA.md) | β 기준시장 선택(S&P500 vs KOSPI)·Adjusted β(0.67/0.33)·CAPM 체계적위험 한계·CSRP·고성장 과대평가 | 회계업계 실무 이슈노트 |
| [영구성장률_PGR_적합성](영구성장률_PGR_적합성.md) | TV 비중 ~75%·한국관행 0~1% vs 글로벌 2~4%(평균3%)·PGR≤GDP 철칙·민감도 | 실무 이슈노트 |
| [검증_클래시스_DCF](검증_클래시스_DCF.md) | ⭐ 2차 실사례 교차검증: EBIT 완전일치, 세금주입·터미널정규화 개선점(A/B), checks.py 위험포착 입증 | pe양식 클래시스 DCF |
| [손상검사_impairment](손상검사_impairment.md) | ⭐ **평가의 다른 목적축**: VIU vs FVLCD·CGU·영업권·손상DCF(내용연수/성능CAPEX제외/synergy제거) | joy-accounting 블로그 |
| [밸류에이션_스코프_로드맵](밸류에이션_스코프_로드맵.md) | ⭐ **전체 스코프 지도**: 거래평가(DCF✅)·손상(VIU)·공정가치(PPA)·복합금융상품(RCPS·TF·이항·OPM) 트랙별 방법론·상태 | 스코프 정리 |
| [복합금융상품_평가](복합금융상품_평가.md) | ⏳ CB·RCPS·BW 옵션평가: 혼합할인율(TF)·이자율모형(BDT/HW)·전환권 자본/부채별·공정가치 Level 3 | 블로그 |
| [PPA_무형자산평가](PPA_무형자산평가.md) | ⏳ 매수가격배분: MEEM(고객관계·CAC)·RFRM(로열티면제)·TAB·WARA | 블로그 |
| [기업리서치_양식](기업리서치_양식.md) | ⭐ **Company Brief 10섹션 정본**(0단계 산출물): 개요·부문매출·제품·ValueChain·경쟁사·시장·peer배수 | pe양식 리서치 예시 2건 |
| [FDD_재무실사_정상화](FDD_재무실사_정상화.md) | 재무실사: QOE(normalized EBITDA)·NWC(peg·pro forma·가격조정)·정상화 | 블로그 |
| [모델링_워크플로우_기초](모델링_워크플로우_기초.md) | ⭐ **업무 프로세스 8단계(RFI→Skeleton→Projection→장표)**·모델 유형 3·엑셀 규율(단방향 참조·hard 1곳·컬러코딩 정본·Sanitizing) | 컨설팅 교육 docx 2편 |
| [DCF_교육_정본](DCF_교육_정본.md) | ⭐ **DCF 이론 백본(도식 Mermaid 재현)**: 3대 접근법·FCFF/FCFE·BS 재분류·재투자 루프·FCFF 산출·WACC(MRP·Hamada·조정베타·size)·TV 정규화·**K-IFRS 1036.35 VIU 5년 상한** | 참고 모델 교육 hardcopy 38p |
| [장표_작성법](장표_작성법.md) | 리포트 산출물 규율: Head/Body·MECE 축·**차트 선택표 8종**(Waterfall·Mekko 등) | 컨설팅 교육 docx |
| [상대가치_계절성_LTM](상대가치_계절성_LTM.md) | ⏳상대가치 트랙 첫 챕터: 분·반기 평가 연환산 왜곡·계절성 peer 제외 원칙·**LTM 보정**·보고서 문구 3종 | polaris 블로그 |
| [MnA_실사_가격구조_SPA](MnA_실사_가격구조_SPA.md) | ⭐ **딜 관점 정본**: 실사 4단계·QoE 조정 사다리·Net Debt/Debt-like·목표운전자본 함정 2종·SPA 7조항·가격조정 3방식+De Minimis/Basket/Cap | M&A ESSENCE(중기부·회계법인 2020) |
| [MnA_구조화_합병규제_세무](MnA_구조화_합병규제_세무.md) | Structuring 4유형·**합병가액 법제(기준시가 ±30%·본질가치 0.4/0.6)**·주식매수청구 가격·적격합병 요건 5·양도세 | M&A ESSENCE |
| [MnA_사례집_유형별_시사점](MnA_사례집_유형별_시사점.md) | 10사례(SPAC·회생·PEF·U-turn 등) 구조·교훈 — 가격조정 75억 실측·SI/FI 가격차 | M&A CASEBOOK(2021) |
| [앤트로픽_금융스킬_벤치마크](앤트로픽_금융스킬_벤치마크.md) | 공식 dcf/lbo/comps·audit-xls 원문 감사 — 채택 규약·DCF 버그 5종·서사 규격 | anthropics/financial-services |
| [모델러스_통합모델_5.4](모델러스_통합모델_5.4.md) | ⭐ **3번째 교차검증 레퍼런스(IB 트레이닝 표준)**: 3표 완전연결·순환스위치·**페이드 스테이지**(명시5+페이드5+Gordon, TV비중 57.8%)·**PGR 인플레 앵커링**·Trading comps(EV브리지·NM/NA·EV vs 지분배수 비대칭)·CHOOSE 시나리오 + **반면교사 6종**(데이터테이블 stale·peer 자기포함·배수 평균·정확일치 CHECK·브리지 불일치) + 반영점 R1~R16 | The Modellers 5.4(COMPLETED).xlsx (Hugel) |

## 온톨로지 + RAG 인덱스
`ontology/` — 북을 자동 컴파일한 개념 그래프·RAG 검색 인덱스(SSOT→컴파일). 재생성:
`python docs/reference/ontology/build.py`. 설계: [ontology/README.md](ontology/README.md).

## 소스 자료 위치 (D:\Valuation\)
- `DCF_비올\` — 메인 벤치마크 비올 (엔진 파일 `DCF Model_최종본.xlsx`, IR, 참고보고서, 유사회사재무)
- `DCF_비올\강의자료\` — 참고 모델 강의(2강 모델링·4강·리포트 예시/템플릿·할인율 서식/강의자료·dcf공시사례.pptx·두산합병 특강)
- `외부평가의견서\` — DART 공시 의견서 13건(스캔 이미지 → **OCR 필요**)
- `pe양식\` — 실무 DCF 템플릿(암호화, 비번=`파일명_비번`, ㅁ→동일위치 영문키)
- `0003-밸류에이션_자료`, `외부평가검토 자료-외부평가검토` — 회계법인 교육자료
- `참고 모델강의자료\` — NOA IBD 참고자료, 한공회 MRP 가이던스, dcf공시사례.pptx
- `모델러스엑셀\` — The Modellers 트레이닝: `5.4(COMPLETED).xlsx`(**Hugel 통합모델 정본** — 14시트 3표연결+DCF+Comps), Excel Practice Materials(EMP), Total Shortcuts Summary

## 핵심 확정 사실 (전 자료 종합)
- **비올 peer 유니버스**(미용 의료기기 6사): 이루다·비올·제이시스메디칼·클래시스·하이로닉·한스바이오메드.
- **비올 동종 마진**: GP% ~77–80%, EBIT% ~51–56% (클래시스 확증).
- **MRP**: 한공회 가이던스(리포트 예시 8%).
- **WACC 방법**: Hamada unlever/relever, 2년 주간 조정베타, 규모별 유효세율(20.9/23.1/27.5%), 목표=유사회사 평균 자본구조.
- **매출추정**: 장비=시장 CAGR(top-down), 소모품=장비 누적연동, 화장품=시장성장률.
- **외부평가**: 비상장 타법인주식양수 = DCF법 기본(11/13), 자산·옵션성 시 보조 병행.

## 추가 확정 사실 (집대성)
- **합병/주식교환**: 상장=자본시장법 기준주가(1M·1W·최근일 산술평균), 비상장=본질가치(자산1:수익1.5). DCF는 수익가치·검토.
- **Size premium**: Kroll(Duff&Phelps) CSRP Deciles 1-10 (0.52%~5.22%+). 소형사 WACC↑ 정량근거.
- **감사인 정합**: WARA ↔ IRR ↔ WACC ±1% reconciliation. Apple-to-Apple(분자·분모 일관성).
- **매출 P×Q 사전**: 구독=고객수×ARPU, 웹툰=결제자×ARPPU, 공간=점포×점포매출, 수주=건수×프로젝트.

## 남은 문서화 (TODO)
- [ ] 회계법인 자료 전문 — CGU·IFRS16·할인율(한글 CID폰트 → OCR 시 보강). 현재 단편만.
- [ ] NOA IBD 구분 참고자료 정밀(스캔 여부 확인).
- [ ] 리포트 템플릿(빈 양식) 셀 구조 → report 슬롯 스키마.
