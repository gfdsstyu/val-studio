import React from "react";
import { MODE_LABEL } from "../../nav.js";

/* 개요 대시보드 — 각 시트가 project.data 에 남긴 산출물을 교차 종합.
   ① 밸류에이션 요약(hero) ② 방식별 가치 비교(DCF·상대가치·시나리오) ③ 워크플로우 진행
   ④ 검증 게이트 ⑤ 평가 설계 ⑥ 다음 할 일. 순수 뷰(상태만 읽음), onNavigate 로 점프. */

const won = (v) => (v == null ? null : Math.round(v).toLocaleString("ko-KR"));
const pct = (v, d = 2) => (v == null ? "-" : (v * 100).toFixed(d) + "%");

/** 방식별 내재 주당가치 수집(있는 것만). */
function collectValues(d) {
  const out = [];
  if (d.dcf_result_summary?.per_share != null)
    out.push({ label: "DCF", value: d.dcf_result_summary.per_share, tone: "brand" });
  if (d.scenario_summary?.weighted_per_share != null)
    out.push({ label: "시나리오(가중)", value: d.scenario_summary.weighted_per_share, tone: "" });
  if (d.relative_summary?.per != null)
    out.push({ label: "상대가치 PER", value: d.relative_summary.per, tone: "" });
  if (d.relative_summary?.pbr != null)
    out.push({ label: "상대가치 PBR", value: d.relative_summary.pbr, tone: "" });
  return out;
}

/** 방식별 가치 비교 — CSS 가로 막대(차트 라이브러리 없이 자기완결). */
function ValueComparison({ values }) {
  if (!values.length) return (
    <div className="pad muted">아직 산출된 가치가 없습니다 — DCF·상대가치·시나리오를 실행하면
      여기서 방식별로 비교됩니다(자본시장법 종합평가).</div>
  );
  const nums = values.map((v) => v.value);
  const max = Math.max(...nums), min = Math.min(...nums);
  const med = [...nums].sort((a, b) => a - b)[Math.floor(nums.length / 2)];
  return (
    <div className="pad">
      <div className="kpis" style={{ marginBottom: 12 }}>
        <div className="kpi"><div className="v">{won(min)}</div><div className="k">최저</div></div>
        <div className="kpi"><div className="v">{won(med)}</div><div className="k">중앙값</div></div>
        <div className="kpi"><div className="v">{won(max)}</div><div className="k">최고</div></div>
        <div className="kpi"><div className="v">{max > 0 ? ((max / min - 1) * 100).toFixed(0) + "%" : "-"}</div><div className="k">최고/최저 격차</div></div>
      </div>
      {values.map((v, i) => (
        <div key={i} style={{ marginBottom: 8 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
            <span>{v.label}</span><span><b>{won(v.value)} 원</b></span>
          </div>
          <div style={{ height: 10, background: "var(--surface, #f0eef0)", borderRadius: 0 }}>
            <div style={{ height: "100%", width: `${max > 0 ? (v.value / max) * 100 : 0}%`,
              background: v.tone === "brand" ? "var(--brand)" : "var(--line)" }} />
          </div>
        </div>
      ))}
    </div>
  );
}

/** 워크플로우 진행 — 단계별 데이터 존재로 완료 판정. */
const STAGES = [
  { id: "materials", label: "0. 자료·Brief", keys: ["materials", "brief", "brief_prefill", "dart_financials"] },
  { id: "mapping", label: "1. 계정분류", keys: ["mapping_pl", "mapping_bs"] },
  { id: "assumptions", label: "2. 가정", keys: ["revenue_built", "costs_built", "fa_built", "wc_built"] },
  { id: "discount", label: "3. 할인율", keys: ["wacc_result", "peer_selected"] },
  { id: "valuation", label: "4. 밸류에이션", keys: ["dcf_result_summary", "scenario_summary", "relative_summary"] },
  { id: "output", label: "5. 산출물", keys: [] },
];

function Progress({ data, onNavigate }) {
  return (
    <div className="pad">
      {STAGES.map((st) => {
        const done = st.keys.some((k) => data[k] != null);
        const partial = st.keys.filter((k) => data[k] != null).length;
        return (
          <div key={st.id} onClick={() => onNavigate?.(st.id)}
            style={{ display: "flex", justifyContent: "space-between", alignItems: "center",
              padding: "6px 8px", borderBottom: "1px solid var(--line)", cursor: "pointer" }}>
            <span style={{ fontSize: 13 }}>{st.label}</span>
            <span className={`finding ${done ? "pass" : "warn"}`}
              style={{ margin: 0, padding: "1px 8px", fontSize: 11 }}>
              {done ? (st.keys.length > 1 ? `진행 ${partial}/${st.keys.length}` : "완료") : "대기"}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function nextTodo(d) {
  if (!d.wacc_result) return "3. 할인율 › WACC 빌드업에서 할인율을 확정하세요.";
  if (!d.dcf_result_summary) return "4. 밸류에이션 › DCF에서 첫 계산을 실행하세요.";
  if (!d.relative_summary && !d.scenario_summary)
    return "상대가치·시나리오로 가치 범위를 넓혀 종합평가를 완성하세요.";
  return "5. 산출물 › 리포트에서 의견서 초안을 확인하세요.";
}

export default function Dashboard({ project, onNavigate }) {
  const d = project?.data || {};
  const setup = project?.setup || {};
  const rec = setup.method_recommendation;
  const methodLabel = rec
    ? [...(rec.primary || []), ...(rec.secondary || [])].find((m) => m.id === setup.method)?.label ?? setup.method
    : setup.method;
  const s = d.dcf_result_summary;
  const w = d.wacc_result;
  const values = collectValues(d);
  const findings = [...(d.wacc_findings || []), ...(d.dcf_findings || [])];
  const fails = findings.filter((f) => f.severity === "fail").length;
  const warns = findings.filter((f) => f.severity === "warn").length;

  return (
    <>
      <div className="card">
        <h2>밸류에이션 요약</h2>
        <div className="pad">
          <div className="kpis">
            <div className="kpi hero"><div className="v">{s ? won(s.per_share) + " 원" : "-"}</div><div className="k">주당가치(DCF)</div></div>
            <div className="kpi"><div className="v">{w ? pct(w.wacc) : "-"}</div><div className="k">WACC</div></div>
            <div className="kpi"><div className="v">{values.length || "-"}</div><div className="k">적용 방식</div></div>
            <div className="kpi"><div className="v">{project.company || "-"}</div><div className="k">대상회사</div></div>
            <div className="kpi"><div className="v">{MODE_LABEL[project.mode]}</div><div className="k">모드</div></div>
          </div>
        </div>
      </div>

      <div className="card">
        <h2>방식별 가치 비교 <span className="muted">— 자본시장법 종합평가</span></h2>
        <ValueComparison values={values} />
      </div>

      <div className="grid2" style={{ gap: 0 }}>
        <div className="card" style={{ margin: "0 8px 0 0" }}>
          <h2>워크플로우 진행</h2>
          <Progress data={d} onNavigate={onNavigate} />
        </div>
        <div className="card" style={{ margin: 0 }}>
          <h2>검증 게이트</h2>
          <div className="pad">
            <div className="kpis">
              <div className="kpi"><div className="v" style={fails ? { color: "var(--err)" } : {}}>{fails}</div><div className="k">FAIL(차단)</div></div>
              <div className="kpi"><div className="v" style={warns ? { color: "var(--warn)" } : {}}>{warns}</div><div className="k">WARN(경고)</div></div>
              <div className="kpi"><div className="v">{Object.keys(d.wacc_provenance || {}).length}</div><div className="k">출처 추적</div></div>
            </div>
            {findings.slice(0, 4).map((f, i) => (
              <div key={i} className={`finding ${f.severity}`}>
                <b>[{f.severity.toUpperCase()}] {f.rule}</b> — {f.message}</div>
            ))}
            {!findings.length && <div className="muted">게이트 경고 없음 — 실행 후 표시됩니다.</div>}
          </div>
        </div>
      </div>

      {setup.method && (
        <div className="card">
          <h2>평가 설계 <span className="muted">— 셋업 위저드 확정값</span></h2>
          <div className="pad">
            <table><tbody>
              <tr><th style={{ width: 140, textAlign: "left" }}>확정 방법론</th><td style={{ textAlign: "left" }}><b>{methodLabel}</b></td></tr>
              <tr><th style={{ textAlign: "left" }}>평가기준일</th><td style={{ textAlign: "left" }}>{setup.valuation_date || "미정"}</td></tr>
              <tr><th style={{ textAlign: "left" }}>추정기간</th><td style={{ textAlign: "left" }}>{setup.horizon_years || "-"}년</td></tr>
              {rec?.legal_basis && (
                <tr><th style={{ textAlign: "left" }}>선정 근거</th><td style={{ textAlign: "left" }} className="muted">{rec.legal_basis}</td></tr>)}
            </tbody></table>
          </div>
        </div>
      )}

      <div className="card">
        <div className="pad">
          <span className="muted">다음 할 일: </span>{nextTodo(d)}
        </div>
      </div>
    </>
  );
}
