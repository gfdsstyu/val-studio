import React, { useState } from "react";
import { api, fileToBase64 } from "../../api.js";

/* 왕복(export ↔ diff) — 5. 산출물 단계.
   export: 로컬 DCF 입력 → 수식 live .xlsx 다운로드(감사 추적·재편집).
   diff:   before/after 워크북 업로드 → 3버킷 diff + apply-정책(자동 반영/승인 대기/차단).
   apply-정책: ① 입력변경(safe) → 자동 재계산·반영 ② 수식변경 → 승인 대기 ③ 구조 → 차단. */

function ExportSheet({ project }) {
  const input = project?.data?.dcf_input;
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const download = async () => {
    setBusy(true); setErr(null);
    try {
      const blob = await api.xlsx.exportBlob(input);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${project.company || "valstudio"}_dcf.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <div className="card">
      <h2>xlsx Export <span className="muted">— 수식 live(감사 추적)</span></h2>
      <div className="pad">
        {!input && <div className="muted">먼저 4. 밸류에이션 › DCF 에서 계산을 실행하세요.</div>}
        {input && (
          <>
            <div className="muted" style={{ marginBottom: 10 }}>
              현재 DCF 입력을 수식이 살아있는 .xlsx 로 내보냅니다. 엑셀에서 편집 후
              아래 '왕복 diff'로 다시 반영할 수 있습니다.
            </div>
            <button className="primary" disabled={busy} onClick={download}>
              {busy ? "생성 중…" : "xlsx 내보내기"}
            </button>
          </>
        )}
        {err && <div className="err" style={{ marginTop: 10 }}>{err}</div>}
      </div>
    </div>
  );
}

function Bucket({ title, tone, changes }) {
  if (!changes?.length) return null;
  return (
    <div className="card">
      <h2>{title} <span className="muted">— {changes.length}건</span></h2>
      <div className="pad">
        <table>
          <thead><tr><th>시트</th><th>셀</th><th>이전</th><th>이후</th></tr></thead>
          <tbody>
            {changes.slice(0, 40).map((c, i) => (
              <tr key={i} className={tone}>
                <td>{c.sheet}</td><td>{c.ref}</td>
                <td><code>{c.old}</code></td><td><code>{c.new}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
        {changes.length > 40 && <div className="muted">…외 {changes.length - 40}건</div>}
      </div>
    </div>
  );
}

function DiffSheet({ project, onSave }) {
  const [before, setBefore] = useState(null);
  const [after, setAfter] = useState(null);
  const [plan, setPlan] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [applied, setApplied] = useState(false);

  const compare = async () => {
    if (!before || !after) { setErr("before/after 두 파일을 선택하세요."); return; }
    setBusy(true); setErr(null); setPlan(null); setApplied(false);
    try {
      const [b, a] = await Promise.all([fileToBase64(before), fileToBase64(after)]);
      setPlan(await api.xlsx.diff(b, a));
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const applySafe = () => {
    if (!plan?.new_input) return;
    onSave?.({
      dcf_input: plan.new_input,
      dcf_result_summary: plan.new_result && {
        per_share: plan.new_result.per_share,
        warn: (plan.new_result.findings || []).filter((f) => f.severity !== "pass").length,
      },
    });
    setApplied(true);
  };

  return (
    <>
      <div className="card">
        <h2>왕복 diff <span className="muted">— 편집본 → 로컬 모델 반영</span></h2>
        <div className="pad">
          <div className="muted" style={{ marginBottom: 10 }}>
            export 한 원본(before)과 엑셀에서 편집한 파일(after)을 올리면, 변경을 3버킷으로
            분류합니다. <b>입력만 바뀌면 자동 반영</b>, 수식 변경은 승인 대기, 구조 변경은 차단.
          </div>
          <div className="row" style={{ gap: 16 }}>
            <label>before(원본) <input type="file" accept=".xlsx"
              onChange={(e) => setBefore(e.target.files[0])} /></label>
            <label>after(편집본) <input type="file" accept=".xlsx"
              onChange={(e) => setAfter(e.target.files[0])} /></label>
            <button className="primary" disabled={busy} onClick={compare}>
              {busy ? "비교 중…" : "비교"}
            </button>
          </div>
          {err && <div className="err" style={{ marginTop: 10 }}>{err}</div>}
        </div>
      </div>

      {plan && (
        <div className="card">
          <h2>판정</h2>
          <div className="pad">
            <div className={plan.safe ? "ok" : "warn-box"}>
              {plan.safe
                ? "✅ 입력 변경만 — 자동 반영 가능"
                : "⚠️ 수식/구조 변경 포함 — 리뷰 필요"}
              {"  "}(입력 {plan.counts.auto_apply} · 수식 {plan.counts.review_queue} · 구조 {plan.counts.blocked})
            </div>
            {plan.safe && plan.new_result && (
              <div style={{ marginTop: 12 }}>
                <div className="muted">
                  재계산 주당가치: <b>{Math.round(plan.new_result.per_share).toLocaleString("ko-KR")} 원</b>
                </div>
                <button className="primary" style={{ marginTop: 8 }}
                  disabled={applied} onClick={applySafe}>
                  {applied ? "반영됨 ✓" : "로컬 모델에 자동 반영"}
                </button>
              </div>
            )}
            {!plan.safe && plan.counts.review_queue > 0 && (
              <div className="muted" style={{ marginTop: 12 }}>
                수식 변경은 평가인 승인이 필요합니다(LLM 해설·개별 승인은 후속 배선). 아래
                '② 수식 변경'을 검토하세요.
              </div>
            )}
            {plan.row_warnings?.length > 0 && (
              <div className="warn-box" style={{ marginTop: 12 }}>
                <b>외딴 편집 감지</b>
                <ul>{plan.row_warnings.slice(0, 10).map((w, i) => <li key={i}>{w}</li>)}</ul>
              </div>
            )}
          </div>
        </div>
      )}

      {plan && <Bucket title="① 입력 변경(정상)" tone="ok" changes={plan.auto_apply} />}
      {plan && <Bucket title="② 수식 변경(리뷰)" tone="warn" changes={plan.review_queue} />}
      {plan && <Bucket title="③ 구조 변경(위험)" tone="err" changes={plan.blocked} />}
    </>
  );
}

export default function Roundtrip({ project, sheet, onSave }) {
  return sheet === "export"
    ? <ExportSheet project={project} />
    : <DiffSheet project={project} onSave={onSave} />;
}
