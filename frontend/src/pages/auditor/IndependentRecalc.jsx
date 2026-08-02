import React, { useState } from "react";
import { api, fileToBase64 } from "../../api.js";

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

/* ── 범위추정 (기준서 540 문단 28~29) ──────────────────────────────────────
   감사인이 가정별 **합리 구간**을 세우면 엔진이 주당가치 범위를 산출하고, 경영진
   주장값이 범위 밖이면 최소 조정액(가까운 경계까지)을 계산한다 — 450 왜곡표시
   집계의 재료. 29(a) 규율: 구간 **양끝 각각에 근거 필수** — 없으면 서버가 계산을
   차단한다. 근거 없이 넓힌 범위는 안전이 아니라 증거 부재다. */

const RANGE_FIELDS = [
  ["wacc", "WACC"],
  ["terminal_growth", "영구성장률 g"],
  ["revenue_scale", "매출 스케일(×)"],
  ["cogs_scale", "매출원가 스케일(×)"],
  ["sga_scale", "판관비 스케일(×)"],
  ["capex_scale", "CAPEX 스케일(×)"],
  ["net_debt", "순차입부채"],
  ["non_operating_assets", "비영업자산"],
];

function RangeSheet({ project, onSave }) {
  const base = project?.data?.audit_input;          // 독립 재계산 입력을 base 로 재사용
  const claimed = project?.data?.audit_claimed;
  const [rows, setRows] = useState(project?.data?.audit_range_input || [
    { field: "wacc", low: "", high: "", basis_low: "", basis_high: "" },
    { field: "terminal_growth", low: "", high: "", basis_low: "", basis_high: "" },
  ]);
  // 재진입 상태(자기 소비) — 하류 산출물은 audit_range_summary(개요 CoverSheet 가 읽음).
  const [res, setRes] = useState(project?.data?.audit_range_state || null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  if (!base)
    return (
      <div className="card"><div className="pad muted">
        먼저 <b>입력 재구성</b>에서 base 입력을 세우고 재계산을 실행하세요 —
        범위추정은 그 입력 위에 가정별 구간을 얹습니다.
      </div></div>
    );

  const setCell = (i, k) => (e) => {
    const next = rows.slice(); next[i] = { ...next[i], [k]: e.target.value }; setRows(next);
  };
  const add = () => setRows([...rows, { field: "revenue_scale", low: "", high: "", basis_low: "", basis_high: "" }]);
  const rm = (i) => setRows(rows.filter((_, j) => j !== i));

  const runRange = async () => {
    setBusy(true); setErr(null); setRes(null);
    const body = {
      wacc: Number(base.wacc), terminal_growth: Number(base.terminal_growth),
      non_operating_assets: Number(base.non_operating_assets),
      net_debt: Number(base.net_debt),
      shares_outstanding: Number(base.shares_outstanding),
      range_assumptions: rows
        .filter((r) => String(r.low).trim() !== "" || String(r.high).trim() !== "")
        .map((r) => ({ field: r.field, low: Number(r.low), high: Number(r.high),
                       basis_low: r.basis_low, basis_high: r.basis_high })),
    };
    for (const [k] of FIELD_LABELS) body[k] = parseSeries(base[k]);
    if (claimed != null) body.claimed_per_share = claimed;
    try {
      const d = await api.rangeEstimate(body);
      setRes(d);
      const patch = { audit_range_input: rows, audit_range_state: d };
      // 조서·450 집계용 요약(차단이면 저장하지 않음 — "있는 척" 방지). 개요 CoverSheet 소비.
      if (!d.blocked) {
        patch.audit_range_summary = { low: d.low, high: d.high,
          claimed_within: d.claimed_within, min_adjustment: d.min_adjustment };
      }
      onSave?.(patch);
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  // 범위 바 시각화용 좌표(주장값·base 를 [low, high] 구간 위에 배치)
  const pos = (v) => res && res.high !== res.low
    ? Math.max(0, Math.min(100, ((v - res.low) / (res.high - res.low)) * 100)) : 50;

  return (
    <>
      <div className="card">
        <h2>범위추정 <span className="muted">— 기준서 540 문단 28~29 · 가정별 합리 구간</span></h2>
        <div className="pad">
          <div className="muted" style={{ marginBottom: 10 }}>
            base = <b>입력 재구성</b>의 저장 입력. 구간을 건 가정만 전송되며, 구간
            <b> 양끝 각각의 근거</b>가 없으면 서버가 계산을 차단합니다(29(a)) —
            근거 없이 넓힌 범위는 안전이 아니라 증거 부재입니다.
          </div>
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead><tr><th>가정</th><th>하한</th><th>상한</th>
                <th>하한 근거</th><th>상한 근거</th><th /></tr></thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i}>
                    <td><select value={r.field} onChange={setCell(i, "field")} style={{ fontSize: 12 }}>
                      {RANGE_FIELDS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                    </select></td>
                    <td><input type="text" value={r.low} onChange={setCell(i, "low")} style={{ width: 80 }} /></td>
                    <td><input type="text" value={r.high} onChange={setCell(i, "high")} style={{ width: 80 }} /></td>
                    <td><input type="text" value={r.basis_low} onChange={setCell(i, "basis_low")}
                      style={{ width: 170 }} placeholder="예: peer 하위4분위 β" /></td>
                    <td><input type="text" value={r.basis_high} onChange={setCell(i, "basis_high")}
                      style={{ width: 170 }} placeholder="예: 산업 CAGR 상단" /></td>
                    <td><button className="ghost xs" onClick={() => rm(i)}>✕</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button className="ghost" onClick={add} style={{ marginTop: 6 }}>+ 가정 추가</button>{" "}
          <button className="primary" disabled={busy} onClick={runRange}>
            {busy ? "계산 중…" : "범위 산출"}
          </button>
          {err && <div className="err" style={{ marginTop: 10 }}>{err}</div>}
        </div>
      </div>

      {res && res.blocked && (
        <div className="card"><h2>차단됨</h2><div className="pad">
          {res.findings.map((f, i) => (
            <div key={i} className={`finding ${f.severity}`}>
              <b>[{f.severity.toUpperCase()}] {f.rule}</b> — {f.message}</div>
          ))}
        </div></div>
      )}

      {res && !res.blocked && (
        <div className="card">
          <h2>감사인 범위 vs 경영진 주장</h2>
          <div className="pad">
            <div className="kpis">
              <div className="kpi"><div className="v">{fmt(res.low)} ~ {fmt(res.high)}</div>
                <div className="k">감사인 범위(원) · 평가 {res.n_evaluations}회</div></div>
              <div className="kpi"><div className="v">{fmt(res.base_per_share)}</div>
                <div className="k">base 점추정</div></div>
              {res.claimed_per_share != null && (
                <div className={`kpi${res.claimed_within ? "" : " hero"}`}>
                  <div className="v">{fmt(res.claimed_per_share)}</div>
                  <div className="k">경영진 주장 — {res.claimed_within ? "범위 내" : "범위 밖"}</div></div>
              )}
            </div>
            {/* 범위 바: [low ── base ── high] 위에 주장값 마커 */}
            <div style={{ position: "relative", height: 26, margin: "16px 4px 4px",
                          background: "var(--brand-50)", border: "1px solid var(--line)" }}>
              <span style={{ position: "absolute", left: `${pos(res.base_per_share)}%`,
                top: 0, bottom: 0, borderLeft: "2px dashed var(--sub)" }} title="base" />
              {res.claimed_per_share != null && (
                <span style={{ position: "absolute", left: `${pos(res.claimed_per_share)}%`,
                  top: 0, bottom: 0, borderLeft: "3px solid var(--brand)" }} title="주장값" />
              )}
            </div>
            <div className="muted" style={{ fontSize: 11 }}>
              점선=base 점추정 · 실선=경영진 주장 · 하한 조합 {JSON.stringify(res.combo_low)}
              · 상한 조합 {JSON.stringify(res.combo_high)}
            </div>
            {res.claimed_within === false && (
              <div className="warn-box" style={{ marginTop: 10 }}>
                최소 조정액 <b>{fmt(res.min_adjustment)} 원</b>
                ({res.min_adjustment > 0 ? "주장값 과대 — 하향" : "주장값 과소 — 상향"} 필요) —
                미수정왜곡표시 집계(기준서 450) 대상 후보. 4. 발견사항에 기록하세요.
              </div>
            )}
            {res.findings.filter((f) => f.severity !== "pass").map((f, i) => (
              <div key={i} className={`finding ${f.severity}`} style={{ marginTop: 8 }}>
                <b>[{f.severity.toUpperCase()}] {f.rule}</b> — {f.message}</div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

/* ── 값-only 복원(기준서 540 문단 22~25 의 입구, P2) ────────────────────────
   평가인이 준 모델은 대개 값 붙여넣기다 — 수식이 없으니 정적 감사·연결성 진단이
   무력하다. 그러나 산술 관계는 값에 새겨져 있다: 표준 레이아웃이면 스파인 전체를
   복원해 재계산 대조하고, 임의 레이아웃이면 FCFF↔PV 행 쌍에서 **암묵 할인율**을
   역산한다. 산출물은 "복원된 모델"이 아니라 **후보 + 질의 목록**이다. */

function RecoverSheet({ project, onSave }) {
  const [file, setFile] = useState(null);
  const [res, setRes] = useState(project?.data?.audit_recover_state || null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [applied, setApplied] = useState(false);

  const run = async () => {
    if (!file) { setErr("xlsx 파일을 선택하세요."); return; }
    setBusy(true); setErr(null); setRes(null); setApplied(false);
    try {
      const d = await api.xlsx.recover(await fileToBase64(file));
      setRes(d);
      onSave?.({ audit_recover_state: d });
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  // 입력 재구성 폼이 지원하지 않는 파라미터 — 있으면 반영을 막는다(조용한 소실 방지).
  const unsupported = res?.input ? [
    ["tax_override", "세금 주입"], ["effective_tax_rate", "유효세율"],
    ["terminal_fcff_override", "터미널 FCFF 주입"], ["fade_years", "페이드"],
    ["terminal_reinvestment_rate", "재투자율"],
  ].filter(([k]) => res.input[k] != null) : [];

  const apply = () => {
    const inp = res.input;
    const s = (arr) => (arr || []).map((v) => String(v)).join(", ");
    onSave?.({
      audit_input: {
        wacc: String(inp.wacc), terminal_growth: String(inp.terminal_growth),
        non_operating_assets: String(inp.non_operating_assets),
        net_debt: String(inp.net_debt),
        shares_outstanding: String(inp.shares_outstanding),
        claimed_per_share: res.cached_per_share != null ? String(res.cached_per_share) : "",
        revenue: s(inp.revenue), cogs: s(inp.cogs), sga: s(inp.sga),
        dep_amort: s(inp.dep_amort), capex: s(inp.capex),
        delta_nwc_cash_adj: s(inp.delta_nwc_cash_adj),
      },
      audit_claimed: res.cached_per_share ?? null,
    });
    setApplied(true);
  };

  return (
    <>
      <div className="card">
        <h2>값-only 복원 <span className="muted">— 경영진 모델 테스트의 입구(540 문단 22~25)</span></h2>
        <div className="pad">
          <div className="muted" style={{ marginBottom: 10, fontSize: "0.82rem" }}>
            수식이 제거된(값 붙여넣기) 모델을 올리세요. 산술 관계는 값에 새겨져 있습니다 —
            할인계수는 PV/FCFF 비율에, 세금 정책은 EBIT 대비 세액 패턴에. 복원 결과는
            <b> 후보</b>이며, 원천·근거는 문서·질의로만 확인됩니다.
          </div>
          <div className="row" style={{ gap: 16 }}>
            <label>값-only xlsx <input type="file" accept=".xlsx"
              onChange={(e) => setFile(e.target.files[0])} /></label>
            <button className="primary" disabled={busy} onClick={run}>
              {busy ? "복원 중…" : "복원 시도"}
            </button>
          </div>
          {err && <div className="err" style={{ marginTop: 10 }}>{err}</div>}
        </div>
      </div>

      {res && (
        <div className="card">
          <h2>복원 결과 <span className="muted">— 모드: {
            { standard: "표준 레이아웃(스파인 복원)", detected: "자동 탐지(암묵 할인율)",
              failed: "복원 불가" }[res.mode] || res.mode}</span></h2>
          <div className="pad">
            {res.mode === "standard" && (
              <>
                <div className="kpis">
                  <div className="kpi"><div className="v">{fmt(res.recomputed_per_share)}</div>
                    <div className="k">복원 재계산 주당가치</div></div>
                  <div className="kpi"><div className="v">{fmt(res.cached_per_share)}</div>
                    <div className="k">워크북 표기값</div></div>
                </div>
                <div style={{ marginTop: 10 }}>
                  {unsupported.length === 0 ? (
                    <button className="primary" disabled={applied} onClick={apply}>
                      {applied ? "반영됨 ✓" : "입력 재구성에 반영"}
                    </button>
                  ) : (
                    <div className="warn-box">
                      복원에 <b>{unsupported.map(([, l]) => l).join("·")}</b> 파라미터가
                      포함돼 있어 폼 반영 시 소실됩니다 — 반영 대신 이 화면의 복원값을
                      직접 근거로 쓰세요(조용한 단순화 방지).
                    </div>
                  )}
                </div>
              </>
            )}
            {res.mode === "detected" && res.candidates?.length > 0 && (
              <div style={{ overflowX: "auto" }}>
                <table>
                  <thead><tr><th>시트</th><th>FCFF행</th><th>PV행</th><th>열수</th>
                    <th>암묵 WACC</th><th>할인 방식</th></tr></thead>
                  <tbody>{res.candidates.map((c, i) => (
                    <tr key={i} className={i === 0 ? "ok" : ""}>
                      <td>{c.sheet}</td><td>{c.fcff_row}</td><td>{c.pv_row}</td>
                      <td>{c.cols}</td>
                      <td><b>{(c.implied_wacc * 100).toFixed(3)}%</b></td>
                      <td>{c.mid_year ? "mid-year" : "기말"}</td>
                    </tr>))}</tbody>
                </table>
              </div>
            )}
            {res.findings.map((f, i) => (
              <div key={i} className={`finding ${f.severity}`} style={{ marginTop: 8 }}>
                <b>[{f.severity.toUpperCase()}] {f.rule}</b> — {f.message}
              </div>
            ))}
            {res.unresolved?.length > 0 && (
              <div className="finding warn" style={{ marginTop: 8 }}>
                <b>미해결(질의사항)</b>
                <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                  {res.unresolved.map((u, i) => <li key={i}>{u}</li>)}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}

export default function IndependentRecalc({ project, sheet, onSave }) {
  if (sheet === "result") return <ResultSheet project={project} />;
  if (sheet === "range") return <RangeSheet project={project} onSave={onSave} />;
  if (sheet === "recover") return <RecoverSheet project={project} onSave={onSave} />;
  return <InputsSheet project={project} onSave={onSave} />;
}
