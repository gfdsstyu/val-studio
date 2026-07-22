import React, { useState } from "react";
import { api } from "../../api.js";
import { loadKey } from "../Byok.jsx";

/* 2.가정 > 원가·판관비 — /api/assumptions/costs-build 배선(비올/참고 모델 성격별 다중드라이버).
   단일 COGS%/SGA% 가 아니라 성격별 라인(원재료·노무비·외주비·감가상각·인건비·지급수수료…)을
   각자 경제동인으로 투영 → 카테고리 합산 → 매출총이익·EBIT. 성격별 항목은 1.계정분류(PL 매핑)
   에서 임포트 가능. */

const parseSeries = (s) => String(s).split(/[\s,]+/).filter(Boolean).map(Number);
const fmt = (v) => (v == null || Number.isNaN(v) ? "-" : Math.round(v).toLocaleString("ko-KR"));

const METHODS = [
  ["growth", "증가율(base×(1+g))"], ["ratio", "매출연동(driver×%)"],
  ["headcount", "인건비(인원×급여×(1+상여+퇴직))"], ["cpi", "물가연동(base×CPI)"],
  ["fa_dep", "감가상각(FA 배분)"], ["fixed", "고정(연도값)"],
];

const DEMO = [
  { name: "원재료", category: "cogs", method: "ratio", pct: "0.45, 0.45, 0.45" },
  { name: "노무비", category: "cogs", method: "headcount", headcount: "100, 105, 110",
    wage_per_head: "50, 52, 54", bonus_rate: "0.1", severance_rate: "0.08" },
  { name: "외주비", category: "cogs", method: "cpi", base: "3000" },
  { name: "제조감가상각", category: "cogs", method: "fa_dep", fa_share: "0.7" },
  { name: "인건비(판관)", category: "sga", method: "headcount", headcount: "30, 31, 32",
    wage_per_head: "60, 62, 64", bonus_rate: "0.1", severance_rate: "0.08" },
  { name: "지급수수료", category: "sga", method: "growth", base: "2000", growth: "0.05, 0.05, 0.05" },
  { name: "판관감가상각", category: "sga", method: "fa_dep", fa_share: "0.3" },
];

export default function CostsSheet({ project, onSave }) {
  const rev = parseSeries(project?.data?.dcf_input?.revenue || project?.data?.revenue_built || "");
  const years = rev.length || 3;
  const [lines, setLines] = useState(project?.data?.costs_lines || DEMO);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const cpi = parseSeries(project?.data?.macro_cpi || "");           // 2.가정 › 거시에서 확정
  const cpiLines = lines.filter((l) => l.method === "cpi");          // CPI 부재 시 경고 대상
  const faDep = project?.data?.fa_built?.dep_amort || null;          // 감가상각 배분원
  const dartKey = loadKey("dart");

  // 주석 성격별 추출(계정세분화 ①단): 붙여넣은 표 → 성격별 금액·드라이버 제안·tie-out.
  const [fnText, setFnText] = useState("");
  const [fnMeta, setFnMeta] = useState({ note_no: "", unit: "백만원", year: "", stated_sga: "", stated_cogs: "" });
  const [fnRes, setFnRes] = useState(null);
  const [fnErr, setFnErr] = useState(null);
  const setFn = (k) => (e) => setFnMeta({ ...fnMeta, [k]: e.target.value });

  // DART 직원현황 → 노무비 headcount 드라이버 실측 시드.
  const [emp, setEmp] = useState({ corp_code: "", bsns_year: "", headcount_growth: "0",
    wage_growth: "0", bonus_rate: "0.1", severance_rate: "0.08" });
  const [empRes, setEmpRes] = useState(null);
  const [empErr, setEmpErr] = useState(null);
  const setE = (k) => (e) => setEmp({ ...emp, [k]: e.target.value });

  const extractFootnote = async () => {
    setFnErr(null); setFnRes(null);
    if (!fnText.trim()) { setFnErr("주석 표를 붙여넣으세요."); return; }
    try {
      const body = { text: fnText };
      if (fnMeta.note_no) body.note_no = Number(fnMeta.note_no);
      if (fnMeta.unit) body.unit = fnMeta.unit;
      if (fnMeta.year) body.year = fnMeta.year;
      if (fnMeta.stated_sga) body.stated_sga = Number(fnMeta.stated_sga);
      if (fnMeta.stated_cogs) body.stated_cogs = Number(fnMeta.stated_cogs);
      setFnRes(await api.footnoteCosts(body));
    } catch (e) { setFnErr(e.message); }
  };

  // 추출 초안 → 원가 라인 append(판정=유저: category null 은 sga 로 시드, headcount 는 벡터 수기).
  const importFootnote = () => {
    if (!fnRes) return;
    const imported = fnRes.drafts.map((d) => ({
      name: d.name, category: d.category || "sga", method: d.method,
      base: d.base != null ? String(Math.round(d.base)) : "0", growth: "0, 0, 0",
    }));
    setLines([...lines, ...imported]);
  };

  const fetchEmployee = async () => {
    setEmpErr(null); setEmpRes(null);
    if (!dartKey) { setEmpErr("BYOK 설정에서 DART 키를 먼저 입력하세요."); return; }
    if (!emp.corp_code.trim() || !emp.bsns_year.trim()) { setEmpErr("corp_code, 사업연도 필요."); return; }
    try {
      setEmpRes(await api.dartEmployee(dartKey, {
        corp_code: emp.corp_code.trim(), bsns_year: emp.bsns_year.trim(), years,
        headcount_growth: Number(emp.headcount_growth), wage_growth: Number(emp.wage_growth),
        bonus_rate: Number(emp.bonus_rate), severance_rate: Number(emp.severance_rate) }));
    } catch (e) { setEmpErr(e.message); }
  };

  const addEmployeeLine = () => {
    const cl = empRes?.costline;
    if (!cl?.headcount) { setEmpErr("인당급여 산출 불가(인원 결측) — 수기 입력 필요."); return; }
    setLines([...lines, { name: cl.name, category: cl.category, method: "headcount",
      headcount: cl.headcount.map((x) => Math.round(x)).join(", "),
      wage_per_head: cl.wage_per_head.map((x) => Number(x).toFixed(2)).join(", "),
      bonus_rate: String(cl.bonus_rate || 0), severance_rate: String(cl.severance_rate || 0) }]);
  };

  const setLine = (i, k) => (e) => {
    const next = lines.slice(); next[i] = { ...next[i], [k]: e.target.value }; setLines(next);
  };
  const addLine = () => setLines([...lines, { name: "", category: "cogs", method: "growth", base: "0", growth: "0" }]);
  const rmLine = (i) => setLines(lines.filter((_, j) => j !== i));

  // 1.계정분류(PL 매핑)에서 성격별 항목 임포트 — COGS/SGA 버킷을 라인으로.
  const importFromMapping = () => {
    const pl = project?.data?.mapping_pl || [];
    const imported = pl
      .filter((r) => ["COGS", "SGA"].includes(r.bucket) && (r.account || "").trim())
      .map((r) => ({ name: r.account, category: r.bucket === "COGS" ? "cogs" : "sga",
        method: "growth", base: String(Math.round(Number(r.amount) || 0)), growth: "0, 0, 0" }));
    if (imported.length) setLines(imported);
    else setErr("1.계정분류 > 손익 매핑에 COGS/SGA 계정이 없습니다.");
  };

  const build = async () => {
    setBusy(true); setErr(null); setRes(null);
    try {
      const payload = lines.map((l) => {
        const o = { name: l.name || "항목", category: l.category, method: l.method };
        if (l.base !== undefined && l.base !== "") o.base = Number(l.base);
        if (l.growth) o.growth = parseSeries(l.growth);
        if (l.pct) o.pct = parseSeries(l.pct);
        if (l.method === "ratio") o.driver = rev;              // 매출 연동
        if (l.headcount) o.headcount = parseSeries(l.headcount);
        if (l.wage_per_head) o.wage_per_head = parseSeries(l.wage_per_head);
        if (l.bonus_rate) o.bonus_rate = Number(l.bonus_rate);
        if (l.severance_rate) o.severance_rate = Number(l.severance_rate);
        if (l.fa_share) o.fa_share = Number(l.fa_share);
        return o;
      });
      const d = await api.assumptionsBuildCosts({ years, lines: payload,
        cpi: cpi.length ? cpi : undefined, fa_dep: faDep || undefined });
      setRes(d);
      onSave?.({ costs_lines: lines, costs_built: d });
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const pushToDcf = () => {
    if (!res) return;
    const prev = project?.data?.dcf_input || {};
    onSave?.({ dcf_input: { ...prev, cogs: res.cogs.map(Math.round).join(", "),
      sga: res.sga.map(Math.round).join(", ") } });
  };

  const ebit = res ? rev.map((r, i) => r - (res.cogs[i] || 0) - (res.sga[i] || 0)) : null;

  return (
    <>
      <div className="card">
        <h2>원가·판관비 <span className="muted">— 성격별 다중 드라이버(비올/참고 모델)</span></h2>
        <div className="pad">
          <div className="muted" style={{ marginBottom: 8 }}>
            성격별(원재료·노무비·외주비·감가상각·인건비·지급수수료…)로 각자 투영합니다.
            매출 {years}개 연도{cpi.length ? " · CPI 연동 有" : ""}{faDep ? " · FA 감가상각 배분 有" : ""}.</div>
          {/* cpi 드라이버는 CPI 부재 시 엔진이 누적계수 1.0(=물가상승 0%)으로 조용히
              계산한다. 조용한 오답을 막기 위해 여기서 표면화한다(감사 §3.2-4). */}
          {cpiLines.length > 0 && !cpi.length && (
            <div className="warn-box" style={{ marginBottom: 10 }}>
              <b>물가연동 드라이버에 CPI가 없습니다</b> — {cpiLines.map((l) => l.name).join(", ")}{" "}
              항목이 <b>물가상승 0%</b>로 계산됩니다. 2.가정 › <b>거시</b> 에서 CPI를 확정하세요.
            </div>
          )}
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead><tr><th>항목</th><th>구분</th><th>방법</th><th>파라미터</th><th></th></tr></thead>
              <tbody>{lines.map((l, i) => (
                <tr key={i}>
                  <td><input type="text" value={l.name} onChange={setLine(i, "name")} style={{ width: 100 }} /></td>
                  <td><select value={l.category} onChange={setLine(i, "category")} style={{ fontSize: 12 }}>
                    <option value="cogs">매출원가</option><option value="sga">판관비</option></select></td>
                  <td><select value={l.method} onChange={setLine(i, "method")} style={{ fontSize: 11 }}>
                    {METHODS.map(([m, lbl]) => <option key={m} value={m}>{lbl}</option>)}</select></td>
                  <td style={{ fontSize: 11 }}>
                    {l.method === "growth" && <>base<input type="text" value={l.base || ""} onChange={setLine(i, "base")} style={{ width: 60 }} /> g<input type="text" value={l.growth || ""} onChange={setLine(i, "growth")} style={{ width: 90 }} /></>}
                    {l.method === "ratio" && <>매출×<input type="text" value={l.pct || ""} onChange={setLine(i, "pct")} style={{ width: 90 }} placeholder="비율(연도별)" /></>}
                    {l.method === "headcount" && <>인원<input type="text" value={l.headcount || ""} onChange={setLine(i, "headcount")} style={{ width: 70 }} /> 급여<input type="text" value={l.wage_per_head || ""} onChange={setLine(i, "wage_per_head")} style={{ width: 70 }} /> 상여<input type="text" value={l.bonus_rate || ""} onChange={setLine(i, "bonus_rate")} style={{ width: 36 }} /> 퇴직<input type="text" value={l.severance_rate || ""} onChange={setLine(i, "severance_rate")} style={{ width: 36 }} /></>}
                    {l.method === "cpi" && <>base<input type="text" value={l.base || ""} onChange={setLine(i, "base")} style={{ width: 60 }} /></>}
                    {l.method === "fa_dep" && <>배분율<input type="text" value={l.fa_share || ""} onChange={setLine(i, "fa_share")} style={{ width: 50 }} /></>}
                    {l.method === "fixed" && <>연도값<input type="text" value={l.growth || ""} onChange={setLine(i, "growth")} style={{ width: 100 }} /></>}
                  </td>
                  <td><button className="ghost xs" onClick={() => rmLine(i)}>✕</button></td>
                </tr>))}</tbody>
            </table>
          </div>
          <div style={{ marginTop: 6 }}>
            <button className="ghost" onClick={addLine}>+ 항목</button>{" "}
            <button className="ghost" onClick={importFromMapping} title="1.계정분류 PL 매핑에서 COGS/SGA 임포트">계정분류에서 임포트</button>{" "}
            <button className="primary" onClick={build} disabled={busy}>{busy ? "계산 중…" : "원가·EBIT 계산"}</button>
          </div>
          {err && <div className="err">{err}</div>}
        </div>
      </div>

      <div className="card">
        <h2>주석에서 성격별 추출 <span className="muted">— 비용의 성격별 분류 표 → 라인 (계정세분화 ①단)</span></h2>
        <div className="pad">
          <div className="muted" style={{ marginBottom: 8 }}>
            사업보고서 '비용의 성격별 분류' 주석 표를 붙여넣으면 성격별 금액을 추출하고
            드라이버(headcount·fa_dep·cpi…)를 <b>제안</b>합니다. 추출=결정론, 판정=유저 승인.
            표기 판관비/매출원가를 주면 Σ성격별 <b>tie-out</b> 검증까지 겁니다.</div>
          <textarea value={fnText} onChange={(e) => setFnText(e.target.value)} rows={5}
            placeholder={"구분        2024      2023\n급여        12,340    11,200\n퇴직급여     1,500     1,300\n감가상각비   3,200     3,000"}
            style={{ width: "100%", fontFamily: "monospace", fontSize: 12 }} />
          <div className="grid2" style={{ marginTop: 6 }}>
            <div className="row"><label>주석 번호(선택)</label>
              <input type="text" value={fnMeta.note_no} onChange={setFn("note_no")} placeholder="예 24" /></div>
            <div className="row"><label>단위</label>
              <input type="text" value={fnMeta.unit} onChange={setFn("unit")} placeholder="백만원" /></div>
            <div className="row"><label>tie-out 기준연도(선택)</label>
              <input type="text" value={fnMeta.year} onChange={setFn("year")} placeholder="예 2024" /></div>
            <div className="row"><label>IS 표기 판관비(선택)</label>
              <input type="text" value={fnMeta.stated_sga} onChange={setFn("stated_sga")} placeholder="Σ tie-out" /></div>
            <div className="row"><label>IS 표기 매출원가(선택)</label>
              <input type="text" value={fnMeta.stated_cogs} onChange={setFn("stated_cogs")} placeholder="Σ tie-out" /></div>
          </div>
          <button className="primary" onClick={extractFootnote} style={{ marginTop: 6 }}>주석 추출</button>
          {fnErr && <div className="err">{fnErr}</div>}

          {fnRes && (
            <div style={{ marginTop: 10 }}>
              {fnRes.extraction.filter((f) => f.severity !== "pass").map((f, i) => (
                <div key={i} className={`finding ${f.severity}`}>[{f.severity.toUpperCase()}] {f.message}</div>))}
              {fnRes.tieout.map((f, i) => (
                <div key={i} className={`finding ${f.severity}`}><b>tie-out</b> {f.message}</div>))}
              <table style={{ marginTop: 8 }}>
                <thead><tr><th style={{ textAlign: "left" }}>성격</th><th>구분</th><th>드라이버(제안)</th>
                  {fnRes.years.map((y) => <th key={y}>{y}</th>)}</tr></thead>
                <tbody>{fnRes.natures.map((n, i) => (
                  <tr key={i}>
                    <td style={{ textAlign: "left" }}>{n.name}</td>
                    <td>{n.uncertain ? <span className="muted">미정</span> : (n.category === "cogs" ? "매출원가" : "판관비")}</td>
                    <td className="muted" title={n.note || ""}>{n.method}{n.uncertain ? " ⚠" : ""}</td>
                    {fnRes.years.map((y) => <td key={y}>{fmt(n.amounts[y])}</td>)}
                  </tr>))}</tbody>
              </table>
              <button className="primary" onClick={importFootnote} style={{ marginTop: 8 }}>
                추출 성격을 원가 라인에 추가</button>
              <span className="muted" style={{ fontSize: 11, marginLeft: 8 }}>
                ⚠ 표시 = 카테고리/드라이버 유저 확인 필요(감가상각 등 애매)</span>
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <h2>DART 직원현황 → 노무비 <span className="muted">— 인원×인당급여 headcount 드라이버 실측</span></h2>
        <div className="pad">
          <div className="muted" style={{ marginBottom: 8 }}>
            직원현황(empSttus)에서 총인원·연간급여총액을 가져와 인당급여를 산출, headcount
            드라이버(노무비=인원×인당급여×(1+상여+퇴직))를 채웁니다. 성장률은 가정입니다.
            {!dartKey && <b style={{ color: "var(--err, #c00)" }}> BYOK 설정에서 DART 키 필요.</b>}</div>
          <div className="grid2">
            <div className="row"><label>corp_code (8자리)</label>
              <input type="text" value={emp.corp_code} onChange={setE("corp_code")} placeholder="예 00126380" /></div>
            <div className="row"><label>사업연도</label>
              <input type="text" value={emp.bsns_year} onChange={setE("bsns_year")} placeholder="예 2024" /></div>
            <div className="row"><label>인원 성장률(가정)</label>
              <input type="text" value={emp.headcount_growth} onChange={setE("headcount_growth")} /></div>
            <div className="row"><label>임금 성장률(가정)</label>
              <input type="text" value={emp.wage_growth} onChange={setE("wage_growth")} /></div>
            <div className="row"><label>상여율</label>
              <input type="text" value={emp.bonus_rate} onChange={setE("bonus_rate")} /></div>
            <div className="row"><label>퇴직급여율</label>
              <input type="text" value={emp.severance_rate} onChange={setE("severance_rate")} /></div>
          </div>
          <button className="primary" onClick={fetchEmployee} style={{ marginTop: 6 }}>직원현황 조회</button>
          {empErr && <div className="err">{empErr}</div>}

          {empRes && (
            <div style={{ marginTop: 10 }}>
              <div className="kpis">
                <div className="kpi"><div className="v">{fmt(empRes.headcount)}</div><div className="k">총 인원(명)</div></div>
                <div className="kpi"><div className="v">{fmt(empRes.total_salary)}</div><div className="k">급여총액(백만원)</div></div>
                <div className="kpi"><div className="v">{empRes.avg_wage != null ? empRes.avg_wage.toFixed(1) : "-"}</div><div className="k">인당급여(백만원)</div></div>
              </div>
              {empRes.findings.filter((f) => f.severity !== "pass").map((f, i) => (
                <div key={i} className={`finding ${f.severity}`}>[{f.severity.toUpperCase()}] {f.message}</div>))}
              <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                {empRes.costline?.note}</div>
              <button className="primary" onClick={addEmployeeLine} style={{ marginTop: 8 }}
                disabled={!empRes.costline?.headcount}>노무비 라인으로 추가</button>
              <span className="muted" style={{ fontSize: 11, marginLeft: 8 }}>
                주석 성격 '급여'와 cross-source tie-out 대조 권장</span>
            </div>
          )}
        </div>
      </div>

      {res && (
        <div className="card"><h2>결과</h2><div className="pad">
          <table>
            <thead><tr><th style={{ textAlign: "left" }}>항목</th>{rev.map((_, i) => <th key={i}>Y{i + 1}</th>)}</tr></thead>
            <tbody>
              <tr><th style={{ textAlign: "left" }}>매출</th>{rev.map((v, i) => <td key={i}>{fmt(v)}</td>)}</tr>
              {Object.entries(res.detail).map(([name, vec]) => (
                <tr key={name}><td style={{ textAlign: "left", paddingLeft: 12 }} className="muted">{name}</td>
                  {vec.map((v, i) => <td key={i} className="muted">{fmt(v)}</td>)}</tr>))}
              <tr style={{ borderTop: "1px solid var(--line)" }}><th style={{ textAlign: "left" }}>매출원가 계</th>{res.cogs.map((v, i) => <td key={i}>{fmt(v)}</td>)}</tr>
              <tr><th style={{ textAlign: "left" }}>판관비 계</th>{res.sga.map((v, i) => <td key={i}>{fmt(v)}</td>)}</tr>
              <tr style={{ borderTop: "2px solid var(--line)" }}><th style={{ textAlign: "left" }}>EBIT</th>{ebit.map((v, i) => <td key={i}><b>{fmt(v)}</b></td>)}</tr>
            </tbody>
          </table>
          <button className="primary" onClick={pushToDcf} style={{ marginTop: 12 }}>매출원가·판관비를 DCF 입력에 반영</button>
        </div></div>
      )}
    </>
  );
}
