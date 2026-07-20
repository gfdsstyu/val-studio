import React, { useMemo, useState } from "react";

/* 5.산출물 > 리포트 — 평가의견서 초안 렌더(클라이언트 조합, 백엔드 불요).
   각 단계 산출물(peer·WACC·매출·DCF·시나리오·검증 findings)을 project.data 에서 모아
   하나의 의견서로 종합. 마크다운 복사 지원. 값이 없는 섹션은 '미완료'로 정직 표기. */

const won = (v) => (v == null ? "-" : Math.round(v).toLocaleString("ko-KR") + " 원");
const pct = (v, d = 2) => (v == null ? "-" : (v * 100).toFixed(d) + "%");
const mm = (v) => (v == null ? "-" : Math.round(v).toLocaleString("ko-KR"));

export default function ReportSheet({ project }) {
  const d = project?.data || {};
  const setup = project?.setup || {};
  const rec = setup.method_recommendation;
  const methodLabel = rec
    ? [...(rec.primary || []), ...(rec.secondary || [])].find((m) => m.id === setup.method)?.label ?? setup.method
    : setup.method;
  const w = d.wacc_result;
  const s = d.dcf_result_summary;
  const sc = d.scenario_summary;
  const ts = d.three_statement_summary;
  const findings = [...(d.wacc_findings || []), ...(d.dcf_findings || []),
    ...(d.three_statement_findings || [])];
  const [copied, setCopied] = useState(false);

  const markdown = useMemo(() => {
    const L = [`# ${project.company || "대상회사"} 가치평가 의견서 (초안)`, ""];
    L.push(`- 평가대상: **${project.company || "-"}**`);
    L.push(`- 평가기준일: ${setup.valuation_date || "미정"}`);
    L.push(`- 평가목적/방법: ${methodLabel || "미정"}`);
    L.push(`- 추정기간: ${setup.horizon_years || "-"}년`, "");
    if (d.peer_selected) {
      L.push("## 1. 유사회사 선정", "");
      L.push(`확정 peer: ${d.peer_selected.map((c) => `${c.name}(${c.ticker})`).join(", ") || "없음"}`);
      if (d.peer_needs_review?.length)
        L.push("", "⚖️ 유저 판단 필요: " + d.peer_needs_review.map((t) => `${t.name} — ${t.reason}`).join("; "));
      L.push("");
    }
    if (w) {
      L.push("## 2. 할인율 (WACC)", "");
      L.push(`WACC ${pct(w.wacc)} = Ke ${pct(w.cost_of_equity)} · 세후 Kd ${pct(w.after_tax_cost_of_debt)} · relever β ${w.relevered_beta?.toFixed(3)}`);
      const prov = d.wacc_provenance || {};
      Object.keys(prov).forEach((k) => L.push(`- ${k}: ${prov[k]}`));
      L.push("");
    }
    if (s) {
      L.push("## 3. DCF 결과", "");
      L.push(`주당가치 **${won(s.per_share)}** · TV 비중 ${pct(s.tv_weight, 1)}`, "");
    }
    if (ts) {
      // 조립 배관 검증 결과 — 밸류에이션 숫자의 신뢰 근거라 의견서에 남긴다.
      L.push("## 3.5 모델 정합성 (3표 연결)", "");
      L.push(ts.ok && ts.converged
        ? "대차·현금연결·이익잉여금 롤포워드 정합 확인(허용오차 내). 순환참조는 고정점 반복으로 수렴."
        : "⚠️ 3표 정합성 불일치 — 조립 배관 재확인 필요. 아래 검증 항목 참조.", "");
    }
    if (sc) {
      L.push("## 4. 시나리오", "");
      L.push(`가중 주당가치 ${won(sc.weighted_per_share)} · 범위 ${mm(sc.spread?.[0])}~${mm(sc.spread?.[1])}`, "");
    }
    if (findings.length) {
      L.push("## 5. 검증·유의사항", "");
      findings.forEach((f) => L.push(`- [${f.severity.toUpperCase()}] ${f.rule}: ${f.message}`));
      L.push("");
    }
    L.push("> 본 초안은 결정론 엔진 산출 + 유저 승인 입력의 종합입니다. 최종 의견서는 검토 후 확정하세요.");
    return L.join("\n");
  }, [project, d, setup, methodLabel, w, s, sc, findings]);

  const copy = () => {
    navigator.clipboard?.writeText(markdown).then(() => {
      setCopied(true); setTimeout(() => setCopied(false), 1500);
    });
  };

  const done = { peer: !!d.peer_selected, wacc: !!w, revenue: !!d.revenue_built,
    dcf: !!s, scenario: !!sc };
  const Section = ({ ok, children }) => (
    <span className={`finding ${ok ? "pass" : "warn"}`} style={{ display: "inline-block", margin: "2px 4px 2px 0" }}>
      {children} {ok ? "✓" : "미완료"}
    </span>
  );

  return (
    <>
      <div className="card">
        <h2>평가의견서 <span className="muted">— 단계 산출물 종합(초안)</span></h2>
        <div className="pad">
          <div style={{ marginBottom: 10 }}>
            <Section ok={done.peer}>유사회사</Section>
            <Section ok={done.wacc}>WACC</Section>
            <Section ok={done.revenue}>매출</Section>
            <Section ok={done.dcf}>DCF</Section>
            <Section ok={!!ts}>3표 정합성</Section>
            <Section ok={done.scenario}>시나리오</Section>
          </div>
          <button className="primary" onClick={copy}>{copied ? "복사됨 ✓" : "마크다운 복사"}</button>
        </div>
      </div>

      <div className="card">
        <div className="pad">
          <h2 style={{ marginTop: 0 }}>{project.company || "대상회사"} 가치평가 의견서 (초안)</h2>
          <table><tbody>
            <tr><th style={{ textAlign: "left", width: 120 }}>평가대상</th><td style={{ textAlign: "left" }}>{project.company || "-"}</td></tr>
            <tr><th style={{ textAlign: "left" }}>평가기준일</th><td style={{ textAlign: "left" }}>{setup.valuation_date || "미정"}</td></tr>
            <tr><th style={{ textAlign: "left" }}>평가방법</th><td style={{ textAlign: "left" }}>{methodLabel || "미정"}</td></tr>
            <tr><th style={{ textAlign: "left" }}>추정기간</th><td style={{ textAlign: "left" }}>{setup.horizon_years || "-"}년</td></tr>
          </tbody></table>

          {s && (
            <div className="kpis" style={{ marginTop: 14 }}>
              <div className="kpi hero"><div className="v">{won(s.per_share)}</div><div className="k">주당가치</div></div>
              {sc && <div className="kpi"><div className="v">{won(sc.weighted_per_share)}</div><div className="k">가중(시나리오)</div></div>}
              {w && <div className="kpi"><div className="v">{pct(w.wacc)}</div><div className="k">WACC</div></div>}
              <div className="kpi"><div className="v">{pct(s.tv_weight, 1)}</div><div className="k">TV 비중</div></div>
            </div>
          )}

          {d.peer_selected && (
            <><h2 style={{ fontSize: "0.95rem", marginTop: 16 }}>1. 유사회사</h2>
              <div>확정: {d.peer_selected.map((c) => `${c.name}(${c.ticker})`).join(", ") || "없음"}</div>
              {d.peer_needs_review?.length > 0 && (
                <div className="muted" style={{ marginTop: 4 }}>⚖️ 판단 필요:{" "}
                  {d.peer_needs_review.map((t) => `${t.name}`).join(", ")}</div>)}
            </>
          )}

          {w && (
            <><h2 style={{ fontSize: "0.95rem", marginTop: 16 }}>2. 할인율 (WACC {pct(w.wacc)})</h2>
              <div className="muted">Ke {pct(w.cost_of_equity)} · 세후 Kd {pct(w.after_tax_cost_of_debt)} · relever β {w.relevered_beta?.toFixed(3)}</div>
              {d.wacc_provenance && (
                <table style={{ marginTop: 6 }}><tbody>
                  {Object.entries(d.wacc_provenance).map(([k, v]) => (
                    <tr key={k}><th style={{ textAlign: "left", width: 120 }}>{k}</th>
                      <td style={{ textAlign: "left" }} className="muted">{v}</td></tr>))}
                </tbody></table>)}
            </>
          )}

          {findings.length > 0 && (
            <><h2 style={{ fontSize: "0.95rem", marginTop: 16 }}>검증·유의사항</h2>
              {findings.map((f, i) => (
                <div key={i} className={`finding ${f.severity}`}>
                  <b>[{f.severity.toUpperCase()}] {f.rule}</b> — {f.message}</div>))}
            </>
          )}

          {!s && !w && (
            <div className="muted" style={{ marginTop: 16 }}>
              아직 산출물이 없습니다 — 유사회사·WACC·DCF·시나리오를 실행하면 여기에 종합됩니다.
            </div>
          )}
        </div>
      </div>
    </>
  );
}
