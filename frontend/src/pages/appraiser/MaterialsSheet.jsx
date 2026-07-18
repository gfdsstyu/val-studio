import React, { useState } from "react";

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

function BriefSheet({ project, onSave }) {
  const [brief, setBrief] = useState(project?.data?.brief || {});
  const set = (k) => (e) => setBrief({ ...brief, [k]: e.target.value });
  return (
    <div className="card">
      <h2>Company Brief <span className="muted">— 수기 작성(LLM 자동 브리프는 후속)</span></h2>
      <div className="pad">
        <div className="muted" style={{ marginBottom: 8 }}>
          사업보고서·IR 를 읽고 핵심을 정리합니다. 이후 RAG 로 초안 자동제안 예정 —
          지금은 매출 트리·유사회사 판정의 근거 컨텍스트로 활용.</div>
        {BRIEF_FIELDS.map(([k, label]) => (
          <div className="row" key={k}>
            <label>{label}</label>
            <textarea rows={2} value={brief[k] || ""} onChange={set(k)} />
          </div>
        ))}
        <button className="primary" onClick={() => onSave?.({ brief })}>저장</button>
      </div>
    </div>
  );
}

export default function MaterialsSheet({ project, sheet, onSave }) {
  return sheet === "brief"
    ? <BriefSheet project={project} onSave={onSave} />
    : <FilesSheet project={project} onSave={onSave} />;
}
