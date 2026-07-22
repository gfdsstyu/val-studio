import React, { useState } from "react";
import { api, fileToBase64 } from "../../api.js";

/* 엑셀 ⇄ 웹 왕복 루프 — 5. 산출물 단계.

   루프: export(수식 live) → 엑셀·Claude for Excel 에서 편집 → 되읽기/비교 →
         로컬 모델 반영 → **새 버전 export** → 반복.

   기준선(before)은 기본이 **프로젝트 저장본 재생성**이다 — 평가인이 원본 파일을
   손수 보관·업로드하지 않아도 편집본 하나만 올리면 루프가 돈다. 반영 정책 4버킷:
   ① 입력변경=자동 ② 수식변경=승인 대기 ③ 구조변경=차단 ④ 상태·로그=증적 이관.
   ②가 섞여 있어도 ①만 부분 반영할 수 있다(전체 safe 를 기다리지 않는다). */

/** 스킬 증적(`_VS_STATE`·`Claude Log`) 표시 — Claude for Excel 세션에서 넘어온 상태. */
function SkillStatePanel({ state }) {
  if (!state) return null;
  const { keys = {}, assumptions = [], log = [], warnings = [] } = state;
  return (
    <div className="card">
      <h2>
        스킬 증적 <span className="muted">— Claude for Excel 세션에서 이관</span>
      </h2>
      <div className="pad">
        <div className="muted" style={{ marginBottom: 10 }}>
          단계 <b>{keys.stage || "-"}</b>
          {keys.last_gate_passed && <> · 마지막 게이트 <b>{keys.last_gate_passed}</b></>}
          {keys.engine_tieout_per_share != null && (
            <> · 워크북 tie-out <b>{Number(keys.engine_tieout_per_share).toLocaleString("ko-KR")} 원</b></>
          )}
        </div>

        {warnings.length > 0 && (
          <div className="warn-box" style={{ marginBottom: 10 }}>
            <b>가정 대장 경고</b>
            <ul>{warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
          </div>
        )}

        {assumptions.length > 0 && (
          <table>
            <thead>
              <tr><th>가정</th><th>값</th><th>출처</th><th>근거</th><th>승인</th></tr>
            </thead>
            <tbody>
              {assumptions.map((a, i) => (
                <tr key={i}>
                  <td>{a.name}</td><td>{a.value}</td><td>{a.source_type}</td>
                  <td>{a.basis}</td><td>{a.approval || "미승인"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {log.length > 0 && (
          <details style={{ marginTop: 10 }}>
            <summary className="muted">Claude Log — {log.length}행</summary>
            <ul>{log.slice(0, 30).map((l, i) => <li key={i}><code>{l}</code></li>)}</ul>
          </details>
        )}
      </div>
    </div>
  );
}

/** 반영 완료 후 루프를 잇는 재-export 버튼(변경버전 내려받기). */
function ReexportButton({ input, company, label = "새 버전 xlsx 내보내기" }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const download = async () => {
    setBusy(true); setErr(null);
    try {
      const blob = await api.xlsx.exportBlob(input);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${company || "valstudio"}_dcf_v${Date.now().toString().slice(-6)}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <>
      <button style={{ marginTop: 8, marginLeft: 8 }} disabled={busy} onClick={download}>
        {busy ? "생성 중…" : `↻ ${label}`}
      </button>
      {err && <div className="err" style={{ marginTop: 8 }}>{err}</div>}
    </>
  );
}

/** 편집본 되읽기 — 단일 .xlsx 업로드 → 표준 레이아웃 역파싱 → 재계산·로컬 반영.
    diff 와 달리 기준선 없이 바로 반영(변경 분류 없이 통째 교체). */
function ImportPanel({ project, onSave }) {
  const [file, setFile] = useState(null);
  const [out, setOut] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [applied, setApplied] = useState(false);

  const load = async () => {
    if (!file) { setErr("xlsx 파일을 선택하세요."); return; }
    setBusy(true); setErr(null); setOut(null); setApplied(false);
    try {
      setOut(await api.xlsx.import(await fileToBase64(file)));
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const apply = () => {
    if (!out) return;
    onSave?.({
      dcf_input: out.input,
      dcf_result_summary: {
        per_share: out.result.per_share,
        warn: (out.result.findings || []).filter((f) => f.severity !== "pass").length,
      },
      ...(out.skill_state ? { skill_state: out.skill_state } : {}),
    });
    setApplied(true);
  };

  return (
    <>
      <div className="card">
        <h2>편집본 되읽기 <span className="muted">— 단일 xlsx → 로컬 모델 재구성</span></h2>
        <div className="pad">
          <div className="muted" style={{ marginBottom: 10 }}>
            내보낸 표준 레이아웃 xlsx 를 엑셀에서 편집했다면, 기준선 없이 바로 올려
            입력을 역파싱·재계산합니다(비표준 템플릿은 거부). 무엇이 바뀌었는지
            분류해서 보려면 <b>왕복 diff</b> 를 쓰세요.
          </div>
          <div className="row" style={{ gap: 16 }}>
            <label>편집본 xlsx <input type="file" accept=".xlsx"
              onChange={(e) => setFile(e.target.files[0])} /></label>
            <button className="primary" disabled={busy} onClick={load}>
              {busy ? "읽는 중…" : "되읽기"}
            </button>
          </div>
          {err && <div className="err" style={{ marginTop: 10 }}>{err}</div>}
          {out && (
            <div style={{ marginTop: 12 }}>
              <div className="muted">재계산 주당가치:
                <b> {Math.round(out.result.per_share).toLocaleString("ko-KR")} 원</b></div>
              <button className="primary" style={{ marginTop: 8 }} disabled={applied} onClick={apply}>
                {applied ? "반영됨 ✓" : "로컬 모델에 반영"}
              </button>
              {applied && <ReexportButton input={out.input} company={project?.company} />}
            </div>
          )}
        </div>
      </div>
      {out?.skill_state && <SkillStatePanel state={out.skill_state} />}
    </>
  );
}

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
              현재 DCF 입력을 수식이 살아있는 .xlsx 로 내보냅니다. 엑셀이나 Claude for
              Excel 에서 편집한 뒤 <b>왕복 diff</b> 에 편집본만 올리면(기준선은 저장본에서
              자동 생성) 변경이 분류·반영됩니다.
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
  const [mode, setMode] = useState("project");   // 기준선: 저장본 재생성 | 원본 업로드
  const [before, setBefore] = useState(null);
  const [after, setAfter] = useState(null);
  const [plan, setPlan] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [applied, setApplied] = useState(null);  // 반영된 input(재-export 재료)

  const hasSaved = !!project?.data?.dcf_input;

  const compare = async () => {
    if (!after) { setErr("편집본 파일을 선택하세요."); return; }
    if (mode === "upload" && !before) { setErr("기준선(before) 파일을 선택하세요."); return; }
    setBusy(true); setErr(null); setPlan(null); setApplied(null);
    try {
      const a = await fileToBase64(after);
      setPlan(mode === "project"
        ? await api.xlsx.diffVsProject(project.id, a)
        : await api.xlsx.diff(await fileToBase64(before), a));
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  /** 입력 변경 반영(전체 safe 면 전량, 아니면 입력분만 — 수식은 리뷰에 남는다). */
  const applyInputs = () => {
    if (!plan?.new_input) return;
    onSave?.({
      dcf_input: plan.new_input,
      dcf_result_summary: plan.new_result && {
        per_share: plan.new_result.per_share,
        warn: (plan.new_result.findings || []).filter((f) => f.severity !== "pass").length,
      },
      ...(plan.skill_state ? { skill_state: plan.skill_state } : {}),
    });
    setApplied(plan.new_input);
  };

  const c = plan?.counts;
  const partial = plan && !plan.safe && plan.new_input && c?.auto_apply > 0;

  return (
    <>
      <div className="card">
        <h2>왕복 diff <span className="muted">— 편집본 → 로컬 모델 반영</span></h2>
        <div className="pad">
          <div className="muted" style={{ marginBottom: 10 }}>
            엑셀·Claude for Excel 에서 편집한 파일을 올리면 변경을 4버킷으로 분류합니다.
            <b> 입력 변경은 자동 반영</b>, 수식 변경은 승인 대기, 구조 변경은 차단,
            스킬 상태·로그는 증적으로 이관됩니다.
          </div>

          <div className="row" style={{ gap: 16, marginBottom: 10 }}>
            <label>
              <input type="radio" checked={mode === "project"} disabled={!hasSaved}
                onChange={() => setMode("project")} />
              {" "}저장본 대비 <span className="muted">(권장 — 편집본만 올리면 됨)</span>
            </label>
            <label>
              <input type="radio" checked={mode === "upload"}
                onChange={() => setMode("upload")} />
              {" "}원본 직접 업로드
            </label>
          </div>
          {!hasSaved && (
            <div className="muted" style={{ marginBottom: 10 }}>
              저장된 DCF 입력이 없어 저장본 기준선을 만들 수 없습니다 — 먼저
              4. 밸류에이션 › DCF 에서 계산·저장하거나 원본을 직접 올리세요.
            </div>
          )}

          <div className="row" style={{ gap: 16 }}>
            {mode === "upload" && (
              <label>before(원본) <input type="file" accept=".xlsx"
                onChange={(e) => setBefore(e.target.files[0])} /></label>
            )}
            <label>편집본 xlsx <input type="file" accept=".xlsx"
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
              {"  "}(입력 {c.auto_apply} · 수식 {c.review_queue} · 구조 {c.blocked}
              {c.state > 0 && <> · 증적 {c.state}</>})
              {plan.baseline === "project" && (
                <span className="muted"> — 기준선: 프로젝트 저장본</span>
              )}
            </div>

            {plan.new_result && (c.auto_apply > 0 || plan.safe) && (
              <div style={{ marginTop: 12 }}>
                <div className="muted">
                  재계산 주당가치: <b>{Math.round(plan.new_result.per_share).toLocaleString("ko-KR")} 원</b>
                </div>
                {partial && (
                  <div className="muted" style={{ marginTop: 6 }}>
                    수식 변경 {c.review_queue}건은 <b>반영되지 않고</b> 아래 ②에 남습니다 —
                    입력 변경분만 먼저 반영합니다.
                  </div>
                )}
                <button className="primary" style={{ marginTop: 8 }}
                  disabled={!!applied} onClick={applyInputs}>
                  {applied ? "반영됨 ✓" : partial ? "입력 변경만 부분 반영" : "로컬 모델에 자동 반영"}
                </button>
                {applied && <ReexportButton input={applied} company={project?.company} />}
              </div>
            )}

            {c.blocked > 0 && (
              <div className="muted" style={{ marginTop: 12 }}>
                구조 변경이 있어 템플릿 정합이 깨졌을 수 있습니다 — 아래 ③을 확인하세요.
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

      {plan?.skill_state && <SkillStatePanel state={plan.skill_state} />}
      {plan && <Bucket title="① 입력 변경(정상)" tone="ok" changes={plan.auto_apply} />}
      {plan && <Bucket title="② 수식 변경(리뷰)" tone="warn" changes={plan.review_queue} />}
      {plan && <Bucket title="③ 구조 변경(위험)" tone="err" changes={plan.blocked} />}
      {plan && <Bucket title="④ 상태·로그(증적)" tone="" changes={plan.state} />}
    </>
  );
}

export default function Roundtrip({ project, sheet, onSave }) {
  if (sheet === "export")
    return (
      <>
        <ExportSheet project={project} />
        <ImportPanel project={project} onSave={onSave} />
      </>
    );
  return <DiffSheet project={project} onSave={onSave} />;
}
