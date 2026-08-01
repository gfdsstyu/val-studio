/** 모드별 네비 정의 — LNB=워크플로우 단계(장), 하단 시트탭=단계 내 시트.
 *  ia_ux_architecture.md §4 매핑표의 코드화. soon=준비중(disabled). */

export const NAV = {
  appraiser: [
    { id: "cover", label: "개요 Cover",
      sheets: [{ id: "summary", label: "상태 요약" }] },
    { id: "materials", label: "0. 자료·Brief", sheets: [
      { id: "files", label: "자료함" },
      { id: "disclosure", label: "공시자료" },
      { id: "brief", label: "Company Brief" },
    ]},
    { id: "mapping", label: "1. 계정분류", sheets: [
      { id: "pl", label: "손익 매핑" },
      { id: "bs", label: "BS 매핑(NOA/IBD)" },
    ]},
    { id: "assumptions", label: "2. 가정", sheets: [
      { id: "macro", label: "거시" },
      { id: "revenue", label: "매출(트리)" },
      { id: "costs", label: "원가·판관비" },
      { id: "fa", label: "FA" },
      { id: "wc", label: "WC" },
    ]},
    { id: "discount", label: "3. 할인율", sheets: [
      { id: "peer", label: "유사회사 4-step" },
      { id: "wacc", label: "WACC 빌드업" },
    ]},
    { id: "valuation", label: "4. 밸류에이션", sheets: [
      { id: "dcf", label: "DCF" },
      { id: "assemble", label: "가정 조립" },
      { id: "model", label: "3표 정합성" },
      { id: "review", label: "분석적 리뷰" },
      { id: "scenario", label: "시나리오" },
      { id: "relative", label: "상대가치" },
    ]},
    { id: "output", label: "5. 산출물", sheets: [
      { id: "report", label: "리포트" },
      { id: "export", label: "xlsx 내보내기·되읽기" },
      { id: "diff", label: "엑셀 왕복 diff" },
      { id: "audit", label: "모델 정적 감사" },
    ]},
  ],
  auditor: [
    { id: "cover", label: "개요",
      sheets: [{ id: "summary", label: "검증 현황" }] },
    { id: "ingest", label: "1. 의견서 인제스트", sheets: [
      { id: "file", label: "의견서 투입" },
      { id: "extracted", label: "추출 가정 확인" },
    ]},
    { id: "recalc", label: "2. 독립 재계산", sheets: [
      { id: "inputs", label: "입력 재구성" },
      { id: "result", label: "재계산 vs 주장" },
    ]},
    { id: "diagnosis", label: "3. 괴리 진단", sheets: [
      { id: "structural", label: "구조버그 가설" },
      { id: "sensitivity", label: "민감도 추적" },
    ]},
    { id: "findings", label: "4. 발견사항", sheets: [
      { id: "list", label: "finding 리스트" },
      { id: "narrative", label: "서사 리포트" },
    ]},
  ],
};

export const MODE_LABEL = { appraiser: "평가인", auditor: "감사인" };

/** Task Pane(?embed=1) 화이트리스트 — 패널은 "작은 Val-Studio"가 아니라 **엑셀 브리지**다.
 *
 *  350px 폭에서 매핑 테이블·매출 트리·리뷰 스파크라인 같은 넓은 시트는 성립하지 않고,
 *  패널 슬롯은 Claude for Excel 과 나눠 써야 한다. 그래서 엑셀 옆에서만 의미 있는 축만
 *  남긴다: ①상태 확인 ②자료 수급(DART — 스킬은 BYOK 키가 없어 이 경로가 유일) ③DCF 검산
 *  ④산출물 검증 루프(getFileAsync 원클릭). 나머지 "스튜디오" 작업은 브라우저 탭에서 한다.
 *  근거: docs/plan/addin_two_panel_ux.md §6-4(패널=루프, 탭=스튜디오).
 *
 *  감사인 트랙은 축약하지 않는다 — 5단계 전부가 검증 성격이라 브리지 정의에 이미 부합.
 */
const EMBED_ALLOW = {
  appraiser: {
    cover: ["summary"],
    materials: ["files", "disclosure"],
    valuation: ["dcf"],
    output: ["export", "diff", "audit"],
  },
  // auditor: 미지정 = 전체 노출
};

/** 모드 + 표시 맥락 → 네비. embed 가 아니면 NAV 원본을 그대로 돌려준다(참조 동일). */
export function navFor(mode, embed = false) {
  const full = NAV[mode];
  const allow = embed ? EMBED_ALLOW[mode] : null;
  if (!allow) return full;
  return full
    .filter((st) => allow[st.id])
    .map((st) => ({ ...st, sheets: st.sheets.filter((sh) => allow[st.id].includes(sh.id)) }))
    .filter((st) => st.sheets.length > 0);
}

/** 축약으로 가려진 시트 수 — 패널에서 "탭에서 이어서" 안내에 쓴다. */
export function hiddenSheetCount(mode) {
  const all = NAV[mode].reduce((n, st) => n + st.sheets.length, 0);
  const shown = navFor(mode, true).reduce((n, st) => n + st.sheets.length, 0);
  return all - shown;
}

export function firstAvailable(mode, embed = false) {
  for (const st of navFor(mode, embed)) {
    const sheet = st.sheets.find((s) => !s.soon);
    if (sheet) return { stage: st.id, sheet: sheet.id };
  }
  const first = navFor(mode, embed)[0] ?? NAV[mode][0];
  return { stage: first.id, sheet: first.sheets[0].id };
}
