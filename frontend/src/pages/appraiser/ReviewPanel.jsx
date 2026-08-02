import React, { useState } from "react";
import { api } from "../../api.js";
import { loadKey } from "../Byok.jsx";

/* 4.밸류에이션 > 분석적 리뷰 — L3 계층(ISA 520 동형): 실적×추정 탑다운 검사.
   항등식 게이트(audit)와 축이 다르다 — 잘못된 비율로도 항등식은 성립하므로,
   비율을 실적→추정 시계열로 늘어놓고 튀는 지점(접합부·V자·믹스·단위경제)을 본다.
   실적은 DART 다개년 자동 수급(BYOK), 추정은 DCF 시트 저장본(dcf_input) 재사용. */

const parseSeries = (s) => String(s || "").split(/[\s,]+/).filter(Boolean).map(Number);
const pp = (v) => (v == null ? "-" : (v * 100).toFixed(1) + "%p");
const won = (v) => (v == null ? "-" : Math.round(v).toLocaleString("ko-KR"));

/** 리뷰 리포트 4층 판정(방법론/구조/실행/검산) 중 L3 가 태깅하는 층위 라벨. */
const LAYER_LABEL = {
  execution: "실행 층위 — 참조·합산 오류 의심",
  judgment: "판단 층위 — 가정(근거 요구)",
  "execution|judgment": "실행 또는 판단 — 분해 역추적 필요",
};

/** DCF 저장본(콤마 문자열 직렬화) → 스파인 body. 시계열 없으면 null. */
function spineFromSaved(di) {
  if (!di) return null;
  const spine = {
    wacc: Number(di.wacc),
    terminal_growth: Number(di.terminal_growth),
    non_operating_assets: Number(di.non_operating_assets) || 0,
    net_debt: Number(di.net_debt) || 0,
    non_controlling_interest: Number(di.non_controlling_interest) || 0,
    shares_outstanding: Number(di.shares_outstanding) || 0,
  };
  for (const k of ["revenue", "cogs", "sga", "dep_amort", "capex", "delta_nwc_cash_adj"])
    spine[k] = parseSeries(di[k]);
  return spine.revenue.length ? spine : null;
}

/** 실적(실선)→추정(점선 이후) 비율 스파크라인 — 접합부에 세로 점선. 수제 SVG. */
function Sparkline({ actuals = [], forecast = [] }) {
  const all = [...actuals, ...forecast];
  if (all.length < 2) return null;
  const W = 220, H = 40, P = 4;
  const min = Math.min(...all), max = Math.max(...all);
  const span = max - min || 1;
  const x = (i) => P + (i * (W - 2 * P)) / (all.length - 1);
  const y = (v) => H - P - ((v - min) * (H - 2 * P)) / span;
  const pts = (arr, off) => arr.map((v, i) => `${x(i + off)},${y(v)}`).join(" ");
  const seamIdx = actuals.length - 1;
  const fcWithSeam = actuals.length ? [actuals[seamIdx], ...forecast] : forecast;
  return (
    <svg width={W} height={H} style={{ display: "block", margin: "4px 0" }}>
      {actuals.length > 0 && forecast.length > 0 && (
        <line x1={x(seamIdx)} y1={0} x2={x(seamIdx)} y2={H}
          stroke="var(--line)" strokeDasharray="3 2" />
      )}
      <polyline points={pts(actuals, 0)} fill="none"
        stroke="var(--brand)" strokeWidth="1.5" />
      <polyline points={pts(fcWithSeam, Math.max(seamIdx, 0))} fill="none"
        stroke="var(--warn, #c49b47)" strokeWidth="1.5" />
    </svg>
  );
}

function FindingRow({ f }) {
  const d = f.detail || {};
  return (
    <div className={`finding ${f.severity}`}>
      <b>[{f.severity.toUpperCase()}] {f.rule}</b> — {f.message}
      {f.rule === "ratio_seam" && Array.isArray(d.actuals) && (
        <Sparkline actuals={d.actuals} forecast={d.forecast} />
      )}
      {f.rule === "spike_revert" && Array.isArray(d.series) && (
        <Sparkline actuals={d.series} forecast={[]} />
      )}
    </div>
  );
}

/** ΔOPM = ΔGPM 기여 − Δ판관비율 기여 (실적 구간) — 리뷰어의 첫 질문에 답하는 표. */
function OpmBridgeTable({ rows, years }) {
  if (!rows?.length) return null;
  return (
    <table>
      <thead><tr><th>연도</th><th>ΔGPM 기여</th><th>Δ판관비율 기여</th><th>ΔOPM</th><th>OPM</th></tr></thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            <th>{years?.[r.t] ?? `t=${r.t}`}</th>
            <td>{pp(r.gpm_contrib)}</td>
            <td>{pp(r.sga_contrib)}</td>
            <td><b>{pp(r.d_opm)}</b></td>
            <td className="muted">{pp(r.opm_from)} → {pp(r.opm_to)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function MixTable({ mix, years }) {
  if (!mix?.steps?.length) return null;
  return (
    <table>
      <thead><tr><th>연도</th><th>믹스 효과</th><th>부문 원가율 효과</th><th>Δ전체 원가율</th></tr></thead>
      <tbody>
        {mix.steps.map((s, i) => (
          <tr key={i}>
            <th>{years?.[s.t] ?? `t=${s.t}`}</th>
            <td>{pp(s.mix_effect)}</td>
            <td>{pp(s.rate_effect)}</td>
            <td><b>{pp(s.total)}</b></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** 오류 영향 분리 원장 — 수정을 한 건씩 적용·재계산해 상쇄 은폐를 해소. */
function LedgerCard({ spine }) {
  const EXAMPLE = JSON.stringify(
    [{ label: "ΔNWC 복원", fields: { delta_nwc_cash_adj: [-3759, -3000, -3500, -3800, -4000] } }],
    null, 2);
  const [txt, setTxt] = useState("");
  const [rows, setRows] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const run = async () => {
    setBusy(true); setErr(null); setRows(null);
    try {
      const patches = JSON.parse(txt);
      const d = await api.review.ledger({ spine, patches });
      setRows(d.ledger);
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <div className="card">
      <h2>오류 영향 분리 원장 <span className="muted">— 수정 1건씩 적용→재계산→Δ 기록</span></h2>
      <div className="pad">
        <div className="muted" style={{ marginBottom: 8, fontSize: "0.82rem" }}>
          반대 방향 오류들은 순 효과에서 서로를 가립니다 — 분리 측정하지 않으면 "결함이
          사소했다"로 오독됩니다. 패치는 DCF 입력 필드 오버라이드(JSON), 적용 순서는
          상류→하류 권장.
        </div>
        {!spine && <div className="muted">DCF 저장본이 없어 원장을 돌릴 수 없습니다 —
          먼저 4.밸류에이션 › DCF 에서 계산·저장하세요.</div>}
        {spine && (
          <>
            <textarea rows={5} style={{ width: "100%", fontFamily: "monospace", fontSize: 12 }}
              value={txt} placeholder={EXAMPLE} onChange={(e) => setTxt(e.target.value)} />
            <button className="primary" style={{ marginTop: 8 }} disabled={busy || !txt.trim()}
              onClick={run}>{busy ? "계산 중…" : "원장 실행"}</button>
            {err && <div className="err" style={{ marginTop: 8 }}>{err}</div>}
            {rows && (
              <table style={{ marginTop: 10 }}>
                <thead><tr><th>수정 항목</th><th>주당가치</th><th>Δ(직전 대비)</th><th>누적 Δ</th></tr></thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={i}>
                      <th style={{ textAlign: "left" }}>{r.label}</th>
                      <td>{won(r.per_share)} 원</td>
                      <td style={r.delta < 0 ? { color: "var(--err)" } : {}}>{i === 0 ? "-" : won(r.delta)}</td>
                      <td>{i === 0 ? "-" : won(r.cum_delta)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default function ReviewPanel({ project, onSave }) {
  const d = project?.data || {};
  const spine = spineFromSaved(d.dcf_input);
  const [corp, setCorp] = useState(d.dart_query?.corp_code || "");
  const baseYear = Number(d.dart_query?.year) || 2023;
  const [yearFrom, setYearFrom] = useState(String(baseYear - 4));
  const [yearTo, setYearTo] = useState(String(baseYear));
  const [fsDiv, setFsDiv] = useState("CFS");
  const [withEmp, setWithEmp] = useState(true);
  const [consensus, setConsensus] = useState([]);
  const [busy, setBusy] = useState(false);
  const [prog, setProg] = useState("");
  const [err, setErr] = useState(null);
  const [res, setRes] = useState(null);
  const key = loadKey("dart");

  const setCon = (i, k) => (e) => {
    const next = consensus.slice();
    next[i] = { ...next[i], [k]: e.target.value };
    setConsensus(next);
  };

  const run = async () => {
    if (!key) { setErr("BYOK 탭에서 DART API 키를 먼저 저장하세요."); return; }
    if (!corp.trim()) { setErr("corp_code(8자리)를 입력하세요."); return; }
    const from = Number(yearFrom), to = Number(yearTo);
    if (!(from <= to && to - from < 10)) { setErr("연도 범위를 확인하세요(최대 10개년)."); return; }
    setBusy(true); setErr(null); setRes(null);
    const dartYears = [], empYears = [], skipped = [];
    try {
      for (let y = from; y <= to; y++) {
        setProg(`${y} 재무제표 조회 중…`);
        try {
          const fin = await api.dartFinancials(key,
            { corp_code: corp.trim(), year: String(y), fs_div: fsDiv });
          dartYears.push({ year: y, accounts: fin.accounts });
        } catch { skipped.push(y); continue; }
        if (withEmp) {
          try {
            const e2 = await api.dartEmployee(key,
              { corp_code: corp.trim(), bsns_year: String(y) });
            empYears.push({ year: y, headcount: e2.headcount, total_salary: e2.total_salary });
          } catch { /* 직원현황 없으면 인당 검사만 생략 */ }
        }
      }
      if (!dartYears.length) throw new Error("조회된 연도가 없습니다 — corp_code·연도를 확인하세요.");
      setProg("분석적 절차 실행 중…");
      const conRows = consensus.filter((c) => c.metric && c.own && c.consensus)
        .map((c) => ({ metric: c.metric, own: Number(c.own),
          consensus: Number(c.consensus), source: c.source || "" }));
      const body = { dart_years: dartYears };
      if (empYears.length) body.employee_years = empYears;
      if (spine) body.spine = spine;
      if (conRows.length) body.consensus = conRows;
      const out = await api.review.analytical(body);
      setRes({ ...out, skipped });
      // 비-pass findings 를 근거 패널·대시보드로 표면화(detail 은 화면 전용이라 제외).
      onSave?.({
        review_summary: { warn: out.warn_count, years: out.years,
          checks: out.findings.length },
        review_findings: out.findings.filter((f) => f.severity !== "pass")
          .map(({ rule, severity, message }) => ({ rule, severity, message })),
      });
    } catch (e) { setErr(e.message); } finally { setBusy(false); setProg(""); }
  };

  const groups = res
    ? res.findings.reduce((m, f) => {
        const k = (f.detail || {}).layer || "기타";
        (m[k] = m[k] || []).push(f); return m;
      }, {})
    : {};
  const nonPass = res ? res.findings.filter((f) => f.severity !== "pass") : [];

  return (
    <>
      <div className="card">
        <h2>분석적 리뷰 <span className="muted">— 실적×추정 시계열 연속성(L3, ISA 520 동형)</span></h2>
        <div className="pad">
          <div className="muted" style={{ marginBottom: 10, fontSize: "0.82rem" }}>
            항등식 검산은 잘못된 비율로도 통과합니다. 이 검사는 <b>비율의 시계열</b>을
            봅니다 — 실적↔추정 접합부 계단(±3%p), 한 해만 튀는 V자(참조 밀림 시그니처),
            부문 믹스 재현, 인당 인건비(±10%), 컨센서스 앵커.
          </div>
          {!key && <div className="finding warn">BYOK 탭에서 OpenDART API 키를 저장해야 실적을 수급합니다.</div>}
          <div className={`finding ${spine ? "pass" : "warn"}`}>
            {spine
              ? `추정: DCF 저장본 사용 (${spine.revenue.length}개년) — 접합부·성장-운전자본 검사 가동`
              : "추정 저장본 없음 — 실적 구간 검사만 수행합니다. 접합부 검사는 4.밸류에이션 › DCF 저장 후."}
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end", marginTop: 8 }}>
            <div className="row" style={{ margin: 0 }}><label>corp_code</label>
              <input type="text" value={corp} onChange={(e) => setCorp(e.target.value)}
                placeholder="0.자료·Brief에서 검색" style={{ width: 110 }} /></div>
            <div className="row" style={{ margin: 0 }}><label>실적 시작연도</label>
              <input type="text" value={yearFrom} onChange={(e) => setYearFrom(e.target.value)} style={{ width: 70 }} /></div>
            <div className="row" style={{ margin: 0 }}><label>종료연도</label>
              <input type="text" value={yearTo} onChange={(e) => setYearTo(e.target.value)} style={{ width: 70 }} /></div>
            <div className="row" style={{ margin: 0 }}><label>연결/별도</label>
              <select value={fsDiv} onChange={(e) => setFsDiv(e.target.value)} style={{ fontSize: 12 }}>
                <option value="CFS">연결(CFS)</option><option value="OFS">별도(OFS)</option></select></div>
            <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12 }}>
              <input type="checkbox" checked={withEmp}
                onChange={(e) => setWithEmp(e.target.checked)} /> 직원현황(인당 인건비)
            </label>
            <button className="primary" onClick={run} disabled={busy}>
              {busy ? (prog || "실행 중…") : "실적 수급 + 리뷰 실행"}
            </button>
          </div>

          <details style={{ marginTop: 10 }}>
            <summary style={{ cursor: "pointer", fontSize: 13 }}>
              컨센서스 앵커 (선택 — 증권사 추정 대조){consensus.length ? ` · ${consensus.length}건` : ""}
            </summary>
            {consensus.map((c, i) => (
              <div key={i} style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
                <input type="text" placeholder="지표 (예 GPM 2024E)" value={c.metric || ""}
                  onChange={setCon(i, "metric")} style={{ width: 140 }} />
                <input type="text" placeholder="자기 추정 (0.712)" value={c.own || ""}
                  onChange={setCon(i, "own")} style={{ width: 110 }} />
                <input type="text" placeholder="컨센서스 (0.78)" value={c.consensus || ""}
                  onChange={setCon(i, "consensus")} style={{ width: 110 }} />
                <input type="text" placeholder="출처 (필수)" value={c.source || ""}
                  onChange={setCon(i, "source")} style={{ width: 160 }} />
                <button className="ghost xs" onClick={() => setConsensus(consensus.filter((_, j) => j !== i))}>✕</button>
              </div>
            ))}
            <button className="ghost xs" style={{ marginTop: 6 }}
              onClick={() => setConsensus([...consensus, {}])}>+ 앵커 추가</button>
          </details>
          {err && <div className="err" style={{ marginTop: 10 }}>{err}</div>}
        </div>
      </div>

      {res && (
        <div className="card">
          <h2>판정 <span className="muted">— 층위별(4층 판정 프레임의 L3 기여분)</span></h2>
          <div className="pad">
            <div className="kpis">
              <div className="kpi"><div className="v">{res.findings.length}</div><div className="k">검사</div></div>
              <div className="kpi"><div className="v" style={res.warn_count ? { color: "var(--warn)" } : {}}>{res.warn_count}</div><div className="k">WARN</div></div>
              <div className="kpi"><div className="v">{res.years.join("–")}</div><div className="k">실적 연도</div></div>
            </div>
            {(res.assembly_notes.length > 0 || res.skipped?.length > 0) && (
              <div className="muted" style={{ margin: "8px 0", fontSize: "0.82rem" }}>
                {res.skipped?.length > 0 && <div>· 조회 실패 연도 제외: {res.skipped.join(", ")}</div>}
                {res.assembly_notes.map((n, i) => <div key={i}>· {n}</div>)}
              </div>
            )}
            {nonPass.length === 0 && (
              <div className="finding pass">경고 없음 — 시계열 연속성 전 검사 통과</div>
            )}
            {Object.entries(groups).map(([layer, fs]) => {
              const warns = fs.filter((f) => f.severity !== "pass");
              if (!warns.length) return null;
              return (
                <div key={layer} style={{ marginTop: 12 }}>
                  <h3 style={{ fontSize: 12, color: "var(--sub)", margin: "4px 0" }}>
                    {LAYER_LABEL[layer] || layer} — {warns.length}건
                  </h3>
                  {warns.map((f, i) => <FindingRow key={i} f={f} />)}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {res?.bridges?.opm_bridge && (
        <div className="card">
          <h2>마진 브리지 <span className="muted">— ΔOPM = ΔGPM 기여 − Δ판관비율 기여</span></h2>
          <div className="pad">
            <OpmBridgeTable rows={res.bridges.opm_bridge} years={res.years} />
            {res.bridges.mix_decomposition && (
              <>
                <h3 style={{ fontSize: 12, color: "var(--sub)", margin: "12px 0 4px" }}>
                  믹스 분해 — Δ원가율 = 믹스 효과 + 부문 원가율 효과 (잔차 0 완전분해)
                </h3>
                <MixTable mix={res.bridges.mix_decomposition} years={res.years} />
              </>
            )}
          </div>
        </div>
      )}

      <LedgerCard spine={spine} />
    </>
  );
}
