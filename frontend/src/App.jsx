import React, { useEffect, useState } from "react";
import { api } from "./api.js";
import { NAV, MODE_LABEL, firstAvailable } from "./nav.js";
import Home from "./pages/Home.jsx";
import ByokPanel from "./pages/Byok.jsx";
import DcfSheet from "./pages/appraiser/DcfSheet.jsx";

/* 셸(ia_ux_architecture.md §3): 헤더(정체성+상태, 액션 無) · LNB=단계 축 ·
   하단 시트탭=단계 내 시트 축 · 우측 접이식 패널(근거·AI 제안 자리) · 본문.
   라우팅: home ↔ project 워크스페이스 ↔ 설정(BYOK 오버레이). */

function CoverSheet({ project }) {
  const s = project?.data?.dcf_result_summary;
  const setup = project?.setup || {};
  const rec = setup.method_recommendation;
  const methodLabel = rec
    ? [...(rec.primary || []), ...(rec.secondary || [])]
        .find((m) => m.id === setup.method)?.label ?? setup.method
    : setup.method;
  return (
    <>
      <div className="card">
        <h2>상태 요약</h2>
        <div className="pad">
          <div className="kpis">
            <div className="kpi"><div className="v">{MODE_LABEL[project.mode]}</div><div className="k">모드</div></div>
            <div className="kpi"><div className="v">{project.company || "-"}</div><div className="k">대상회사</div></div>
            <div className="kpi"><div className="v">{s ? Math.round(s.per_share).toLocaleString("ko-KR") + " 원" : "-"}</div><div className="k">최근 주당가치</div></div>
            <div className="kpi"><div className="v">{s ? s.warn : "-"}</div><div className="k">audit 경고</div></div>
          </div>
          <div className="muted" style={{ marginTop: 12 }}>
            다음 할 일: {s ? "가정 근거 보강 후 시나리오·리포트로" : "4. 밸류에이션 > DCF 에서 첫 계산을 실행하세요"}
          </div>
        </div>
      </div>

      {setup.method && (
        <div className="card">
          <h2>평가 설계 <span className="muted">— 셋업 위저드 확정값</span></h2>
          <div className="pad">
            <table>
              <tbody>
                <tr><th style={{ width: 140, textAlign: "left" }}>확정 방법론</th>
                  <td style={{ textAlign: "left" }}><b>{methodLabel}</b></td></tr>
                <tr><th style={{ textAlign: "left" }}>평가기준일</th>
                  <td style={{ textAlign: "left" }}>{setup.valuation_date || "미정"}</td></tr>
                <tr><th style={{ textAlign: "left" }}>추정기간</th>
                  <td style={{ textAlign: "left" }}>{setup.horizon_years}년</td></tr>
                {rec?.legal_basis && (
                  <tr><th style={{ textAlign: "left" }}>선정 근거</th>
                    <td style={{ textAlign: "left" }} className="muted">{rec.legal_basis}</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}

function Workspace({ projectId, onHome }) {
  const [project, setProject] = useState(null);
  const [err, setErr] = useState(null);
  const [pos, setPos] = useState(null);            // {stage, sheet}
  const [panelOpen, setPanelOpen] = useState(false);
  const [showByok, setShowByok] = useState(false);

  useEffect(() => {
    api.projects.get(projectId)
      .then((p) => { setProject(p); setPos(firstAvailable(p.mode)); })
      .catch((e) => setErr(e.message));
  }, [projectId]);

  if (err) return <div className="err" style={{ padding: 20 }}>{err}</div>;
  if (!project || !pos) return <div className="placeholder">불러오는 중…</div>;

  const stages = NAV[project.mode];
  const stage = stages.find((s) => s.id === pos.stage) ?? stages[0];
  const sheet = stage.sheets.find((s) => s.id === pos.sheet) ?? stage.sheets[0];

  const gotoStage = (st) => {
    const first = st.sheets.find((s) => !s.soon) ?? st.sheets[0];
    setPos({ stage: st.id, sheet: first.id });
  };

  const saveData = (patch) =>
    api.projects.patch(project.id, { data: patch })
      .then(setProject).catch(() => {});

  const body = (() => {
    if (showByok) return <ByokPanel />;
    if (stage.id === "cover") return <CoverSheet project={project} />;
    if (stage.id === "valuation" && sheet.id === "dcf")
      return <DcfSheet project={project} onSave={saveData} />;
    return <div className="placeholder">'{stage.label} › {sheet.label}' 화면은 준비중입니다.</div>;
  })();

  return (
    <div className="shell">
      <div className="header">
        <img src="/logo@2x.png" alt="Val.Studio" className="logo-img"
          style={{ cursor: "pointer" }} onClick={onHome} title="홈으로" />
        <span className="screen">
          {project.name}
          <span className={`mode-badge ${project.mode}`} style={{ marginLeft: 8 }}>
            {MODE_LABEL[project.mode]}
          </span>
        </span>
        <span className="mode">
          <button className="linklike" onClick={() => setShowByok(!showByok)}>
            {showByok ? "← 작업으로" : "설정(BYOK)"}
          </button>
        </span>
      </div>

      <div className={`body ${panelOpen ? "with-panel" : ""}`}>
        <nav className="lnb">
          {stages.map((st) => (
            <button key={st.id}
              className={!showByok && stage.id === st.id ? "active" : ""}
              onClick={() => { setShowByok(false); gotoStage(st); }}>
              {st.label}
              {st.sheets.every((s) => s.soon) && <span className="soon">준비중</span>}
            </button>
          ))}
        </nav>

        <main className="main">
          <div className="main-inner">{body}</div>
        </main>

        {panelOpen && (
          <aside className="context-panel">
            <h2>근거·판단 보조</h2>
            <div className="pad muted">
              선택한 항목의 출처(provenance)·audit finding·AI 제안(⚖️ 애매 큐)이
              여기에 표시됩니다 — 추후 배선.
            </div>
          </aside>
        )}
        <button className="panel-toggle" title="근거·판단 보조 패널"
          onClick={() => setPanelOpen(!panelOpen)}>
          {panelOpen ? "»" : "«"}
        </button>
      </div>

      <div className="sheettabs">
        {!showByok && stage.sheets.map((sh) => (
          <button key={sh.id} disabled={sh.soon}
            className={sheet.id === sh.id ? "active" : ""}
            onClick={() => setPos({ stage: stage.id, sheet: sh.id })}>
            {sh.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function App() {
  const [view, setView] = useState({ page: "home" });
  if (view.page === "home")
    return <Home onOpen={(id) => setView({ page: "project", id })} />;
  return <Workspace projectId={view.id} onHome={() => setView({ page: "home" })} />;
}
