import React, { useState } from "react";
import { api } from "../../api.js";

/* 2.가정 > FA — /api/assumptions/build(fa) 배선.
   자산군별 기존자산 정액상각(순장부/잔여내용연수) + 신규 CAPEX 빈티지 상각 누적
   → D&A, CAPEX. 내용연수는 DART 주석 출처(후속 자동추출). DCF 입력에 반영. */

const parseSeries = (s) => String(s).split(/[\s,]+/).filter(Boolean).map(Number);
const fmt = (v) => (v == null || Number.isNaN(v) ? "-" : Math.round(v).toLocaleString("ko-KR"));

const DEMO = [
  { name: "설비", opening_net_book: "300", remaining_life: "3", useful_life: "10",
    capex: "50, 50, 50", maintenance: "20, 20, 20" },
];

export default function FaSheet({ project, onSave }) {
  const [rows, setRows] = useState(project?.data?.fa_input || DEMO);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  // K-IFRS 1116 리스: ROU 감가상각 → D&A 합산, 리스부채 → 순차입부채 브리지.
  const [lease, setLease] = useState(project?.data?.lease_input ||
    { term: "5", discount_rate: "0.05", annual_payment: "1000", initial_liability: "" });
  const [leaseRes, setLeaseRes] = useState(project?.data?.lease_built || null);
  const setL = (k) => (e) => setLease({ ...lease, [k]: e.target.value });

  const buildLease = async () => {
    setErr(null);
    try {
      const body = { term: Number(lease.term), discount_rate: Number(lease.discount_rate) };
      if (lease.initial_liability.trim()) body.initial_liability = Number(lease.initial_liability);
      else body.annual_payment = Number(lease.annual_payment);
      const d = await api.assumptionsLease(body);
      setLeaseRes(d);
      onSave?.({ lease_input: lease, lease_built: d });
    } catch (e) { setErr(e.message); }
  };

  const setRow = (i, k) => (e) => {
    const next = rows.slice(); next[i] = { ...next[i], [k]: e.target.value }; setRows(next);
  };
  const addRow = () => setRows([...rows, { name: "", opening_net_book: "0",
    remaining_life: "5", useful_life: "10", capex: "0", maintenance: "0" }]);
  const rmRow = (i) => setRows(rows.filter((_, j) => j !== i));

  const build = async () => {
    setBusy(true); setErr(null); setRes(null);
    try {
      // 유지보수 CAPEX 있으면 분리 전달(신규=성장 빈티지, 유지보수=자본유지). detail 반환.
      const maint = Object.fromEntries(rows
        .filter((r) => (r.maintenance || "").trim())
        .map((r) => [r.name || "자산", parseSeries(r.maintenance)]));
      const d = await api.assumptionsBuild({
        asset_classes: rows.map((r) => ({ name: r.name || "자산",
          opening_net_book: Number(r.opening_net_book),
          remaining_life: Number(r.remaining_life), useful_life: Number(r.useful_life) })),
        new_capex_by_class: Object.fromEntries(rows.map((r) => [r.name || "자산", parseSeries(r.capex)])),
        maintenance_capex_by_class: Object.keys(maint).length ? maint : undefined,
      });
      setRes(d.fa);
      onSave?.({ fa_input: rows, fa_built: d.fa });
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const pushToDcf = () => {
    if (!res) return;
    const prev = project?.data?.dcf_input || {};
    // ROU 감가상각을 D&A 에 합산(리스 계산 시).
    const rou = leaseRes?.rou_depreciation || [];
    const dep = res.dep_amort.map((v, i) => Math.round(v + (rou[i] || 0)));
    onSave?.({ dcf_input: { ...prev, dep_amort: dep.join(", "),
      capex: res.capex.map(Math.round).join(", ") } });
  };

  const pushLeaseDebt = () => {
    if (!leaseRes) return;
    const prev = project?.data?.dcf_input || {};
    const base = Number(prev.net_debt) || 0;
    onSave?.({ dcf_input: { ...prev, net_debt: Math.round(base + leaseRes.liability_open[0]) } });
  };

  return (
    <>
      <div className="card">
        <h2>감가상각·CAPEX <span className="muted">— 기존자산 상각 + 신규 CAPEX 빈티지</span></h2>
        <div className="pad">
          <div className="muted" style={{ marginBottom: 8 }}>
            CAPEX 는 연도별 콤마 구분(길이=추정연수). 신규(성장)=새 빈티지 상각,
            유지보수=자본유지(terminal 년 ≈ D&A 정규화). 내용연수는 정액법 기준.</div>
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead><tr><th>자산군</th><th>기초순장부</th><th>잔여내용연수</th>
                <th>신규내용연수</th><th>신규(성장) CAPEX</th><th>유지보수 CAPEX</th><th></th></tr></thead>
              <tbody>{rows.map((r, i) => (
                <tr key={i}>
                  <td><input type="text" value={r.name} onChange={setRow(i, "name")} style={{ width: 80 }} /></td>
                  <td><input type="text" value={r.opening_net_book} onChange={setRow(i, "opening_net_book")} style={{ width: 72 }} /></td>
                  <td><input type="text" value={r.remaining_life} onChange={setRow(i, "remaining_life")} style={{ width: 52 }} /></td>
                  <td><input type="text" value={r.useful_life} onChange={setRow(i, "useful_life")} style={{ width: 52 }} /></td>
                  <td><input type="text" value={r.capex} onChange={setRow(i, "capex")} style={{ width: 110 }} /></td>
                  <td><input type="text" value={r.maintenance || ""} onChange={setRow(i, "maintenance")} style={{ width: 110 }} placeholder="선택" /></td>
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
              {res.detail?.maint_dep?.some((v) => v) && (
                <tr><td style={{ textAlign: "left", paddingLeft: 12 }} className="muted">↳ 유지보수분 상각</td>
                  {res.detail.maint_dep.map((v, i) => <td key={i} className="muted">{fmt(v)}</td>)}</tr>)}
              <tr><th style={{ textAlign: "left" }}>CAPEX 계</th>
                {res.capex.map((v, i) => <td key={i}>{fmt(v)}</td>)}</tr>
              {res.detail?.new_capex && (
                <tr><td style={{ textAlign: "left", paddingLeft: 12 }} className="muted">↳ 신규(성장)</td>
                  {res.detail.new_capex.map((v, i) => <td key={i} className="muted">{fmt(v)}</td>)}</tr>)}
              {res.detail?.maintenance_capex?.some((v) => v) && (
                <tr><td style={{ textAlign: "left", paddingLeft: 12 }} className="muted">↳ 유지보수</td>
                  {res.detail.maintenance_capex.map((v, i) => <td key={i} className="muted">{fmt(v)}</td>)}</tr>)}
            </tbody>
          </table>
          <button className="primary" onClick={pushToDcf} style={{ marginTop: 12 }}>
            D&A·CAPEX 를 DCF 입력에 반영{leaseRes ? " (+ROU 감가상각)" : ""}</button>
        </div></div>
      )}

      <div className="card">
        <h2>리스 (K-IFRS 1116) <span className="muted">— 사용권자산 감가상각 + 리스부채</span></h2>
        <div className="pad">
          <div className="muted" style={{ marginBottom: 8 }}>
            리스료가 이자·원금으로 분리되고 사용권자산은 정액 감가상각됩니다. ROU 감가상각은
            D&A 에 가산, 리스부채 잔액은 순차입부채(EV→지분)에 반영.</div>
          <div className="grid2">
            <div className="row"><label>리스기간(년)</label>
              <input type="text" value={lease.term} onChange={setL("term")} /></div>
            <div className="row"><label>리스이자율</label>
              <input type="text" value={lease.discount_rate} onChange={setL("discount_rate")} /></div>
            <div className="row"><label>연 리스료 (또는 아래 리스부채)</label>
              <input type="text" value={lease.annual_payment} onChange={setL("annual_payment")} /></div>
            <div className="row"><label>초기 리스부채 (있으면 우선)</label>
              <input type="text" value={lease.initial_liability} onChange={setL("initial_liability")} placeholder="선택" /></div>
          </div>
          <button className="primary" onClick={buildLease}>리스 스케줄 계산</button>

          {leaseRes && (
            <>
              <table style={{ marginTop: 12 }}>
                <thead><tr><th style={{ textAlign: "left" }}>항목</th>
                  {leaseRes.rou_depreciation.map((_, i) => <th key={i}>Y{i + 1}</th>)}</tr></thead>
                <tbody>
                  <tr><th style={{ textAlign: "left" }}>ROU 감가상각(→D&A)</th>{leaseRes.rou_depreciation.map((v, i) => <td key={i}>{fmt(v)}</td>)}</tr>
                  <tr><th style={{ textAlign: "left" }}>리스이자(금융비용)</th>{leaseRes.interest.map((v, i) => <td key={i}>{fmt(v)}</td>)}</tr>
                  <tr><th style={{ textAlign: "left" }}>원금상환</th>{leaseRes.principal.map((v, i) => <td key={i}>{fmt(v)}</td>)}</tr>
                  <tr style={{ borderTop: "1px solid var(--line)" }}><th style={{ textAlign: "left" }}>리스부채 잔액</th>{leaseRes.liability_close.map((v, i) => <td key={i}>{fmt(v)}</td>)}</tr>
                </tbody>
              </table>
              <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                기초 리스부채 <b>{fmt(leaseRes.liability_open[0])}</b> → 순차입부채 반영 대상.</div>
              <button className="primary" onClick={pushLeaseDebt} style={{ marginTop: 8 }}>
                리스부채를 순차입부채에 반영</button>
            </>
          )}
        </div>
      </div>
    </>
  );
}
