import React, { useEffect, useState } from "react";
import { api, fileToBase64 } from "../../api.js";
import { loadKey } from "../Byok.jsx";

/* 3.할인율 > WACC 빌드업 — 커넥터 어셈블리(/api/wacc/assemble) 소비.
   Rf·MRP·Kd 는 복붙(문자열) → 서버가 range 게이트. peers 무부채화·Kroll size·
   β/MRP 시장정합까지 서버 결정론. 여기선 폼이 JSON 만들고 응답(blocked/findings/
   provenance/WACC)을 그린다. 계산 로직 0줄. 확정 WACC 는 프로젝트에 저장돼 DCF 로 흐른다. */

/** Rf 를 한국은행 ECOS(국고채 10년)에서 조회해 **제안**한다.

    자동 주입이 아니라 프리필이다 — 확정은 평가인 몫이고, 채택 시 조회 기간을
    provenance 로 남겨 F3 게이트·가정 대장이 근거를 갖는다(역할 3분할).
    ECOS 키가 없으면 버튼을 숨긴다(복붙 경로가 기본). */
function RfFromEcos({ baseDate, onPick }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const key = loadKey("ecos");
  if (!key) return null;

  const fetchRf = async () => {
    setBusy(true); setErr(null);
    try {
      const end = baseDate || new Date().toISOString().slice(0, 10);
      const d = await api.macroSeries(
        { indicator: "risk_free_10y", start: end.slice(0, 4), end,
          base_date: baseDate || undefined }, key);
      const last = d.observations?.[d.observations.length - 1];
      if (!last) { setErr("가드 통과 관측치 없음 — 복붙을 쓰세요."); return; }
      onPick(`${(last.value * 100).toFixed(2)}%`,
             { period: last.period, source: last.source || "ECOS", indicator: d.indicator });
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <>
      <button className="ghost" disabled={busy} onClick={fetchRf}
        title="한국은행 ECOS 국고채 10년 — 조회 후 평가인이 확정">
        {busy ? "조회 중…" : "ECOS 국고채 조회"}
      </button>
      {err && <span className="err" style={{ fontSize: 12 }}>{err}</span>}
    </>
  );
}

const DEMO = {
  risk_free: "3.45%", mrp: "8",
  target_de: "0.4", tax_rate: "0.22",
  kd_matrix_text: "등급 3Y 5Y\nAAA 3.21 3.48\nAA 4.10 4.35\nBBB 5.40 5.80\n",
  kd_grade: "BBB", kd_tenor: "5Y", market_cap_musd: "1500",
  beta_source: "bloomberg", beta_market: "KOSPI",
  mrp_source: "kicpa", mrp_market: "KOSPI",
};
const DEMO_PEERS = [
  { ticker: "유사사A", levered_beta: "1.20", debt_to_equity: "0.5", tax_rate: "0.22" },
  { ticker: "유사사B", levered_beta: "1.05", debt_to_equity: "0.3", tax_rate: "0.22" },
];

const pct = (v, d = 2) => (v == null ? "-" : (v * 100).toFixed(d) + "%");
const num = (v, d = 3) => (v == null ? "-" : Number(v).toFixed(d));

/** 게이트 리포트 — assemble 응답의 findings 를 severity 색으로. blocked 배너 동반. */
function Findings({ report }) {
  if (!report) return null;
  const nonPass = report.findings.filter((f) => f.severity !== "pass");
  return (
    <>
      {report.blocked ? (
        <div className="finding fail" style={{ borderLeftWidth: 6 }}>
          <b>차단됨</b> — 아래 FAIL 게이트를 통과해야 WACC 가 산출됩니다(복붙 오타·look-ahead·정합 확인).
        </div>
      ) : (
        <div className="finding pass"><b>게이트 통과</b> — 검증된 입력으로 WACC 산출됨.</div>
      )}
      {nonPass.map((f, i) => (
        <div key={i} className={`finding ${f.severity}`}>
          <b>[{f.severity.toUpperCase()}] {f.rule}</b> — {f.message}
        </div>
      ))}
    </>
  );
}

/** provenance — 각 원천의 감사 라벨(어느 복붙/커넥터에서 왔나). */
function Provenance({ prov }) {
  const keys = prov ? Object.keys(prov) : [];
  if (!keys.length) return null;
  return (
    <table>
      <tbody>
        {keys.map((k) => (
          <tr key={k}>
            <th style={{ textAlign: "left", width: 180 }}>{k}</th>
            <td style={{ textAlign: "left" }} className="muted">{prov[k]}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function DiscountSheet({ project, onSave }) {
  const saved = project?.data?.wacc_input;
  const baseDate = project?.setup?.valuation_date;
  const [form, setForm] = useState(saved?.form || DEMO);
  // 유사회사 선정(PeerSheet)에서 확정된 peer 를 프리필 — 선정→무부채화 흐름 연결(재입력 방지).
  // β·D/E 는 비워두고 "주가로 β 계산"(종목코드) 또는 수기 입력.
  const _selected = project?.data?.peer_selected;
  const [peers, setPeers] = useState(
    saved?.peers ||
    (_selected?.length
      ? _selected.map((p) => ({ ticker: p.ticker, levered_beta: "", debt_to_equity: "", tax_rate: "0.22" }))
      : DEMO_PEERS),
  );
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [country, setCountry] = useState(saved?.country || "한국");
  const [countries, setCountries] = useState([]);
  const [crp, setCrp] = useState(null);
  const [rfMeta, setRfMeta] = useState(saved?.rf_meta || null);   // ECOS Rf provenance

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  // Damodaran CRP — 국가 목록 로드 + 선택국 CRP 조회(WACC 마지막 입력).
  useEffect(() => { api.damodaranCrp().then((d) => setCountries(d.countries)).catch(() => {}); }, []);
  useEffect(() => {
    api.damodaranCrp(country).then((d) => setCrp(d.crp)).catch(() => setCrp(null));
  }, [country]);
  const setPeer = (i, k) => (e) => {
    const next = peers.slice();
    next[i] = { ...next[i], [k]: e.target.value };
    setPeers(next);
  };
  const addPeer = () =>
    setPeers([...peers, { ticker: "", levered_beta: "", debt_to_equity: "", tax_rate: "0.22" }]);
  const rmPeer = (i) => setPeers(peers.filter((_, j) => j !== i));

  // 주가에서 β 자동계산 — 각 peer 티커(종목코드) 2년 주간 회귀(look-ahead 가드). KRX 무료.
  const [betaBusy, setBetaBusy] = useState(false);
  const fetchBetas = async () => {
    if (!baseDate) { setErr("평가기준일(셋업)이 필요합니다 — 프로젝트 설계에서 지정하세요."); return; }
    setBetaBusy(true); setErr(null);
    try {
      const next = await Promise.all(peers.map(async (p) => {
        const tk = (p.ticker || "").trim();
        if (!/^\d{6}$/.test(tk)) return p;              // 6자리 종목코드만
        try {
          const b = await api.priceBeta({ ticker: tk, base_date: baseDate, freq: "W", years: 2 });
          return { ...p, levered_beta: b.raw.toFixed(3), _r2: b.r_squared };
        } catch { return p; }
      }));
      setPeers(next);
    } finally { setBetaBusy(false); }
  };

  const assemble = async () => {
    setBusy(true); setErr(null); setRes(null);
    const body = {
      risk_free: form.risk_free.trim(),          // 복붙 문자열 → 서버 range 게이트
      mrp: form.mrp.trim(),
      peers: peers
        .filter((p) => p.levered_beta !== "")
        .map((p) => ({
          ticker: p.ticker || "?",
          levered_beta: Number(p.levered_beta),
          debt_to_equity: Number(p.debt_to_equity),
          tax_rate: Number(p.tax_rate),
        })),
      target_debt_to_equity: Number(form.target_de),
      tax_rate: Number(form.tax_rate),
      kd_matrix_text: form.kd_matrix_text,
      kd_grade: form.kd_grade, kd_tenor: form.kd_tenor,
      beta_source: form.beta_source || null, beta_market: form.beta_market || null,
      mrp_source: form.mrp_source || null, mrp_market: form.mrp_market || null,
      country_risk_premium: crp != null ? crp : 0,
      pasted_at: baseDate || undefined,
    };
    if (form.market_cap_musd.trim()) body.market_cap_musd = Number(form.market_cap_musd);
    try {
      const d = await api.wacc.assemble(body);
      setRes(d);
      if (!d.blocked) {
        onSave?.({
          wacc_input: { form, peers, country, rf_meta: rfMeta },
          wacc_result: {
            wacc: d.wacc, cost_of_equity: d.cost_of_equity,
            relevered_beta: d.relevered_beta,
            after_tax_cost_of_debt: d.after_tax_cost_of_debt,
          },
          // 근거·판단 보조 패널이 소비: 출처 라벨 + 비-pass 게이트.
          wacc_provenance: d.provenance,
          wacc_findings: d.findings.filter((f) => f.severity !== "pass"),
        });
      }
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="card">
        <h2>WACC 빌드업 <span className="muted">— 커넥터 어셈블리(복붙 → 검증 → WACC)</span></h2>
        <div className="pad">
          <div className="muted" style={{ marginBottom: 10 }}>
            Rf·MRP·Kd 는 Bloomberg/KOFIABOND/한공회에서 <b>복붙</b>하세요. 서버가 자동/복붙
            동일 게이트(단위·범위·정합)를 겁니다{baseDate ? ` · 평가기준일 ${baseDate}` : ""}.
          </div>

          <div className="grid2">
            <div className="row"><label>무위험이자율 Rf (복붙, 예 3.45%)</label>
              <input type="text" value={form.risk_free} onChange={set("risk_free")} placeholder="3.45%" />
              <RfFromEcos baseDate={baseDate}
                onPick={(v, meta) => { setForm({ ...form, risk_free: v }); setRfMeta(meta); }} />
              {rfMeta && (
                <span className="muted" style={{ fontSize: 12 }}>
                  ↳ ECOS 국고채 10년 {rfMeta.period} 조회값 — 평가인 확정 필요
                </span>
              )}
            </div>
            <div className="row"><label>시장위험프리미엄 MRP (복붙, 예 8)</label>
              <input type="text" value={form.mrp} onChange={set("mrp")} placeholder="8 또는 8%" /></div>
          </div>

          <h2 style={{ marginTop: 14, fontSize: "0.95rem" }}>유사회사 (레버드 β → 무부채화)</h2>
          {!saved?.peers && _selected?.length > 0 && (
            <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>
              유사회사 선정(4-step)에서 확정된 {_selected.length}사를 불러왔습니다 — β·D/E 입력 또는 "주가로 β 계산".
            </div>
          )}
          <table>
            <thead><tr><th>회사</th><th>레버드 β</th><th>D/E</th><th>세율</th><th></th></tr></thead>
            <tbody>
              {peers.map((p, i) => (
                <tr key={i}>
                  <td><input type="text" value={p.ticker} onChange={setPeer(i, "ticker")} /></td>
                  <td><input type="text" value={p.levered_beta} onChange={setPeer(i, "levered_beta")} /></td>
                  <td><input type="text" value={p.debt_to_equity} onChange={setPeer(i, "debt_to_equity")} /></td>
                  <td><input type="text" value={p.tax_rate} onChange={setPeer(i, "tax_rate")} /></td>
                  <td><button className="ghost" onClick={() => rmPeer(i)} title="행 삭제">✕</button></td>
                </tr>
              ))}
            </tbody>
          </table>
          <button className="ghost" onClick={addPeer} style={{ marginTop: 6 }}>+ 유사회사 추가</button>{" "}
          <button className="ghost" onClick={fetchBetas} disabled={betaBusy} style={{ marginTop: 6 }}
            title="종목코드(6자리)에서 2년 주간 β 회귀 — KRX 무료">
            {betaBusy ? "β 계산 중…" : "주가로 β 계산(KRX)"}</button>

          <div className="grid2" style={{ marginTop: 14 }}>
            <div className="row"><label>대상회사 목표 D/E</label>
              <input type="text" value={form.target_de} onChange={set("target_de")} /></div>
            <div className="row"><label>유효세율 t</label>
              <input type="text" value={form.tax_rate} onChange={set("tax_rate")} /></div>
          </div>

          <div className="row"><label>Kd 신용등급×만기 매트릭스 (복붙 또는 CSV/엑셀 업로드)</label>
            <textarea rows={4} value={form.kd_matrix_text} onChange={set("kd_matrix_text")} />
            <div style={{ marginTop: 4 }}>
              <input type="file" accept=".csv,.xlsx" style={{ fontSize: 11 }}
                onChange={async (e) => {
                  const f = e.target.files[0]; if (!f) return;
                  try {
                    const body = /\.xlsx$/i.test(f.name)
                      ? { xlsx_b64: await fileToBase64(f) }
                      : { csv: await f.text() };
                    const d = await api.uploadSheet(body);
                    setForm({ ...form, kd_matrix_text: d.text });
                  } catch (er) { setErr(er.message); }
                }} />
              <span className="muted" style={{ fontSize: 11 }}> CSV/엑셀 표 → 매트릭스 자동 채움</span>
            </div></div>
          <div className="grid2">
            <div className="row"><label>Kd 선택 등급</label>
              <input type="text" value={form.kd_grade} onChange={set("kd_grade")} placeholder="BBB" /></div>
            <div className="row"><label>Kd 선택 만기</label>
              <input type="text" value={form.kd_tenor} onChange={set("kd_tenor")} placeholder="5Y" /></div>
          </div>

          <div className="grid2">
            <div className="row"><label>시가총액 ($백만 — Kroll size premium)</label>
              <input type="text" value={form.market_cap_musd} onChange={set("market_cap_musd")} placeholder="선택" /></div>
            <div className="row"><label>β 출처 / 기준시장</label>
              <div style={{ display: "flex", gap: 6 }}>
                <input type="text" value={form.beta_source} onChange={set("beta_source")} placeholder="bloomberg" />
                <input type="text" value={form.beta_market} onChange={set("beta_market")} placeholder="KOSPI" />
              </div></div>
            <div className="row"><label>MRP 출처 / 기준시장</label>
              <div style={{ display: "flex", gap: 6 }}>
                <input type="text" value={form.mrp_source} onChange={set("mrp_source")} placeholder="kicpa" />
                <input type="text" value={form.mrp_market} onChange={set("mrp_market")} placeholder="KOSPI" />
              </div></div>
            <div className="row"><label>국가위험프리미엄 CRP (Damodaran)</label>
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <select value={country} onChange={(e) => setCountry(e.target.value)} style={{ fontSize: 12 }}>
                  {countries.map((c) => <option key={c.country} value={c.country}>{c.country}</option>)}
                </select>
                <span className="muted" style={{ fontSize: 12 }}>
                  CRP = {crp != null ? (crp * 100).toFixed(2) + "%" : "미등록(0)"}</span>
              </div></div>
          </div>

          <button className="primary" onClick={assemble} disabled={busy}>
            {busy ? "조립·검증 중…" : "WACC 조립"}
          </button>
          {err && <div className="err">{err}</div>}
        </div>
      </div>

      {res && (
        <div className="card">
          <h2>WACC 결과 {res.blocked && <span className="muted">— 차단(게이트 FAIL)</span>}</h2>
          <div className="pad">
            {!res.blocked && (
              <div className="kpis">
                <div className="kpi hero"><div className="v">{pct(res.wacc)}</div><div className="k">WACC</div></div>
                <div className="kpi"><div className="v">{pct(res.cost_of_equity)}</div><div className="k">Ke (자기자본)</div></div>
                <div className="kpi"><div className="v">{num(res.relevered_beta)}</div><div className="k">βL' (relever)</div></div>
                <div className="kpi"><div className="v">{pct(res.after_tax_cost_of_debt)}</div><div className="k">Kd (세후)</div></div>
                <div className="kpi"><div className="v">{pct(res.equity_weight, 0)}/{pct(res.debt_weight, 0)}</div><div className="k">We / Wd</div></div>
              </div>
            )}

            <h2 style={{ marginTop: 16, fontSize: "0.95rem" }}>검증 게이트</h2>
            <Findings report={res} />

            <h2 style={{ marginTop: 16, fontSize: "0.95rem" }}>출처 추적 (provenance)</h2>
            <Provenance prov={res.provenance} />

            {!res.blocked && (
              <div className="finding pass" style={{ marginTop: 12 }}>
                이 WACC 가 프로젝트에 저장됐습니다 — <b>4. 밸류에이션 › DCF</b> 에서 자동 사용됩니다.
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
