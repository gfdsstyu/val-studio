import React, { useMemo, useState } from "react";
import { api } from "../../api.js";

/* 1.계정분류 — pl(손익)·bs(BS NOA/IBD). 계정 → 밸류에이션 버킷 수동 매핑.
   자동 분류(LLM)는 후속 — v1 은 유저 수동(정확성 우선, 타사 자동분류 Sales 오분류 약점 회피).
   PL 버킷: Sales/COGS/SGA/NonOp. BS 버킷: WC(운전자본)/FA(유형)/NOA(비영업)/IBD(이자부부채)/EQU.
   BS 의 NOA/IBD 분류는 EV→Equity 브리지(비영업자산 +, 순차입부채 −)에 직결. */

const PL_BUCKETS = ["Sales", "COGS", "SGA", "NonOp(영업외)"];
const BS_BUCKETS = ["WC(운전자본)", "FA(유형자산)", "NOA(비영업자산)", "IBD(이자부부채)", "OAL(기타)", "EQU(자본)"];

const num = (v) => { const n = Number(String(v).replace(/,/g, "")); return Number.isNaN(n) ? 0 : n; };
const fmt = (v) => Math.round(v).toLocaleString("ko-KR");

export default function MappingSheet({ project, sheet, onSave }) {
  const isBs = sheet === "bs";
  const buckets = isBs ? BS_BUCKETS : PL_BUCKETS;
  const key = isBs ? "mapping_bs" : "mapping_pl";
  const [rows, setRows] = useState(project?.data?.[key] || [
    { account: "", amount: "", bucket: buckets[0] },
  ]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const setRow = (i, k) => (e) => {
    const next = rows.slice(); next[i] = { ...next[i], [k]: e.target.value, _sug: undefined }; setRows(next);
  };

  // 자동 분류 제안 — 서버 2단(택사노미 account_id → 계정명 키워드). judgment(평가목적
  // 판단 사항)는 버킷을 자동 확정하지 않고 배지로만 제안, uncertain/저신뢰도 배지 표기.
  const autoClassify = async () => {
    const named = rows.map((r, i) => [i, (r.account || "").trim(), r.account_id])
      .filter(([, a]) => a);
    if (!named.length) { setErr("계정과목을 먼저 입력하세요."); return; }
    setBusy(true); setErr(null);
    try {
      const { classifications } = await api.fsClassify({
        statement: isBs ? "BS" : "PL",
        accounts: named.map(([, name, account_id]) => ({ name, account_id })) });
      const next = rows.slice();
      named.forEach(([i], k) => {
        const c = classifications[k];
        next[i] = { ...next[i],
          // judgment 는 유저 판단 몫 → 자동 확정 금지(기존 버킷 유지). 확정 분류만 채움.
          bucket: (c.bucket && !c.judgment) ? c.bucket : next[i].bucket,
          _sug: { bucket: c.bucket, conf: c.confidence, uncertain: c.uncertain,
                  note: c.note, judgment: c.judgment } };
      });
      setRows(next);
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const add = () => setRows([...rows, { account: "", amount: "", bucket: buckets[0] }]);
  const rm = (i) => setRows(rows.filter((_, j) => j !== i));

  const subtotals = useMemo(() => {
    const t = {};
    for (const b of buckets) t[b] = 0;
    for (const r of rows) t[r.bucket] = (t[r.bucket] || 0) + num(r.amount);
    return t;
  }, [rows, buckets]);

  // BS: EV→Equity 브리지 미리보기(NOA 합 = 비영업자산, IBD 합 = 순차입부채)
  const noa = subtotals["NOA(비영업자산)"] || 0;
  const ibd = subtotals["IBD(이자부부채)"] || 0;

  const save = () => {
    const patch = { [key]: rows };
    if (isBs) patch.bridge = { non_operating_assets: noa, net_debt: ibd };
    onSave?.(patch);
  };
  const pushBridge = () => {
    const prev = project?.data?.dcf_input || {};
    onSave?.({ dcf_input: { ...prev, non_operating_assets: Math.round(noa), net_debt: Math.round(ibd) } });
  };

  return (
    <>
      <div className="card">
        <h2>{isBs ? "BS 매핑 (NOA/IBD)" : "손익 매핑"}{" "}
          <span className="muted">— 계정 → 밸류에이션 버킷(수동, LLM 제안은 후속)</span></h2>
        <div className="pad">
          <div className="muted" style={{ marginBottom: 8 }}>
            {isBs
              ? "재무상태표 계정을 버킷으로 분류합니다. NOA(비영업자산)·IBD(이자부부채)는 EV→지분가치 브리지에 직결됩니다."
              : "손익계산서 계정을 Sales/COGS/SGA/영업외로 분류합니다. 원가·판관비 가정의 기초."}</div>
          <table>
            <thead><tr><th>계정과목</th><th>금액(백만원)</th><th>버킷</th><th>제안</th><th></th></tr></thead>
            <tbody>{rows.map((r, i) => (
              <tr key={i}>
                <td><input type="text" value={r.account} onChange={setRow(i, "account")} style={{ width: 160 }} /></td>
                <td><input type="text" value={r.amount} onChange={setRow(i, "amount")} style={{ width: 100, textAlign: "right" }} /></td>
                <td><select value={r.bucket} onChange={setRow(i, "bucket")} style={{ fontSize: 12 }}>
                  {buckets.map((b) => <option key={b} value={b}>{b}</option>)}</select></td>
                <td style={{ fontSize: 11 }}>
                  {r._sug && (r._sug.uncertain
                    ? <span className="muted" title="규칙 무매칭 — 유저 분류">⚖️ 미상</span>
                    : r._sug.judgment
                    ? <span style={{ color: "var(--warn)" }}
                        title={`제안 ${r._sug.bucket} · ${r._sug.note || "평가목적 재분류 판단 필요"}`}>
                        ⚖️ 판단 → {r._sug.bucket}</span>
                    : <span className={r._sug.conf < 0.7 ? "" : "muted"}
                        style={r._sug.conf < 0.7 ? { color: "var(--warn)" } : {}}
                        title={r._sug.note || `신뢰도 ${(r._sug.conf * 100).toFixed(0)}%`}>
                        {(r._sug.conf * 100).toFixed(0)}%{r._sug.note ? " ⚠" : ""}</span>)}
                </td>
                <td><button className="ghost xs" onClick={() => rm(i)}>✕</button></td>
              </tr>))}</tbody>
          </table>
          <button className="ghost" onClick={add} style={{ marginTop: 6 }}>+ 계정 추가</button>{" "}
          <button className="ghost" onClick={autoClassify} disabled={busy}>
            {busy ? "분류 중…" : "자동 분류 제안"}</button>{" "}
          <button className="primary" onClick={save}>저장</button>
          {err && <div className="err">{err}</div>}
          <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>
            자동 분류는 <b>제안</b>입니다. DART 계정은 표준코드(account_id)로 결정론 분류하고,
            ⚖️ 판단(미지급비용·리스부채·초과현금 등 평가목적 재분류)·⚖️ 미상·⚠ 저신뢰는
            버킷을 자동 확정하지 않으니 직접 확인하세요.</div>
        </div>
      </div>

      <div className="card"><h2>버킷 소계</h2><div className="pad">
        <table><thead><tr><th style={{ textAlign: "left" }}>버킷</th><th>합계</th></tr></thead>
          <tbody>{buckets.map((b) => (
            <tr key={b}><td style={{ textAlign: "left" }}>{b}</td><td>{fmt(subtotals[b] || 0)}</td></tr>))}</tbody>
        </table>
        {isBs && (
          <div style={{ marginTop: 12 }}>
            <div className="finding pass">
              EV→지분가치 브리지: (+)비영업자산 <b>{fmt(noa)}</b> · (−)순차입부채 <b>{fmt(ibd)}</b></div>
            <button className="primary" onClick={pushBridge} style={{ marginTop: 8 }}>
              브리지를 DCF 입력에 반영</button>
          </div>
        )}
      </div></div>
    </>
  );
}
