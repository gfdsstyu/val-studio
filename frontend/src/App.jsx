import React, { useState } from "react";

/* 셸 구조(docs/design_system.md §4): 헤더 + 다크 LNB(활성=버건디 좌측 실선)
   + 본문 + 하단 시트탭. 색 통제: 브랜드는 액션 버튼·활성 표시·핵심 KPI 만. */

/** BYOK: 키는 localStorage 에만 — 서버는 요청 헤더로 통과만 받는다. */
const KEYS = { gemini: "byok_gemini_key", anthropic: "byok_anthropic_key" };
const loadKey = (k) => localStorage.getItem(KEYS[k]) || "";
const saveKey = (k, v) => localStorage.setItem(KEYS[k], v);

function ByokPanel() {
  const [gemini, setGemini] = useState(loadKey("gemini"));
  const [anthropic, setAnthropic] = useState(loadKey("anthropic"));
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);

  const save = () => {
    saveKey("gemini", gemini.trim());
    saveKey("anthropic", anthropic.trim());
    setStatus({ msg: "저장됨 (이 브라우저 localStorage 에만)", ok: true });
  };

  const validate = async () => {
    setBusy(true); setStatus(null);
    try {
      const r = await fetch("/api/keys/validate", {
        method: "POST",
        headers: { "X-Gemini-Key": gemini.trim() },
      });
      const d = await r.json();
      setStatus(d.valid
        ? { msg: "Gemini 키 유효 ✓", ok: true }
        : { msg: `Gemini 키 무효 (HTTP ${d.status ?? "?"})`, ok: false });
    } catch (e) {
      setStatus({ msg: `검증 실패: ${e.message}`, ok: false });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <h2>BYOK — API 키 (클라이언트 보관, 서버 미저장)</h2>
      <div className="pad">
        <div className="grid2">
          <div className="row">
            <label>Gemini API Key (딥서치·임베딩)</label>
            <input type="password" value={gemini} placeholder="AI Studio 키"
              onChange={(e) => setGemini(e.target.value)} />
          </div>
          <div className="row">
            <label>Anthropic API Key (판단 보조 — 추후 배선)</label>
            <input type="password" value={anthropic} placeholder="sk-ant-…"
              onChange={(e) => setAnthropic(e.target.value)} />
          </div>
        </div>
        <button className="primary" onClick={save}>저장</button>{" "}
        <button className="ghost" onClick={validate} disabled={busy || !gemini.trim()}>
          {busy ? "검증 중…" : "Gemini 키 검증"}
        </button>
        {status && <div className={status.ok ? "ok" : "bad"} style={{ marginTop: 8 }}>{status.msg}</div>}
      </div>
    </div>
  );
}

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

function DcfCalculator() {
  const [form, setForm] = useState(DEMO);
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
      const r = await fetch("/api/dcf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      setRes(d);
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
              <input type="text" value={form.wacc} onChange={set("wacc")} /></div>
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

/* 워크플로우 네비 정의 — 준비중 화면은 disabled (단계↔화면 매핑) */
const NAV = [
  { group: "설정", items: [{ id: "byok", label: "API 키 (BYOK)" }] },
  {
    group: "평가 워크플로우",
    items: [
      { id: "brief", label: "0. Company Brief", soon: true },
      { id: "peer", label: "3b. 유사회사 선정", soon: true },
      { id: "dcf", label: "4. DCF 계산" },
      { id: "scenario", label: "4b. 시나리오", soon: true },
    ],
  },
  {
    group: "감사인 트랙",
    items: [{ id: "diff", label: "xlsx 왕복 diff", soon: true }],
  },
];

const SCREENS = {
  byok: { title: "API 키 (BYOK)", el: <ByokPanel /> },
  dcf: { title: "DCF 계산", el: <DcfCalculator /> },
};

export default function App() {
  const [page, setPage] = useState("dcf");
  const flat = NAV.flatMap((g) => g.items);
  const current = flat.find((i) => i.id === page);

  return (
    <div className="shell">
      <div className="header">
        <span className="logo">val<b>·</b>studio</span>
        <span className="screen">{current?.label}</span>
        <span className="mode">LOCAL · BYOK · 판단은 유저, 계산은 엔진</span>
      </div>

      <div className="body">
        <nav className="lnb">
          {NAV.map((g) => (
            <div key={g.group}>
              <div className="group">{g.group}</div>
              {g.items.map((it) => (
                <button key={it.id} disabled={it.soon}
                  className={page === it.id ? "active" : ""}
                  onClick={() => setPage(it.id)}>
                  {it.label}{it.soon && <span className="soon">준비중</span>}
                </button>
              ))}
            </div>
          ))}
        </nav>

        <main className="main">
          <div className="main-inner">
            {SCREENS[page]?.el ?? <div className="placeholder">준비중</div>}
          </div>
        </main>
      </div>

      <div className="sheettabs">
        {flat.map((it) => (
          <button key={it.id} disabled={it.soon}
            className={page === it.id ? "active" : ""}
            onClick={() => setPage(it.id)}>
            {it.label}
          </button>
        ))}
      </div>
    </div>
  );
}
