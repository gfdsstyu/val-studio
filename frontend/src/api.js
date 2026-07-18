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
  priceBeta: (body) => j("POST", "/api/price/beta", body),
  priceMarketcap: (body) => j("POST", "/api/price/marketcap", body),
  priceFx: (body) => j("POST", "/api/price/fx", body),
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
