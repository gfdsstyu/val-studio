import React, { useState } from "react";
import { api, fileToBase64 } from "../../api.js";

/* 4.밸류에이션 > 상대가치 — /api/relative/value 배선.
   peer 배수(PER·PBR·EV/EBITDA) → median/mean × 대상 지표 → 내재 주당가치. 5-10 Rule.
   pykrx 자동조회는 KRX 로그인 필요 → 수동 입력 또는 CSV 업로드(복붙 대안)로 배수 확보. */

const numOrNull = (v) => (String(v).trim() === "" ? null : Number(v));
const won = (v) => (v == null ? "-" : Math.round(v).toLocaleString("ko-KR"));
const x = (v) => (v == null ? "-" : Number(v).toFixed(2));

const DEMO = [
  { name: "유사사A", per: "10", pbr: "1.0", ev_ebitda: "8" },
  { name: "유사사B", per: "12", pbr: "1.2", ev_ebitda: "10" },
  { name: "유사사C", per: "14", pbr: "1.4", ev_ebitda: "12" },
];

export default function RelativeSheet({ project, onSave }) {
  const [rows, setRows] = useState(project?.data?.relative_peers || DEMO);
  const [t, setT] = useState(project?.data?.relative_target ||
    { eps: "", bps: "", ebitda: "", net_debt: "0", shares: "" });
  const [use, setUse] = useState("median");
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const setRow = (i, k) => (e) => {
    const next = rows.slice(); next[i] = { ...next[i], [k]: e.target.value }; setRows(next);
  };
  const add = () => setRows([...rows, { name: "", per: "", pbr: "", ev_ebitda: "" }]);
  const rm = (i) => setRows(rows.filter((_, j) => j !== i));
  const setT_ = (k) => (e) => setT({ ...t, [k]: e.target.value });

  const compute = async () => {
    setBusy(true); setErr(null); setRes(null);
    try {
      const d = await api.relativeValue({
        peers: rows.filter((r) => r.name.trim()).map((r) => ({
          name: r.name, per: numOrNull(r.per), pbr: numOrNull(r.pbr), ev_ebitda: numOrNull(r.ev_ebitda) })),
        target_eps: numOrNull(t.eps), target_bps: numOrNull(t.bps), target_ebitda: numOrNull(t.ebitda),
        net_debt: Number(t.net_debt) || 0, shares_outstanding: numOrNull(t.shares), use });
      setRes(d);
      onSave?.({ relative_peers: rows, relative_target: t,
        relative_summary: { per: d.per.implied_per_share, pbr: d.pbr.implied_per_share } });
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const uploadCsv = async (file) => {
    if (!file) return;
    try {
      const body = /\.xlsx$/i.test(file.name)
        ? { xlsx_b64: await fileToBase64(file) }
        : { csv: await file.text() };
      const d = await api.uploadSheet(body);
      // 각 행: 회사, PER, PBR, EV/EBITDA (헤더행 스킵: PER 비숫자면)
      const parsed = d.rows.filter((r) => r.length >= 2 && !Number.isNaN(Number(r[1])))
        .map((r) => ({ name: r[0], per: r[1] ?? "", pbr: r[2] ?? "", ev_ebitda: r[3] ?? "" }));
      if (parsed.length) setRows(parsed);
    } catch (e) { setErr(e.message); }
  };

  const Method = ({ label, m, target }) => {
    if (!m) return null;
    return (
      <tr>
        <td style={{ textAlign: "left" }}>{label}</td>
        <td>{m.stats.n}</td>
        <td>{x(m.stats.median)}</td>
        <td>{x(m.stats.mean)}</td>
        <td><b>{target != null ? won(m.implied_per_share) : "지표 입력 필요"}</b></td>
      </tr>
    );
  };

  return (
    <>
      <div className="card">
        <h2>상대가치 <span className="muted">— peer 배수 × 대상 지표(자본시장법 종합평가 트랙)</span></h2>
        <div className="pad">
          <div className="muted" style={{ marginBottom: 8 }}>
            peer 배수를 입력하거나 CSV/엑셀로 업로드하세요(회사·PER·PBR·EV/EBITDA 순).
            pykrx 자동조회는 KRX 로그인 필요 — 수동/업로드가 기본.</div>
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead><tr><th>유사회사</th><th>PER</th><th>PBR</th><th>EV/EBITDA</th><th></th></tr></thead>
              <tbody>{rows.map((r, i) => (
                <tr key={i}>
                  <td><input type="text" value={r.name} onChange={setRow(i, "name")} style={{ width: 100 }} /></td>
                  <td><input type="text" value={r.per} onChange={setRow(i, "per")} style={{ width: 60 }} /></td>
                  <td><input type="text" value={r.pbr} onChange={setRow(i, "pbr")} style={{ width: 60 }} /></td>
                  <td><input type="text" value={r.ev_ebitda} onChange={setRow(i, "ev_ebitda")} style={{ width: 70 }} /></td>
                  <td><button className="ghost xs" onClick={() => rm(i)}>✕</button></td>
                </tr>))}</tbody>
            </table>
          </div>
          <div style={{ marginTop: 6 }}>
            <button className="ghost" onClick={add}>+ 유사회사</button>{" "}
            <input type="file" accept=".csv,.xlsx" style={{ fontSize: 11 }}
              onChange={(e) => uploadCsv(e.target.files[0])} />
          </div>

          <h2 style={{ fontSize: "0.95rem", marginTop: 14 }}>대상회사 지표</h2>
          <div className="grid2">
            <div className="row"><label>EPS (주당순이익 → PER)</label>
              <input type="text" value={t.eps} onChange={setT_("eps")} /></div>
            <div className="row"><label>BPS (주당순자산 → PBR)</label>
              <input type="text" value={t.bps} onChange={setT_("bps")} /></div>
            <div className="row"><label>EBITDA (→ EV/EBITDA, <b>원</b>)</label>
              <input type="text" value={t.ebitda} onChange={setT_("ebitda")} /></div>
            <div className="row"><label>순차입부채 (EV→지분, <b>원</b>)</label>
              <input type="text" value={t.net_debt} onChange={setT_("net_debt")} /></div>
            <div className="row"><label>발행주식수 (EV/EBITDA용)</label>
              <input type="text" value={t.shares} onChange={setT_("shares")} /></div>
            <div className="row"><label>통계</label>
              <select value={use} onChange={(e) => setUse(e.target.value)} style={{ fontSize: 12 }}>
                <option value="median">중앙값(median, 권장)</option><option value="mean">평균(mean)</option></select></div>
          </div>
          <button className="primary" onClick={compute} disabled={busy}>
            {busy ? "계산 중…" : "상대가치 계산"}</button>
          {err && <div className="err">{err}</div>}
        </div>
      </div>

      {res && (
        <div className="card"><h2>내재가치 ({use})</h2><div className="pad">
          {res.warnings.map((w, i) => <div key={i} className="finding warn">{w}</div>)}
          <table style={{ marginTop: 8 }}>
            <thead><tr><th style={{ textAlign: "left" }}>방식</th><th>n</th><th>median</th><th>mean</th><th>내재 주당가치</th></tr></thead>
            <tbody>
              <Method label="PER" m={res.per} target={numOrNull(t.eps)} />
              <Method label="PBR" m={res.pbr} target={numOrNull(t.bps)} />
              <Method label="EV/EBITDA" m={res.ev_ebitda} target={numOrNull(t.ebitda)} />
            </tbody>
          </table>
        </div></div>
      )}
    </>
  );
}
