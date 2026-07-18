import React, { useState } from "react";
import { api } from "../../api.js";

/* 2.가정 > 원가·판관비 — /api/assumptions/build(ebit) 배선.
   매출(트리/DCF 저장본) × COGS%·SGA% → 매출원가·판관비·매출총이익·EBIT.
   확정 시리즈는 DCF 입력(cogs·sga)에 반영. */

const parseSeries = (s) => String(s).split(/[\s,]+/).filter(Boolean).map(Number);
const fmt = (v) => (v == null || Number.isNaN(v) ? "-" : Math.round(v).toLocaleString("ko-KR"));

export default function CostsSheet({ project, onSave }) {
  const rev = parseSeries(project?.data?.dcf_input?.revenue || project?.data?.revenue_built || "");
  const n = rev.length;
  const [cogsPct, setCogsPct] = useState(project?.data?.costs_input?.cogs_pct
    || Array(n || 3).fill("0.6").join(", "));
  const [sgaPct, setSgaPct] = useState(project?.data?.costs_input?.sga_pct
    || Array(n || 3).fill("0.2").join(", "));
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const build = async () => {
    if (!n) { setErr("먼저 매출(2.가정>매출 또는 DCF)을 확정하세요."); return; }
    setBusy(true); setErr(null); setRes(null);
    try {
      const d = await api.assumptionsBuild({ revenue: rev,
        cogs_pct: parseSeries(cogsPct), sga_pct: parseSeries(sgaPct) });
      setRes(d.ebit);
      onSave?.({ costs_input: { cogs_pct: cogsPct, sga_pct: sgaPct },
        costs_built: d.ebit });
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const pushToDcf = () => {
    if (!res) return;
    const prev = project?.data?.dcf_input || {};
    onSave?.({ dcf_input: { ...prev, cogs: res.cogs.map(Math.round).join(", "),
      sga: res.sga.map(Math.round).join(", ") } });
  };

  const ROWS = res && [["매출", rev], ["매출원가", res.cogs], ["매출총이익", res.gross_profit],
    ["판관비", res.sga], ["EBIT", res.ebit]];

  return (
    <>
      <div className="card">
        <h2>원가·판관비 <span className="muted">— 매출 × COGS%·SGA% → EBIT</span></h2>
        <div className="pad">
          {!n && <div className="muted" style={{ marginBottom: 8 }}>
            매출 벡터가 없습니다 — 2.가정 &gt; 매출 또는 4.DCF 에서 먼저 확정하세요.</div>}
          {n > 0 && <div className="muted" style={{ marginBottom: 8 }}>
            매출 {n}개 연도 감지. 비율은 연도별 콤마 구분(소수, 예 0.6).</div>}
          <div className="row"><label>매출원가율 COGS% (연도별)</label>
            <input type="text" value={cogsPct} onChange={(e) => setCogsPct(e.target.value)} /></div>
          <div className="row"><label>판관비율 SGA% (연도별)</label>
            <input type="text" value={sgaPct} onChange={(e) => setSgaPct(e.target.value)} /></div>
          <button className="primary" onClick={build} disabled={busy}>
            {busy ? "계산 중…" : "원가·EBIT 계산"}</button>
          {err && <div className="err">{err}</div>}
        </div>
      </div>

      {res && (
        <div className="card"><h2>결과</h2><div className="pad">
          <table>
            <thead><tr><th style={{ textAlign: "left" }}>항목</th>
              {rev.map((_, i) => <th key={i}>Y{i + 1}</th>)}</tr></thead>
            <tbody>{ROWS.map(([label, vec]) => (
              <tr key={label} style={label === "EBIT" ? { borderTop: "2px solid var(--line)" } : {}}>
                <th style={{ textAlign: "left" }}>{label}</th>
                {vec.map((v, i) => <td key={i}>{label === "EBIT" ? <b>{fmt(v)}</b> : fmt(v)}</td>)}
              </tr>))}</tbody>
          </table>
          <button className="primary" onClick={pushToDcf} style={{ marginTop: 12 }}>
            매출원가·판관비를 DCF 입력에 반영</button>
        </div></div>
      )}
    </>
  );
}
