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
  validateGeminiKey: (key) =>
    j("POST", "/api/keys/validate", undefined, { "X-Gemini-Key": key }),
  projects: {
    list: () => j("GET", "/api/projects"),
    create: (body) => j("POST", "/api/projects", body),
    get: (id) => j("GET", `/api/projects/${id}`),
    patch: (id, body) => j("PATCH", `/api/projects/${id}`, body),
    remove: (id) => j("DELETE", `/api/projects/${id}`),
  },
};
