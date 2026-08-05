import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api.js";
import { loadKey } from "../Byok.jsx";
import TableTransfer from "../../TableTransfer.jsx";

/* 0-2-6. 원문·주석 — 접수번호 하나로 공시서류 원문을 구조화한다.
 *
 * 자료함의 다년도 재무제표(fnlttSinglAcntAll)와 **출처가 다르다**. OpenDART 에는 주석
 * 조회 API 가 없어서, 주석 본문과 **계정↔주석번호 매핑**은 접수번호 원문에만 있다.
 * 그 매핑이 이 화면의 존재 이유다 — 계정 옆 주석 배지를 누르면 근거 주석으로 바로 간다.
 *
 * 정합성 판정은 자료함과 **같은 항등식 SSOT**(fs_integrity)에서 나온다. 여기서 FAIL 이
 * 없다는 건 공시가 맞다는 뜻이면서 동시에 **파서가 표를 옳게 읽었다**는 뜻이다
 * (원문은 들여쓰기를 열 오프셋으로 표현해서, 잘못 읽으면 대차가 즉시 깨진다).
 */

const num = (v) => (v == null ? "—" : Math.round(v).toLocaleString("ko-KR"));
const SEV = { fail: "err", warn: "warn", pass: "pass" };

/** 주석 표 셀 → 숫자면 number 로. 전송 계약(TableTransfer)이 요구하는 형태다.
 *
 *  문자열로 넘기면 엑셀에서 텍스트 셀이 되어 계산에 못 쓴다 — 전송의 존재 이유가
 *  사라진다. 괄호음수 `(116,226,231)` 는 음수로, 대시 `-` 는 **원문 그대로 둔다**
 *  (0 으로 바꾸면 '해당 없음'과 '실제 0'을 구분할 수 없게 되고, SUM 은 텍스트를 무시한다).
 */
function numify(rows) {
  return rows.map((r) => r.map((c) => {
    const s = String(c ?? "").trim();
    if (!/\d/.test(s) || !/^\(?-?[\d,]+(\.\d+)?\)?$/.test(s)) return c;
    const v = Number(s.replace(/[(),]/g, ""));
    if (!Number.isFinite(v)) return c;
    return s.startsWith("(") ? -v : v;
  }));
}

export default function DocumentPanel({ project, onSave, filings, initialRcept }) {
  const saved = project?.data?.document_parse || null;
  const [rcept, setRcept] = useState(saved?.rcept_no || "");
  const [res, setRes] = useState(saved);
  const [docIdx, setDocIdx] = useState(0);
  const [tab, setTab] = useState("BS");
  const [openNote, setOpenNote] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  // CompanyPicker 가 프로젝트 전역에 저장한 대상회사(구 키 폴백 포함).
  const corpCode = project?.data?.dart_target?.corp_code
    || project?.data?.disclosure?.corp_code || "";
  const [year, setYear] = useState(saved?.bsns_year || "");
  const [priorYear, setPriorYear] = useState("");
  const [priorRcept, setPriorRcept] = useState("");
  const [cmp, setCmp] = useState(null);
  const [cmpBusy, setCmpBusy] = useState(false);
  const key = loadKey("dart");

  /** 연도 간 대조 — 원문 zip 을 1개 더 받아 당해 '전기' ↔ 직전 '당기' 를 맞춘다. */
  const runCompare = async () => {
    if (!key) { setErr("DART 키가 없습니다 — BYOK 화면에서 입력하세요."); return; }
    if (!res?.rcept_no || !(priorRcept || priorYear)) return;
    setCmpBusy(true); setErr(null); setCmp(null);
    try {
      // 연도를 주면 서버가 접수번호를 찾는다(정정본 우선). 직접 고른 접수번호가 우선.
      setCmp(await api.dartDocumentCompare(key, priorRcept
        ? { rcept_no: res.rcept_no, prior_rcept_no: priorRcept }
        : { rcept_no: res.rcept_no, corp_code: corpCode, prior_year: priorYear }));
    } catch (e) { setErr(e.message); } finally { setCmpBusy(false); }
  };

  const run = async (no) => {
    const target = String(no || rcept).trim();
    if (!key) { setErr("BYOK 탭에서 OpenDART API 키를 먼저 저장하세요."); return; }
    if (!/^\d{14}$/.test(target)) { setErr("접수번호는 숫자 14자리입니다."); return; }
    setBusy(true); setErr(null);
    try {
      const d = await api.dartDocumentParse(key, { rcept_no: target });
      setRcept(target); setRes(d); setDocIdx(0); setOpenNote(null);
      setTab(d.documents?.[0]?.statements?.[0]?.sj_div || "BS");
      onSave?.({ document_parse: d });
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  /** 사업연도만으로 가져오기 — 접수번호 해소는 서버가 한다(정정본 우선). */
  const runByYear = async () => {
    if (!key) { setErr("BYOK 탭에서 OpenDART API 키를 먼저 저장하세요."); return; }
    if (!/^\d{4}$/.test(String(year).trim())) { setErr("사업연도는 4자리입니다."); return; }
    setBusy(true); setErr(null);
    try {
      const d = await api.dartDocumentParse(key, { corp_code: corpCode, bsns_year: year });
      setRcept(d.rcept_no || ""); setRes(d); setDocIdx(0); setOpenNote(null);
      setTab(d.documents?.[0]?.statements?.[0]?.sj_div || "BS");
      onSave?.({ document_parse: { ...d, bsns_year: year } });
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  /* 공시목록에서 '파싱'을 눌러 넘어온 접수번호는 바로 실행한다 — 유저가 이미 의사를
     밝혔으므로 탭에서 또 누르게 하지 않는다. 같은 번호로 두 번 돌지 않게 ref 로 가둔다
     (파싱 1회 = DART 원문 1콜). */
  const fired = useRef("");
  useEffect(() => {
    const no = String(initialRcept || "").trim();
    if (!no || fired.current === no) return;
    fired.current = no;
    setRcept(no);
    if (res?.rcept_no !== no) run(no);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialRcept]);

  const doc = res?.documents?.[docIdx] || null;
  const statements = doc?.statements || [];
  const st = statements.find((s) => s.sj_div === tab) || statements[0] || null;

  /** 항등식 × 연도 매트릭스 — 자료함 화면과 같은 표현(같은 규칙에서 나오므로). */
  const matrix = useMemo(() => {
    if (!doc?.checks) return null;
    const years = [...new Set(doc.checks.map((c) => c.detail?.year).filter((y) => y != null))]
      .sort((a, b) => a - b);
    const rows = new Map();
    for (const c of doc.checks) {
      if (c.detail?.skipped || c.detail?.year == null) continue;
      const title = c.detail.title || c.rule;
      if (!rows.has(title)) rows.set(title, { title, by: {} });
      rows.get(title).by[c.detail.year] = c;
    }
    return { years, rows: [...rows.values()] };
  }, [doc]);

  /** 주석번호 → 주석 객체(배지 클릭 점프용). */
  const noteByNo = useMemo(
    () => Object.fromEntries((doc?.notes || []).map((n) => [String(n.number), n])), [doc]);

  const tsv = () => {
    if (!st) return [];
    return [["계정", "주석", ...st.periods],
      ...st.rows.map((r) => [r.label, r.note_refs.join(", "),
        ...st.periods.map((p) => (r.values[p] == null ? "" : r.values[p]))])];
  };

  const sum = doc?.summary;
  const gate = !doc ? "" : sum?.fail ? "err" : sum?.warn ? "warn" : "pass";

  return (
    <>
      <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
        {filings?.length > 0 && (
          <div className="row" style={{ margin: 0, maxWidth: 320 }}>
            <label>공시목록에서 선택</label>
            <select value={rcept} onChange={(e) => setRcept(e.target.value)} style={{ fontSize: 12 }}>
              <option value="">— 보고서 선택 —</option>
              {filings.map((f) => (
                <option key={f.rcept_no} value={f.rcept_no}>
                  {f.rcept_dt} · {f.report_nm}
                </option>
              ))}
            </select>
          </div>
        )}
        {/* 사업연도만 주면 접수번호를 서버가 찾는다 — 사업연도는 표제의 (YYYY.MM) 이지
            접수일이 아니고(2025 보고서는 2026-03 접수), 정정본이 있으면 정정본을 쓴다. */}
        {corpCode && (
          <div className="row" style={{ margin: 0 }}><label>사업연도로 바로</label>
            <div style={{ display: "flex", gap: 4 }}>
              <input type="text" value={year} onChange={(e) => setYear(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && runByYear()}
                placeholder="2025" style={{ width: 70 }} />
              <button className="primary" onClick={runByYear} disabled={busy}>
                {busy ? "파싱 중…" : "가져오기"}</button>
            </div>
          </div>
        )}
        <div className="row" style={{ margin: 0 }}><label>접수번호(14자리)</label>
          <input type="text" value={rcept} onChange={(e) => setRcept(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && run()} style={{ width: 150 }} /></div>
        <button className={corpCode ? "ghost" : "primary"} onClick={() => run()} disabled={busy}>
          {busy ? "파싱 중…" : "원문 파싱"}</button>
      </div>
      <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
        재무제표 본표와 <b>주석 전문</b>을 함께 가져옵니다. 주석은 OpenDART 재무 API 로는
        얻을 수 없어 원문에서만 나옵니다 — 사업보고서 본문이 아니라
        <b> 감사보고서 첨부</b>에 실립니다(본표 없는 문서는 자동 제외).
      </div>
      {err && <div className="err" style={{ marginTop: 8 }}>{err}</div>}

      {doc && (
        <>
          {res.documents.length > 1 && (
            <div style={{ marginTop: 10 }}>
              {res.documents.map((d, i) => (
                <button key={d.filename} className={i === docIdx ? "primary xs" : "ghost xs"}
                  style={{ marginRight: 6 }}
                  onClick={() => { setDocIdx(i); setOpenNote(null); setTab(d.statements[0]?.sj_div || "BS"); }}>
                  {d.kind}</button>
              ))}
            </div>
          )}

          <div className={`finding ${gate}`} style={{ marginTop: 10 }}>
            <b>{doc.kind}</b> · {doc.company} · 본표 {statements.length}개 ·
            주석 {doc.notes.length}개 · 계정↔주석 매핑 {Object.keys(doc.note_map).length}건 ·
            정합성 {sum?.checked}건 중 <b>FAIL {sum?.fail}</b> / WARN {sum?.warn}
            {sum?.fail === 0 && <span className="muted"> — 대차·손익체인·CF 롤포워드 통과(파서 자기검증)</span>}
          </div>

          {/* 주석 정합성 — 본표 항등식과 층위가 다르다(주석은 XBRL 로 안 나와 이 검사가
              유일한 자기검산이다). 소계·롤포워드는 표 내부 산술, 대사는 본표 대응. */}
          {doc.note_checks && (
            <div className={`finding ${doc.note_summary?.fail ? "fail" : "pass"}`}
              style={{ marginTop: 8 }}>
              <b>주석 정합성</b> — 본표 대사 성립 <b>{doc.note_summary?.tieout ?? 0}</b>건 ·
              FAIL {doc.note_summary?.fail ?? 0} / WARN {doc.note_summary?.warn ?? 0}
              <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>
                소계(Σ개별=합계) · 롤포워드(기초+변동=기말) · 본표 대사(계정↔주석번호).
                대사 미확인은 <b>불일치가 아니라</b> 주석번호가 다대다라 대응을 못 찾은 것.
              </div>
              {doc.note_checks.filter((c) => c.severity !== "pass").length > 0 && (
                <ul style={{ marginTop: 6 }}>
                  {doc.note_checks.filter((c) => c.severity !== "pass").slice(0, 8)
                    .map((c, i) => <li key={i}>[{c.severity}] {c.message}</li>)}
                </ul>
              )}
              {doc.note_checks.some((c) => c.rule === "note_tieout") && (
                <details style={{ marginTop: 6 }}>
                  <summary style={{ cursor: "pointer", fontSize: 12 }}>
                    대사 성립 내역 보기
                  </summary>
                  <ul style={{ marginTop: 4, fontSize: 12 }}>
                    {doc.note_checks.filter((c) => c.rule === "note_tieout")
                      .map((c, i) => <li key={i}>{c.message}</li>)}
                  </ul>
                </details>
              )}
            </div>
          )}

          {/* 연도 간 대조 — 당해의 '전기' 열 ↔ 직전의 '당기' 열. 주석은 XBRL 로 안 나와
              다년도 API 대조가 불가능하므로 원문 zip 2개가 유일한 경로다. */}
          <div style={{ marginTop: 8, padding: 8, border: "1px solid var(--line)", borderRadius: 6 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
              <div style={{ flex: 1, minWidth: 220 }}>
                <label>직전 보고서(전기 재작성 검출용)</label>
                <select value={priorRcept} onChange={(e) => setPriorRcept(e.target.value)}
                  style={{ fontSize: 12, width: "100%" }}>
                  <option value="">— 선택 —</option>
                  {(filings || []).filter((f) => f.rcept_no !== res?.rcept_no).map((f) => (
                    <option key={f.rcept_no} value={f.rcept_no}>
                      {f.rcept_dt} {f.report_nm}</option>
                  ))}
                </select>
              </div>
              {corpCode && (
                <div><label>또는 직전 사업연도</label>
                  <input type="text" value={priorYear} placeholder="2024"
                    onChange={(e) => setPriorYear(e.target.value)} style={{ width: 70 }} /></div>
              )}
              <button className="ghost" onClick={runCompare}
                disabled={cmpBusy || !(priorRcept || priorYear)}>
                {cmpBusy ? "대조 중…" : "연도 간 대조"}
              </button>
            </div>
            <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
              당해 보고서가 말하는 <b>전기</b>와 직전 보고서가 말하는 <b>당기</b>를 맞춰봅니다.
              어긋나면 재작성·재분류입니다. 원문 zip 을 1개 더 내려받습니다.
            </div>
            {cmp && (
              <div className={`finding ${cmp.summary?.restated ? "warn" : "pass"}`}
                style={{ marginTop: 8 }}>
                <b>주석 {cmp.summary?.paired}개 짝지음 · 표 {cmp.summary?.compared_tables}개 대조</b>
                {" "}— 재작성 {cmp.summary?.restated ?? 0} · 재분류 {cmp.summary?.reclassified ?? 0}
                {cmp.summary?.unpaired ? ` · 짝 못 지음 ${cmp.summary.unpaired}` : ""}
                {cmp.findings?.length > 0 && (
                  <ul style={{ marginTop: 6, fontSize: 12 }}>
                    {cmp.findings.slice(0, 12).map((f, i) => (
                      <li key={i}>[{f.severity}] {f.message}</li>
                    ))}
                    {cmp.findings.length > 12 && (
                      <li className="muted">…외 {cmp.findings.length - 12}건</li>
                    )}
                  </ul>
                )}
                {!cmp.findings?.length && (
                  <span className="muted"> — 전기 수치가 직전 보고서와 일치합니다</span>
                )}
              </div>
            )}
          </div>

          {matrix?.rows.length > 0 && (
            <div style={{ overflowX: "auto", marginTop: 8 }}>
              <table>
                <thead><tr><th style={{ textAlign: "left" }}>항등식</th>
                  {matrix.years.map((y) => <th key={y}>{y}</th>)}</tr></thead>
                <tbody>{matrix.rows.map((r) => (
                  <tr key={r.title}>
                    <td style={{ textAlign: "left", fontSize: 12 }}>{r.title}</td>
                    {matrix.years.map((y) => {
                      const c = r.by[y];
                      if (!c) return <td key={y} className="muted">—</td>;
                      const ok = c.severity === "pass";
                      return <td key={y} className={SEV[c.severity]} title={c.message}
                        style={{ fontWeight: ok ? 400 : 700 }}>
                        {ok ? "✓" : `✗ ${num(Number(c.detail?.diff))}`}</td>;
                    })}
                  </tr>))}
                </tbody>
              </table>
            </div>
          )}

          {/* ── 본표 ─────────────────────────────────────────────── */}
          <div style={{ marginTop: 12, display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
            {statements.map((s) => (
              <button key={s.sj_div + s.title} className={st === s ? "primary xs" : "ghost xs"}
                onClick={() => setTab(s.sj_div)}>{s.title || s.sj_div} ({s.rows.length})</button>
            ))}
            {st && <TableTransfer label="현재 제표" rows={tsv()}
              hint={`단위 ${st.unit || "?"} · 주석번호 포함`} />}
          </div>

          {st && (
            <div style={{ overflowX: "auto", marginTop: 6, maxHeight: 420, overflowY: "auto" }}>
              <table>
                <thead><tr>
                  <th style={{ textAlign: "left" }}>과목</th><th>주석</th>
                  {st.periods.map((p) => <th key={p}>{p}</th>)}
                </tr></thead>
                <tbody>{st.rows.map((r, i) => (
                  <tr key={i}>
                    <td style={{ textAlign: "left", fontSize: 12,
                      fontWeight: r.is_total ? 700 : 400,
                      paddingLeft: 6 + Math.max(0, r.depth - 1) * 12 }}>{r.label}</td>
                    <td>
                      {/* 주석 배지 — 이 화면의 존재 이유. 누르면 근거 주석이 펼쳐진다. */}
                      {r.note_refs.map((n) => (
                        <button key={n} className="ghost xs" style={{ margin: "0 2px" }}
                          disabled={!noteByNo[String(n)]}
                          title={noteByNo[String(n)]?.title || `주석 ${n} (본문 없음)`}
                          onClick={() => setOpenNote(String(n))}>{n}</button>
                      ))}
                    </td>
                    {st.periods.map((p) => (
                      <td key={p} style={{ textAlign: "right", fontWeight: r.is_total ? 700 : 400 }}>
                        {num(r.values[p])}</td>
                    ))}
                  </tr>))}
                </tbody>
              </table>
            </div>
          )}
          <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
            단위 {st?.unit || "?"} · 계정 순서·계층은 공시 표시 그대로 · 주석 열의 숫자를 누르면
            해당 주석 본문이 열립니다.
          </div>

          {/* ── 주석 ─────────────────────────────────────────────── */}
          <h3 style={{ margin: "16px 0 6px", fontSize: 13 }}>주석 {doc.notes.length}개</h3>
          {doc.notes.map((n) => (
            <details key={n.number} open={openNote === String(n.number)}
              onToggle={(e) => e.target.open && setOpenNote(String(n.number))}
              style={{ marginBottom: 6 }}>
              <summary style={{ cursor: "pointer", fontSize: 13 }}>
                <b>{n.number}.</b> {n.title}
                <span className="muted" style={{ fontSize: 11 }}>
                  {" "}— 문단 {n.paragraphs.length} · 표 {n.tables.length}</span>
              </summary>
              <div style={{ padding: "6px 0 6px 12px" }}>
                {n.paragraphs.map((p, i) => (
                  <p key={i} style={{ fontSize: 12, margin: "4px 0", lineHeight: 1.5 }}>{p}</p>
                ))}
                {n.tables.map((t, i) => (
                  <div key={i} style={{ overflowX: "auto", margin: "8px 0" }}>
                    <TableTransfer label={`주석 ${n.number} 표 ${i + 1}`} rows={numify(t)}
                      hint="원문 표 · 숫자는 number 로 전송(엑셀에서 바로 계산)" />
                    <table><tbody>{t.slice(0, 12).map((row, ri) => (
                      <tr key={ri}>{row.map((c, ci) => (
                        <td key={ci} style={{ textAlign: ri === 0 ? "center" : "left", fontSize: 11 }}>
                          {c}</td>))}</tr>))}
                    </tbody></table>
                    {t.length > 12 && <div className="muted" style={{ fontSize: 11 }}>
                      …외 {t.length - 12}행 (전송 버튼은 전량)</div>}
                  </div>
                ))}
              </div>
            </details>
          ))}
        </>
      )}
    </>
  );
}
