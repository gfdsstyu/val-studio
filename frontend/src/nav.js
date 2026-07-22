/** 모드별 네비 정의 — LNB=워크플로우 단계(장), 하단 시트탭=단계 내 시트.
 *  ia_ux_architecture.md §4 매핑표의 코드화. soon=준비중(disabled). */

export const NAV = {
  appraiser: [
    { id: "cover", label: "개요 Cover",
      sheets: [{ id: "summary", label: "상태 요약" }] },
    { id: "materials", label: "0. 자료·Brief", sheets: [
      { id: "files", label: "자료함" },
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
      { id: "model", label: "3표 정합성" },
      { id: "scenario", label: "시나리오" },
      { id: "relative", label: "상대가치" },
    ]},
    { id: "output", label: "5. 산출물", sheets: [
      { id: "report", label: "리포트" },
      { id: "export", label: "xlsx 내보내기·되읽기" },
      { id: "diff", label: "엑셀 왕복 diff" },
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

export function firstAvailable(mode) {
  for (const st of NAV[mode]) {
    const sheet = st.sheets.find((s) => !s.soon);
    if (sheet) return { stage: st.id, sheet: sheet.id };
  }
  return { stage: NAV[mode][0].id, sheet: NAV[mode][0].sheets[0].id };
}
