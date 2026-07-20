import React, { useEffect, useState } from "react";
import { api } from "./api.js";
import { NAV, MODE_LABEL, firstAvailable } from "./nav.js";
import Home from "./pages/Home.jsx";
import ByokPanel from "./pages/Byok.jsx";
import DcfSheet from "./pages/appraiser/DcfSheet.jsx";
import DiscountSheet from "./pages/appraiser/DiscountSheet.jsx";
import ScenarioSheet from "./pages/appraiser/ScenarioSheet.jsx";
import ModelSheet from "./pages/appraiser/ModelSheet.jsx";
import RelativeSheet from "./pages/appraiser/RelativeSheet.jsx";
import MacroSheet from "./pages/appraiser/MacroSheet.jsx";
import RevenueSheet from "./pages/appraiser/RevenueSheet.jsx";
import PeerSheet from "./pages/appraiser/PeerSheet.jsx";
import ReportSheet from "./pages/appraiser/ReportSheet.jsx";
import CostsSheet from "./pages/appraiser/CostsSheet.jsx";
import FaSheet from "./pages/appraiser/FaSheet.jsx";
import WcSheet from "./pages/appraiser/WcSheet.jsx";
import MaterialsSheet from "./pages/appraiser/MaterialsSheet.jsx";
import MappingSheet from "./pages/appraiser/MappingSheet.jsx";
import Dashboard from "./pages/appraiser/Dashboard.jsx";
import Roundtrip from "./pages/appraiser/Roundtrip.jsx";
import OpinionIngest from "./pages/auditor/OpinionIngest.jsx";
import IndependentRecalc from "./pages/auditor/IndependentRecalc.jsx";
import GapDiagnosis from "./pages/auditor/GapDiagnosis.jsx";
import Findings from "./pages/auditor/Findings.jsx";

/* 셸(ia_ux_architecture.md §3): 헤더(정체성+상태, 액션 無) · LNB=단계 축 ·
   하단 시트탭=단계 내 시트 축 · 우측 접이식 패널(근거·AI 제안 자리) · 본문.
   라우팅: home ↔ project 워크스페이스 ↔ 설정(BYOK 오버레이). */

function CoverSheet({ project }) {
  const auditor = project.mode === "auditor";
  const d = project?.data || {};
  // 감사인은 독립 재계산 결과가 요약 대상(평가인의 dcf_result_summary 와 데이터 격리).
  const s = auditor
    ? (d.audit_result && {
        per_share: d.audit_result.per_share,
        warn: (d.audit_result.findings || []).filter((f) => f.severity !== "pass").length,
      })
    : d.dcf_result_summary;
  const claimed = d.audit_claimed;
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
            <div className="kpi"><div className="v">{s ? Math.round(s.per_share).toLocaleString("ko-KR") + " 원" : "-"}</div><div className="k">{auditor ? "독립 추정 주당가치" : "최근 주당가치"}</div></div>
            {auditor && (
              <div className="kpi"><div className="v">{claimed != null ? Math.round(claimed).toLocaleString("ko-KR") + " 원" : "-"}</div><div className="k">의견서 주장</div></div>
            )}
            <div className="kpi"><div className="v">{s ? s.warn : "-"}</div><div className="k">audit 경고</div></div>
          </div>
          <div className="muted" style={{ marginTop: 12 }}>
            다음 할 일: {auditor
              ? (!d.opinion_extract ? "1. 의견서 인제스트에서 의견서를 투입하세요"
                : !d.audit_result ? "2. 독립 재계산에서 감사인 추정을 세우세요"
                : "3. 괴리 진단 → 4. 발견사항으로 조서를 마무리하세요")
              : (s ? "가정 근거 보강 후 시나리오·리포트로" : "4. 밸류에이션 > DCF 에서 첫 계산을 실행하세요")}
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

/** 근거·판단 보조 패널 — 저장된 provenance(출처 라벨) + 비-pass 게이트 findings.
    DiscountSheet/DcfSheet 가 onSave 로 남긴 데이터를 감사 추적용으로 표면화. */
function ContextPanel({ project }) {
  const d = project?.data || {};
  const prov = d.wacc_provenance || {};
  const provKeys = Object.keys(prov);
  const findings = [...(d.wacc_findings || []), ...(d.dcf_findings || []),
    ...(d.three_statement_findings || [])];
  const empty = !provKeys.length && !findings.length;
  return (
    <aside className="context-panel">
      <h2>근거·판단 보조</h2>
      <div className="pad">
        {empty && (
          <div className="muted">
            WACC 빌드업·DCF 를 실행하면 출처(provenance)와 게이트 경고가 여기 모입니다.
          </div>
        )}
        {provKeys.length > 0 && (
          <>
            <h3 style={{ fontSize: 12, color: "var(--sub)", margin: "4px 0" }}>출처 (provenance)</h3>
            <table><tbody>
              {provKeys.map((k) => (
                <tr key={k}><th style={{ textAlign: "left", width: 96 }}>{k}</th>
                  <td style={{ textAlign: "left" }} className="muted">{prov[k]}</td></tr>
              ))}
            </tbody></table>
          </>
        )}
        {findings.length > 0 && (
          <>
            <h3 style={{ fontSize: 12, color: "var(--sub)", margin: "10px 0 4px" }}>게이트 경고</h3>
            {findings.map((f, i) => (
              <div key={i} className={`finding ${f.severity}`}>
                <b>[{f.severity.toUpperCase()}] {f.rule}</b> — {f.message}
              </div>
            ))}
          </>
        )}
      </div>
    </aside>
  );
}

/** Task Pane 임베드 모드(?embed=1) — 좁은 폭(~350px) 대응. FR-M2.7. */
const EMBED = new URLSearchParams(window.location.search).has("embed");

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
    if (stage.id === "cover")
      return project.mode === "appraiser"
        ? <Dashboard project={project}
            onNavigate={(sid) => { const st = stages.find((x) => x.id === sid); if (st) gotoStage(st); }} />
        : <CoverSheet project={project} />;
    if (stage.id === "materials")
      return <MaterialsSheet project={project} sheet={sheet.id} onSave={saveData} />;
    if (stage.id === "mapping")
      return <MappingSheet project={project} sheet={sheet.id} onSave={saveData} />;
    if (stage.id === "assumptions" && sheet.id === "macro")
      return <MacroSheet project={project} onSave={saveData} />;
    if (stage.id === "assumptions" && sheet.id === "revenue")
      return <RevenueSheet project={project} onSave={saveData} />;
    if (stage.id === "assumptions" && sheet.id === "costs")
      return <CostsSheet project={project} onSave={saveData} />;
    if (stage.id === "assumptions" && sheet.id === "fa")
      return <FaSheet project={project} onSave={saveData} />;
    if (stage.id === "assumptions" && sheet.id === "wc")
      return <WcSheet project={project} onSave={saveData} />;
    if (stage.id === "discount" && sheet.id === "peer")
      return <PeerSheet project={project} onSave={saveData} />;
    if (stage.id === "discount" && sheet.id === "wacc")
      return <DiscountSheet project={project} onSave={saveData} />;
    if (stage.id === "output" && sheet.id === "report")
      return <ReportSheet project={project} />;
    if (stage.id === "valuation" && sheet.id === "dcf")
      return <DcfSheet project={project} onSave={saveData} />;
    if (stage.id === "valuation" && sheet.id === "model")
      return <ModelSheet project={project} onSave={saveData} />;
    if (stage.id === "valuation" && sheet.id === "scenario")
      return <ScenarioSheet project={project} onSave={saveData} />;
    if (stage.id === "valuation" && sheet.id === "relative")
      return <RelativeSheet project={project} onSave={saveData} />;
    if (stage.id === "output" && (sheet.id === "export" || sheet.id === "diff"))
      return <Roundtrip project={project} sheet={sheet.id} onSave={saveData} />;
    // 감사인 트랙 — 평가인 트랙과 데이터·화면 모두 격리(모드는 생성 시 1회 확정).
    if (stage.id === "ingest")
      return <OpinionIngest project={project} sheet={sheet.id} onSave={saveData} />;
    if (stage.id === "recalc")
      return <IndependentRecalc project={project} sheet={sheet.id} onSave={saveData} />;
    if (stage.id === "diagnosis")
      return <GapDiagnosis project={project} sheet={sheet.id} />;
    if (stage.id === "findings")
      return <Findings project={project} sheet={sheet.id} onSave={saveData} />;
    return <div className="placeholder">'{stage.label} › {sheet.label}' 화면은 준비중입니다.</div>;
  })();

  return (
    <div className={`shell${EMBED ? " embed" : ""}`}>
      <div className="header">
        <img src="/logo@2x.png" alt="Val.Studio" className="logo-img"
          style={{ cursor: "pointer" }} onClick={onHome} title="홈으로" />
        <span className="screen">
          {EMBED ? sheet.label : project.name}
          {!EMBED && (
          <span className={`mode-badge ${project.mode}`} style={{ marginLeft: 8 }}>
            {MODE_LABEL[project.mode]}
          </span>
          )}
        </span>
        <span className="mode">
          {EMBED && !showByok && (
            <select className="embed-stage" value={stage.id}
              onChange={(e) => gotoStage(stages.find((s) => s.id === e.target.value))}>
              {stages.map((st) => (
                <option key={st.id} value={st.id}
                  disabled={st.sheets.every((s) => s.soon)}>{st.label}</option>
              ))}
            </select>
          )}
          <button className="linklike" onClick={() => setShowByok(!showByok)}>
            {showByok ? "←" : "BYOK"}
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

        {panelOpen && <ContextPanel project={project} />}
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
