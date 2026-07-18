import React, { useState } from "react";
import { api } from "../../api.js";

/* 2.가정 > 원가·판관비 — /api/assumptions/costs-build 배선(비올/MSVALUE 성격별 다중드라이버).
   단일 COGS%/SGA% 가 아니라 성격별 라인(원재료·노무비·외주비·감가상각·인건비·지급수수료…)을
   각자 경제동인으로 투영 → 카테고리 합산 → 매출총이익·EBIT. 성격별 항목은 1.계정분류(PL 매핑)
   에서 임포트 가능. */

const parseSeries = (s) => String(s).split(/[\s,]+/).filter(Boolean).map(Number);
const fmt = (v) => (v == null || Number.isNaN(v) ? "-" : Math.round(v).toLocaleString("ko-KR"));

const METHODS = [
  ["growth", "증가율(base×(1+g))"], ["ratio", "매출연동(driver×%)"],
  ["headcount", "인건비(인원×급여×(1+상여+퇴직))"], ["cpi", "물가연동(base×CPI)"],
  ["fa_dep", "감가상각(FA 배분)"], ["fixed", "고정(연도값)"],
];

const DEMO = [
  { name: "원재료", category: "cogs", method: "ratio", pct: "0.45, 0.45, 0.45" },
  { name: "노무비", category: "cogs", method: "headcount", headcount: "100, 105, 110",
    wage_per_head: "50, 52, 54", bonus_rate: "0.1", severance_rate: "0.08" },
  { name: "외주비", category: "cogs", method: "cpi", base: "3000" },
  { name: "제조감가상각", category: "cogs", method: "fa_dep", fa_share: "0.7" },
  { name: "인건비(판관)", category: "sga", method: "headcount", headcount: "30, 31, 32",
    wage_per_head: "60, 62, 64", bonus_rate: "0.1", severance_rate: "0.08" },
  { name: "지급수수료", category: "sga", method: "growth", base: "2000", growth: "0.05, 0.05, 0.05" },
  { name: "판관감가상각", category: "sga", method: "fa_dep", fa_share: "0.3" },
];

export default function CostsSheet({ project, onSave }) {
  const rev = parseSeries(project?.data?.dcf_input?.revenue || project?.data?.revenue_built || "");
  const years = rev.length || 3;
  const [lines, setLines] = useState(project?.data?.costs_lines || DEMO);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const cpi = parseSeries(project?.data?.macro_cpi || "");           // 외주비 CPI(있으면)
  const faDep = project?.data?.fa_built?.dep_amort || null;          // 감가상각 배분원

  const setLine = (i, k) => (e) => {
    const next = lines.slice(); next[i] = { ...next[i], [k]: e.target.value }; setLines(next);
  };
  const addLine = () => setLines([...lines, { name: "", category: "cogs", method: "growth", base: "0", growth: "0" }]);
  const rmLine = (i) => setLines(lines.filter((_, j) => j !== i));

  // 1.계정분류(PL 매핑)에서 성격별 항목 임포트 — COGS/SGA 버킷을 라인으로.
  const importFromMapping = () => {
    const pl = project?.data?.mapping_pl || [];
    const imported = pl
      .filter((r) => ["COGS", "SGA"].includes(r.bucket) && (r.account || "").trim())
      .map((r) => ({ name: r.account, category: r.bucket === "COGS" ? "cogs" : "sga",
        method: "growth", base: String(Math.round(Number(r.amount) || 0)), growth: "0, 0, 0" }));
    if (imported.length) setLines(imported);
    else setErr("1.계정분류 > 손익 매핑에 COGS/SGA 계정이 없습니다.");
  };

  const build = async () => {
    setBusy(true); setErr(null); setRes(null);
    try {
      const payload = lines.map((l) => {
        const o = { name: l.name || "항목", category: l.category, method: l.method };
        if (l.base !== undefined && l.base !== "") o.base = Number(l.base);
        if (l.growth) o.growth = parseSeries(l.growth);
        if (l.pct) o.pct = parseSeries(l.pct);
        if (l.method === "ratio") o.driver = rev;              // 매출 연동
        if (l.headcount) o.headcount = parseSeries(l.headcount);
        if (l.wage_per_head) o.wage_per_head = parseSeries(l.wage_per_head);
        if (l.bonus_rate) o.bonus_rate = Number(l.bonus_rate);
        if (l.severance_rate) o.severance_rate = Number(l.severance_rate);
        if (l.fa_share) o.fa_share = Number(l.fa_share);
        return o;
      });
      const d = await api.assumptionsBuildCosts({ years, lines: payload,
        cpi: cpi.length ? cpi : undefined, fa_dep: faDep || undefined });
      setRes(d);
      onSave?.({ costs_lines: lines, costs_built: d });
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const pushToDcf = () => {
    if (!res) return;
    const prev = project?.data?.dcf_input || {};
    onSave?.({ dcf_input: { ...prev, cogs: res.cogs.map(Math.round).join(", "),
      sga: res.sga.map(Math.round).join(", ") } });
  };

  const ebit = res ? rev.map((r, i) => r - (res.cogs[i] || 0) - (res.sga[i] || 0)) : null;

  return (
    <>
      <div className="card">
        <h2>원가·판관비 <span className="muted">— 성격별 다중 드라이버(비올/MSVALUE)</span></h2>
        <div className="pad">
          <div className="muted" style={{ marginBottom: 8 }}>
            성격별(원재료·노무비·외주비·감가상각·인건비·지급수수료…)로 각자 투영합니다.
            매출 {years}개 연도{cpi.length ? " · CPI 연동 有" : ""}{faDep ? " · FA 감가상각 배분 有" : ""}.</div>
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead><tr><th>항목</th><th>구분</th><th>방법</th><th>파라미터</th><th></th></tr></thead>
              <tbody>{lines.map((l, i) => (
                <tr key={i}>
                  <td><input type="text" value={l.name} onChange={setLine(i, "name")} style={{ width: 100 }} /></td>
                  <td><select value={l.category} onChange={setLine(i, "category")} style={{ fontSize: 12 }}>
                    <option value="cogs">매출원가</option><option value="sga">판관비</option></select></td>
                  <td><select value={l.method} onChange={setLine(i, "method")} style={{ fontSize: 11 }}>
                    {METHODS.map(([m, lbl]) => <option key={m} value={m}>{lbl}</option>)}</select></td>
                  <td style={{ fontSize: 11 }}>
                    {l.method === "growth" && <>base<input type="text" value={l.base || ""} onChange={setLine(i, "base")} style={{ width: 60 }} /> g<input type="text" value={l.growth || ""} onChange={setLine(i, "growth")} style={{ width: 90 }} /></>}
                    {l.method === "ratio" && <>매출×<input type="text" value={l.pct || ""} onChange={setLine(i, "pct")} style={{ width: 90 }} placeholder="비율(연도별)" /></>}
                    {l.method === "headcount" && <>인원<input type="text" value={l.headcount || ""} onChange={setLine(i, "headcount")} style={{ width: 70 }} /> 급여<input type="text" value={l.wage_per_head || ""} onChange={setLine(i, "wage_per_head")} style={{ width: 70 }} /> 상여<input type="text" value={l.bonus_rate || ""} onChange={setLine(i, "bonus_rate")} style={{ width: 36 }} /> 퇴직<input type="text" value={l.severance_rate || ""} onChange={setLine(i, "severance_rate")} style={{ width: 36 }} /></>}
                    {l.method === "cpi" && <>base<input type="text" value={l.base || ""} onChange={setLine(i, "base")} style={{ width: 60 }} /></>}
                    {l.method === "fa_dep" && <>배분율<input type="text" value={l.fa_share || ""} onChange={setLine(i, "fa_share")} style={{ width: 50 }} /></>}
                    {l.method === "fixed" && <>연도값<input type="text" value={l.growth || ""} onChange={setLine(i, "growth")} style={{ width: 100 }} /></>}
                  </td>
                  <td><button className="ghost xs" onClick={() => rmLine(i)}>✕</button></td>
                </tr>))}</tbody>
            </table>
          </div>
          <div style={{ marginTop: 6 }}>
            <button className="ghost" onClick={addLine}>+ 항목</button>{" "}
            <button className="ghost" onClick={importFromMapping} title="1.계정분류 PL 매핑에서 COGS/SGA 임포트">계정분류에서 임포트</button>{" "}
            <button className="primary" onClick={build} disabled={busy}>{busy ? "계산 중…" : "원가·EBIT 계산"}</button>
          </div>
          {err && <div className="err">{err}</div>}
        </div>
      </div>

      {res && (
        <div className="card"><h2>결과</h2><div className="pad">
          <table>
            <thead><tr><th style={{ textAlign: "left" }}>항목</th>{rev.map((_, i) => <th key={i}>Y{i + 1}</th>)}</tr></thead>
            <tbody>
              <tr><th style={{ textAlign: "left" }}>매출</th>{rev.map((v, i) => <td key={i}>{fmt(v)}</td>)}</tr>
              {Object.entries(res.detail).map(([name, vec]) => (
                <tr key={name}><td style={{ textAlign: "left", paddingLeft: 12 }} className="muted">{name}</td>
                  {vec.map((v, i) => <td key={i} className="muted">{fmt(v)}</td>)}</tr>))}
              <tr style={{ borderTop: "1px solid var(--line)" }}><th style={{ textAlign: "left" }}>매출원가 계</th>{res.cogs.map((v, i) => <td key={i}>{fmt(v)}</td>)}</tr>
              <tr><th style={{ textAlign: "left" }}>판관비 계</th>{res.sga.map((v, i) => <td key={i}>{fmt(v)}</td>)}</tr>
              <tr style={{ borderTop: "2px solid var(--line)" }}><th style={{ textAlign: "left" }}>EBIT</th>{ebit.map((v, i) => <td key={i}><b>{fmt(v)}</b></td>)}</tr>
            </tbody>
          </table>
          <button className="primary" onClick={pushToDcf} style={{ marginTop: 12 }}>매출원가·판관비를 DCF 입력에 반영</button>
        </div></div>
      )}
    </>
  );
}
