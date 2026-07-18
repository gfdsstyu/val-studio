import React, { useState } from "react";
import { api } from "../../api.js";

/* 4.밸류에이션 > DCF 시트 — 결정론 엔진 호출. 결과는 항상 KPI+게이트 동반.
   ⚠️ 과도기: 입력이 아직 이 시트에 있다 — IA 확정안(hard number 는 2.가정에만)대로
   가정 화면 구현 시 입력부는 그쪽으로 이관하고 여기는 읽기전용+참조 점프가 된다. */

const parseSeries = (s) => s.split(/[\s,]+/).filter(Boolean).map(Number);

const DEMO = {
  wacc: "0.10", terminal_growth: "0.01",
  revenue: "100000, 115000, 132000, 149000, 165000",
  cogs: "40000, 46000, 52800, 59600, 66000",
  sga: "20000, 23000, 26400, 29800, 33000",
  dep_amort: "5000, 5000, 5000, 5000, 5000",
  capex: "5000, 5000, 5000, 5000, 5000",
  delta_nwc_cash_adj: "0, 0, 0, 0, 0",
  non_operating_assets: "20000", net_debt: "10000",
  shares_outstanding: "10000000", claimed_per_share: "",
};

const FIELD_LABELS = [
  ["revenue", "매출액 (백만원, 연도별 콤마 구분)"],
  ["cogs", "매출원가"],
  ["sga", "판관비"],
  ["dep_amort", "감가상각비"],
  ["capex", "CAPEX"],
  ["delta_nwc_cash_adj", "운전자본 변동(ΔNWC)"],
];

const fmt = (v, d = 0) =>
  v == null || Number.isNaN(v) ? "-" : v.toLocaleString("ko-KR", { maximumFractionDigits: d });

function SensitivityTable({ sens }) {
  if (!sens?.per_share) return null;
  const { wacc_axis, g_axis, per_share } = sens;
  const mid = { r: Math.floor(wacc_axis.length / 2), c: Math.floor(g_axis.length / 2) };
  return (
    <table>
      <thead>
        <tr>
          <th>WACC \ PGR</th>
          {g_axis.map((g, i) => <th key={i}>{(g * 100).toFixed(1)}%</th>)}
        </tr>
      </thead>
      <tbody>
        {per_share.map((row, r) => (
          <tr key={r}>
            <th>{(wacc_axis[r] * 100).toFixed(1)}%</th>
            {row.map((v, c) => (
              <td key={c} className={r === mid.r && c === mid.c ? "center-cell" : ""}>
                {fmt(v)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function DcfSheet({ project, onSave }) {
  const saved = project?.data?.dcf_input;
  // 3.할인율 > WACC 빌드업에서 조립·저장된 WACC 를 이어받는다(front-back 배선).
  const assembledWacc = project?.data?.wacc_result?.wacc;
  const [form, setForm] = useState(() => {
    const init = saved || DEMO;
    return assembledWacc != null ? { ...init, wacc: String(assembledWacc) } : init;
  });
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const runDcf = async () => {
    setBusy(true); setErr(null); setRes(null);
    const lens = FIELD_LABELS.map(([k]) => parseSeries(form[k]).length);
    if (new Set(lens).size !== 1) {
      setErr(`연도 수 불일치: ${FIELD_LABELS.map(([k], i) => `${k}=${lens[i]}`).join(", ")}`);
      setBusy(false); return;
    }
    const body = {
      wacc: Number(form.wacc),
      terminal_growth: Number(form.terminal_growth),
      non_operating_assets: Number(form.non_operating_assets),
      net_debt: Number(form.net_debt),
      shares_outstanding: Number(form.shares_outstanding),
    };
    for (const [k] of FIELD_LABELS) body[k] = parseSeries(form[k]);
    if (form.claimed_per_share.trim()) body.claimed_per_share = Number(form.claimed_per_share);
    try {
      const d = await api.dcf(body);
      setRes(d);
      onSave?.({ dcf_input: form, dcf_result_summary: {
        per_share: d.per_share, tv_weight: d.tv_weight,
        warn: d.findings.filter((f) => f.severity !== "pass").length,
      }});
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="card">
        <h2>DCF 입력 <span className="muted">— 결정론 엔진(calc_core)</span></h2>
        <div className="pad">
          <div className="grid2">
            <div className="row"><label>WACC (소수, 예 0.10)</label>
              <input type="text" value={form.wacc} onChange={set("wacc")} />
              {assembledWacc != null && (
                <div className="muted" style={{ fontSize: "0.8rem", marginTop: 2 }}>
                  ↳ 3.할인율 빌드업에서 조립됨: <b>{(assembledWacc * 100).toFixed(2)}%</b> (수정 가능)
                </div>
              )}</div>
            <div className="row"><label>영구성장률 PGR (소수)</label>
              <input type="text" value={form.terminal_growth} onChange={set("terminal_growth")} /></div>
          </div>
          {FIELD_LABELS.map(([k, label]) => (
            <div className="row" key={k}>
              <label>{label}</label>
              <input type="text" value={form[k]} onChange={set(k)} />
            </div>
          ))}
          <div className="grid2">
            <div className="row"><label>비영업자산 (백만원)</label>
              <input type="text" value={form.non_operating_assets} onChange={set("non_operating_assets")} /></div>
            <div className="row"><label>순차입부채 (백만원)</label>
              <input type="text" value={form.net_debt} onChange={set("net_debt")} /></div>
            <div className="row"><label>발행주식수 (주)</label>
              <input type="text" value={form.shares_outstanding} onChange={set("shares_outstanding")} /></div>
            <div className="row"><label>주장 주당가치 (선택 — 감사인 괴리 진단)</label>
              <input type="text" value={form.claimed_per_share} onChange={set("claimed_per_share")}
                placeholder="의견서 주장값(원)" /></div>
          </div>
          <button className="primary" onClick={runDcf} disabled={busy}>
            {busy ? "계산 중…" : "DCF 계산"}
          </button>
          {err && <div className="err">{err}</div>}
        </div>
      </div>

      {res && (
        <div className="card">
          <h2>결과</h2>
          <div className="pad">
            <div className="kpis">
              <div className="kpi hero"><div className="v">{fmt(res.per_share)} 원</div><div className="k">주당가치</div></div>
              <div className="kpi"><div className="v">{fmt(res.enterprise_value)}</div><div className="k">EV (백만원)</div></div>
              <div className="kpi"><div className="v">{fmt(res.equity_value)}</div><div className="k">지분가치 (백만원)</div></div>
              <div className="kpi"><div className="v">{res.tv_weight != null ? (res.tv_weight * 100).toFixed(1) + "%" : "-"}</div><div className="k">TV 비중</div></div>
            </div>

            <h2 style={{ marginTop: 18 }}>가정 타당성 (audit)</h2>
            {res.findings.filter((f) => f.severity !== "pass").length === 0 && (
              <div className="finding pass">경고 없음 — 전 게이트 통과</div>
            )}
            {res.findings.filter((f) => f.severity !== "pass").map((f, i) => (
              <div key={i} className={`finding ${f.severity}`}>
                <b>[{f.severity.toUpperCase()}] {f.rule}</b> — {f.message}
              </div>
            ))}

            {res.gap_diagnosis && (
              <>
                <h2 style={{ marginTop: 18 }}>괴리 구조버그 진단</h2>
                <div className={`finding ${res.gap_diagnosis.severity}`}>{res.gap_diagnosis.message}</div>
              </>
            )}

            <h2 style={{ marginTop: 18 }}>민감도 (WACC × PGR) <span className="muted">— 강조 셀 = base</span></h2>
            <SensitivityTable sens={res.sensitivity} />
          </div>
        </div>
      )}
    </>
  );
}
