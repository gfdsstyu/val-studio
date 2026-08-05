/** 로컬 API 헬퍼 — BYOK 키는 호출별 헤더로만 전달(서버 미저장). */

async function j(method, url, body, headers = {}) {
  const r = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json", ...headers } : headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (r.status === 204) return null;
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw httpError(r.status, d.detail);
  return d;
}

/** HTTP 오류 → status 를 실은 Error.
 *
 * 호출부가 상태를 알아야 분기할 수 있는데(404=사라짐 vs 5xx=서버 장애), 메시지 문자열로
 * 판별하면 서버 문구가 바뀌는 순간 조용히 오작동한다("프로젝트 없음"에 '404'가 없다).
 */
function httpError(status, detail) {
  const e = new Error(detail || `HTTP ${status}`);
  e.status = status;
  return e;
}

/** 바이너리 응답(zip 등) 헬퍼 — 오류 본문은 JSON detail 로 파싱해 던진다. */
async function blob(method, url, body, headers = {}) {
  const r = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json", ...headers } : headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw httpError(r.status, d.detail);
  }
  return r.blob();
}

export const api = {
  health: () => j("GET", "/api/health"),
  dcf: (body) => j("POST", "/api/dcf", body),
  scenario: (body) => j("POST", "/api/scenario", body),
  // 감사인 범위추정(기준서 540 문단 28~29): base 입력 + 가정별 구간(양끝 근거 필수)
  // → 주당가치 범위 + 주장값 판정·최소 조정액. 근거 없는 구간은 서버가 계산을 차단.
  rangeEstimate: (body) => j("POST", "/api/range-estimate", body),
  // 어셈블리: 커넥터 원천값(복붙 문자열 or 숫자) → 검증된 WACC/DCF.
  // 복붙 문자열(예 "3.45%")은 서버가 커넥터로 통과시켜 range 게이트를 건다.
  wacc: { assemble: (body) => j("POST", "/api/wacc/assemble", body) },
  dcfAssemble: (body) => j("POST", "/api/dcf/assemble", body),
  revenueBuild: (body) => j("POST", "/api/revenue/build", body),
  peerSelect: (body) => j("POST", "/api/peer/select", body),
  // Step2(사업유사성) 판정 **초안** — 4-step 중 판단이 필요한 한 스텝만 모델이 채운다.
  // 산출물은 판정 표를 채울 뿐 퍼널로 바로 흐르지 않는다: 확정·실행은 사람이 별도로
  // peerSelect 를 눌러서 한다(제안 → 판단 → 검증). 사유 없는 판정은 서버가 버린다.
  peerJudge: (key, body) => j("POST", "/api/peer/judge", body, { "X-Anthropic-Key": key }),
  // 사업 설명 프리필 — Step2 판정의 근거를 상장사 인덱스의 **주요 제품**에서 채운다.
  // DART 키 불필요(FDR 2콜 로컬 인덱스). 못 찾은 종목은 채우지 않고 warnings 로 온다.
  peerPrefill: (body) => j("POST", "/api/peer/prefill", body),
  // 워크북 공유 원장(`_VS_FACTS`) append 계획 — 클라가 읽은 격자를 서버가 fold 해서
  // **바뀐 것만** 새 행으로 돌려준다(같은 값 재기록은 멱등하게 건너뜀).
  factsAppendPlan: (body) => j("POST", "/api/facts/append-plan", body),
  // 선택 가능한 판정 모델 — 어댑터가 구현된 것만 온다(고를 수 있는데 실패 = 금지).
  agentModels: () => j("GET", "/api/agent/models"),
  // 전환사채 — T-F 격자 + with-without 분해 + S1 게이트(분해 정합·신용악화·상쇄효과).
  // 엔진은 TF 워크북 골든까지 검증돼 있었는데 화면이 없어 노출되지 않던 능력이다.
  convertible: (body) => j("POST", "/api/convertible", body),
  // 기업 스크리너 — peer 모집단 탐색. DART 키 불필요(FDR 2콜로 만든 로컬 인덱스).
  // 검색은 명칭·종목코드·업종·**주요 제품**을 함께 훑는다(같은 업종코드라도 제품이
  // 다르면 유사회사가 아니다). 시가총액은 시변이라 응답의 as_of·stale 을 확인할 것.
  screener: (body) => j("POST", "/api/screener", body),
  screenerRefresh: () => j("POST", "/api/screener/refresh", {}),
  ksicSearch: (q) => j("GET", `/api/ksic/search?q=${encodeURIComponent(q)}`),
  // 산업 벤치마크 분포(OPM·DSO·DIO·CAPEX, p25/p50/p75) — IndustryProfileCard·감사 스킬용.
  benchmarksIndustry: (name) => j("GET", `/api/benchmarks/industry?name=${encodeURIComponent(name)}`),
  // 사업 성격 플래그 → 기법 추천(밸류에이션_기법선택_로직.md). MethodWizard용.
  methodRecommend: (flags) => j("POST", "/api/method/recommend", flags),
  assumptionsBuild: (body) => j("POST", "/api/assumptions/build", body),
  assumptionsBuildCosts: (body) => j("POST", "/api/assumptions/costs-build", body),
  assumptionsLease: (body) => j("POST", "/api/assumptions/lease", body),
  // 성격별 원가 주석표 → 추출(charspan)+드라이버 제안+tie-out+CostLine 초안. 추출=결정론.
  footnoteCosts: (body) => j("POST", "/api/footnote/costs", body),
  fsClassify: (body) => j("POST", "/api/fs/classify", body),
  briefFromXbrl: (body) => j("POST", "/api/brief/from_xbrl", body),
  validateGeminiKey: (key) =>
    j("POST", "/api/keys/validate", undefined, { "X-Gemini-Key": key }),
  validateDartKey: (key) =>
    j("POST", "/api/dart/validate", undefined, { "X-Dart-Key": key }),
  dartFinancials: (key, body) =>
    j("POST", "/api/dart/financials", body, { "X-Dart-Key": key }),
  // 다년도 공시 재무제표 — BS/IS/CIS/CF 를 공시 표시순서·계층 그대로, 요청 연도를 열로.
  // 응답에 3표 항등식 판정(checks)과 H_FS 2시트 배치도(sheet_plan)가 함께 온다.
  // 연도당 API 1콜이므로 범위를 넓히면 그만큼 쿼터를 쓴다(서버가 10개년으로 상한).
  dartFinancialsMulti: (key, body) =>
    j("POST", "/api/dart/financials/multi", body, { "X-Dart-Key": key }),
  // 같은 입력 → rFS + H_FS 2시트 .xlsx(수식 살아있음). Task Pane 이 아닌 브라우저에서
  // 다년도 3표를 한 번에 받는 경로 — 제표별로 하나씩 복사하지 않아도 된다.
  dartFinancialsXlsx: (key, body) =>
    blob("POST", "/api/dart/financials/xlsx", body, { "X-Dart-Key": key }),
  // 고른 corp_code 가 실제 '공시 주체'인지 확정 — 개황 + 정기공시 실적.
  // 동명 후보 중 사업보고서를 안 내는 쪽을 고르면 이후 조회가 전부 빈손이 되는데,
  // 화면에는 '결과 없음'으로만 보여 원인을 알 수 없다.
  dartCompanyCheck: (key, body) =>
    j("POST", "/api/dart/company-check", body, { "X-Dart-Key": key }),
  dartCorpSearch: (key, q, listedOnly) =>
    j("POST", "/api/dart/corp-search", { q, listed_only: !!listedOnly }, { "X-Dart-Key": key }),
  dartFilings: (key, body) =>
    j("POST", "/api/dart/filings", body, { "X-Dart-Key": key }),
  // 공시 원본 zip(document.xml) — JSON 이 아니라 바이너리라 blob 헬퍼로 받는다.
  dartDocument: (key, body) =>
    blob("POST", "/api/dart/document", body, { "X-Dart-Key": key }),
  // 원본 zip → 재무제표 본표 + **주석 전문** + 계정↔주석번호 매핑 + 같은 항등식 checks.
  // OpenDART 에 주석 API 가 없어 fnlttSinglAcntAll 로는 못 얻는 정보다.
  dartDocumentParse: (key, body) =>
    j("POST", "/api/dart/document/parse", body, { "X-Dart-Key": key }),
  // 두 보고서의 주석 연도 간 대조 — 당해의 '전기' 열 ↔ 직전의 '당기' 열.
  // 주석은 XBRL 로 안 나와 다년도 API 대조가 불가능하므로 원문 zip 2개가 유일한 경로다
  // (접수번호당 zip 1개를 내려받는다 — 비용을 화면에 알릴 것).
  dartDocumentCompare: (key, body) =>
    j("POST", "/api/dart/document/compare", body, { "X-Dart-Key": key }),
  // 정기보고서 주요정보 5종 — 재무 숫자 밖의 구조·귀속 정보.
  dartCompany: (key, body) =>
    j("POST", "/api/dart/company", body, { "X-Dart-Key": key }),
  dartAuditOpinion: (key, body) =>
    j("POST", "/api/dart/audit-opinion", body, { "X-Dart-Key": key }),
  dartShares: (key, body) =>
    j("POST", "/api/dart/shares", body, { "X-Dart-Key": key }),
  dartInvestments: (key, body) =>
    j("POST", "/api/dart/investments", body, { "X-Dart-Key": key }),
  dartDividends: (key, body) =>
    j("POST", "/api/dart/dividends", body, { "X-Dart-Key": key }),
  // 직원현황 → 인원·인당급여 집계 + headcount CostLine(노무비 드라이버 실측 시드).
  dartEmployee: (key, body) =>
    j("POST", "/api/dart/employee", body, { "X-Dart-Key": key }),
  priceBeta: (body) => j("POST", "/api/price/beta", body),
  priceMarketcap: (body) => j("POST", "/api/price/marketcap", body),
  priceFx: (body) => j("POST", "/api/price/fx", body),
  uploadSheet: (body) => j("POST", "/api/upload/sheet", body),
  damodaranCrp: (country) => j("GET", `/api/damodaran/crp${country ? `?country=${encodeURIComponent(country)}` : ""}`),
  relativeValue: (body) => j("POST", "/api/relative/value", body),
  backlog: (body) => j("POST", "/api/backlog", body),
  briefFromXbrl: (body) => j("POST", "/api/brief/from_xbrl", body),
  bridgeCheck: (body) => j("POST", "/api/bridge/check", body),
  pgrSuggest: (body) => j("POST", "/api/macro/pgr-suggest", body),
  threeStatement: (body) => j("POST", "/api/three-statement", body),
  // 감사인 트랙: 외부평가의견서 → 유의적 가정 후보(고정양식 앵커, 확정은 감사인).
  opinionExtract: (body) => j("POST", "/api/opinion/extract", body),
  // 거시 시계열: 복붙(항상) 또는 ECOS(키 있을 때). base_date 주면 look-ahead 가드.
  macroSeries: (body, ecosKey) =>
    j("POST", "/api/macro/series", body, ecosKey ? { "X-Ecos-Key": ecosKey } : {}),
  // 서사 표현 가드: 단정·순환설명·무설명·뭉뚱그리기 + 필수 슬롯 공란(전부 WARN).
  reportLint: (body) => j("POST", "/api/report/lint", body),
  // L3 분석적 절차(ISA 520 동형): 실적(DART)×추정 탑다운 검사 + 결함 영향 분리 원장.
  review: {
    analytical: (body) => j("POST", "/api/review/analytical", body),
    ledger: (body) => j("POST", "/api/review/ledger", body),
    // 추정치 간 교차 일관성(540 문단 24(c)) — 손상 g vs 평가 g 같은 공유 가정 대조.
    crossEstimate: (body) => j("POST", "/api/review/cross-estimate", body),
    // 편의 징후(540 문단 14·32) — 소급 검토 + 판단 방향성 집계.
    bias: (body) => j("POST", "/api/review/bias", body),
  },
  projects: {
    list: () => j("GET", "/api/projects"),
    create: (body) => j("POST", "/api/projects", body),
    get: (id) => j("GET", `/api/projects/${id}`),
    patch: (id, body) => j("PATCH", `/api/projects/${id}`, body),
    remove: (id) => j("DELETE", `/api/projects/${id}`),
  },
  xlsx: {
    // export 는 바이너리(.xlsx) → blob 반환(다운로드는 호출부에서).
    exportBlob: async (body) => {
      const r = await fetch("/api/xlsx/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || `HTTP ${r.status}`);
      }
      return r.blob();
    },
    import: (xlsx_b64) => j("POST", "/api/xlsx/import", { xlsx_b64 }),
    // 같은 DCF 시트를 **파일이 아니라 격자 플랜**으로 — 열린 워크북에 병설해 정본 분기를
    // 없앤다(§7-1). 응답 형태가 fs_sheet 플랜과 같아 writeSheetPlan 이 그대로 소비한다.
    sheetPlan: (body) => j("POST", "/api/xlsx/sheet-plan", body),
    // 정적 감사(재계산 없는 수식 분석): 패턴 린트·하드코딩 스캔·민감도 중심셀 검산.
    audit: (xlsx_b64) => j("POST", "/api/xlsx/audit", { xlsx_b64 }),
    // 연결성 진단(의존성 그래프): "이 가정이 결과에 도달하는가" — 끊긴 시트·상수 잎·고아.
    connectivity: (xlsx_b64, target) =>
      j("POST", "/api/xlsx/connectivity", { xlsx_b64, ...(target ? { target } : {}) }),
    // 값-only 복원(540 문단 22~25 입구): 표준=스파인 복원, 임의=암묵 WACC 역산.
    recover: (xlsx_b64) => j("POST", "/api/xlsx/recover", { xlsx_b64 }),
    // 기준선 2방식: 저장된 프로젝트에서 재생성(권장 — 왕복 루프가 닫힘) 또는 원본 업로드.
    diffVsProject: (project_id, after_b64) =>
      j("POST", "/api/xlsx/diff", { project_id, after_b64 }),
    diff: (before_b64, after_b64) =>
      j("POST", "/api/xlsx/diff", { before_b64, after_b64 }),
  },
};

/** File → base64(순수 데이터, data: 접두 제거). 업로드용. */
export function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",")[1]);
    r.onerror = () => reject(new Error("파일 읽기 실패"));
    r.readAsDataURL(file);
  });
}
