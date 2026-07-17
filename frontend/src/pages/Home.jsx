import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { MODE_LABEL } from "../nav.js";

/* 홈 = 프로젝트 목록 (최초화면, SharePoint 벤치마크: 극미니멀 리스트 —
   세로 구분선 無·컬럼 헤더 생략·상대시간·모드 뱃지). 랜딩 페이지는 만들지 않는다. */

const rel = (iso) => {
  if (!iso) return "";
  const d = (Date.now() - new Date(iso).getTime()) / 1000;
  if (d < 60) return "방금";
  if (d < 3600) return `${Math.floor(d / 60)}분 전`;
  if (d < 86400) return `${Math.floor(d / 3600)}시간 전`;
  return new Date(iso).toLocaleDateString("ko-KR");
};

function NewProjectForm({ onCreated, onCancel }) {
  const [name, setName] = useState("");
  const [company, setCompany] = useState("");
  const [mode, setMode] = useState("appraiser");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const create = async () => {
    setBusy(true); setErr(null);
    try {
      const p = await api.projects.create({ name, company, mode });
      onCreated(p);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card" style={{ maxWidth: 560 }}>
      <h2>새 프로젝트</h2>
      <div className="pad">
        <div className="row"><label>프로젝트명</label>
          <input type="text" value={name} placeholder="예: OO사 주식가치평가 (2026)"
            onChange={(e) => setName(e.target.value)} autoFocus /></div>
        <div className="row"><label>대상회사</label>
          <input type="text" value={company} placeholder="예: 주식회사 OO"
            onChange={(e) => setCompany(e.target.value)} /></div>
        <div className="row">
          <label>모드 — 생성 후 변경 불가(역할이 바뀌면 새 프로젝트)</label>
          <div className="mode-pick">
            {["appraiser", "auditor"].map((m) => (
              <button key={m} className={mode === m ? "picked" : ""}
                onClick={() => setMode(m)}>
                <b>{MODE_LABEL[m]}</b>
                <span>{m === "appraiser"
                  ? "가치평가 수행 → 모델·의견서 산출"
                  : "제공된 의견서를 독립 재수행으로 검증"}</span>
              </button>
            ))}
          </div>
        </div>
        <button className="primary" onClick={create} disabled={busy || !name.trim()}>
          {busy ? "생성 중…" : "생성"}
        </button>{" "}
        <button className="ghost" onClick={onCancel}>취소</button>
        {err && <div className="err">{err}</div>}
      </div>
    </div>
  );
}

export default function Home({ onOpen }) {
  const [projects, setProjects] = useState(null);
  const [creating, setCreating] = useState(false);
  const [err, setErr] = useState(null);

  const load = () =>
    api.projects.list().then(setProjects).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);

  const remove = async (e, p) => {
    e.stopPropagation();
    if (!window.confirm(`'${p.name}' 프로젝트를 삭제할까요? (되돌릴 수 없음)`)) return;
    await api.projects.remove(p.id);
    load();
  };

  return (
    <div className="home">
      <h1 className="home-title">Val.Studio</h1>
      <div className="home-sub">프로젝트를 열거나 새로 시작하세요 — 모드(평가인/감사인)는 프로젝트 속성입니다.</div>

      {creating ? (
        <NewProjectForm onCreated={(p) => onOpen(p.id)} onCancel={() => setCreating(false)} />
      ) : (
        <div className="home-actions">
          <button className="primary" onClick={() => setCreating(true)}>새 평가 시작</button>
        </div>
      )}

      {err && <div className="err">{err}</div>}
      {projects && projects.length === 0 && !creating && (
        <div className="placeholder">아직 프로젝트가 없습니다.</div>
      )}
      {projects && projects.length > 0 && (
        <div className="proj-list">
          {projects.map((p) => (
            <div key={p.id} className="proj-row" onClick={() => onOpen(p.id)}>
              <span className={`mode-badge ${p.mode}`}>{MODE_LABEL[p.mode]}</span>
              <span className="proj-name">{p.name}</span>
              <span className="proj-company">{p.company}</span>
              <span className="proj-time">{rel(p.updated_at)}</span>
              <button className="proj-del" title="삭제" onClick={(e) => remove(e, p)}>×</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
