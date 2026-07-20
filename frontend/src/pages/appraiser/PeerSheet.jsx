import React, { useState } from "react";
import { api } from "../../api.js";

/* 3.할인율 > 유사회사 4-step — /api/peer/select 배선.
   결정론 퍼널: step1 산업코드 → step2 사업유사성(판정) → step3 매출비중 → step4 상장·거래.
   판정 없이 실행 = 결정론 필터만(step2 no-op). 생존자에 사유 있는 판정 입력 후 재실행.
   애매(uncertain)는 자동 탈락 아닌 ⚖️ 큐(유저 결정). 확정 peer 는 WACC βu 로 흐름. */

const DEMO = [
  { ticker: "A", name: "동종A", industry_code: "2710", revenue_share_related: "0.9",
    listed_years: "5", suspended: false, judg: "유사", reason: "동일 의료기기 사업" },
  { ticker: "B", name: "무관B", industry_code: "5811", revenue_share_related: "0.9",
    listed_years: "5", suspended: false, judg: "", reason: "" },
  { ticker: "C", name: "저비중C", industry_code: "2710", revenue_share_related: "0.4",
    listed_years: "5", suspended: false, judg: "유사", reason: "동일 산업 소모품" },
  { ticker: "D", name: "신규D", industry_code: "2710", revenue_share_related: "0.9",
    listed_years: "1", suspended: false, judg: "애매", reason: "사업 유사하나 상장 이력 짧음" },
];
const JUDG = { "유사": { similar: true, uncertain: false }, "비유사": { similar: false, uncertain: false },
  "애매": { similar: true, uncertain: true } };

function KsicLookup() {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState(null);
  const go = async () => { if (q.trim()) setRows(await api.ksicSearch(q).then((d) => d.results)); };
  return (
    <div className="pad" style={{ borderTop: "1px solid var(--line)" }}>
      <label>KSIC 코드 찾기(모집단 코드 보조)</label>
      <div style={{ display: "flex", gap: 6 }}>
        <input type="text" value={q} onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && go()} placeholder="예: 의료기기" style={{ maxWidth: 220 }} />
        <button className="ghost" onClick={go}>검색</button>
      </div>
      {rows && (
        <div className="muted" style={{ marginTop: 6, fontSize: 12 }}>
          {rows.length ? rows.slice(0, 8).map((r) => `${r.code} ${r.name}`).join(" · ") : "결과 없음"}
        </div>
      )}
    </div>
  );
}

export default function PeerSheet({ project, onSave }) {
  const [cands, setCands] = useState(project?.data?.peer_candidates || DEMO);
  const [codes, setCodes] = useState(project?.data?.peer_codes || "2710");
  const [targetTicker, setTargetTicker] = useState(
    project?.data?.peer_target_ticker || project?.ticker || "");
  // Step1a: rough 유사회사(Research ⑦⑨ 경쟁사)에서 KSIC 역산 → 모집단 코드
  const [seedMode, setSeedMode] = useState(false);
  const [seeds, setSeeds] = useState(project?.data?.peer_seeds || [{ ticker: "", name: "", industry_code: "" }]);
  const [useJudg, setUseJudg] = useState(true);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const setRow = (i, k) => (e) => {
    const next = cands.slice();
    next[i] = { ...next[i], [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value };
    setCands(next);
  };
  const addRow = () => setCands([...cands, { ticker: "", name: "", industry_code: "",
    revenue_share_related: "", listed_years: "", suspended: false, judg: "", reason: "" }]);
  const rmRow = (i) => setCands(cands.filter((_, j) => j !== i));

  const setSeed = (i, k) => (e) => {
    const next = seeds.slice();
    next[i] = { ...next[i], [k]: e.target.value };
    setSeeds(next);
  };
  const addSeed = () => setSeeds([...seeds, { ticker: "", name: "", industry_code: "" }]);
  const rmSeed = (i) => setSeeds(seeds.filter((_, j) => j !== i));

  const run = async () => {
    setBusy(true); setErr(null); setRes(null);
    const numOrNull = (v) => (String(v).trim() === "" ? null : Number(v));
    const body = {
      // R11 자기제외 — 평가대상을 peer 통계에 넣으면 배수가 현재 주가로 끌려간다.
      // 비우면 서버가 자기제외를 **실행하지 않는다**(퍼널에도 행이 찍히지 않음).
      target_ticker: targetTicker.trim() || undefined,
      candidates: cands.filter((c) => c.ticker.trim()).map((c) => ({
        ticker: c.ticker, name: c.name || c.ticker,
        industry_code: c.industry_code || null,
        revenue_share_related: numOrNull(c.revenue_share_related),
        listed_years: numOrNull(c.listed_years), suspended: !!c.suspended,
      })),
    };
    if (seedMode) {                          // Step1a: seed → 서버가 KSIC 역산
      body.seed_peers = seeds
        .filter((s) => s.ticker.trim())
        .map((s) => ({ ticker: s.ticker, name: s.name || s.ticker, industry_code: s.industry_code || null }));
    } else {
      body.target_industry_codes = codes.split(/[\s,]+/).filter(Boolean);
    }
    if (useJudg) {
      body.judgments = cands
        .filter((c) => c.ticker.trim() && c.reason.trim() && c.judg)
        .map((c) => ({ ticker: c.ticker, ...JUDG[c.judg], reason: c.reason }));
    }
    try {
      const d = await api.peerSelect(body);
      setRes(d);
      onSave?.({ peer_candidates: cands, peer_codes: codes, peer_target_ticker: targetTicker, peer_seeds: seeds,
        peer_selected: d.selected, peer_needs_review: d.needs_review });
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <>
      <div className="card">
        <h2>유사회사 4-step <span className="muted">— 결정론 퍼널 + 사업유사성 판정</span></h2>
        <div className="pad">
          <label style={{ marginBottom: 6 }}>
            <input type="checkbox" checked={seedMode} onChange={(e) => setSeedMode(e.target.checked)} />
            {" "}Step1a 역산 — rough 유사회사(Research ⑦⑨ 경쟁사)의 KSIC 로 모집단 코드 산출
          </label>
          {!seedMode ? (
            <div className="row" style={{ maxWidth: 320 }}>
              <label>평가대상 종목코드 (자기제외)</label>
              <input type="text" value={targetTicker}
                onChange={(e) => setTargetTicker(e.target.value)}
                placeholder="예 145020 (A145020 도 인식)" />
              <div className="muted" style={{ fontSize: "0.8rem", margin: "2px 0 8px" }}>
                평가대상을 peer 통계에 넣으면 <b>자기 배수로 자기를 평가</b>하는 순환논법이 되어
                상승여력이 구조적으로 희석된다(실측 주당 7.9% 왜곡). 비우면 자기제외를
                <b> 실행하지 않는다</b>.
              </div>
              <label>모집단 산업코드 (KSIC, 콤마 구분)</label>
              <input type="text" value={codes} onChange={(e) => setCodes(e.target.value)} />
            </div>
          ) : (
            <div style={{ marginBottom: 8 }}>
              <label>rough 유사회사 시드 (Ticker·회사·KSIC) → 코드 역산(union)</label>
              <table style={{ maxWidth: 420 }}>
                <thead><tr><th>Ticker</th><th>회사</th><th>KSIC</th><th></th></tr></thead>
                <tbody>
                  {seeds.map((s, i) => (
                    <tr key={i}>
                      <td><input type="text" value={s.ticker} onChange={setSeed(i, "ticker")} style={{ width: 64 }} /></td>
                      <td><input type="text" value={s.name} onChange={setSeed(i, "name")} style={{ width: 96 }} /></td>
                      <td><input type="text" value={s.industry_code} onChange={setSeed(i, "industry_code")} style={{ width: 64 }} /></td>
                      <td><button className="ghost xs" onClick={() => rmSeed(i)}>✕</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button className="ghost" onClick={addSeed} style={{ marginTop: 4 }}>+ 시드 추가</button>
            </div>
          )}
          <label style={{ marginTop: 8 }}>
            <input type="checkbox" checked={useJudg} onChange={(e) => setUseJudg(e.target.checked)} />
            {" "}사업유사성 판정 포함(끄면 결정론 필터 1·3·4단계만)
          </label>
          <div style={{ overflowX: "auto", marginTop: 8 }}>
            <table>
              <thead><tr>
                <th>코드</th><th>회사</th><th>KSIC</th><th>관련매출</th><th>상장연수</th>
                <th>정지</th><th>판정</th><th>사유</th><th></th>
              </tr></thead>
              <tbody>
                {cands.map((c, i) => (
                  <tr key={i}>
                    <td><input type="text" value={c.ticker} onChange={setRow(i, "ticker")} style={{ width: 56 }} /></td>
                    <td><input type="text" value={c.name} onChange={setRow(i, "name")} style={{ width: 80 }} /></td>
                    <td><input type="text" value={c.industry_code} onChange={setRow(i, "industry_code")} style={{ width: 56 }} /></td>
                    <td><input type="text" value={c.revenue_share_related} onChange={setRow(i, "revenue_share_related")} style={{ width: 48 }} /></td>
                    <td><input type="text" value={c.listed_years} onChange={setRow(i, "listed_years")} style={{ width: 44 }} /></td>
                    <td style={{ textAlign: "center" }}><input type="checkbox" checked={!!c.suspended} onChange={setRow(i, "suspended")} /></td>
                    <td><select value={c.judg} onChange={setRow(i, "judg")} disabled={!useJudg} style={{ fontSize: 12 }}>
                      <option value="">-</option><option value="유사">유사</option>
                      <option value="비유사">비유사</option><option value="애매">애매</option>
                    </select></td>
                    <td><input type="text" value={c.reason} onChange={setRow(i, "reason")} style={{ width: 130 }} disabled={!useJudg} /></td>
                    <td><button className="ghost xs" onClick={() => rmRow(i)}>✕</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button className="ghost" onClick={addRow} style={{ marginTop: 6 }}>+ 후보 추가</button>
          {" "}
          <button className="primary" onClick={run} disabled={busy}>
            {busy ? "선정 중…" : "4-step 실행"}
          </button>
          {err && <div className="err">{err}</div>}
        </div>
        <KsicLookup />
      </div>

      {res && (
        <div className="card">
          <h2>선정 결과</h2>
          <div className="pad">
            {res.size_note && <div className="finding warn">{res.size_note}</div>}
            {res.codes_used && res.codes_used.length > 0 && (
              <div className="muted" style={{ marginBottom: 8 }}>
                모집단 코드: {res.codes_used.join(", ")}{seedMode ? " (Step1a 역산)" : ""}
              </div>
            )}
            <table style={{ marginBottom: 12 }}>
              <thead><tr><th style={{ textAlign: "left" }}>단계</th><th>생존</th></tr></thead>
              <tbody>{Object.entries(res.funnel).map(([k, n]) => (
                <tr key={k}><td style={{ textAlign: "left" }}>{k}</td><td>{n}</td></tr>))}</tbody>
            </table>
            <div className="finding pass"><b>확정 peer ({res.selected.length})</b> —{" "}
              {res.selected.map((c) => `${c.name}(${c.ticker})`).join(", ") || "없음"}</div>
            {res.needs_review.length > 0 && (
              <div className="finding warn"><b>⚖️ 애매 — 유저 판단 필요</b>
                <ul>{res.needs_review.map((t, i) => <li key={i}>{t.name}({t.ticker}) — {t.reason}</li>)}</ul>
              </div>
            )}
            {res.dropped.length > 0 && (
              <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>
                탈락: {res.dropped.map((t) => `${t.name}[${t.dropped_at}]`).join(" · ")}
              </div>
            )}
            {res.warnings.length > 0 && (
              <div className="warn-box" style={{ marginTop: 8 }}>
                <b>데이터 결측</b><ul>{res.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
