# Val-Studio 워크북 규약 (자체 시트 아키텍처 — W0 정본)

MSVALUE·xDCF 양식을 **복제하지 않고**, 모델링 기초 지식으로 정제한 자체 아키텍처. 시트명·
레이아웃·색상은 이 문서를 따른다.

---

## 1. 시트 아키텍처 (점진 성장)

처음부터 멀티시트를 찍지 않는다. 각 단계가 자기 시트를 만들며 워크북이 자란다.

| 단계 | 시트 | 역할 |
|------|------|------|
| W0 | `DCF` | 스파인(가정 블록 + 5개년 + 결과), scaffold 생성 |
| W0 | `_VS_STATE` | 상태·가정 대장·매핑 대장(숨김) |
| W1 | `Research` | Company Brief(숫자 셀 + 서사 텍스트) = 리서치 SSOT |
| W2 | `FS_Hist` | `Raw`(원문 불변)/`Normalized`/`Map` 3영역 |
| W3 | `Reclass` | 계정 태깅 + `_A`(실사조정)/`_F`(최종) 레이어 |
| W4 | `Fcst_Rev`·`Fcst_Cost`·`Capex_Dep`·`WC` | 드라이버별 추정 |
| W5 | `WACC` | CAPM 빌드업 |
| W7 | `Scenario` | Up/Base/Down |
| W8 | `Sens` | WACC×PGR 5×5 |

**참조 방향 단방향**: `뒤 시트 → 앞 시트`만(순환 금지). 예: `Fcst_Rev`는 `Research`를 참조하되 역참조 금지.

---

## 2. 색상 규약 (3색 + 강조)

| 색 | 의미 | 예 |
|----|------|-----|
| **Blue** | 직접 입력 hard 값 | 가정값, 원천 데이터 |
| **Black** | 해당 시트 계산 수식 | EBIT=매출−원가−판관비 |
| **Green** | 타 시트 참조 값 | `=Research!C10` |
| **Yellow fill** | 핵심 가정 강조 | WACC·PGR |

**hard number 1곳 규율**: 하드값은 최초 1곳만 입력, 나머지는 참조(soft). 상류 시트가 생기면
DCF 가정 셀(Blue)을 상류 참조 수식(Green)으로 승격 — 교체 전후 per_share 불변을 `roundtrip.py`로 확인.

---

## 3. 수식·서식 규약 (anthropic xlsx 규약 채택)

- **살아있는 수식**: 계산 결과는 하드값이 아니라 수식으로(감사 추적). `scaffold.py`가 이미 이렇게 생성.
- **함수 화이트리스트**: Excel-2007 세대 우선. post-2007(XLOOKUP·FILTER·SORT·LET·LAMBDA)은 호환성 위험 → 피하고, 불가피하면 `_xlfn.` 접두 확인.
- **서식**: 백분율은 fraction으로 저장(0.113, 표시만 %), 0→'-', 음수는 괄호.
- **외부링크 금지**: 타 파일 참조(`[Book2.xlsx]`)는 `#REF!` 위험 → 값으로 붙여넣기.
- **recalc 게이트**: 산출 xlsx는 LibreOffice headless recalc 0에러 확인 후 출고(W8 외곽 셀 검증).

---

## 4. DCF 스파인 레이아웃 (scaffold.py 생성 — 참조용)

`scaffold.py`가 만드는 `DCF` 시트 고정 레이아웃(`roundtrip.py` 왕복 대상):

```
가정 블록:  C3=WACC  C4=g  C5=주식수  C6=비영업자산  C7=순차입부채
연도(C..G): 10=Year 11=매출 12=매출원가 13=매출총이익 14=판관비 15=EBIT
            16=법인세 17=NOPLAT 18=D&A 19=CAPEX 20=ΔNWC 21=FCFF 22=할인기간 23=현가계수 24=PV
결과:       C27=명시적PV합 C28=TerminalFCFF C29=TV C30=TerminalPV C31=EV C32=주식가치 C33=주당가치
메타:       C37=effective_tax_rate C38=terminal_fcff_override C39=terminal_reinvestment_rate
```

이 레이아웃을 임의로 바꾸면 `roundtrip.py` import가 깨진다 — 확장은 build 도구와 함께.

---

## 5. Research 시트 (SSOT)

- **숫자 영역**: 시장 CAGR·목표 점유율·회전일·peer 목록·거시가정 → 셀로 저장(하류 Green 참조 대상).
- **서사 영역**: 사업모델·경쟁구도·원가구조·투자포인트 → 텍스트 블록(판단 맥락).
- Company Brief 10섹션 구조는 `기업리서치_양식.md` 참조. MD Brief는 필요 시 이 시트에서 뽑는 파생뷰(이중 유지 금지).

**레이아웃 참조 양식**(복제 아님·구조 참조): `D:\Valuation\pe양식\`(기업리서치 템플릿·티에스이 실례),
`D:\Valuation\DCF_비올\`. 열람 암호는 파일명 "비번" 뒤 문자열.
