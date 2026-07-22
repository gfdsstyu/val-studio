/** 로컬 API 헬퍼 — BYOK 키는 호출별 헤더로만 전달(서버 미저장). */

async function j(method, url, body, headers = {}) {
  const r = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json", ...headers } : headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (r.status === 204) return null;
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
  return d;
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
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return r.blob();
}

export const api = {
  health: () => j("GET", "/api/health"),
  dcf: (body) => j("POST", "/api/dcf", body),
  scenario: (body) => j("POST", "/api/scenario", body),
  // 어셈블리: 커넥터 원천값(복붙 문자열 or 숫자) → 검증된 WACC/DCF.
  // 복붙 문자열(예 "3.45%")은 서버가 커넥터로 통과시켜 range 게이트를 건다.
  wacc: { assemble: (body) => j("POST", "/api/wacc/assemble", body) },
  dcfAssemble: (body) => j("POST", "/api/dcf/assemble", body),
  revenueBuild: (body) => j("POST", "/api/revenue/build", body),
  peerSelect: (body) => j("POST", "/api/peer/select", body),
  ksicSearch: (q) => j("GET", `/api/ksic/search?q=${encodeURIComponent(q)}`),
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
  dartCorpSearch: (key, q, listedOnly) =>
    j("POST", "/api/dart/corp-search", { q, listed_only: !!listedOnly }, { "X-Dart-Key": key }),
  dartFilings: (key, body) =>
    j("POST", "/api/dart/filings", body, { "X-Dart-Key": key }),
  // 공시 원본 zip(document.xml) — JSON 이 아니라 바이너리라 blob 헬퍼로 받는다.
  dartDocument: (key, body) =>
    blob("POST", "/api/dart/document", body, { "X-Dart-Key": key }),
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
