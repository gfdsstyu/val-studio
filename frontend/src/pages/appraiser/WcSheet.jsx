import React, { useState } from "react";
import { api } from "../../api.js";

/* 2.가정 > WC — /api/assumptions/build(wc) 배선.
   회전율(driver/잔액)→회전기간(365/회전율) 고정→투영 잔액→순운전자본→ΔNWC(현금조정).
   각 항목은 driver(매출 or 매출원가)에 연동. ΔNWC 는 DCF 입력에 반영. */

const parseSeries = (s) => String(s).split(/[\s,]+/).filter(Boolean).map(Number);
const fmt = (v) => (v == null || Number.isNaN(v) ? "-" : Math.round(v).toLocaleString("ko-KR"));

const DEMO = [
  { name: "매출채권", base_balance: "100", base_driver: "1000", is_asset: true, driver: "1000, 1100, 1210" },
  { name: "매입채무", base_balance: "60", base_driver: "600", is_asset: false, driver: "600, 660, 726" },
];

export default function WcSheet({ project, onSave }) {
  const [rows, setRows] = useState(project?.data?.wc_input?.rows || DEMO);
  const [baseNwc, setBaseNwc] = useState(project?.data?.wc_input?.base_nwc || "40");
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const setRow = (i, k) => (e) => {
    const next = rows.slice();
    next[i] = { ...next[i], [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value };
    setRows(next);
  };
  const addRow = () => setRows([...rows, { name: "", base_balance: "0", base_driver: "0",
    is_asset: true, driver: "0" }]);
  const rmRow = (i) => setRows(rows.filter((_, j) => j !== i));

  const build = async () => {
    setBusy(true); setErr(null); setRes(null);
    try {
      const d = await api.assumptionsBuild({
        wc_items: rows.map((r) => ({ name: r.name || "항목",
          base_balance: Number(r.base_balance), base_driver: Number(r.base_driver),
          is_asset: !!r.is_asset })),
        wc_driver_by_item: Object.fromEntries(rows.map((r) => [r.name || "항목", parseSeries(r.driver)])),
        base_net_working_capital: Number(baseNwc),
      });
      setRes(d.wc);
      onSave?.({ wc_input: { rows, base_nwc: baseNwc }, wc_built: d.wc });
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const pushToDcf = () => {
    if (!res) return;
    const prev = project?.data?.dcf_input || {};
    onSave?.({ dcf_input: { ...prev,
      delta_nwc_cash_adj: res.delta_nwc_cash_adj.map(Math.round).join(", ") } });
  };

  return (
    <>
      <div className="card">
        <h2>운전자본 (WC) <span className="muted">— 회전율 고정 → ΔNWC 현금조정</span></h2>
        <div className="pad">
          <div className="muted" style={{ marginBottom: 8 }}>
            각 항목의 driver(매출/매출원가)는 연도별 콤마 구분. 자산=채권·재고, 부채=매입채무.</div>
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead><tr><th>항목</th><th>기초잔액</th><th>기초driver</th><th>자산?</th>
                <th>driver(연도별)</th><th></th></tr></thead>
              <tbody>{rows.map((r, i) => (
                <tr key={i}>
                  <td><input type="text" value={r.name} onChange={setRow(i, "name")} style={{ width: 80 }} /></td>
                  <td><input type="text" value={r.base_balance} onChange={setRow(i, "base_balance")} style={{ width: 60 }} /></td>
                  <td><input type="text" value={r.base_driver} onChange={setRow(i, "base_driver")} style={{ width: 60 }} /></td>
                  <td style={{ textAlign: "center" }}><input type="checkbox" checked={!!r.is_asset} onChange={setRow(i, "is_asset")} /></td>
                  <td><input type="text" value={r.driver} onChange={setRow(i, "driver")} style={{ width: 120 }} /></td>
                  <td><button className="ghost xs" onClick={() => rmRow(i)}>✕</button></td>
                </tr>))}</tbody>
            </table>
          </div>
          <div className="row" style={{ maxWidth: 200, marginTop: 8 }}>
            <label>기초 순운전자본</label>
            <input type="text" value={baseNwc} onChange={(e) => setBaseNwc(e.target.value)} />
          </div>
          <button className="ghost" onClick={addRow}>+ 항목 추가</button>{" "}
          <button className="primary" onClick={build} disabled={busy}>
            {busy ? "계산 중…" : "ΔNWC 계산"}</button>
          {err && <div className="err">{err}</div>}
        </div>
      </div>

      {res && (
        <div className="card"><h2>결과</h2><div className="pad">
          <table>
            <thead><tr><th style={{ textAlign: "left" }}>항목</th>
              {res.delta_nwc_cash_adj.map((_, i) => <th key={i}>Y{i + 1}</th>)}</tr></thead>
            <tbody>
              <tr><th style={{ textAlign: "left" }}>순운전자본</th>
                {res.net_working_capital.map((v, i) => <td key={i}>{fmt(v)}</td>)}</tr>
              <tr style={{ borderTop: "2px solid var(--line)" }}>
                <th style={{ textAlign: "left" }}>ΔNWC(현금조정)</th>
                {res.delta_nwc_cash_adj.map((v, i) => <td key={i}><b>{fmt(v)}</b></td>)}</tr>
            </tbody>
          </table>
          <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
            음수 = 운전자본 증가로 현금유출(FCFF 차감).</div>
          <button className="primary" onClick={pushToDcf} style={{ marginTop: 12 }}>
            ΔNWC 를 DCF 입력에 반영</button>
        </div></div>
      )}
    </>
  );
}
