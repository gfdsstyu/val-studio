import React, { useState } from "react";
import { api, fileToBase64 } from "../../api.js";

/* 0.자료·Brief — files(자료함)·brief(Company Brief).
   업로드/파싱 파이프라인·LLM 자동 브리프는 후속(백엔드 인제스트 미배선) — 지금은
   자료 메타·메모와 수기 브리프를 project.data 에 보존(감사추적·컨텍스트 관리 기초). */

function FilesSheet({ project, onSave }) {
  const [rows, setRows] = useState(project?.data?.materials || []);
  const setRow = (i, k) => (e) => {
    const next = rows.slice(); next[i] = { ...next[i], [k]: e.target.value }; setRows(next);
  };
  const add = () => setRows([...rows, { name: "", kind: "사업보고서", note: "", link: "" }]);
  const rm = (i) => setRows(rows.filter((_, j) => j !== i));
  const save = () => onSave?.({ materials: rows });

  return (
    <div className="card">
      <h2>자료함 <span className="muted">— 자료 메타·메모(업로드 파이프라인은 후속)</span></h2>
      <div className="pad">
        <div className="muted" style={{ marginBottom: 8 }}>
          평가에 사용한 자료의 출처·성격을 기록합니다(감사추적). 파일 업로드·DART 인제스트·
          RAG 는 후속 배선 — 지금은 메타데이터·메모 관리.</div>
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead><tr><th>자료명</th><th>종류</th><th>메모</th><th>링크</th><th></th></tr></thead>
            <tbody>{rows.map((r, i) => (
              <tr key={i}>
                <td><input type="text" value={r.name} onChange={setRow(i, "name")} style={{ width: 140 }} /></td>
                <td><select value={r.kind} onChange={setRow(i, "kind")} style={{ fontSize: 12 }}>
                  {["사업보고서", "감사보고서", "IR", "Big4 의견서", "복붙자료", "기타"].map((k) =>
                    <option key={k} value={k}>{k}</option>)}</select></td>
                <td><input type="text" value={r.note} onChange={setRow(i, "note")} style={{ width: 160 }} /></td>
                <td><input type="text" value={r.link} onChange={setRow(i, "link")} style={{ width: 120 }} placeholder="경로/URL" /></td>
                <td><button className="ghost xs" onClick={() => rm(i)}>✕</button></td>
              </tr>))}
              {!rows.length && <tr><td colSpan={5} className="muted">등록된 자료 없음.</td></tr>}
            </tbody>
          </table>
        </div>
        <button className="ghost" onClick={add} style={{ marginTop: 6 }}>+ 자료 추가</button>{" "}
        <button className="primary" onClick={save}>저장</button>
      </div>
    </div>
  );
}

const BRIEF_FIELDS = [
  ["overview", "사업 개요"], ["products", "주요 제품·서비스"],
  ["segments", "세그먼트·매출 구성"], ["market", "시장·산업 동향"],
  ["competition", "경쟁 구도·유사회사 후보"], ["risks", "주요 리스크·유의사항"],
];

const won = (v) => (v == null ? "-" : Math.round(v).toLocaleString("ko-KR"));

function BriefSheet({ project, onSave }) {
  const [brief, setBrief] = useState(project?.data?.brief || {});
  const [pre, setPre] = useState(project?.data?.brief_prefill || null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const set = (k) => (e) => setBrief({ ...brief, [k]: e.target.value });

  // DART 원문 XBRL 업로드 → 재무·세그먼트·주식수 결정론 추출 → 세그먼트 필드 자동 프리필.
  const loadXbrl = async (file) => {
    if (!file) return;
    setBusy(true); setErr(null);
    try {
      const d = await api.briefFromXbrl({ xbrl_b64: await fileToBase64(file),
        company_hint: project.company || "" });
      setPre(d);
      // 세그먼트 매출을 브리프 '세그먼트' 필드에 초안 주입(유저 편집 가능)
      const segLines = d.segments.map((s) => `${s.label}: ${won(s.revenue)}백만 (${s.period})`).join("\n");
      const nb = { ...brief, segments: segLines || brief.segments };
      setBrief(nb);
      onSave?.({ brief: nb, brief_prefill: d });
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const latest = pre?.periods?.length ? pre.financials[pre.periods[pre.periods.length - 1]] : null;

  return (
    <>
      <div className="card">
        <h2>Company Brief <span className="muted">— DART 원문 XBRL 추출 + 수기 보강</span></h2>
        <div className="pad">
          <div className="muted" style={{ marginBottom: 8 }}>
            DART 원문 XBRL(.xbrl)을 올리면 재무·부문매출·주식수를 결정론 추출합니다.
            (전체 자동 브리프 서사는 후속 — 지금은 프리필 + 수기 보강.)</div>
          <div className="row" style={{ gap: 12 }}>
            <label>DART XBRL(.xbrl) <input type="file" accept=".xbrl,.xml"
              onChange={(e) => loadXbrl(e.target.files[0])} disabled={busy} /></label>
            {busy && <span className="muted">추출 중…</span>}
          </div>
          {err && <div className="err">{err}</div>}
        </div>
      </div>

      {pre && (
        <div className="card">
          <h2>추출 결과 <span className="muted">— {pre.company || "회사"} · {pre.doc_period || ""}</span></h2>
          <div className="pad">
            {latest && (
              <div className="kpis">
                {latest.revenue != null && <div className="kpi"><div className="v">{won(latest.revenue)}</div><div className="k">매출액(백만)</div></div>}
                {latest.operating_income != null && <div className="kpi"><div className="v">{won(latest.operating_income)}</div><div className="k">영업이익</div></div>}
                {latest.equity != null && <div className="kpi"><div className="v">{won(latest.equity)}</div><div className="k">자본총계</div></div>}
                {latest.cash != null && <div className="kpi"><div className="v">{won(latest.cash)}</div><div className="k">현금성자산</div></div>}
              </div>
            )}
            {pre.segments.length > 0 && (
              <><h2 style={{ fontSize: "0.9rem", marginTop: 12 }}>부문 매출</h2>
                <table><thead><tr><th style={{ textAlign: "left" }}>부문</th><th>매출(백만)</th><th>기간</th></tr></thead>
                  <tbody>{pre.segments.map((s, i) => (
                    <tr key={i}><td style={{ textAlign: "left" }}>{s.label}</td>
                      <td>{won(s.revenue)}</td><td>{s.period}</td></tr>))}</tbody></table></>
            )}
            {Object.keys(pre.floating_ratio || {}).length > 0 && (
              <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>
                유통주식비율: {Object.entries(pre.floating_ratio).map(([k, v]) =>
                  `${k} ${(v * 100).toFixed(1)}%`).join(" · ")}</div>
            )}
          </div>
        </div>
      )}

      <div className="card">
        <h2>브리프 작성</h2>
        <div className="pad">
          {BRIEF_FIELDS.map(([k, label]) => (
            <div className="row" key={k}>
              <label>{label}</label>
              <textarea rows={2} value={brief[k] || ""} onChange={set(k)} />
            </div>
          ))}
          <button className="primary" onClick={() => onSave?.({ brief })}>저장</button>
        </div>
      </div>
    </>
  );
}

export default function MaterialsSheet({ project, sheet, onSave }) {
  return sheet === "brief"
    ? <BriefSheet project={project} onSave={onSave} />
    : <FilesSheet project={project} onSave={onSave} />;
}
