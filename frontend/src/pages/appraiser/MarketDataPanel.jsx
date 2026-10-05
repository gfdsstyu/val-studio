import React, { useEffect, useRef, useState } from "react";
import { api } from "../../api.js";
import { loadKey } from "../Byok.jsx";
import { appendMarketWorkbook, applyMarketBinding, marketExcelAvailable,
  readMarketTarget, readMarketWorkbook } from "../../marketBridge.js";

const stages = { raw_written: "원자료 재읽기 완료", facts_written: "사실 원장 재읽기 완료",
  inputs_written: "채택 입력 기록 완료", target_written: "대상 수식 기록 완료",
  bindings_verified: "모델 수식·값 대사 완료", adoption_recorded: "채택 이력 기록 완료" };

export default function MarketDataPanel({ project, onSave }) {
  const base = project.setup?.valuation_date || "";
  const [dataset, setDataset] = useState("exchange");
  const [day, setDay] = useState(base);
  const [policy, setPolicy] = useState("exact");
  const [mode, setMode] = useState("historical_reference");
  const [cap, setCap] = useState(null);
  const [result, setResult] = useState(null);
  const [query, setQuery] = useState(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const [selected, setSelected] = useState("");
  const [targetSheet, setTargetSheet] = useState("");
  const [targetCell, setTargetCell] = useState("");
  const [reason, setReason] = useState("");
  const [ack, setAck] = useState(false);
  const [binding, setBinding] = useState(null);
  const [pendingSave, setPendingSave] = useState(null);
  const excel = marketExcelAvailable();
  const ob = result?.observations.find(o => o.observation_id === selected);

  useEffect(() => {
    let alive = true;
    setDay(base); setResult(null); setBinding(null); setSelected("");
    api.market.capabilities().then(v => alive && setCap(v)).catch(e => alive && setError(e.message));
    const previous = project.data?.market_data;
    if (previous?.snapshot_id && previous.query?.valuation_date === base) {
      api.market.restore({ ...previous.query, snapshot_id: previous.snapshot_id }).then(v => {
        if (!alive) return;
        setResult(v); setQuery(previous.query); setDataset(previous.query.dataset);
        setDay(previous.query.requested_date); setPolicy(previous.query.date_policy); setMode(previous.query.asof_mode);
        setStatus("저장된 스냅샷을 복원했습니다. 현재 워크북 기록 상태는 다시 확인하세요.");
      }).catch(e => alive && setError(`복원 실패: ${e.message}`));
    }
    return () => { alive = false; };
  }, [project.id, base]); // Saved query never triggers an automatic network quote request.

  const work = async action => {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError("");
    try { await action(); } catch (e) { setError(`${e.code ? e.code + ": " : ""}${e.message}`); }
    finally { lock.current = false; setBusy(false); }
  };
  const save = async (view, q, state, adoption = null) => {
    const payload = { market_data: { version: 1, query: q, snapshot_id: view.snapshot_id,
      state, persistence: view.persistence, adoption } };
    setPendingSave(payload);
    await onSave(payload);
    setPendingSave(null);
  };
  const lookup = cachePolicy => work(async () => {
    setResult(null); setBinding(null); setSelected(""); setStatus("조회 중…");
    const q = { dataset, valuation_date: base, requested_date: day, date_policy: policy,
      asof_mode: mode, currencies: ["USD", "JPY", "EUR"], max_lookback_days: 7, cache_policy: cachePolicy };
    const view = await api.market.quotes(loadKey("kexim"), q);
    setResult(view); setQuery(q); setStatus("조회 완료 · 프로젝트 저장 중…");
    await save(view, q, "preview_ready"); setStatus("조회 결과를 프로젝트에 저장했습니다.");
  });
  const record = () => work(async () => {
    const grids = await readMarketWorkbook();
    const plan = await api.market.sheetPlan({ ...query, snapshot_id: result.snapshot_id, ...grids });
    setStatus("워크북 기록 중…");
    await appendMarketWorkbook(plan, s => setStatus(stages[s]));
    await save(result, query, "facts_written"); setStatus("원자료·사실 기록 및 프로젝트 저장 완료");
  });
  const previewBinding = () => work(async () => {
    setBinding(null);
    const grids = await readMarketWorkbook();
    const target = await readMarketTarget(targetSheet, targetCell);
    const plan = await api.market.bindingPlan({ ...query, snapshot_id: result.snapshot_id,
      observation_id: selected, ...grids, target_sheet: targetSheet, target_address: targetCell,
      expected_target: target, expected_unit: ob.value_unit, reason, acknowledge_warnings: ack });
    setBinding(plan); setStatus("변경 내용을 확인한 뒤 ‘이 환율을 모델에 반영’을 누르세요.");
  });
  const adopt = () => work(async () => {
    // Revalidate server snapshot/date eligibility at the final write boundary.
    const fresh = await api.market.bindingPlan({ ...query, snapshot_id: result.snapshot_id,
      observation_id: selected, market_grid: binding.expected_market_grid,
      inputs_grid: binding.inputs.expected_grid, facts_grid: binding.facts.expected_grid, target_sheet: targetSheet,
      target_address: targetCell, expected_target: binding.target.expected,
      expected_unit: ob.value_unit, reason, acknowledge_warnings: ack });
    const written = await applyMarketBinding(fresh, s => setStatus(stages[s]));
    setBinding(null); await save(result, query, written.state, written);
    setStatus("모델 입력값·수식 대사, 채택 이력 및 프로젝트 저장 완료");
  });
  const invalidate = setter => e => { setter(e.target.value); setResult(null); setBinding(null); };
  const changeBinding = setter => e => { setter(e.target.value); setBinding(null); };

  return <div className="card">
    <h2>한국수출입은행 환율·금리</h2>
    <div className="pad" style={{ display: "grid", gap: 12 }}>
      <p>평가기준일 <strong>{base || "프로젝트 설정 필요"}</strong>에 사용할 시장자료를 조회하고 출처와 함께 기록합니다.</p>
      {cap && <p className="muted">저장: {cap.persistence === "ephemeral" ? "임시 저장 — 서버 재시작 시 사라질 수 있음" : "로컬 스냅샷"}
        {" · "}{cap.date_contracts[dataset]?.verified ? "조회일·적용일 대응 검증됨" : "적용일 실검증 전 — 조회·원자료 기록 가능, 모델 반영 대기"}</p>}
      {cap && !cap.enabled && <p role="alert">이 환경의 시장자료 기능이 비활성화되어 있습니다.</p>}
      <fieldset disabled={busy} style={{ display: "grid", gap: 8 }}>
        <label>자료 <select value={dataset} onChange={invalidate(setDataset)}>
          <option value="exchange">현재환율 (매매기준율)</option><option value="lending">대출금리 (공시 기준금리)</option>
          <option value="international">국제금리</option></select></label>
        <label>조회일 <input type="date" value={day} max={base} onChange={invalidate(setDay)} /></label>
        <label>빈 날짜 처리 <select value={policy} onChange={invalidate(setPolicy)}>
          <option value="exact">해당 날짜만</option><option value="previous_available">이전 자료 탐색 (최대 7일)</option></select></label>
        <label>정보시점 <select value={mode} onChange={invalidate(setMode)}>
          <option value="historical_reference">과거 자료 참고 (공표·개정 이력 미상 경고)</option>
          <option value="strict_snapshot">당시 이용 가능 정보만 (증빙 없으면 반영 차단)</option></select></label>
        <div><button className="primary" disabled={!base || !day || !cap?.enabled} onClick={() => lookup("prefer_cache")}>자료 조회</button>{" "}
          <button className="ghost" disabled={!base || !day || !cap?.enabled} onClick={() => lookup("refresh")}>서버에서 새로 조회</button></div>
      </fieldset>
      <small>인증키는 설정 → BYOK에서 저장하세요. 현재환율은 실시간 체결 시세가 아닙니다. 금리의 통화·종류·단위가 확인되기 전에는 할인율에 반영할 수 없습니다.</small>
      {status && <p role="status">{status}</p>}
      {error && <p role="alert" className="bad">{error}</p>}
      {pendingSave && <button disabled={busy} onClick={() => work(async () => {
        await onSave(pendingSave); setPendingSave(null); setStatus("프로젝트 저장 재시도 완료");
      })}>프로젝트 저장 재시도</button>}
      {result && <>
        <p>조회일 {result.requested_date} / 선택 자료일 {result.selected_request_date} / 수집 {result.fetched_at}<br />
          {result.status === "no_data" ? "해당 날짜에 자료가 없습니다." : `관측 ${result.observations.length}건`}
          {" · "}<a href={result.source_url} target="_blank" rel="noreferrer">공식 API 설명</a></p>
        {result.findings.map((f, i) => <p key={i}>{f.message}</p>)}
        <div style={{ overflowX: "auto" }}><table><thead><tr><th>선택</th><th>통화·만기</th><th>원본</th><th>정규화</th><th>적용일·검증</th></tr></thead>
          <tbody>{result.observations.map(o => <tr key={o.observation_id}>
            <td><input aria-label={`${o.currency_label} 선택`} type="radio" name="market-observation" checked={selected === o.observation_id}
              disabled={busy} onChange={() => { setSelected(o.observation_id); setBinding(null); }} /></td>
            <td>{o.currency_label} {o.tenor_label}</td><td>{o.raw_value || "결측"}</td>
            <td>{o.normalized_value ?? "미확인"}<br /><small>{o.value_unit}</small></td>
            <td>{o.effective_date || "미확인"}{o.findings.map((f, i) => <div key={i}><small>{f.message}</small></div>)}</td>
          </tr>)}</tbody></table></div>
        <small>스냅샷: {result.snapshot_id}</small>
        <button disabled={busy || !excel || !result.observations.length} onClick={record}>Excel에 원자료·출처 기록</button>
        {!excel && <p>Excel 추가 기능에서 열면 원자료 기록과 모델 셀 연결을 사용할 수 있습니다.</p>}
        {excel && <fieldset disabled={busy || !ob?.adoption_eligible} style={{ display: "grid", gap: 8 }}>
          <legend>선택 환율을 모델 입력에 채택</legend>
          <label>대상 시트 <input value={targetSheet} onChange={changeBinding(setTargetSheet)} placeholder="예: Assumptions" /></label>
          <label>대상 셀 <input value={targetCell} onChange={changeBinding(setTargetCell)} placeholder="예: D12" /></label>
          <label>채택 사유 <input value={reason} onChange={changeBinding(setReason)} /></label>
          <label><input type="checkbox" checked={ack} onChange={e => { setAck(e.target.checked); setBinding(null); }} />
            경고를 확인했습니다. 워크북 평가기준일은 {query?.valuation_date}이며,
            대상 셀의 단위는 {ob?.value_unit || "외화 1단위당 원화"}입니다.</label>
          <button disabled={!targetSheet || !targetCell || reason.trim().length < 3 || !ack} onClick={previewBinding}>변경 내용 확인</button>
          {binding && <div><p>{binding.target.sheet}!{binding.target.address}: 현재 {String(binding.target.expected.value)}
            {" → "}{binding.expected_value} ({ob?.value_unit})<br />수식: {binding.target.formula}</p>
            <button className="primary" onClick={adopt}>이 환율을 모델에 반영</button></div>}
        </fieldset>}
      </>}
    </div>
  </div>;
}
