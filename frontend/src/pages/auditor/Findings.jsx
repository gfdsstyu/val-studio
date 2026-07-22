import React, { useEffect, useState } from "react";
import { api } from "../../api.js";

/* 감사인 4. 발견사항 — 게이트·진단 결과를 감사조서 항목으로 확정하고 서사로 쓴다.

   서사 규격은 앤트로픽 finance 플러그인 variance-analysis 정본을 채택:
     [항목]: [유리/불리] 금액(%) / Driver: 왜 / Outlook: 지속·일회성 / Action: 조치
   안티패턴(순환설명 "예상보다 높음", 무설명 "timing", 뭉뚱그리기 "various items")은
   금지. 기계가 모은 finding 위에 감사인이 Driver·Action 을 채우는 구조다. */

const SEVERITY_LABEL = { fail: "🔴 FAIL", warn: "⚠️ WARN", pass: "✅ PASS" };

const fmt = (v) =>
  v == null || Number.isNaN(v) ? "-" : Math.round(v).toLocaleString("ko-KR");

/** 프로젝트 데이터에서 기계가 모을 수 있는 발견사항 전량. */
function collectFindings(data) {
  const out = [];
  const res = data?.audit_result;
  const claimed = data?.audit_claimed;

  if (claimed != null && res?.per_share != null) {
    const diff = res.per_share - claimed;
    const pct = (diff / claimed) * 100;
    out.push({
      key: "gap",
      severity: Math.abs(pct) > 10 ? "fail" : Math.abs(pct) > 3 ? "warn" : "pass",
      title: "주장값 대비 독립 추정 괴리",
      detail: `주장 ${fmt(claimed)}원 vs 독립 ${fmt(res.per_share)}원 — `
        + `${fmt(diff)}원(${pct > 0 ? "+" : ""}${pct.toFixed(1)}%)`,
    });
  }
  if (res?.gap_diagnosis) {
    out.push({
      key: "gap_diagnosis", severity: res.gap_diagnosis.severity,
      title: "구조버그 가설 진단", detail: res.gap_diagnosis.message,
    });
  }
  for (const f of res?.findings || []) {
    if (f.severity === "pass") continue;      // 통과 규칙은 조서에 싣지 않는다
    out.push({ key: f.rule, severity: f.severity, title: f.rule, detail: f.message });
  }
  const ex = data?.opinion_extract;
  if (ex && ex.confidence < 0.6) {
    out.push({
      key: "opinion_confidence", severity: "warn",
      title: "의견서 추출 신뢰도 저하",
      detail: `confidence ${ex.confidence} — 한글 CID 손실 의심. 유의적 가정을 수기 확인 필요`
        + (ex.note ? ` (${ex.note})` : ""),
    });
  }
  return out;
}

function Empty() {
  return (
    <div className="card"><div className="pad muted">
      먼저 <b>2. 독립 재계산</b> 을 실행하세요 — 발견사항은 게이트·진단 결과에서 모입니다.
    </div></div>
  );
}

function ListSheet({ project, onSave }) {
  const data = project?.data || {};
  const auto = collectFindings(data);
  const notes = data.audit_finding_notes || {};
  const [draft, setDraft] = useState(notes);

  if (!auto.length) return <Empty />;

  const setNote = (key, field) => (e) =>
    setDraft({ ...draft, [key]: { ...(draft[key] || {}), [field]: e.target.value } });

  return (
    <div className="card">
      <h2>finding 리스트 <span className="muted">— {auto.length}건(기계 수집)</span></h2>
      <div className="pad">
        <div className="muted" style={{ marginBottom: 10 }}>
          엔진 게이트·괴리 진단이 모은 항목입니다. 각 항목의 <b>Driver</b>(왜 발생했나)와{" "}
          <b>Action</b>(조치)은 감사인이 채웁니다 — 기계는 사실만, 판단은 감사인.
        </div>
        <table>
          <thead>
            <tr><th>심각도</th><th>항목</th><th>내용</th><th>Driver</th><th>Action</th></tr>
          </thead>
          <tbody>
            {auto.map((f) => (
              <tr key={f.key} className={f.severity === "fail" ? "err" : "warn"}>
                <td>{SEVERITY_LABEL[f.severity] || f.severity}</td>
                <td>{f.title}</td>
                <td>{f.detail}</td>
                <td><input type="text" style={{ width: 160 }}
                  value={draft[f.key]?.driver || ""} onChange={setNote(f.key, "driver")}
                  placeholder="왜 발생했나" /></td>
                <td><input type="text" style={{ width: 140 }}
                  value={draft[f.key]?.action || ""} onChange={setNote(f.key, "action")}
                  placeholder="없음/모니터/조사" /></td>
              </tr>
            ))}
          </tbody>
        </table>
        <button className="primary" style={{ marginTop: 12 }}
          onClick={() => onSave?.({ audit_finding_notes: draft })}>
          Driver·Action 저장
        </button>
      </div>
    </div>
  );
}

/** variance-analysis 서사 규격으로 조서 초안을 만든다(백엔드 불요 — 순수 조립). */
function buildNarrative(project) {
  const data = project?.data || {};
  const findings = collectFindings(data);
  const notes = data.audit_finding_notes || {};
  const res = data.audit_result;
  const claimed = data.audit_claimed;
  const ex = data.opinion_extract;

  const L = [];
  L.push(`# 평가 검증 조서 — ${project?.company || project?.name || "(대상 미지정)"}`);
  L.push("");
  L.push("## 1. 검증 범위");
  L.push("- 대상: 제출된 외부평가의견서의 유의적 가정·방법·데이터 (ISA 540 회계추정치)");
  L.push("- 방법: 감사인의 독립적 점추정(calc_core 결정론 엔진) + 구조버그 가설 진단 + 민감도 추적");
  L.push("");

  L.push("## 2. 의견서에서 식별한 유의적 가정");
  if (ex) {
    L.push(`- 평가대상 개수: ${ex.entity_count}${ex.is_sotp ? " (SOTP 의심)" : ""}`);
    L.push(`- 영구성장률 후보: ${ex.terminal_growths?.length
      ? ex.terminal_growths.map((g) => `${(g * 100).toFixed(2)}%`).join(", ") : "앵커 실패"}`);
    L.push(`- 규모프리미엄 후보: ${ex.size_premiums?.length
      ? ex.size_premiums.map((g) => `${(g * 100).toFixed(2)}%`).join(", ") : "미검출"}`);
    L.push(`- 통화: ${ex.currencies?.join(", ") || "-"} · 추출 신뢰도 ${ex.confidence}`);
  } else {
    L.push("- (의견서 미투입 — 1. 의견서 인제스트 단계 미완)");
  }
  L.push("");

  L.push("## 3. 독립 재계산 결과");
  if (res) {
    L.push(`- 감사인 독립 추정 주당가치: **${fmt(res.per_share)} 원**`);
    if (claimed != null) {
      const diff = res.per_share - claimed;
      const pct = (diff / claimed) * 100;
      L.push(`- 의견서 주장: ${fmt(claimed)} 원 → 괴리 ${fmt(diff)} 원 (${pct > 0 ? "+" : ""}${pct.toFixed(1)}%)`);
    }
    L.push(`- 기업가치(EV): ${fmt(res.enterprise_value)} · TV 비중: ${
      res.tv_weight != null ? `${(res.tv_weight * 100).toFixed(1)}%` : "-"}`);
  } else {
    L.push("- (재계산 미실행)");
  }
  L.push("");

  L.push("## 4. 발견사항");
  if (!findings.length) {
    L.push("- 없음");
  } else {
    for (const f of findings) {
      const n = notes[f.key] || {};
      const sev = f.severity === "fail" ? "불리(중대)" : f.severity === "warn" ? "주의" : "정상";
      L.push(`### ${f.title}`);
      L.push(`- 판정: ${sev} — ${f.detail}`);
      L.push(`- Driver: ${n.driver || "_(감사인 기재 필요)_"}`);
      L.push(`- Outlook: ${n.outlook || "_(지속/일회성 판단 필요)_"}`);
      L.push(`- Action: ${n.action || "_(없음/모니터/조사 중 선택)_"}`);
      L.push("");
    }
  }

  L.push("## 5. 결론");
  if (res && claimed != null) {
    const pct = Math.abs((res.per_share - claimed) / claimed) * 100;
    L.push(pct > 10
      ? "- 주장 주당가치와 감사인 독립 추정 간 유의적 괴리가 존재한다. 상기 발견사항의 조치가 완료되기 전에는 해당 추정치의 합리성을 결론내릴 수 없다."
      : "- 주장 주당가치는 감사인 독립 추정 범위와 정합한다. 다만 상기 주의 항목은 문서화가 필요하다.");
  } else {
    L.push("- (재계산·주장값 미확정 — 결론 보류)");
  }
  L.push("");
  L.push("> 본 조서는 결정론 엔진의 계산·게이트 결과 위에 감사인 판단을 기재한 초안이다.");
  return L.join("\n");
}

/** 표현 가드 결과 — 숫자 게이트와 같은 층위의 텍스트 게이트(전부 WARN, 차단 아님). */
function LintPanel({ lint }) {
  if (!lint) return null;
  if (lint.ok)
    return (
      <div className="ok" style={{ marginBottom: 10 }}>
        ✅ 표현 규칙 위반 없음 — 단정·순환설명·무설명·뭉뚱그리기 및 필수 슬롯 통과
      </div>
    );
  return (
    <div className="warn-box" style={{ marginBottom: 10 }}>
      <b>표현 규칙 위반 {lint.count}건</b>
      <ul>
        {lint.findings.map((f, i) => (
          <li key={i}>
            {f.message}
            {f.detail?.context && <> <code>…{f.detail.context}…</code></>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function NarrativeSheet({ project }) {
  const [copied, setCopied] = useState(false);
  const [lint, setLint] = useState(null);
  const md = buildNarrative(project);
  const notes = project?.data?.audit_finding_notes || {};

  // 조서가 바뀔 때마다 자동 린트 — 별도 버튼을 누르게 하면 아무도 안 누른다.
  useEffect(() => {
    let alive = true;
    api.reportLint({ text: md, notes, where: "조서" })
      .then((d) => { if (alive) setLint(d); })
      .catch(() => { if (alive) setLint(null); });
    return () => { alive = false; };
  }, [md]);                       // notes 는 md 에 반영되므로 md 변화로 충분

  const copy = () => {
    navigator.clipboard?.writeText(md).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <div className="card">
      <h2>서사 리포트 <span className="muted">— 조서 초안(variance 서사 규격)</span></h2>
      <div className="pad">
        <div className="muted" style={{ marginBottom: 10 }}>
          "예상보다 높음"(순환설명)·"timing"(무설명)·"기타 소액 항목"(뭉뚱그리기)은
          금지 표현입니다. 근거 없는 단정("분식입니다")도 감사 위험이므로
          "가능성/확인 필요/권고"로 표현하세요 — 아래 가드가 결정론으로 검사합니다.
        </div>
        <LintPanel lint={lint} />
        <button className="primary" onClick={copy}>{copied ? "복사됨 ✓" : "마크다운 복사"}</button>
        <pre style={{ marginTop: 12, whiteSpace: "pre-wrap" }}>{md}</pre>
      </div>
    </div>
  );
}

export default function Findings({ project, sheet, onSave }) {
  return sheet === "narrative"
    ? <NarrativeSheet project={project} />
    : <ListSheet project={project} onSave={onSave} />;
}
