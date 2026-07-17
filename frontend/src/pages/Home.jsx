import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { MODE_LABEL } from "../nav.js";

/* 홈 = 프로젝트 목록 (SharePoint 벤치마크: 극미니멀 리스트). 랜딩 없음.
   새 프로젝트 = 2단계 위저드: ①기본(명칭·회사·모드) ②평가 설계(목적·거래유형·
   상장여부·기준일·추정기간 → 방법론 결정론 추천(법적 근거 병기) → 유저 확정).
   추천은 강제가 아니다 — override 가능, 규칙 없는 조합은 ⚖️ uncertain 표면화. */

const rel = (iso) => {
  if (!iso) return "";
  const d = (Date.now() - new Date(iso).getTime()) / 1000;
  if (d < 60) return "방금";
  if (d < 3600) return `${Math.floor(d / 60)}분 전`;
  if (d < 86400) return `${Math.floor(d / 3600)}시간 전`;
  return new Date(iso).toLocaleDateString("ko-KR");
};

const TRI = [["", "미정"], ["yes", "상장"], ["no", "비상장"]];
const triToBool = (v) => (v === "yes" ? true : v === "no" ? false : null);

function MethodCard({ m, picked, onPick }) {
  return (
    <button className={`method-card ${picked ? "picked" : ""}`} onClick={() => onPick(m.id)}>
      <b>{m.label}</b>
      <span className={m.available ? "avail" : "unavail"}>
        {m.available ? "엔진 가동" : "미구현(정직 표기)"}
      </span>
      <span className="muted">{m.engine}</span>
    </button>
  );
}

function NewProjectWizard({ onCreated, onCancel }) {
  const [step, setStep] = useState(1);
  const [name, setName] = useState("");
  const [company, setCompany] = useState("");
  const [mode, setMode] = useState("appraiser");
  // ── 평가 설계 ──
  const [opts, setOpts] = useState(null);
  const [purpose, setPurpose] = useState("transaction");
  const [dealType, setDealType] = useState("share_purchase");
  const [listed, setListed] = useState("");
  const [cpListed, setCpListed] = useState("");
  const [valDate, setValDate] = useState("");
  const [horizon, setHorizon] = useState("5");
  const [rec, setRec] = useState(null);
  const [chosen, setChosen] = useState(null);            // 확정 방법 id
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { api.health().then(() => api.projects); }, []);
  useEffect(() => {
    fetch("/api/method/options").then((r) => r.json()).then(setOpts).catch(() => {});
  }, []);

  const askRecommend = async () => {
    setBusy(true); setErr(null); setRec(null); setChosen(null);
    try {
      const r = await fetch("/api/method/recommend", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          purpose, deal_type: dealType,
          target_listed: triToBool(listed),
          counterparty_listed: triToBool(cpListed),
        }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      setRec(d);
      if (!d.uncertain && d.primary.length === 1) setChosen(d.primary[0].id);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const create = async () => {
    setBusy(true); setErr(null);
    try {
      const p = await api.projects.create({
        name, company, mode,
        setup: {
          purpose, deal_type: dealType,
          target_listed: triToBool(listed),
          counterparty_listed: triToBool(cpListed),
          valuation_date: valDate || null,
          horizon_years: Number(horizon) || 5,
          method: chosen,
          method_recommendation: rec,          // 추천 근거 스냅샷(감사 추적)
        },
      });
      onCreated(p);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const allMethods = rec ? [...rec.primary, ...rec.secondary] : [];

  return (
    <div className="card" style={{ maxWidth: 640 }}>
      <h2>새 프로젝트 <span className="muted">— {step}/2 {step === 1 ? "기본 정보" : "평가 설계"}</span></h2>
      <div className="pad">
        {step === 1 && (
          <>
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
                  <button key={m} className={mode === m ? "picked" : ""} onClick={() => setMode(m)}>
                    <b>{MODE_LABEL[m]}</b>
                    <span>{m === "appraiser"
                      ? "가치평가 수행 → 모델·의견서 산출"
                      : "제공된 의견서를 독립 재수행으로 검증"}</span>
                  </button>
                ))}
              </div>
            </div>
            <button className="primary" disabled={!name.trim()} onClick={() => setStep(2)}>
              다음 → 평가 설계
            </button>{" "}
            <button className="ghost" onClick={onCancel}>취소</button>
          </>
        )}

        {step === 2 && (
          <>
            <div className="grid2">
              <div className="row"><label>평가 목적</label>
                <select value={purpose} onChange={(e) => { setPurpose(e.target.value); setRec(null); }}>
                  {opts && Object.entries(opts.purposes).map(([k, v]) =>
                    <option key={k} value={k}>{v}</option>)}
                </select></div>
              <div className="row"><label>거래·대상 유형</label>
                <select value={dealType} onChange={(e) => { setDealType(e.target.value); setRec(null); }}>
                  {opts && Object.entries(opts.deal_types).map(([k, v]) =>
                    <option key={k} value={k}>{v}</option>)}
                </select></div>
              <div className="row"><label>평가대상 상장 여부</label>
                <select value={listed} onChange={(e) => { setListed(e.target.value); setRec(null); }}>
                  {TRI.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select></div>
              {dealType === "merger" && (
                <div className="row"><label>합병 상대방 상장 여부</label>
                  <select value={cpListed} onChange={(e) => { setCpListed(e.target.value); setRec(null); }}>
                    {TRI.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select></div>
              )}
              <div className="row"><label>평가기준일</label>
                <input type="date" value={valDate} onChange={(e) => setValDate(e.target.value)} /></div>
              <div className="row"><label>명시적 추정기간 (년, 관행 5)</label>
                <input type="number" min="1" max="10" value={horizon}
                  onChange={(e) => setHorizon(e.target.value)} /></div>
            </div>

            <button className="ghost" onClick={askRecommend} disabled={busy}>
              {busy ? "판정 중…" : "방법론 추천 받기 (결정론·법제 매핑)"}
            </button>

            {rec && (
              <div className="rec-box">
                {rec.uncertain && (
                  <div className="finding warn">⚖️ 이 조합엔 확립된 규칙이 없거나 정보가
                    부족합니다 — 아래에서 직접 선택하세요. {rec.notes[0]}</div>
                )}
                <div className="muted" style={{ margin: "8px 0 4px" }}>
                  근거: {rec.legal_basis}
                </div>
                <div className="method-grid">
                  {allMethods.map((m) => (
                    <MethodCard key={m.id} m={m} picked={chosen === m.id}
                      onPick={setChosen} />
                  ))}
                </div>
                {rec.notes.length > 0 && !rec.uncertain && (
                  <ul className="muted" style={{ margin: "8px 0 0", paddingLeft: 18 }}>
                    {rec.notes.map((n, i) => <li key={i}>{n}</li>)}
                  </ul>
                )}
              </div>
            )}

            <div style={{ marginTop: 12 }}>
              <button className="ghost" onClick={() => setStep(1)}>← 기본 정보</button>{" "}
              <button className="primary" onClick={create}
                disabled={busy || !rec || !chosen}>
                {busy ? "생성 중…" : "방법 확정 후 생성"}
              </button>
              {rec && !chosen && <span className="muted" style={{ marginLeft: 8 }}>방법을 선택하세요</span>}
            </div>
          </>
        )}
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
        <NewProjectWizard onCreated={(p) => onOpen(p.id)} onCancel={() => setCreating(false)} />
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
