import React, { useMemo, useState } from "react";
import { api } from "../../api.js";
import { loadKey } from "../Byok.jsx";
import TableTransfer from "../../TableTransfer.jsx";
import { excelWriteAvailable, writeSheetPlan } from "../../officeBridge.js";
import CompanyPicker, { dartTarget } from "./CompanyPicker.jsx";

/* 0-1. 다년도 공시 재무제표 — 여러 사업연도를 한 번에, 공시 원형 그대로.
 *
 * 아래의 단년 `DartFetchPanel`(매핑 시트로 계정을 넘기는 경로)과 목적이 다르다.
 * 여기는 **모델의 H_FS 탭을 만드는 경로**다: 재무상태표·포괄손익계산서·현금흐름표를
 * 공시 표시순서·계층 그대로, 요청 사업연도를 열로 펼치고, 3표 항등식을 통과한 뒤
 * rFS(원문·원 단위) + H_FS(참조 수식) 2시트로 워크북에 심는다.
 *
 * 화면의 체크 판정과 워크북의 체크행은 서버의 같은 항등식 표(fs_integrity.IDENTITIES)
 * 에서 나온다 — 두 표면이 서로 다른 규칙을 말할 수 없게 만든 구조다.
 */

const CUR = new Date().getFullYear();
const num = (v) => (v == null ? "" : Math.round(v).toLocaleString("ko-KR"));
const SEV = { fail: "err", warn: "warn", pass: "pass" };

export default function MultiYearFsPanel({ project, onSave }) {
  const saved = project?.data?.dart_fs_multi || null;
  // 대상회사는 프로젝트 단일값(CompanyPicker) — 화면마다 다시 찾지 않는다.
  const target = dartTarget(project);
  const corp = target?.corp_code || "";
  const [from, setFrom] = useState(String(saved?.years?.[0] ?? CUR - 4));
  const [to, setTo] = useState(String(saved?.years?.[saved.years.length - 1] ?? CUR));
  const [fsDiv, setFsDiv] = useState(saved?.fs_div || "CFS");
  const [res, setRes] = useState(saved);
  const [tab, setTab] = useState("BS");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [err, setErr] = useState(null);
  const key = loadKey("dart");

  /** 구간 검증 — 조회 전에 몇 개년·몇 콜인지 확정해 보여준다(쿼터·공간 예측). */
  const span = useMemo(() => {
    const a = Number(from), b = Number(to);
    if (!Number.isInteger(a) || !Number.isInteger(b))
      return { ok: false, why: "사업연도를 숫자로 입력하세요.", years: [], label: "구간" };
    const [lo, hi] = a <= b ? [a, b] : [b, a];
    if (lo < 2015)
      return { ok: false, why: `${lo}년 — DART 재무정보는 2015 사업보고서부터입니다.`,
        years: [], label: "구간" };
    const years = Array.from({ length: hi - lo + 1 }, (_, i) => lo + i);
    if (years.length > 10)
      return { ok: false, why: `${years.length}개년 — 한 번에 최대 10개년입니다.`,
        years, label: "구간" };
    return { ok: true, why: "", years, label: `${lo}~${hi}` };
  }, [from, to]);

  /** 최근 n개 사업연도로 구간 설정. 올해분 사업보고서는 보통 이듬해 3월에 나온다. */
  const setRange = (n) => {
    const last = CUR - (new Date().getMonth() + 1 >= 4 ? 0 : 1);
    setFrom(String(last - n + 1)); setTo(String(last));
  };

  const fetchAll = async () => {
    if (!key) { setErr("BYOK 탭에서 OpenDART API 키를 먼저 저장하세요."); return; }
    if (!corp) { setErr("위에서 대상회사를 먼저 선택하세요(고유번호 미확정)."); return; }
    setBusy(true); setErr(null); setMsg(null);
    try {
      const d = await api.dartFinancialsMulti(key, {
        corp_code: corp, year_from: Number(from), year_to: Number(to),
        fs_div: fsDiv, company: target?.corp_name || project?.company || "",
      });
      setRes(d);
      setTab(Object.keys(d.statements)[0] || "BS");
      onSave?.({ dart_fs_multi: d });
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  /** 체크 결과를 [규칙 × 연도] 매트릭스로 접는다 — 어느 해에 깨졌는지가 한눈에 보여야 한다. */
  const matrix = useMemo(() => {
    if (!res?.checks) return null;
    const rows = new Map();
    const skipped = [];
    for (const c of res.checks) {
      const title = c.detail?.title || c.rule;
      if (c.detail?.skipped) {
        if (!c.detail.year) skipped.push({ title, why: c.message });
        continue;
      }
      if (!rows.has(title)) rows.set(title, { title, rule: c.rule, note: c.detail?.note, by: {} });
      rows.get(title).by[c.detail.year] = c;
    }
    return { rows: [...rows.values()], skipped };
  }, [res]);

  /* 수집 단계 소견 — 정합성 항등식과 층위가 다르다(공시 원문 사이의 관측 차이).
     세 종류를 구분해 보여준다: 진짜 금액 재작성 / 부호 표시규약 / 계정 중복 의심.
     한 덩어리로 뭉치면 진짜 재작성이 노이즈에 묻힌다. */
  const INGEST_KINDS = [
    ["fs_restated", "전기 재작성·재분류 의심", "채택값은 최신 공시"],
    ["fs_sign_convention", "부호 표시규약 차이", "금액 재작성 아님"],
    ["fs_duplicate_suspect", "계정 중복 의심", "이름·코드가 함께 바뀐 같은 계정일 수 있음 — 요약 대사가 깨집니다"],
  ];
  const ingest = (res?.ingest_findings || []);
  const byKind = INGEST_KINDS.map(([rule, title, hint]) => ({
    rule, title, hint, items: ingest.filter((f) => f.rule === rule) }))
    .filter((g) => g.items.length);

  const makeSheets = async () => {
    if (!res?.sheet_plan) return;
    const names = res.sheet_plan.sheets.map((s) => s.name).join(", ");
    if (!window.confirm(
      `워크북에 [${names}] 시트를 만듭니다.\n같은 이름의 시트가 있으면 삭제 후 다시 만듭니다. 계속할까요?`))
      return;
    setBusy(true); setErr(null);
    try {
      const w = await writeSheetPlan(res.sheet_plan);
      setMsg(`시트 생성 완료 — ${w.map((x) => `${x.name}(${x.rows}행)`).join(" · ")}. `
        + "H_FS 의 체크행이 모두 TRUE 인지 확인하세요.");
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  /** rFS + H_FS 2시트 .xlsx 다운로드 — Task Pane 없이도 전 제표·전 연도를 한 번에. */
  const downloadXlsx = async () => {
    if (!key || !span.ok || !corp) return;
    setBusy(true); setErr(null); setMsg(null);
    try {
      const b = await api.dartFinancialsXlsx(key, {
        corp_code: corp, year_from: span.years[0],
        year_to: span.years[span.years.length - 1],
        fs_div: fsDiv, company: project?.company || "",
      });
      const url = URL.createObjectURL(b);
      const a = document.createElement("a");
      a.href = url;
      a.download = `FS_${corp}_${span.label}_${fsDiv}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
      setMsg("엑셀 파일을 내려받았습니다 — rFS(원문) + H_FS(참조 수식) 2시트. "
        + "열어서 시트를 통째로 모델에 복사하면 수식이 그대로 살아 옵니다.");
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  /** 값 전송용 표(TSV) — 빠른 붙여넣기용. 수식이 아니라 값. */
  const tsvRows = (sj) => {
    const rows = res?.statements?.[sj] || [];
    return [["계정", ...res.years.map(String)],
      ...rows.map((a) => [a.label, ...res.years.map((y) => a.values[String(y)] ?? "")])];
  };

  const sum = res?.summary;
  const gateClass = !res ? "" : (sum?.fail || !res.ingest_ok) ? "err"
    : (sum?.warn || byKind.length) ? "warn" : "pass";

  return (
    <div className="card">
      <h2>다년도 재무제표 <span className="muted">— 공시 원형(BS·CIS·CF) + 정합성 체크 → H_FS 시트</span></h2>
      <div className="pad">
        {!key && <div className="finding warn">BYOK 탭에서 OpenDART API 키를 저장해야 조회됩니다.</div>}

        <CompanyPicker project={project} onSave={onSave} />

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <div className="row" style={{ margin: 0 }}><label>사업연도 범위</label>
            <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <input type="number" value={from} onChange={(e) => setFrom(e.target.value)}
                style={{ width: 76 }} aria-label="시작 사업연도" />
              <b>~</b>
              <input type="number" value={to} onChange={(e) => setTo(e.target.value)}
                style={{ width: 76 }} aria-label="종료 사업연도" />
            </span></div>
          <div className="row" style={{ margin: 0 }}><label>연결/별도</label>
            <select value={fsDiv} onChange={(e) => setFsDiv(e.target.value)} style={{ fontSize: 12 }}>
              <option value="CFS">연결(CFS)</option><option value="OFS">별도(OFS)</option></select></div>
          <button className="primary" onClick={fetchAll} disabled={busy || !span.ok}>
            {busy ? "조회 중…" : `${span.label} 한 번에 조회`}</button>
        </div>
        {/* 프리셋 — '연도를 하나씩' 이 아니라 구간을 한 번에 잡는 입구.
            최신 사업보고서는 보통 이듬해 3월 제출이라 올해분은 아직 없을 수 있다. */}
        <div style={{ marginTop: 6, display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
          <span className="muted" style={{ fontSize: 11 }}>빠른 설정</span>
          {[3, 5, 10].map((n) => (
            <button key={n} className="ghost xs" onClick={() => setRange(n)}
              title={`최근 ${n}개 사업연도`}>최근 {n}개년</button>
          ))}
          <span className={span.ok ? "muted" : "err"} style={{ fontSize: 11 }}>
            {span.ok
              ? `→ ${span.years.join(", ")} · ${span.years.length}개년 · API ${span.years.length}콜`
              : span.why}
          </span>
        </div>
        <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
          한 번의 조회로 <b>선택 구간 전체 × 재무상태표·손익·포괄손익·현금흐름표</b>를 가져옵니다.
          각 보고서가 당기·전기·전전기를 함께 실어오므로 겹치는 해는 <b>서로 대조</b>되어
          전기 재작성·재분류가 자동으로 드러납니다. DART 재무정보는 2015 사업보고서부터입니다.
        </div>
        {err && <div className="err" style={{ marginTop: 8 }}>{err}</div>}
        {msg && <div className="finding pass" style={{ marginTop: 8 }}>{msg}</div>}

        {res && (
          <>
            {/* ── 게이트 요약 ─────────────────────────────────────────── */}
            <div className={`finding ${gateClass}`} style={{ marginTop: 12 }}>
              <b>{res.years.join(" · ")}</b> · {res.fs_div === "CFS" ? "연결" : "별도"} ·
              계정 {Object.values(res.statements).reduce((s, v) => s + v.length, 0)}건 ·
              정합성 검사 {sum?.checked}건 중 <b>FAIL {sum?.fail}</b> / WARN {sum?.warn}
              {sum?.skipped ? ` / 앵커부재 skip ${sum.skipped}` : ""}
              {!res.ingest_ok && <span> · <b>수집 게이트 FAIL</b></span>}
              {byKind.map((g) => <span key={g.rule}> · {g.title} {g.items.length}건</span>)}
            </div>

            {/* ── 정합성 체크 매트릭스 ────────────────────────────────── */}
            {matrix && (
              <div style={{ overflowX: "auto", marginTop: 10 }}>
                <table>
                  <thead><tr><th style={{ textAlign: "left" }}>항등식</th>
                    {res.years.map((y) => <th key={y}>{y}</th>)}</tr></thead>
                  <tbody>{matrix.rows.map((r) => (
                    <tr key={r.title}>
                      <td style={{ textAlign: "left", fontSize: 12 }} title={r.note || r.rule}>{r.title}</td>
                      {res.years.map((y) => {
                        const c = r.by[y];
                        if (!c) return <td key={y} className="muted">—</td>;
                        const okc = c.severity === "pass";
                        return (
                          <td key={y} className={SEV[c.severity]} title={c.message}
                            style={{ fontWeight: okc ? 400 : 700 }}>
                            {okc ? (c.detail?.skipped ? "—" : "✓")
                              : `✗ ${num(Number(c.detail?.diff))}`}
                          </td>
                        );
                      })}
                    </tr>))}
                  </tbody>
                </table>
                <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
                  ✗ 옆 숫자는 차이(백만원). 대차 불일치는 <b>FAIL</b>(공시상 성립해야 하는 항등식 —
                  수집·환산 결함을 먼저 의심), 나머지는 표시관행 차이로 정당할 수 있어 WARN 입니다.
                  {matrix.skipped.length > 0 && ` 앵커 부재로 건너뛴 검사: ${matrix.skipped.map((s) => s.title).join(", ")}.`}
                </div>
              </div>
            )}

            {/* ── 수집 소견(재작성 / 부호규약 / 중복 의심) ──────────────── */}
            {byKind.map((g) => (
              <details key={g.rule} style={{ marginTop: 10 }}>
                <summary style={{ cursor: "pointer", fontSize: 13 }}>
                  {g.title} {g.items.length}건 <span className="muted">— {g.hint}</span></summary>
                <div style={{ overflowX: "auto", marginTop: 6 }}>
                  {g.rule === "fs_duplicate_suspect" ? (
                    <table>
                      <thead><tr><th>제표</th><th style={{ textAlign: "left" }}>중복 의심 짝</th>
                        <th style={{ textAlign: "left" }}>일치 연도</th></tr></thead>
                      <tbody>{g.items.map((f, i) => (
                        <tr key={i}>
                          <td>{f.detail.sj_div}</td>
                          <td style={{ textAlign: "left", fontSize: 12 }}>
                            {(f.detail.accounts || []).map((a) =>
                              `${a.name} [${a.source_years?.join("/")}년보고서]`).join("  ↔  ")}</td>
                          <td style={{ textAlign: "left", fontSize: 12 }}>
                            {(f.detail.years || []).join(", ")}</td>
                        </tr>))}</tbody>
                    </table>
                  ) : (
                    <table>
                      <thead><tr><th>연도</th><th style={{ textAlign: "left" }}>계정</th>
                        <th style={{ textAlign: "left" }}>관측</th><th>채택</th></tr></thead>
                      <tbody>{g.items.map((f, i) => (
                        <tr key={i}>
                          <td>{f.detail.year}</td>
                          <td style={{ textAlign: "left" }}>{f.detail.account}</td>
                          <td style={{ textAlign: "left", fontSize: 12 }}>
                            {(f.detail.observations || []).map((o) =>
                              `${o.source_year}년보고서 ${num(Number(o.value))}`).join(" / ")}</td>
                          <td>{num(Number(f.detail.adopted))}</td>
                        </tr>))}</tbody>
                    </table>
                  )}
                </div>
              </details>
            ))}

            {/* ── 워크북 전송 — 전 제표·전 연도를 한 번에 ─────────────── */}
            <div style={{ marginTop: 12, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              {excelWriteAvailable() && (
                <button className="primary" onClick={makeSheets} disabled={busy}
                  title="열려 있는 워크북에 2시트를 만들고 수식까지 기입합니다">
                  열린 워크북에 시트 만들기</button>
              )}
              <button className="ghost" onClick={downloadXlsx} disabled={busy}
                title="rFS + H_FS 2시트 .xlsx — 수식 포함">
                엑셀 파일로 받기 (rFS + H_FS)</button>
              <TableTransfer label="현재 제표" rows={tsvRows(tab)}
                hint="현재 탭만 · 값 전용(수식 아님)" />
            </div>
            {/* 배치 미리보기 — '공간이 맞는지' 를 기입 전에 답한다. */}
            {res.sheet_plan?.meta?.layout && (
              <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>
                배치: {res.sheet_plan.meta.layout.map((L) =>
                  `${L.name} ${L.rows}행×${L.cols}열(연도 ${L.year_cols})`).join(" · ")}
                {res.sheet_plan.meta.blocks?.length > 0 && (
                  <> · H_FS 블록: {res.sheet_plan.meta.blocks.map((b) =>
                    `${b.title} ${b.range}`).join(", ")}</>
                )}
                {!excelWriteAvailable() &&
                  " · 시트 직접 생성은 Excel Task Pane 전용이라, 브라우저에서는 파일로 받으세요."}
              </div>
            )}

            {/* ── 제표 ───────────────────────────────────────────────── */}
            <div style={{ marginTop: 12 }}>
              {Object.keys(res.statements).map((sj) => (
                <button key={sj} className={tab === sj ? "primary xs" : "ghost xs"}
                  style={{ marginRight: 6 }} onClick={() => setTab(sj)}>
                  {res.statements[sj][0]?.sj_nm || sj} ({res.statements[sj].length})</button>
              ))}
            </div>
            <div style={{ overflowX: "auto", marginTop: 6, maxHeight: 460, overflowY: "auto" }}>
              <table>
                <thead><tr><th style={{ textAlign: "left" }}>계정</th>
                  {res.years.map((y) => <th key={y}>{y}</th>)}</tr></thead>
                <tbody>{(res.statements[tab] || []).map((a, i) => {
                  const total = a.depth <= 1;
                  return (
                    <tr key={i}>
                      <td style={{ textAlign: "left", whiteSpace: "pre",
                        fontWeight: total ? 700 : 400, fontSize: 12 }}
                        title={a.account_id + (a.is_standard ? "" : " (회사 확장계정)")}>
                        {a.label}
                        {a.restated_years.length > 0 &&
                          <span style={{ color: "var(--warn)" }} title="전기 재작성 의심"> *</span>}
                      </td>
                      {res.years.map((y) => (
                        <td key={y} style={{ textAlign: "right", fontWeight: total ? 700 : 400 }}>
                          {a.values[String(y)] == null ? "—" : num(a.values[String(y)])}</td>
                      ))}
                    </tr>
                  );
                })}</tbody>
              </table>
            </div>
            <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>
              단위 백만원 · 계정 순서·들여쓰기는 공시 표시 그대로 · 굵은 행은 소계·총계 ·
              계정명에 마우스를 올리면 표준계정코드가 보입니다 ·
              출처: 금융감독원 OpenDART(정확성 무보증).
              {res.notes?.length > 0 && <> · 수집 소견: {res.notes.join(" / ")}</>}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
