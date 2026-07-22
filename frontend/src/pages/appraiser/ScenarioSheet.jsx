import React, { useState } from "react";
import { api } from "../../api.js";

/* 4.밸류에이션 > 시나리오 — /api/scenario 배선.
   base DCF 입력(저장본)에서 매출·원가·판관비를 같은 배수로 스케일해 하방/기준/상방
   3케이스 파생(마진 보존=볼륨 시나리오). 가중치 합=1(백엔드 강제·암묵균등 금지)을
   클라이언트도 검증. 서버 run_scenarios → 케이스별 주당가치·spread·가중종합. */

const parseSeries = (s) =>
  String(s).split(/[\s,]+/).filter(Boolean).map(Number);
const fmt = (v) =>
  v == null || Number.isNaN(v) ? "-" : Math.round(v).toLocaleString("ko-KR");

const DEFAULT_CASES = [
  { key: "down", name: "하방", scale: "0.9", weight: "0.25" },
  { key: "base", name: "기준", scale: "1.0", weight: "0.50" },
  { key: "up", name: "상방", scale: "1.1", weight: "0.25" },
];

export default function ScenarioSheet({ project, onSave }) {
  const base = project?.data?.dcf_input;
  const [cases, setCases] = useState(project?.data?.scenario_cases || DEFAULT_CASES);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const setCase = (i, k) => (e) => {
    const next = cases.slice();
    next[i] = { ...next[i], [k]: e.target.value };
    setCases(next);
  };

  const weightSum = cases.reduce((a, c) => a + (Number(c.weight) || 0), 0);

  /** 선택 숫자필드: 값이 있을 때만 키를 넣는다(빈 문자열 → 서버 500 방지). */
  const num = (k) => (base?.[k]?.toString().trim() ? { [k]: Number(base[k]) } : {});

  const buildSpine = (scale) => {
    const s = Number(scale);
    return {
      wacc: Number(base.wacc),
      terminal_growth: Number(base.terminal_growth),
      revenue: parseSeries(base.revenue).map((v) => v * s),
      cogs: parseSeries(base.cogs).map((v) => v * s),
      sga: parseSeries(base.sga).map((v) => v * s),
      dep_amort: parseSeries(base.dep_amort),
      capex: parseSeries(base.capex),
      delta_nwc_cash_adj: parseSeries(base.delta_nwc_cash_adj),
      non_operating_assets: Number(base.non_operating_assets),
      net_debt: Number(base.net_debt),
      non_controlling_interest: Number(base.non_controlling_interest) || 0,
      shares_outstanding: Number(base.shares_outstanding),
      // ⚠️ 터미널·페이드 구조를 빠뜨리면 시나리오가 DCF 와 **다른 모델**이 된다.
      // Dashboard 는 둘을 같은 막대차트에 나란히 놓으므로, 구조 차이가 시나리오
      // 효과로 오독된다(실측 Δ-13.2% 가 전부 구조 차이였던 사례).
      ...num("terminal_discount_period"),
      ...num("terminal_wc_ratio"),
      ...num("fade_years"),
      ...num("fade_growth"),
      ...(base.terminal_from_last_fcff ? { terminal_from_last_fcff: true } : {}),
    };
  };

  const run = async () => {
    if (Math.abs(weightSum - 1) > 1e-6) {
      setErr(`가중치 합이 1이 아닙니다(현재 ${weightSum.toFixed(2)}). 암묵 균등배분은 금지됩니다.`);
      return;
    }
    setBusy(true); setErr(null); setRes(null);
    const body = { cases: {}, weights: {} };
    for (const c of cases) {
      body.cases[c.name] = buildSpine(c.scale);
      body.weights[c.name] = Number(c.weight);
    }
    try {
      const d = await api.scenario(body);
      setRes(d);
      onSave?.({ scenario_cases: cases, scenario_summary: {
        weighted_per_share: d.weighted_per_share,
        spread: d.spread,
      }});
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (!base) {
    return (
      <div className="card"><div className="pad muted">
        먼저 <b>4. 밸류에이션 › DCF</b> 에서 기준 케이스를 계산·저장하세요 —
        시나리오는 그 입력을 스케일해 파생합니다.
      </div></div>
    );
  }

  return (
    <>
      <div className="card">
        <h2>시나리오 <span className="muted">— 매출·원가·판관비 볼륨 스케일(마진 보존)</span></h2>
        <div className="pad">
          <div className="muted" style={{ marginBottom: 10 }}>
            기준 DCF 입력을 케이스별 배수로 스케일합니다. 가중치 합은 <b>1</b> 이어야
            합니다(암묵 균등배분 금지).
          </div>
          <table>
            <thead><tr><th>케이스</th><th>매출 배수</th><th>가중치</th></tr></thead>
            <tbody>
              {cases.map((c, i) => (
                <tr key={c.key}>
                  <td><input type="text" value={c.name} onChange={setCase(i, "name")} /></td>
                  <td><input type="text" value={c.scale} onChange={setCase(i, "scale")} /></td>
                  <td><input type="text" value={c.weight} onChange={setCase(i, "weight")} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className={`muted ${Math.abs(weightSum - 1) > 1e-6 ? "err" : ""}`}
            style={{ marginTop: 6 }}>
            가중치 합: {weightSum.toFixed(2)} {Math.abs(weightSum - 1) < 1e-6 ? "✓" : "(1이어야 함)"}
          </div>
          <button className="primary" onClick={run} disabled={busy} style={{ marginTop: 8 }}>
            {busy ? "계산 중…" : "시나리오 실행"}
          </button>
          {err && <div className="err">{err}</div>}
        </div>
      </div>

      {res && (
        <div className="card">
          <h2>결과</h2>
          <div className="pad">
            <div className="kpis">
              <div className="kpi hero"><div className="v">{fmt(res.weighted_per_share)} 원</div>
                <div className="k">가중 주당가치</div></div>
              <div className="kpi"><div className="v">{fmt(res.spread[0])}–{fmt(res.spread[1])}</div>
                <div className="k">범위 (하방–상방)</div></div>
            </div>
            <table style={{ marginTop: 12 }}>
              <thead><tr><th>케이스</th><th>가중치</th><th>주당가치</th><th>EV</th><th>TV 비중</th></tr></thead>
              <tbody>
                {res.rows.map((r, i) => (
                  <tr key={i}>
                    <td style={{ textAlign: "left" }}>{r.name}</td>
                    <td>{(r.weight * 100).toFixed(0)}%</td>
                    <td><b>{fmt(r.per_share)}</b></td>
                    <td>{fmt(r.enterprise_value)}</td>
                    <td>{r.tv_weight != null && !Number.isNaN(r.tv_weight)
                      ? (r.tv_weight * 100).toFixed(1) + "%" : "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
