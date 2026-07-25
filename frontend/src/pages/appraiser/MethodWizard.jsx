import React, { useState } from "react";
import { api } from "../../api.js";

/* 기법선택 위저드 — 사업 성격 질문 → 밸류에이션 기법 추천(참고).
   근거: docs/reference/밸류에이션_기법선택_로직.md (레퍼런스 코퍼스 귀납).
   로직 SSOT는 calc_core.method_selector.recommend_by_business_nature (엔진).
   법제 목적(합병·PPA·손상)은 별도 recommend() — 여기는 '사업을 어떻게 볼까' 축. */

const QUESTIONS = [
  ["is_pipeline_bio", "파이프라인 바이오인가? (이익 부재·성공확률 기반)", "→ rNPV"],
  ["is_holding_or_heterogeneous", "지주사·부문 이질적인가? (성장·마진·시황 상이)", "→ SOTP"],
  ["is_capital_intensive_or_cyclical", "자본집약·사이클 산업인가? (이익 변동성↑, 순자산 중요)", "→ PBR"],
  ["is_predictable_high_growth", "현금흐름 예측가능 + 고성장인가? (멀티플이 성장 미반영)", "→ DCF"],
  ["has_stable_earnings_and_peers", "안정 이익 + peer 풍부한가?", "→ 상대가치(PER)"],
];

export default function MethodWizard() {
  const [flags, setFlags] = useState({});
  const [rec, setRec] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const toggle = (k) => setFlags((f) => ({ ...f, [k]: !f[k] }));

  const recommend = async () => {
    setBusy(true); setErr(null);
    try {
      setRec(await api.methodRecommend(flags));
    } catch (e) { setErr(String(e?.message || e)); } finally { setBusy(false); }
  };

  return (
    <div className="card">
      <h2>기법 선택 위저드 <span className="muted">— 사업 성격 → 밸류에이션 기법</span></h2>
      <div className="pad">
        <div className="muted" style={{ fontSize: 12, marginBottom: 10 }}>
          해당하는 항목을 체크하세요. 우선순위(위→아래)로 첫 매치를 추천합니다.
          법제 목적(합병·PPA·손상)은 별도 셀렉터가 담당합니다.
        </div>
        {QUESTIONS.map(([k, q, hint]) => (
          <label key={k} style={{ display: "flex", alignItems: "center", gap: 8,
            padding: "6px 0", fontSize: 13, cursor: "pointer" }}>
            <input type="checkbox" checked={!!flags[k]} onChange={() => toggle(k)} />
            <span>{q}</span>
            <span className="muted" style={{ fontSize: 11, marginLeft: "auto" }}>{hint}</span>
          </label>
        ))}
        <button onClick={recommend} disabled={busy} style={{ marginTop: 10 }}>
          {busy ? "추천 중…" : "기법 추천"}
        </button>
        {err && <div style={{ color: "#c5221f", fontSize: 13, marginTop: 8 }}>{err}</div>}
        {rec && (
          <div style={{ marginTop: 12, padding: 12, border: "1px solid #dadce0",
            borderRadius: 8, background: "#f8fbff" }}>
            <div style={{ fontSize: 15 }}>
              추천 기법: <b style={{ color: "#1a73e8" }}>{rec.label}</b>
            </div>
            <div style={{ fontSize: 13, color: "#3c4043", marginTop: 4 }}>{rec.rationale}</div>
            {rec.alternatives?.length > 0 && (
              <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                대안: {rec.alternatives.join(" · ")}
              </div>
            )}
            <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>
              근거: {rec.provenance}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
