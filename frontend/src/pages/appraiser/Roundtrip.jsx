import React, { useState } from "react";
import { api, fileToBase64 } from "../../api.js";
import { officeAvailable, currentWorkbookB64 } from "../../officeBridge.js";

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

  /** Task Pane 전용: 열려 있는 워크북을 다운로드 없이 바로 되읽기(다리 2 해소). */
  const loadFromPane = async () => {
    setBusy(true); setErr(null); setOut(null); setApplied(false);
    try {
      setOut(await api.xlsx.import(await currentWorkbookB64()));
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
            입력을 역파싱·재계산합니다. 무엇이 바뀌었는지 분류해서 보려면
            <b> 왕복 diff</b> 를 쓰세요.
          </div>
          {/* 실측 피드백: 자체 템플릿(연수 모델 등)으로 되읽기를 시도해 좌표 오류가 났다.
              어떤 기능이 어떤 파일에 되는지를 **시도 전에** 알려준다. */}
          <table style={{ marginBottom: 10, fontSize: 12 }}>
            <thead><tr><th style={{ textAlign: "left" }}>기능</th>
              <th>Val-Studio export</th><th>자체·타사 모델</th></tr></thead>
            <tbody>
              <tr><td style={{ textAlign: "left" }}>모델 정적 감사</td><td>○</td><td>○</td></tr>
              <tr><td style={{ textAlign: "left" }}>되읽기 · 왕복 diff</td><td>○</td><td>✕ (셀 좌표 고정 필요)</td></tr>
            </tbody>
          </table>
          <div className="row" style={{ gap: 16 }}>
            <label>편집본 xlsx <input type="file" accept=".xlsx"
              onChange={(e) => setFile(e.target.files[0])} /></label>
            <button className="primary" disabled={busy} onClick={load}>
              {busy ? "읽는 중…" : "되읽기"}
            </button>
            {officeAvailable() && (
              <button className="ghost" disabled={busy} onClick={loadFromPane}>
                {busy ? "읽는 중…" : "현재 워크북 되읽기"}
              </button>
            )}
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

  /** Task Pane 전용: 열려 있는 워크북을 편집본으로, 저장본을 기준선으로 즉시 비교. */
  const compareCurrent = async () => {
    if (!hasSaved) { setErr("저장된 DCF 입력이 없어 기준선을 만들 수 없습니다."); return; }
    setBusy(true); setErr(null); setPlan(null); setApplied(null);
    try {
      setPlan(await api.xlsx.diffVsProject(project.id, await currentWorkbookB64()));
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
            {officeAvailable() && (
              <button className="ghost" disabled={busy || !hasSaved} onClick={compareCurrent}>
                {busy ? "비교 중…" : "현재 워크북으로 비교"}
              </button>
            )}
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

/** 모델 정적 감사 — 재계산 없는 수식 분석(패턴 린트·하드코딩·민감도 중심셀).
    외부 편집본·임의 워크북에도 작동(표준 레이아웃이면 중심셀 검산까지). 표시 전용. */
function AuditSheet() {
  const [file, setFile] = useState(null);
  const [out, setOut] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const run = async () => {
    if (!file) { setErr("xlsx 파일을 선택하세요."); return; }
    setBusy(true); setErr(null); setOut(null);
    try {
      setOut(await api.xlsx.audit(await fileToBase64(file)));
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  /** Task Pane 전용: 열려 있는 워크북을 다운로드 없이 즉시 정적 감사(다리 2 해소). */
  const runCurrent = async () => {
    setBusy(true); setErr(null); setOut(null);
    try {
      setOut(await api.xlsx.audit(await currentWorkbookB64()));
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const nonPass = out ? out.findings.filter((f) => f.severity !== "pass") : [];
  const center = out?.findings.find((f) => f.rule === "sensitivity_center");
  /* 우선순위 분리 — 실측(비올 워크북)에서 패턴 경고의 대부분이 **구간 양끝**이었고
     (edge 73 vs inner 7), 양끝은 첫해 반년상각·터미널 외삽처럼 정상일 여지가 크다.
     다만 실제 결함도 양끝에서 나온 적이 있어 **숨기지 않고 접어서** 둔다(끄지 않고 순서). */
  const primary = nonPass.filter((f) => f.detail?.position !== "edge");
  const edge = nonPass.filter((f) => f.detail?.position === "edge");

  return (
    <>
      <div className="card">
        <h2>모델 정적 감사 <span className="muted">— 수식 패턴 린트·하드코딩·중심셀 검산</span></h2>
        <div className="pad">
          <div className="muted" style={{ marginBottom: 10, fontSize: "0.82rem" }}>
            재계산 없이 수식 문자열만 분석합니다: <b>이웃 패턴을 깨는 수식</b>(참조 밀림
            시그니처 — R1C1 정규화 대조), <b>수식 내 숫자 리터럴</b>(숨은 가정),
            표준 레이아웃이면 <b>민감도 중심셀 ≟ 재계산</b>(축 순환·stale 동시 적발)까지.
            ⚠️ 행 전체가 균일하게 밀린 오류는 이웃 대조로 안 잡힙니다 — 분석적 리뷰
            (4.밸류에이션)와 병행하세요.
          </div>
          <div className="row" style={{ gap: 16 }}>
            <label>감사 대상 xlsx <input type="file" accept=".xlsx"
              onChange={(e) => setFile(e.target.files[0])} /></label>
            <button className="primary" disabled={busy} onClick={run}>
              {busy ? "분석 중…" : "정적 감사 실행"}
            </button>
            {officeAvailable() && (
              <button className="ghost" disabled={busy} onClick={runCurrent}>
                {busy ? "분석 중…" : "현재 워크북 감사"}
              </button>
            )}
          </div>
          {err && <div className="err" style={{ marginTop: 10 }}>{err}</div>}
        </div>
      </div>

      {out && (
        <div className="card">
          <h2>감사 결과</h2>
          <div className="pad">
            <div className="kpis">
              <div className="kpi"><div className="v">{out.sheets.length}</div><div className="k">시트</div></div>
              <div className="kpi"><div className="v" style={out.warn_count ? { color: "var(--warn)" } : {}}>{out.warn_count}</div><div className="k">WARN</div></div>
              <div className="kpi"><div className="v">{out.center_checked ? (center?.severity === "pass" ? "정합 ✓" : "불일치 ⚠") : "생략"}</div><div className="k">민감도 중심셀</div></div>
            </div>
            {!out.center_checked && (
              <div className="muted" style={{ fontSize: "0.82rem", margin: "6px 0" }}>
                비표준 레이아웃 — 중심셀 검산은 Val-Studio export 템플릿에서만 수행됩니다.
              </div>
            )}
            {nonPass.length === 0 && (
              <div className="finding pass">경고 없음 — 패턴·리터럴·중심셀 전 검사 통과</div>
            )}
            {primary.map((f, i) => (
              <div key={i} className={`finding ${f.severity}`}>
                <b>[{f.severity.toUpperCase()}] {f.rule}</b> — {f.message}
                {f.rule === "formula_pattern" && f.detail?.mode_sample && (
                  <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
                    이웃 다수 패턴: <code>{f.detail.mode_sample}</code>
                  </div>
                )}
              </div>
            ))}
            {edge.length > 0 && (
              <details style={{ marginTop: 10 }}>
                <summary style={{ cursor: "pointer", fontSize: 12 }}>
                  구간 양끝 경고 {edge.length}건 — 첫 열(반년상각)·마지막 열(터미널 외삽)처럼
                  구조가 달라도 정상인 자리. 다만 참조 밀림이 여기서 나온 사례도 있어 접어만 둡니다.
                </summary>
                {edge.map((f, i) => (
                  <div key={i} className={`finding ${f.severity}`}>
                    <b>[{f.severity.toUpperCase()}] {f.rule}</b> — {f.message}
                    {f.detail?.mode_sample && (
                      <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
                        이웃 다수 패턴: <code>{f.detail.mode_sample}</code>
                      </div>
                    )}
                  </div>
                ))}
              </details>
            )}
          </div>
        </div>
      )}
    </>
  );
}

/** 모델 연결성 진단(P1) — "이 가정이 결과에 도달하는가"를 의존성 그래프로 판정.
    실측 근거: 비올 진본에서 WACC 시트 전체 미도달 + 스파인이 중간 상수(DCF!M15)에서
    재시작(EBIT·WC·매출추정 미도달)을 검출 — **셀 단위 리뷰로는 '연결의 부재'가 보이지
    않는다**(부재는 어느 셀에도 적혀 있지 않으므로). 표시 전용(저장 없음). */
function ConnectivitySheet() {
  const [file, setFile] = useState(null);
  const [target, setTarget] = useState("");
  const [out, setOut] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const runWith = async (b64) => {
    setBusy(true); setErr(null); setOut(null);
    try {
      setOut(await api.xlsx.connectivity(b64, target.trim() || undefined));
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const run = async () => {
    if (!file) { setErr("xlsx 파일을 선택하세요."); return; }
    runWith(await fileToBase64(file));
  };
  const runCurrent = async () => {
    try { runWith(await currentWorkbookB64()); } catch (e) { setErr(e.message); }
  };

  const deadSet = out ? new Set(out.dead_sheets) : new Set();
  const rows = out ? Object.entries(out.sheet_summary)
    .sort((a, b) => (deadSet.has(b[0]) - deadSet.has(a[0]))
      || (b[1].not_reaching - a[1].not_reaching)) : [];

  return (
    <>
      <div className="card">
        <h2>모델 연결성 <span className="muted">— 이 가정이 결과에 도달하는가(의존성 그래프)</span></h2>
        <div className="pad">
          <div className="muted" style={{ marginBottom: 10, fontSize: "0.82rem" }}>
            수식 참조를 그래프로 추적해 <b>목표셀(주당가치)에 도달하지 못하는 시트</b>,
            경로상 <b>상수 잎</b>(참조화 후보), 아무도 읽지 않는 <b>고아 계산</b>을 찾습니다.
            셀을 하나씩 읽는 리뷰로는 "연결의 부재"가 보이지 않습니다 — WACC 시트를 다
            고쳐도 결과가 안 변하는 모델이 실제로 있었습니다(비올 진본 실측).
          </div>
          <div className="row" style={{ gap: 16, flexWrap: "wrap" }}>
            <label>대상 xlsx <input type="file" accept=".xlsx"
              onChange={(e) => setFile(e.target.files[0])} /></label>
            <label>목표셀 <input type="text" value={target} placeholder="비우면 표준(DCF!C33) · 예: DCF!H49"
              onChange={(e) => setTarget(e.target.value)} style={{ width: 170 }} /></label>
            <button className="primary" disabled={busy} onClick={run}>
              {busy ? "분석 중…" : "연결성 진단"}
            </button>
            {officeAvailable() && (
              <button className="ghost" disabled={busy} onClick={runCurrent}>
                {busy ? "분석 중…" : "현재 워크북 진단"}
              </button>
            )}
          </div>
          {err && <div className="err" style={{ marginTop: 10 }}>{err}</div>}
        </div>
      </div>

      {out && (
        <div className="card">
          <h2>진단 결과 <span className="muted">— 목표 {out.target}</span></h2>
          <div className="pad">
            <div className="kpis">
              <div className="kpi"><div className="v">{out.n_formulas.toLocaleString()}</div>
                <div className="k">수식 셀 / 노드 {out.n_nodes.toLocaleString()}</div></div>
              <div className={`kpi${out.dead_sheets.length ? " hero" : ""}`}>
                <div className="v">{out.dead_sheets.length}</div>
                <div className="k">결과 미도달 시트</div></div>
              <div className="kpi"><div className="v">{out.constant_inputs_total}</div>
                <div className="k">경로상 상수 잎(참조화 후보)</div></div>
              <div className="kpi"><div className="v">{out.orphan_total}</div>
                <div className="k">고아 수식(표시용/죽은 계산)</div></div>
            </div>

            {out.values_only_suspect && (
              <div className="warn-box" style={{ marginTop: 10 }}>
                수식 비율 {(out.formula_ratio * 100).toFixed(1)}% — <b>값 붙여넣기 모델</b>로
                보입니다. 연결성 진단이 무의미하며, 감사인 트랙의 독립 재계산·범위추정으로
                검증하세요(값-only 복원은 로드맵 P2).
              </div>
            )}

            {out.dead_sheets.length > 0 && (
              <div className="finding warn" style={{ marginTop: 10 }}>
                <b>미도달 시트</b> — {out.dead_sheets.join(" · ")}
                <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
                  이 시트들의 계산은 {out.target} 에 흘러들지 않습니다. 고치더라도 결과가
                  변하지 않으며, 오류가 생겨도 결과에서 드러나지 않습니다("값으로 죽은
                  수식" 위험). 의도적 참고 시트인지, 끊긴 배선인지 판단하세요.
                </div>
              </div>
            )}

            <div style={{ overflowX: "auto", marginTop: 10 }}>
              <table>
                <thead><tr><th style={{ textAlign: "left" }}>시트</th>
                  <th>도달 수식</th><th>미도달 수식</th><th>고아</th></tr></thead>
                <tbody>{rows.map(([s, c]) => (
                  <tr key={s} className={deadSet.has(s) ? "warn" : ""}>
                    <td style={{ textAlign: "left" }}>{deadSet.has(s) ? "⚠ " : ""}{s}</td>
                    <td>{c.reaching}</td><td>{c.not_reaching}</td>
                    <td>{out.orphan_by_sheet[s] || 0}</td>
                  </tr>))}</tbody>
              </table>
            </div>

            {out.constant_inputs_in_path.length > 0 && (
              <details style={{ marginTop: 10 }}>
                <summary style={{ cursor: "pointer", fontSize: 12 }}>
                  경로상 상수 잎 {out.constant_inputs_total}건 — 결과에 직접 흘러드는
                  하드 입력(가정이면 참조화 후보, R4)
                </summary>
                <table style={{ marginTop: 6 }}>
                  <tbody>{out.constant_inputs_in_path.slice(0, 40).map((c, i) => (
                    <tr key={i}><td style={{ textAlign: "left" }}>{c.cell}</td>
                      <td>{typeof c.value === "number"
                        ? c.value.toLocaleString("ko-KR", { maximumFractionDigits: 4 })
                        : String(c.value)}</td></tr>))}</tbody>
                </table>
                {out.constant_inputs_total > 40 && (
                  <div className="muted">…외 {out.constant_inputs_total - 40}건</div>)}
              </details>
            )}

            {out.unknown_cells.length > 0 && (
              <div className="finding warn" style={{ marginTop: 8 }}>
                <b>동적 참조 {out.unknown_cells.length}건</b>(INDIRECT/OFFSET) —
                이 셀들의 연결은 추적할 수 없어 진단이 <b>과소평가</b>될 수 있습니다:
                {" "}{out.unknown_cells.slice(0, 8).join(", ")}
              </div>
            )}
            {out.external_cells.length > 0 && (
              <div className="finding warn" style={{ marginTop: 8 }}>
                <b>외부 워크북 참조 {out.external_cells.length}건</b> —
                {" "}{out.external_cells.slice(0, 8).join(", ")}
              </div>
            )}
            {out.cycles.length > 0 && (
              <div className="finding warn" style={{ marginTop: 8 }}>
                <b>순환 참조 {out.cycles.length}건</b>(3표 Model 시트 정상 순환 제외) —
                예: {out.cycles[0].slice(0, 5).join(" → ")}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}

export default function Roundtrip({ project, sheet, onSave }) {
  if (sheet === "connectivity") return <ConnectivitySheet />;
  if (sheet === "export")
    return (
      <>
        <ExportSheet project={project} />
        <ImportPanel project={project} onSave={onSave} />
      </>
    );
  if (sheet === "audit") return <AuditSheet />;
  return <DiffSheet project={project} onSave={onSave} />;
}
