import React, { useState } from "react";
import { api } from "../../api.js";

/* 2.가정 > FA — /api/assumptions/build(fa) 배선.
   자산군별 기존자산 정액상각(순장부/잔여내용연수) + 신규 CAPEX 빈티지 상각 누적
   → D&A, CAPEX. 내용연수는 DART 주석 출처(후속 자동추출). DCF 입력에 반영. */

const parseSeries = (s) => String(s).split(/[\s,]+/).filter(Boolean).map(Number);
const fmt = (v) => (v == null || Number.isNaN(v) ? "-" : Math.round(v).toLocaleString("ko-KR"));

const DEMO = [
  { name: "설비", opening_net_book: "300", remaining_life: "3", useful_life: "10", capex: "50, 50, 50" },
];

export default function FaSheet({ project, onSave }) {
  const [rows, setRows] = useState(project?.data?.fa_input || DEMO);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const setRow = (i, k) => (e) => {
    const next = rows.slice(); next[i] = { ...next[i], [k]: e.target.value }; setRows(next);
  };
  const addRow = () => setRows([...rows, { name: "", opening_net_book: "0",
    remaining_life: "5", useful_life: "10", capex: "0" }]);
  const rmRow = (i) => setRows(rows.filter((_, j) => j !== i));

  const build = async () => {
    setBusy(true); setErr(null); setRes(null);
    try {
      const d = await api.assumptionsBuild({
        asset_classes: rows.map((r) => ({ name: r.name || "자산",
          opening_net_book: Number(r.opening_net_book),
          remaining_life: Number(r.remaining_life), useful_life: Number(r.useful_life) })),
        new_capex_by_class: Object.fromEntries(rows.map((r) => [r.name || "자산", parseSeries(r.capex)])),
      });
      setRes(d.fa);
      onSave?.({ fa_input: rows, fa_built: d.fa });
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const pushToDcf = () => {
    if (!res) return;
    const prev = project?.data?.dcf_input || {};
    onSave?.({ dcf_input: { ...prev, dep_amort: res.dep_amort.map(Math.round).join(", "),
      capex: res.capex.map(Math.round).join(", ") } });
  };

  return (
    <>
      <div className="card">
        <h2>감가상각·CAPEX <span className="muted">— 기존자산 상각 + 신규 CAPEX 빈티지</span></h2>
        <div className="pad">
          <div className="muted" style={{ marginBottom: 8 }}>
            신규 CAPEX 는 연도별 콤마 구분(길이=추정연수). 내용연수는 정액법 기준.</div>
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead><tr><th>자산군</th><th>기초순장부</th><th>잔여내용연수</th>
                <th>신규내용연수</th><th>신규 CAPEX(연도별)</th><th></th></tr></thead>
              <tbody>{rows.map((r, i) => (
                <tr key={i}>
                  <td><input type="text" value={r.name} onChange={setRow(i, "name")} style={{ width: 80 }} /></td>
                  <td><input type="text" value={r.opening_net_book} onChange={setRow(i, "opening_net_book")} style={{ width: 72 }} /></td>
                  <td><input type="text" value={r.remaining_life} onChange={setRow(i, "remaining_life")} style={{ width: 52 }} /></td>
                  <td><input type="text" value={r.useful_life} onChange={setRow(i, "useful_life")} style={{ width: 52 }} /></td>
                  <td><input type="text" value={r.capex} onChange={setRow(i, "capex")} style={{ width: 120 }} /></td>
                  <td><button className="ghost xs" onClick={() => rmRow(i)}>✕</button></td>
                </tr>))}</tbody>
            </table>
          </div>
          <button className="ghost" onClick={addRow} style={{ marginTop: 6 }}>+ 자산군 추가</button>{" "}
          <button className="primary" onClick={build} disabled={busy}>
            {busy ? "계산 중…" : "D&A·CAPEX 계산"}</button>
          {err && <div className="err">{err}</div>}
        </div>
      </div>

      {res && (
        <div className="card"><h2>결과</h2><div className="pad">
          <table>
            <thead><tr><th style={{ textAlign: "left" }}>항목</th>
              {res.dep_amort.map((_, i) => <th key={i}>Y{i + 1}</th>)}</tr></thead>
            <tbody>
              <tr><th style={{ textAlign: "left" }}>감가상각비 D&A</th>
                {res.dep_amort.map((v, i) => <td key={i}>{fmt(v)}</td>)}</tr>
              <tr><th style={{ textAlign: "left" }}>CAPEX</th>
                {res.capex.map((v, i) => <td key={i}>{fmt(v)}</td>)}</tr>
            </tbody>
          </table>
          <button className="primary" onClick={pushToDcf} style={{ marginTop: 12 }}>
            D&A·CAPEX 를 DCF 입력에 반영</button>
        </div></div>
      )}
    </>
  );
}
