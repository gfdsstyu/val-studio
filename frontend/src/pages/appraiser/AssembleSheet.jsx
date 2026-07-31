import React, { useState } from "react";
import { api } from "../../api.js";

/* 4.밸류에이션 > 가정 조립 — 2.가정(매출·원가·FA·WC)·3.할인율(WACC) 시트가 저장한
   산출물을 /api/dcf/assemble 의 ops 계약으로 매핑해 엔드투엔드 조립을 실행한다.
   서버가 실행 순서 게이트(PGR≥WACC → dcf_run 차단 등)를 걸고, 성공 시 응답의
   spine 시계열을 DCF 시트 입력(dcf_input)으로 반영 → export·분석적 리뷰·시나리오가
   같은 숫자를 쓰는 왕복 루프가 닫힌다.

   매핑 주의(가정 시트 저장 계약 실측):
   - cogs_pct/sga_pct 는 미저장 — costs_built 절대금액 ÷ revenue_built 로 파생.
   - 자산클래스·WC 정의는 결과 키(fa_built·wc_built)에 없다 — 입력 키(fa_input·
     wc_input, 전부 문자열)에서 재구성.
   - WACC 서브바디는 wacc_input(UI 폼 스냅샷)에서 재조립 — CRP 는 미저장이라
     국가명으로 재조회, pasted_at 은 setup.valuation_date.
   - 연도 수 정합은 시트 간 보장이 없다 — 서버 422 전에 프리플라이트로 잡는다. */

const parseSeries = (s) => String(s || "").split(/[\s,]+/).filter(Boolean).map(Number);
const fmt = (v, d = 0) =>
  v == null || Number.isNaN(v) ? "-" : v.toLocaleString("ko-KR", { maximumFractionDigits: d });

/** 소스 시트별 준비 상태 판정 — 없는 재료는 해당 시트로 안내. */
function sourceStatus(d) {
  return [
    { key: "revenue", label: "매출 벡터", from: "2.가정 › 매출(트리)",
      ok: Array.isArray(d.revenue_built) && d.revenue_built.length > 0,
      note: d.revenue_built ? `${d.revenue_built.length}개년` : "매출 빌드 후 저장 필요" },
    { key: "costs", label: "원가·판관비", from: "2.가정 › 원가·판관비",
      ok: !!(d.costs_built?.cogs?.length && d.costs_built?.sga?.length),
      note: d.costs_built?.cogs ? `${d.costs_built.cogs.length}개년(비율은 매출로 파생)` : "성격별 빌드 필요" },
    { key: "fa", label: "자산클래스·CAPEX", from: "2.가정 › FA",
      ok: Array.isArray(d.fa_input) && d.fa_input.length > 0,
      note: d.fa_input ? `${d.fa_input.length}개 클래스` : "자산클래스 정의 필요" },
    { key: "wc", label: "운전자본 항목", from: "2.가정 › WC",
      ok: !!(d.wc_input?.rows?.length),
      note: d.wc_input?.rows ? `${d.wc_input.rows.length}개 항목` : "WC 항목 정의 필요" },
    { key: "wacc", label: "WACC 원천값", from: "3.할인율 › WACC 빌드업",
      ok: !!(d.wacc_input?.form),
      note: d.wacc_input ? "커넥터 원천값 재조립" : "WACC 빌드업 실행 필요" },
  ];
}

export default function AssembleSheet({ project, onSave }) {
  const d = project?.data || {};
  const di = d.dcf_input || {};
  const sources = sourceStatus(d);
  const ready = sources.every((s) => s.ok);

  // 브리지 4종은 가정 시트가 저장하지 않는다 — DCF 저장본 프리필 + 여기서 확정.
  const [bridge, setBridge] = useState({
    terminal_growth: String(di.terminal_growth ?? "0.02"),
    non_operating_assets: String(di.non_operating_assets ?? "0"),
    net_debt: String(di.net_debt ?? "0"),          // FaSheet 리스 반영 시 number — String 흡수
    shares_outstanding: String(di.shares_outstanding ?? ""),
  });
  const setB = (k) => (e) => setBridge({ ...bridge, [k]: e.target.value });

  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [res, setRes] = useState(null);
  const [applied, setApplied] = useState(false);

  /** wacc_input(폼 스냅샷) → /api/wacc/assemble body 재조립 (DiscountSheet 미러). */
  const buildWaccBody = async () => {
    const w = d.wacc_input, form = w.form || {};
    let crp = 0;
    if (w.country) {
      try { crp = (await api.damodaranCrp(w.country)).crp ?? 0; } catch { crp = 0; }
    }
    const body = {
      risk_free: String(form.risk_free || "").trim(),
      mrp: String(form.mrp || "").trim(),
      peers: (w.peers || []).filter((p) => p.levered_beta !== "").map((p) => ({
        ticker: p.ticker || "?", levered_beta: Number(p.levered_beta),
        debt_to_equity: Number(p.debt_to_equity), tax_rate: Number(p.tax_rate) })),
      target_debt_to_equity: Number(form.target_de),
      tax_rate: Number(form.tax_rate),
      kd_matrix_text: form.kd_matrix_text,
      kd_grade: form.kd_grade, kd_tenor: form.kd_tenor,
      beta_source: form.beta_source || null, beta_market: form.beta_market || null,
      mrp_source: form.mrp_source || null, mrp_market: form.mrp_market || null,
      country_risk_premium: crp,
      pasted_at: project?.setup?.valuation_date || undefined,
    };
    if (String(form.market_cap_musd || "").trim())
      body.market_cap_musd = Number(form.market_cap_musd);
    return body;
  };

  /** 프리플라이트 — 시트 간 연도 수 정합을 서버 422 전에 잡는다(교차검증 부재 보완). */
  const preflight = (revenue) => {
    const years = revenue.length;
    const errs = [];
    if (revenue.some((r) => !(r > 0))) errs.push("매출 ≤ 0 연도 존재 — 비율 파생 불가");
    for (const [name, arr] of [["원가", d.costs_built.cogs], ["판관비", d.costs_built.sga]])
      if (arr.length !== years) errs.push(`${name} ${arr.length}개년 ≠ 매출 ${years}개년 — 원가·판관비 시트 재빌드`);
    for (const r of d.fa_input)
      if (parseSeries(r.capex).length !== years)
        errs.push(`FA '${r.name || "자산"}' CAPEX ${parseSeries(r.capex).length}개년 ≠ ${years}`);
    for (const r of d.wc_input.rows)
      if (parseSeries(r.driver).length !== years)
        errs.push(`WC '${r.name || "항목"}' 드라이버 ${parseSeries(r.driver).length}개년 ≠ ${years}`);
    if (!(Number(bridge.shares_outstanding) > 0)) errs.push("발행주식수를 입력하세요");
    return errs;
  };

  const run = async () => {
    setBusy(true); setErr(null); setRes(null); setApplied(false);
    try {
      const revenue = d.revenue_built.map(Number);
      const pre = preflight(revenue);
      if (pre.length) { setErr(pre.join(" / ")); setBusy(false); return; }
      const ops = {
        revenue,
        cogs_pct: d.costs_built.cogs.map((c, i) => c / revenue[i]),
        sga_pct: d.costs_built.sga.map((s, i) => s / revenue[i]),
        asset_classes: d.fa_input.map((r) => ({
          name: r.name || "자산", opening_net_book: Number(r.opening_net_book),
          remaining_life: Number(r.remaining_life), useful_life: Number(r.useful_life) })),
        new_capex_by_class: Object.fromEntries(
          d.fa_input.map((r) => [r.name || "자산", parseSeries(r.capex)])),
        wc_items: d.wc_input.rows.map((r) => ({
          name: r.name || "항목", base_balance: Number(r.base_balance),
          base_driver: Number(r.base_driver), is_asset: !!r.is_asset })),
        wc_driver_by_item: Object.fromEntries(
          d.wc_input.rows.map((r) => [r.name || "항목", parseSeries(r.driver)])),
        base_net_working_capital: Number(d.wc_input.base_nwc) || 0,
        terminal_growth: Number(bridge.terminal_growth),
        non_operating_assets: Number(bridge.non_operating_assets) || 0,
        net_debt: Number(bridge.net_debt) || 0,
        shares_outstanding: Number(bridge.shares_outstanding),
      };
      const maint = Object.fromEntries(d.fa_input
        .filter((r) => String(r.maintenance || "").trim())
        .map((r) => [r.name || "자산", parseSeries(r.maintenance)]));
      if (Object.keys(maint).length) ops.maintenance_capex_by_class = maint;
      setRes(await api.dcfAssemble({ wacc: await buildWaccBody(), ops }));
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  /** spine → dcf_input 반영(콤마 문자열·반올림 — 각 시트 pushToDcf 관용구와 동일). */
  const apply = () => {
    if (!res?.spine) return;
    const s = res.spine;
    onSave?.({ dcf_input: { ...di,
      wacc: String(res.wacc),
      terminal_growth: bridge.terminal_growth,
      non_operating_assets: bridge.non_operating_assets,
      net_debt: bridge.net_debt,
      shares_outstanding: bridge.shares_outstanding,
      revenue: s.revenue.map(Math.round).join(", "),
      cogs: s.cogs.map(Math.round).join(", "),
      sga: s.sga.map(Math.round).join(", "),
      dep_amort: s.dep_amort.map(Math.round).join(", "),
      capex: s.capex.map(Math.round).join(", "),
      delta_nwc_cash_adj: s.delta_nwc_cash_adj.map(Math.round).join(", "),
    }});
    setApplied(true);
  };

  const nonPass = res ? res.findings.filter((f) => f.severity !== "pass") : [];
  const provKeys = res ? Object.keys(res.provenance || {}) : [];

  return (
    <>
      <div className="card">
        <h2>가정 조립 <span className="muted">— 2.가정 + 3.할인율 → 엔드투엔드 DCF (서버 게이트 내장)</span></h2>
        <div className="pad">
          <table>
            <thead><tr><th style={{ textAlign: "left" }}>재료</th><th style={{ textAlign: "left" }}>출처 시트</th><th>상태</th></tr></thead>
            <tbody>
              {sources.map((s) => (
                <tr key={s.key}>
                  <th style={{ textAlign: "left" }}>{s.label}</th>
                  <td style={{ textAlign: "left" }} className="muted">{s.from}</td>
                  <td><span className={`finding ${s.ok ? "pass" : "warn"}`}
                    style={{ margin: 0, padding: "1px 8px", fontSize: 11 }}>
                    {s.ok ? s.note : s.note}</span></td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3 style={{ fontSize: 12, color: "var(--sub)", margin: "12px 0 4px" }}>
            브리지 (가정 시트 밖 — 여기서 확정)
          </h3>
          <div className="grid2">
            <div className="row"><label>영구성장률 PGR</label>
              <input type="text" value={bridge.terminal_growth} onChange={setB("terminal_growth")} /></div>
            <div className="row"><label>비영업자산 (백만원)</label>
              <input type="text" value={bridge.non_operating_assets} onChange={setB("non_operating_assets")} /></div>
            <div className="row"><label>순차입부채 (백만원)</label>
              <input type="text" value={bridge.net_debt} onChange={setB("net_debt")} /></div>
            <div className="row"><label>발행주식수 (주)</label>
              <input type="text" value={bridge.shares_outstanding} onChange={setB("shares_outstanding")} /></div>
          </div>

          <button className="primary" onClick={run} disabled={busy || !ready}>
            {busy ? "조립 중…" : "엔드투엔드 조립 실행"}
          </button>
          {!ready && <div className="muted" style={{ marginTop: 6, fontSize: "0.82rem" }}>
            위 재료가 전부 준비돼야 실행됩니다 — 각 출처 시트에서 빌드·저장하세요.</div>}
          {err && <div className="err" style={{ marginTop: 10 }}>{err}</div>}
        </div>
      </div>

      {res && (
        <div className="card">
          <h2>조립 결과 {res.blocked && <span className="muted">— 게이트 차단</span>}</h2>
          <div className="pad">
            {res.blocked && (
              <div className="finding fail">게이트 FAIL — 결과가 생성되지 않았습니다.
                아래 findings 의 원인을 해소한 뒤 재실행하세요.</div>
            )}
            {!res.blocked && (
              <div className="kpis">
                <div className="kpi hero"><div className="v">{fmt(res.per_share)} 원</div><div className="k">주당가치</div></div>
                <div className="kpi"><div className="v">{fmt(res.enterprise_value)}</div><div className="k">EV (백만원)</div></div>
                <div className="kpi"><div className="v">{res.wacc != null ? (res.wacc * 100).toFixed(2) + "%" : "-"}</div><div className="k">WACC(조립)</div></div>
                <div className="kpi"><div className="v">{res.tv_weight != null ? (res.tv_weight * 100).toFixed(1) + "%" : "-"}</div><div className="k">TV 비중</div></div>
              </div>
            )}
            {nonPass.map((f, i) => (
              <div key={i} className={`finding ${f.severity}`}>
                <b>[{f.severity.toUpperCase()}] {f.rule}</b> — {f.message}
              </div>
            ))}
            {provKeys.length > 0 && (
              <details style={{ marginTop: 8 }}>
                <summary className="muted" style={{ cursor: "pointer", fontSize: 13 }}>
                  출처(provenance) {provKeys.length}건</summary>
                <table><tbody>
                  {provKeys.map((k) => (
                    <tr key={k}><th style={{ textAlign: "left", width: 140 }}>{k}</th>
                      <td style={{ textAlign: "left" }} className="muted">{res.provenance[k]}</td></tr>
                  ))}
                </tbody></table>
              </details>
            )}
            {!res.blocked && res.spine && (
              <div style={{ marginTop: 12 }}>
                <button className="primary" disabled={applied} onClick={apply}>
                  {applied ? "반영됨 ✓" : "DCF 입력으로 반영"}
                </button>
                <div className="muted" style={{ fontSize: "0.82rem", marginTop: 4 }}>
                  조립된 스파인 6개 시계열 + WACC·브리지를 4.밸류에이션 › DCF 입력에 저장
                  — export·분석적 리뷰·시나리오가 같은 숫자를 씁니다.
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
