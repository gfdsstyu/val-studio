import React, { useState } from "react";
import { api } from "../../api.js";

/* 감사인 2. 독립 재계산 — 감사인이 스스로 세운 입력으로 점추정치를 만들고 주장값과 대조.

   평가자 트랙과 **데이터가 격리**된다(모드 불변 = 감사인 독립성). 여기 입력은
   의견서에서 읽은 가정 + 감사인이 재무제표에서 직접 뽑은 수치이지, 평가자 모델을
   그대로 가져오는 게 아니다. 주장 주당가치를 함께 넣으면 엔진이 구조버그 가설
   진단(diagnose_dcf_gap)까지 붙여준다. */

const parseSeries = (s) => String(s).split(/[\s,]+/).filter(Boolean).map(Number);

const FIELD_LABELS = [
  ["revenue", "매출액"],
  ["cogs", "매출원가"],
  ["sga", "판관비"],
  ["dep_amort", "감가상각비"],
  ["capex", "CAPEX"],
  ["delta_nwc_cash_adj", "운전자본 변동(ΔNWC)"],
];

const BLANK = {
  wacc: "0.10", terminal_growth: "0.01",
  revenue: "0, 0, 0, 0, 0", cogs: "0, 0, 0, 0, 0", sga: "0, 0, 0, 0, 0",
  dep_amort: "0, 0, 0, 0, 0", capex: "0, 0, 0, 0, 0", delta_nwc_cash_adj: "0, 0, 0, 0, 0",
  non_operating_assets: "0", net_debt: "0", shares_outstanding: "0", claimed_per_share: "",
};

const fmt = (v, d = 0) =>
  v == null || Number.isNaN(v) ? "-" : v.toLocaleString("ko-KR", { maximumFractionDigits: d });

function InputsSheet({ project, onSave }) {
  const saved = project?.data?.audit_input;
  const extract = project?.data?.opinion_extract;
  // 의견서에서 뽑힌 영구성장률 후보가 있으면 초기값으로 제안(감사인이 덮어쓸 수 있음).
  const suggestedG = extract?.terminal_growths?.[0];
  const [form, setForm] = useState(() => {
    const init = saved || BLANK;
    return suggestedG != null && !saved
      ? { ...init, terminal_growth: String(suggestedG) } : init;
  });
  const [grid, setGrid] = useState(() =>
    Object.fromEntries(FIELD_LABELS.map(([k]) =>
      [k, parseSeries((saved || BLANK)[k]).map(String)])));
  const [res, setRes] = useState(project?.data?.audit_result || null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const years = grid.revenue.length;
  const setCell = (k, i) => (e) => {
    const next = grid[k].slice();
    next[i] = e.target.value;
    setGrid({ ...grid, [k]: next });
  };
  const addYear = () =>
    setGrid(Object.fromEntries(FIELD_LABELS.map(([k]) => [k, [...grid[k], "0"]])));
  const rmYear = (i) =>
    setGrid(Object.fromEntries(FIELD_LABELS.map(([k]) => [k, grid[k].filter((_, j) => j !== i)])));

  const run = async () => {
    setBusy(true); setErr(null); setRes(null);
    for (const [k, label] of FIELD_LABELS) {
      if (grid[k].some((v) => v.trim() === "" || Number.isNaN(Number(v)))) {
        setErr(`${label}: 숫자가 아닌/빈 셀이 있습니다.`); setBusy(false); return;
      }
    }
    const body = {
      wacc: Number(form.wacc),
      terminal_growth: Number(form.terminal_growth),
      non_operating_assets: Number(form.non_operating_assets),
      net_debt: Number(form.net_debt),
      shares_outstanding: Number(form.shares_outstanding),
    };
    for (const [k] of FIELD_LABELS) body[k] = grid[k].map(Number);
    if (String(form.claimed_per_share).trim())
      body.claimed_per_share = Number(form.claimed_per_share);
    try {
      const d = await api.dcf(body);
      setRes(d);
      const seriesStr = Object.fromEntries(FIELD_LABELS.map(([k]) => [k, grid[k].join(", ")]));
      onSave?.({
        audit_input: { ...form, ...seriesStr },
        audit_result: d,
        audit_claimed: body.claimed_per_share ?? null,
      });
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <>
      <div className="card">
        <h2>입력 재구성 <span className="muted">— 감사인의 독립 추정</span></h2>
        <div className="pad">
          <div className="muted" style={{ marginBottom: 10 }}>
            의견서 가정을 그대로 베끼지 말고, 재무제표·주석에서 감사인이 직접 확인한
            수치로 세우세요. 주장 주당가치를 넣으면 괴리를 구조버그 가설로 진단합니다.
            {suggestedG != null && !saved && (
              <> 영구성장률은 의견서 추출값 <b>{(suggestedG * 100).toFixed(2)}%</b> 를
              초기값으로 넣었습니다 — 감사인이 검증·수정하세요.</>
            )}
          </div>
          <div className="grid2">
            <div className="row"><label>WACC (소수)</label>
              <input type="text" value={form.wacc} onChange={set("wacc")} /></div>
            <div className="row"><label>영구성장률 g</label>
              <input type="text" value={form.terminal_growth}
                onChange={set("terminal_growth")} /></div>
            <div className="row"><label>비영업자산</label>
              <input type="text" value={form.non_operating_assets}
                onChange={set("non_operating_assets")} /></div>
            <div className="row"><label>순차입부채</label>
              <input type="text" value={form.net_debt} onChange={set("net_debt")} /></div>
            <div className="row"><label>발행주식수</label>
              <input type="text" value={form.shares_outstanding}
                onChange={set("shares_outstanding")} /></div>
            <div className="row"><label>주장 주당가치(의견서)</label>
              <input type="text" value={form.claimed_per_share}
                onChange={set("claimed_per_share")} placeholder="예 40600" /></div>
          </div>

          <table style={{ marginTop: 12 }}>
            <thead>
              <tr>
                <th>항목(백만원)</th>
                {Array.from({ length: years }, (_, i) => (
                  <th key={i}>{i + 1}년차 <button onClick={() => rmYear(i)}>×</button></th>
                ))}
                <th><button onClick={addYear}>+연도</button></th>
              </tr>
            </thead>
            <tbody>
              {FIELD_LABELS.map(([k, label]) => (
                <tr key={k}>
                  <th>{label}</th>
                  {grid[k].map((v, i) => (
                    <td key={i}>
                      <input type="text" value={v} onChange={setCell(k, i)}
                        style={{ width: 90 }} />
                    </td>
                  ))}
                  <td />
                </tr>
              ))}
            </tbody>
          </table>

          <button className="primary" style={{ marginTop: 12 }} disabled={busy} onClick={run}>
            {busy ? "계산 중…" : "독립 재계산"}
          </button>
          {err && <div className="err" style={{ marginTop: 10 }}>{err}</div>}
        </div>
      </div>
      {res && <ResultCard res={res} claimed={Number(form.claimed_per_share) || null} />}
    </>
  );
}

function ResultCard({ res, claimed }) {
  const diff = claimed ? res.per_share - claimed : null;
  const pct = claimed ? (diff / claimed) * 100 : null;
  return (
    <div className="card">
      <h2>재계산 vs 주장</h2>
      <div className="pad">
        <div className="grid2">
          <div><div className="muted">감사인 독립 추정</div>
            <div className="kpi">{fmt(res.per_share)} 원</div></div>
          {claimed != null && (
            <div><div className="muted">의견서 주장</div>
              <div className="kpi">{fmt(claimed)} 원</div></div>
          )}
        </div>
        {claimed != null && (
          <div className={Math.abs(pct) > 10 ? "warn-box" : "ok"} style={{ marginTop: 10 }}>
            괴리 <b>{fmt(diff)} 원 ({pct > 0 ? "+" : ""}{pct.toFixed(1)}%)</b>
            {Math.abs(pct) > 10 && " — 유의적 괴리. 3. 괴리 진단에서 원인을 좁히세요."}
          </div>
        )}
        <div className="muted" style={{ marginTop: 10 }}>
          EV {fmt(res.enterprise_value)} · TV 비중{" "}
          {res.tv_weight != null ? `${(res.tv_weight * 100).toFixed(1)}%` : "-"}
        </div>
        {res.gap_diagnosis && (
          <div className="warn-box" style={{ marginTop: 10 }}>
            <b>구조 진단</b> — {res.gap_diagnosis.message}
          </div>
        )}
      </div>
    </div>
  );
}

function ResultSheet({ project }) {
  const res = project?.data?.audit_result;
  if (!res)
    return (
      <div className="card"><div className="pad muted">
        먼저 <b>2. 독립 재계산 › 입력 재구성</b> 에서 재계산을 실행하세요.
      </div></div>
    );
  return <ResultCard res={res} claimed={project?.data?.audit_claimed ?? null} />;
}

export default function IndependentRecalc({ project, sheet, onSave }) {
  return sheet === "result"
    ? <ResultSheet project={project} />
    : <InputsSheet project={project} onSave={onSave} />;
}
