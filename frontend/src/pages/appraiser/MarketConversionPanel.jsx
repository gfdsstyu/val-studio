import React, { useEffect, useState } from "react";
import { api } from "../../api.js";
import { applyMarketConversion, readConversionRanges, readMarketWorkbook, selectedConversionRange } from "../../marketBridge.js";

const sourceUnits = { unit: "외화 1단위", thousand: "외화 천단위", million: "외화 백만단위" };
const outputUnits = { KRW: "원", KRW_thousand: "천원", KRW_million: "백만원" };

export default function MarketConversionPanel({ view, query, observation, busy, work, save, setStatus, onStage }) {
  const [sourceSheet, setSourceSheet] = useState("");
  const [sourceAddress, setSourceAddress] = useState("");
  const [outputSheet, setOutputSheet] = useState("");
  const [outputStart, setOutputStart] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [sourceScale, setSourceScale] = useState("unit");
  const [outputUnit, setOutputUnit] = useState("KRW_million");
  const [reason, setReason] = useState("");
  const [ack, setAck] = useState(false);
  const [preview, setPreview] = useState(null);
  useEffect(() => { setPreview(null); setAck(false); }, [view.snapshot_id, observation?.observation_id]);
  const change = setter => e => { setter(e.target.value); setPreview(null); setAck(false); };
  const chooseSource = () => work(async () => {
    const selected = await selectedConversionRange();
    setSourceSheet(selected.sheet); setSourceAddress(selected.address); setPreview(null); setAck(false);
    setStatus("선택 범위를 가져왔습니다. 원본 통화·단위와 출력 위치를 확인하세요.");
  });
  const lookup = () => work(async () => {
    setPreview(null);
    const grids = await readMarketWorkbook();
    const ranges = await readConversionRanges(sourceSheet, sourceAddress, outputSheet, outputStart);
    const payload = { ...query, snapshot_id: view.snapshot_id, observation_id: observation.observation_id,
      ...grids, ...ranges, source_sheet: sourceSheet, source_address: sourceAddress,
      output_sheet: outputSheet, output_start: outputStart, source_currency: currency,
      source_scale: sourceScale, output_unit: outputUnit, expected_unit: observation.value_unit,
      reason, acknowledge_warnings: ack };
    const plan = await api.market.conversionPlan(payload);
    setPreview({ plan, payload }); setStatus("환산 미리보기를 확인한 뒤 적용하세요.");
  });
  const apply = () => work(async () => {
    const { payload } = preview;
    setPreview(null);
    const fresh = await api.market.conversionPlan(payload);
    const written = await applyMarketConversion(fresh, onStage);
    await save(view, query, written.state, written);
    setStatus("외화 금액 환산·수식/계산값 대사·근거 기록 및 프로젝트 저장 완료");
  });
  const p = preview?.plan;
  const samples = p ? p.source.expected.values.flatMap((row, r) => row.map((value, c) =>
    ({ r, c, value, result: p.output.expected_values[r][c] }))).slice(0, 10) : [];
  return <fieldset disabled={busy || !observation?.adoption_eligible} style={{ display: "grid", gap: 8 }}>
    <legend>외화 금액 환산</legend>
    <p>선택한 날짜의 환율로 외화 금액을 환산합니다. 원본은 유지하고 같은 크기의 빈 출력 범위에 수식을 만듭니다.</p>
    <button onClick={chooseSource}>Excel 선택 범위 가져오기</button>
    <label>원본 시트 <input value={sourceSheet} onChange={change(setSourceSheet)} placeholder="예: Revenue" /></label>
    <label>원본 범위 <input value={sourceAddress} onChange={change(setSourceAddress)} placeholder="예: B5:D12" /></label>
    <label>원본 통화 <select value={currency} onChange={change(setCurrency)}>
      {["USD", "JPY", "EUR"].map(v => <option key={v}>{v}</option>)}</select></label>
    <label>원본 금액 단위 <select value={sourceScale} onChange={change(setSourceScale)}>
      {Object.entries(sourceUnits).map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select></label>
    <label>출력 시트 <input value={outputSheet} onChange={change(setOutputSheet)} placeholder="기존 시트 이름" /></label>
    <label>출력 시작 셀 <input value={outputStart} onChange={change(setOutputStart)} placeholder="예: F5" /></label>
    <label>출력 단위 <select value={outputUnit} onChange={change(setOutputUnit)}>
      {Object.entries(outputUnits).map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select></label>
    <label>환산 사유 <input value={reason} onChange={change(setReason)} /></label>
    <label><input type="checkbox" checked={ack} onChange={e => { setAck(e.target.checked); setPreview(null); }} />
      원본의 통화·단위와 환율 적용일을 확인했으며, 원본은 원화로 환산되지 않은 외화 금액입니다.</label>
    <small>최대 2,000셀·100열, 단일 통화의 연속 범위. 숫자·빈 셀을 지원하며 병합 셀은 제외합니다.
      기간평균 환율과 미래 환율 경로는 별도 가정이 필요합니다.</small>
    <button disabled={!sourceSheet || !sourceAddress || !outputSheet || !outputStart || reason.trim().length < 3 || !ack}
      onClick={lookup}>환산 미리보기</button>
    {p && <div>
      <p>{p.source.sheet}!{p.source.address} → {p.output.sheet}!{p.output.address}<br />
        {p.currency} · {sourceUnits[p.source_scale]} → {outputUnits[p.output_unit]}<br />
        적용일 {p.effective_date} · 환율 {p.expected_rate} 원/{p.currency} 1단위</p>
      <table><thead><tr><th>범위 내 위치</th><th>원본 금액</th><th>환산 결과 ({outputUnits[p.output_unit]})</th></tr></thead>
        <tbody>{samples.map(({ r, c, value, result }) => <tr key={`${r}:${c}`}>
          <td>{r + 1}행 {c + 1}열</td><td>{value ?? ""}</td><td>{result}</td></tr>)}</tbody></table>
      <small>미리보기는 처음 10셀까지 표시합니다. 전체 {p.source.height * p.source.width}셀을 적용합니다.</small>
      <p>수식 예: <code>{p.output.formulas[0][0]}</code></p>
      <button className="primary" onClick={apply}>외화 금액 환산 적용</button>
    </div>}
  </fieldset>;
}
