import React, { useEffect, useState } from "react";
import { api } from "../../api.js";
import { loadKey } from "../Byok.jsx";
import { appendFactRows, excelWriteAvailable, readSheetGrid } from "../../officeBridge.js";
import MethodWizard from "./MethodWizard.jsx";

/* 3.할인율 > 유사회사 4-step — /api/peer/select 배선.
   결정론 퍼널: step1 산업코드 → step2 사업유사성(판정) → step3 매출비중 → step4 상장·거래.
   판정 없이 실행 = 결정론 필터만(step2 no-op). 생존자에 사유 있는 판정 입력 후 재실행.
   애매(uncertain)는 자동 탈락 아닌 ⚖️ 큐(유저 결정). 확정 peer 는 WACC βu 로 흐름.

   ⭐ Step2 초안(/api/peer/judge): 4-step 중 **판단이 필요한 한 스텝만** 모델이 채운다.
   초안은 아래 판정 표를 채울 뿐이고 퍼널로 바로 흐르지 않는다 — 사람이 보고 고친 뒤
   "4-step 실행"을 눌러야 확정된다(제안 → 판단 → 검증). 사업 설명이 빈 후보는 근거가
   없으므로 서버가 애매로 돌린다. */

const DEMO = [
  { ticker: "A", name: "동종A", industry_code: "2710", revenue_share_related: "0.9",
    listed_years: "5", suspended: false, judg: "유사", reason: "동일 의료기기 사업",
    business: "미용 의료기기 제조·판매" },
  { ticker: "B", name: "무관B", industry_code: "5811", revenue_share_related: "0.9",
    listed_years: "5", suspended: false, judg: "", reason: "", business: "모바일 게임 퍼블리싱" },
  { ticker: "C", name: "저비중C", industry_code: "2710", revenue_share_related: "0.4",
    listed_years: "5", suspended: false, judg: "유사", reason: "동일 산업 소모품",
    business: "의료기기용 소모품" },
  { ticker: "D", name: "신규D", industry_code: "2710", revenue_share_related: "0.9",
    listed_years: "1", suspended: false, judg: "애매", reason: "사업 유사하나 상장 이력 짧음",
    business: "" },
];
const JUDG = { "유사": { similar: true, uncertain: false }, "비유사": { similar: false, uncertain: false },
  "애매": { similar: true, uncertain: true } };
// 초안 → 표 라벨 역매핑. uncertain 이 우선(애매는 similar 값과 무관하게 애매다).
const labelOf = (j) => (j.uncertain ? "애매" : j.similar ? "유사" : "비유사");

function KsicLookup() {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState(null);
  const go = async () => { if (q.trim()) setRows(await api.ksicSearch(q).then((d) => d.results)); };
  return (
    <div className="pad" style={{ borderTop: "1px solid var(--line)" }}>
      <label>KSIC 코드 찾기(모집단 코드 보조)</label>
      <div style={{ display: "flex", gap: 6 }}>
        <input type="text" value={q} onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && go()} placeholder="예: 의료기기" style={{ maxWidth: 220 }} />
        <button className="ghost" onClick={go}>검색</button>
      </div>
      {rows && (
        <div className="muted" style={{ marginTop: 6, fontSize: 12 }}>
          {rows.length ? rows.slice(0, 8).map((r) => `${r.code} ${r.name}`).join(" · ") : "결과 없음"}
        </div>
      )}
    </div>
  );
}

export default function PeerSheet({ project, onSave }) {
  const [cands, setCands] = useState(project?.data?.peer_candidates || DEMO);
  const [codes, setCodes] = useState(project?.data?.peer_codes || "2710");
  const [targetTicker, setTargetTicker] = useState(
    project?.data?.peer_target_ticker || project?.ticker || "");
  // Step1a: rough 유사회사(Research ⑦⑨ 경쟁사)에서 KSIC 역산 → 모집단 코드
  const [seedMode, setSeedMode] = useState(false);
  const [seeds, setSeeds] = useState(project?.data?.peer_seeds || [{ ticker: "", name: "", industry_code: "" }]);
  const [useJudg, setUseJudg] = useState(true);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  // Step2 초안(모델) — 표를 채우는 보조. 확정은 아래 "4-step 실행"이 한다.
  const [targetName, setTargetName] = useState(project?.data?.peer_target_name || project?.name || "");
  const [targetBiz, setTargetBiz] = useState(project?.data?.peer_target_business || "");
  const [models, setModels] = useState([]);
  const [modelId, setModelId] = useState("");
  const [draft, setDraft] = useState(null);
  const [drafting, setDrafting] = useState(false);
  const [prefill, setPrefill] = useState(null);
  const [prefilling, setPrefilling] = useState(false);
  const [ledger, setLedger] = useState(null);
  const [recording, setRecording] = useState(false);
  const canWriteWorkbook = excelWriteAvailable();

  useEffect(() => {
    // 어댑터가 구현된 모델만 온다 — 실패해도 화면은 그대로(초안은 부가 기능).
    api.agentModels()
      .then((d) => { setModels(d.models); setModelId((m) => m || d.default); })
      .catch(() => setModels([]));
  }, []);

  const setRow = (i, k) => (e) => {
    const next = cands.slice();
    next[i] = { ...next[i], [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value };
    setCands(next);
  };
  const addRow = () => setCands([...cands, { ticker: "", name: "", industry_code: "",
    revenue_share_related: "", listed_years: "", suspended: false, judg: "", reason: "",
    business: "" }]);
  const rmRow = (i) => setCands(cands.filter((_, j) => j !== i));

  const setSeed = (i, k) => (e) => {
    const next = seeds.slice();
    next[i] = { ...next[i], [k]: e.target.value };
    setSeeds(next);
  };
  const addSeed = () => setSeeds([...seeds, { ticker: "", name: "", industry_code: "" }]);
  const rmSeed = (i) => setSeeds(seeds.filter((_, j) => j !== i));

  /** 사업 설명 프리필 — 상장사 인덱스의 주요 제품으로 '사업' 열을 채운다(키 불필요).
   *
   *  판정보다 **먼저** 눌러야 의미가 있다: 사업 설명이 비면 Step2 초안이 근거 없음으로
   *  전부 애매 처리된다. 이미 손으로 채운 칸은 덮지 않는다(사람 입력 우선).
   */
  const prefillBusiness = async () => {
    const rows = cands.filter((c) => c.ticker.trim());
    if (!rows.length && !targetTicker.trim()) { setErr("종목코드가 없습니다."); return; }
    setPrefilling(true); setErr(null); setPrefill(null);
    try {
      const d = await api.peerPrefill({
        target: targetTicker.trim()
          ? { ticker: targetTicker.trim(), name: targetName.trim() || undefined } : undefined,
        candidates: rows.map((c) => ({ ticker: c.ticker, name: c.name || undefined })),
      });
      const byTicker = Object.fromEntries(d.candidates.map((f) => [f.ticker, f]));
      setCands(cands.map((c) => {
        const f = byTicker[c.ticker];
        // 사람이 이미 쓴 설명은 보존 — 프리필은 빈 칸만 채운다.
        return f && !String(c.business || "").trim() ? { ...c, business: f.business } : c;
      }));
      if (d.target && !targetBiz.trim()) setTargetBiz(d.target.business);
      if (d.target?.name && !targetName.trim()) setTargetName(d.target.name);
      setPrefill(d);
    } catch (e) { setErr(e.message); } finally { setPrefilling(false); }
  };

  /** Step2 초안 — 모델이 판정 열(판정·사유)만 채운다. 나머지 열은 손대지 않는다. */
  const draftJudgments = async () => {
    const key = loadKey("anthropic");
    if (!key) { setErr("Anthropic 키가 없습니다 — BYOK 화면에서 먼저 입력하세요."); return; }
    const rows = cands.filter((c) => c.ticker.trim());
    if (!rows.length) { setErr("후보가 없습니다."); return; }
    setDrafting(true); setErr(null); setDraft(null);
    try {
      const d = await api.peerJudge(key, {
        target: { name: targetName.trim() || "(평가대상)", ticker: targetTicker.trim() || undefined,
                  business: targetBiz },
        candidates: rows.map((c) => ({ ticker: c.ticker, name: c.name || c.ticker,
                                       business: c.business || "" })),
        model: modelId || undefined,
      });
      // 판정이 온 행만 덮어쓴다 — 사유 미제시로 서버가 버린 행은 사람이 채우도록 비워둔다.
      const byTicker = Object.fromEntries(d.judgments.map((j) => [j.ticker, j]));
      setCands(cands.map((c) => {
        const j = byTicker[c.ticker];
        return j ? { ...c, judg: labelOf(j), reason: j.reason } : c;
      }));
      setDraft(d);
      setUseJudg(true);
    } catch (e) { setErr(e.message); } finally { setDrafting(false); }
  };

  /** 프리필·판정 결과를 워크북 공유 원장(`_VS_FACTS`)에 append 한다(Task Pane 전용).
   *
   *  Claude for Excel 은 우리 API 를 못 부르므로, 웹이 아는 사실이 워크북에 남아야
   *  비로소 두 애드인이 같은 것을 본다. 원장은 append-only — 지우지 않는다.
   *  같은 값 재기록은 서버가 멱등하게 건너뛴다(두 번 눌러도 원장이 붓지 않는다).
   */
  const recordToLedger = async () => {
    const facts = [];
    const push = (f) => f && facts.push(f);
    const factOf = (f) => ({
      key: f.key, value: f.business, method: f.method, source_id: f.source_id,
      locator: f.locator, as_of: f.as_of, confidence: f.confidence, approval: f.approval,
    });
    push(prefill?.target && factOf(prefill.target));
    (prefill?.candidates || []).forEach((f) => push(factOf(f)));
    if (draft?.judgments?.length) {
      const today = new Date().toISOString().slice(0, 10);
      const p = draft.provenance;
      draft.judgments.forEach((j) => push({
        key: j.key,                                  // 키는 서버가 만든다(정규화 규칙 SSOT)
        value: `${labelOf(j)} — ${j.reason}`,
        method: p.method, source_id: p.model,
        locator: `prompt:${String(p.prompt_sha256 || "").slice(0, 12)}`,
        as_of: today, confidence: "", approval: p.approval,
      }));
    }
    if (!facts.length) { setErr("원장에 기록할 사실이 없습니다 — ①·② 를 먼저 실행하세요."); return; }
    setRecording(true); setErr(null); setLedger(null);
    try {
      const existing = await readSheetGrid("_VS_FACTS");
      const plan = await api.factsAppendPlan({ existing, facts });
      const done = await appendFactRows(plan);
      setLedger({ ...plan, ...done });
    } catch (e) { setErr(e.message); } finally { setRecording(false); }
  };

  const run = async () => {
    setBusy(true); setErr(null); setRes(null);
    const numOrNull = (v) => (String(v).trim() === "" ? null : Number(v));
    const body = {
      // R11 자기제외 — 평가대상을 peer 통계에 넣으면 배수가 현재 주가로 끌려간다.
      // 비우면 서버가 자기제외를 **실행하지 않는다**(퍼널에도 행이 찍히지 않음).
      target_ticker: targetTicker.trim() || undefined,
      candidates: cands.filter((c) => c.ticker.trim()).map((c) => ({
        ticker: c.ticker, name: c.name || c.ticker,
        industry_code: c.industry_code || null,
        revenue_share_related: numOrNull(c.revenue_share_related),
        listed_years: numOrNull(c.listed_years), suspended: !!c.suspended,
      })),
    };
    if (seedMode) {                          // Step1a: seed → 서버가 KSIC 역산
      body.seed_peers = seeds
        .filter((s) => s.ticker.trim())
        .map((s) => ({ ticker: s.ticker, name: s.name || s.ticker, industry_code: s.industry_code || null }));
    } else {
      body.target_industry_codes = codes.split(/[\s,]+/).filter(Boolean);
    }
    if (useJudg) {
      body.judgments = cands
        .filter((c) => c.ticker.trim() && c.reason.trim() && c.judg)
        .map((c) => ({ ticker: c.ticker, ...JUDG[c.judg], reason: c.reason }));
    }
    try {
      const d = await api.peerSelect(body);
      setRes(d);
      onSave?.({ peer_candidates: cands, peer_codes: codes, peer_target_ticker: targetTicker, peer_seeds: seeds,
        peer_target_name: targetName, peer_target_business: targetBiz,
        peer_judge_provenance: draft?.provenance || null,   // 초안 증적(누가 판정했나)
        // 프리필 사실 레코드 — 워크북 공유 원장(`_VS_FACTS`)으로 옮기기 전 임시 보관처.
        peer_prefill_facts: prefill?.candidates || null,
        peer_selected: d.selected, peer_needs_review: d.needs_review });
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <>
      <MethodWizard />
      <div className="card">
        <h2>유사회사 4-step <span className="muted">— 결정론 퍼널 + 사업유사성 판정</span></h2>
        <div className="pad">
          <label style={{ marginBottom: 6 }}>
            <input type="checkbox" checked={seedMode} onChange={(e) => setSeedMode(e.target.checked)} />
            {" "}Step1a 역산 — rough 유사회사(Research ⑦⑨ 경쟁사)의 KSIC 로 모집단 코드 산출
          </label>
          {!seedMode ? (
            <div className="row" style={{ maxWidth: 320 }}>
              <label>평가대상 종목코드 (자기제외)</label>
              <input type="text" value={targetTicker}
                onChange={(e) => setTargetTicker(e.target.value)}
                placeholder="예 145020 (A145020 도 인식)" />
              <div className="muted" style={{ fontSize: "0.8rem", margin: "2px 0 8px" }}>
                평가대상을 peer 통계에 넣으면 <b>자기 배수로 자기를 평가</b>하는 순환논법이 되어
                상승여력이 구조적으로 희석된다(실측 주당 7.9% 왜곡). 비우면 자기제외를
                <b> 실행하지 않는다</b>.
              </div>
              <label>모집단 산업코드 (KSIC, 콤마 구분)</label>
              <input type="text" value={codes} onChange={(e) => setCodes(e.target.value)} />
            </div>
          ) : (
            <div style={{ marginBottom: 8 }}>
              <label>rough 유사회사 시드 (Ticker·회사·KSIC) → 코드 역산(union)</label>
              <table style={{ maxWidth: 420 }}>
                <thead><tr><th>Ticker</th><th>회사</th><th>KSIC</th><th></th></tr></thead>
                <tbody>
                  {seeds.map((s, i) => (
                    <tr key={i}>
                      <td><input type="text" value={s.ticker} onChange={setSeed(i, "ticker")} style={{ width: 64 }} /></td>
                      <td><input type="text" value={s.name} onChange={setSeed(i, "name")} style={{ width: 96 }} /></td>
                      <td><input type="text" value={s.industry_code} onChange={setSeed(i, "industry_code")} style={{ width: 64 }} /></td>
                      <td><button className="ghost xs" onClick={() => rmSeed(i)}>✕</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button className="ghost" onClick={addSeed} style={{ marginTop: 4 }}>+ 시드 추가</button>
            </div>
          )}
          {/* ── Step2 보조: ①사업 설명 프리필(결정론·키 불필요) → ②판정 초안(모델) ──
              순서가 중요하다 — 사업 설명이 비면 ②가 근거 없음으로 전부 애매 처리된다. */}
          <div style={{ marginTop: 10, padding: 8, border: "1px solid var(--line)", borderRadius: 6 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
              <div><label>평가대상 회사명</label>
                <input type="text" value={targetName} onChange={(e) => setTargetName(e.target.value)}
                  placeholder="예 비올" style={{ width: 120 }} /></div>
              <div style={{ flex: 1, minWidth: 200 }}><label>평가대상 사업</label>
                <input type="text" value={targetBiz} onChange={(e) => setTargetBiz(e.target.value)}
                  placeholder="주요 제품·수익모델(비면 근거 없음)" /></div>
              <button className="ghost" onClick={prefillBusiness} disabled={prefilling}>
                {prefilling ? "조회 중…" : "① 사업 설명 자동 채움"}
              </button>
              {models.length > 0 && (
                <>
                  <div><label>판정 모델</label>
                    <select value={modelId} onChange={(e) => setModelId(e.target.value)} style={{ fontSize: 12 }}>
                      {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
                    </select></div>
                  <button className="ghost" onClick={draftJudgments} disabled={drafting}>
                    {drafting ? "판정 중…" : "② Step2 판정 초안"}
                  </button>
                </>
              )}
              {canWriteWorkbook && (
                <button className="ghost" onClick={recordToLedger} disabled={recording}>
                  {recording ? "기록 중…" : "③ 워크북 원장에 기록"}
                </button>
              )}
            </div>
            <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
              ①은 상장사 인덱스의 <b>주요 제품</b>으로 '사업' 열을 채운다(DART 키 불필요,
              <b> 이미 쓴 칸은 덮지 않는다</b>). ②는 4-step 중 <b>사업유사성만</b> 모델이 채운다 —
              산업코드·매출비중·상장연수는 결정론 코드 몫. 초안은 표를 채울 뿐이고,
              <b> 확정은 표를 고친 뒤 "4-step 실행"</b>. 사유 없는 판정은 서버가 버린다.
            </div>
            {prefill && (
              <div className="finding pass" style={{ marginTop: 8 }}>
                <b>사업 설명 {prefill.candidates.length}건</b> 채움 — 출처 상장사 인덱스
                (as_of {prefill.as_of} · {prefill.universe}사) · 승인상태 <b>suggested</b>(미승인)
                {prefill.warnings.length > 0 && (
                  <ul style={{ marginTop: 4 }}>
                    {prefill.warnings.map((w, i) => <li key={i}>{w}</li>)}
                  </ul>
                )}
              </div>
            )}
            {ledger && (
              <div className="finding pass" style={{ marginTop: 8 }}>
                <b>_VS_FACTS 에 {ledger.written}행 기록</b>
                {ledger.created ? " (원장 신규 생성)" : ` (기존 ${ledger.existing_count}행에 이어씀)`}
                {" "}— Claude for Excel 이 같은 사실을 읽는다
                {ledger.skipped?.length > 0 && (
                  <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                    멱등 건너뜀 {ledger.skipped.length}건(값이 같아 새 행을 만들지 않음)
                  </div>
                )}
              </div>
            )}
            {draft && (
              <div className="finding pass" style={{ marginTop: 8 }}>
                <b>판정 초안 {draft.judgments.length}건</b> — {draft.provenance.model} ·
                {" "}${draft.estimated_usd.toFixed(4)} 예상 ·
                {" "}입력 {draft.usage.input_tokens}/출력 {draft.usage.output_tokens} tok ·
                {" "}승인상태 <b>{draft.provenance.approval}</b>(미승인)
                {draft.warnings.length > 0 && (
                  <ul style={{ marginTop: 4 }}>
                    {draft.warnings.map((w, i) => <li key={i}>{w}</li>)}
                  </ul>
                )}
              </div>
            )}
          </div>
          <label style={{ marginTop: 8 }}>
            <input type="checkbox" checked={useJudg} onChange={(e) => setUseJudg(e.target.checked)} />
            {" "}사업유사성 판정 포함(끄면 결정론 필터 1·3·4단계만)
          </label>
          <div style={{ overflowX: "auto", marginTop: 8 }}>
            <table>
              <thead><tr>
                <th>코드</th><th>회사</th><th>사업</th><th>KSIC</th><th>관련매출</th><th>상장연수</th>
                <th>정지</th><th>판정</th><th>사유</th><th></th>
              </tr></thead>
              <tbody>
                {cands.map((c, i) => (
                  <tr key={i}>
                    <td><input type="text" value={c.ticker} onChange={setRow(i, "ticker")} style={{ width: 56 }} /></td>
                    <td><input type="text" value={c.name} onChange={setRow(i, "name")} style={{ width: 80 }} /></td>
                    {/* 사업 설명 = Step2 초안의 유일한 판단 근거. 비면 서버가 애매로 돌린다. */}
                    <td><input type="text" value={c.business || ""} onChange={setRow(i, "business")}
                      placeholder="주요 제품·수익모델" style={{ width: 150 }} /></td>
                    <td><input type="text" value={c.industry_code} onChange={setRow(i, "industry_code")} style={{ width: 56 }} /></td>
                    <td><input type="text" value={c.revenue_share_related} onChange={setRow(i, "revenue_share_related")} style={{ width: 48 }} /></td>
                    <td><input type="text" value={c.listed_years} onChange={setRow(i, "listed_years")} style={{ width: 44 }} /></td>
                    <td style={{ textAlign: "center" }}><input type="checkbox" checked={!!c.suspended} onChange={setRow(i, "suspended")} /></td>
                    <td><select value={c.judg} onChange={setRow(i, "judg")} disabled={!useJudg} style={{ fontSize: 12 }}>
                      <option value="">-</option><option value="유사">유사</option>
                      <option value="비유사">비유사</option><option value="애매">애매</option>
                    </select></td>
                    <td><input type="text" value={c.reason} onChange={setRow(i, "reason")} style={{ width: 130 }} disabled={!useJudg} /></td>
                    <td><button className="ghost xs" onClick={() => rmRow(i)}>✕</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button className="ghost" onClick={addRow} style={{ marginTop: 6 }}>+ 후보 추가</button>
          {" "}
          <button className="primary" onClick={run} disabled={busy}>
            {busy ? "선정 중…" : "4-step 실행"}
          </button>
          {err && <div className="err">{err}</div>}
        </div>
        <KsicLookup />
      </div>

      {res && (
        <div className="card">
          <h2>선정 결과</h2>
          <div className="pad">
            {res.size_note && <div className="finding warn">{res.size_note}</div>}
            {res.codes_used && res.codes_used.length > 0 && (
              <div className="muted" style={{ marginBottom: 8 }}>
                모집단 코드: {res.codes_used.join(", ")}{seedMode ? " (Step1a 역산)" : ""}
              </div>
            )}
            <table style={{ marginBottom: 12 }}>
              <thead><tr><th style={{ textAlign: "left" }}>단계</th><th>생존</th></tr></thead>
              <tbody>{Object.entries(res.funnel).map(([k, n]) => (
                <tr key={k}><td style={{ textAlign: "left" }}>{k}</td><td>{n}</td></tr>))}</tbody>
            </table>
            <div className="finding pass"><b>확정 peer ({res.selected.length})</b> —{" "}
              {res.selected.map((c) => `${c.name}(${c.ticker})`).join(", ") || "없음"}</div>
            {res.needs_review.length > 0 && (
              <div className="finding warn"><b>⚖️ 애매 — 유저 판단 필요</b>
                <ul>{res.needs_review.map((t, i) => <li key={i}>{t.name}({t.ticker}) — {t.reason}</li>)}</ul>
              </div>
            )}
            {res.dropped.length > 0 && (
              <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>
                탈락: {res.dropped.map((t) => `${t.name}[${t.dropped_at}]`).join(" · ")}
              </div>
            )}
            {res.warnings.length > 0 && (
              <div className="warn-box" style={{ marginTop: 8 }}>
                <b>데이터 결측</b><ul>{res.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
