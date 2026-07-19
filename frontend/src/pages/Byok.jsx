import React, { useState } from "react";
import { api } from "../api.js";

/** BYOK: 키는 localStorage 에만 — 서버는 요청 헤더로 통과만 받는다. */
const KEYS = { gemini: "byok_gemini_key", anthropic: "byok_anthropic_key",
               dart: "byok_dart_key", ecos: "byok_ecos_key" };
export const loadKey = (k) => localStorage.getItem(KEYS[k]) || "";
const saveKey = (k, v) => localStorage.setItem(KEYS[k], v);

export default function ByokPanel() {
  const [gemini, setGemini] = useState(loadKey("gemini"));
  const [anthropic, setAnthropic] = useState(loadKey("anthropic"));
  const [dart, setDart] = useState(loadKey("dart"));
  const [ecos, setEcos] = useState(loadKey("ecos"));
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);

  const save = () => {
    saveKey("gemini", gemini.trim());
    saveKey("anthropic", anthropic.trim());
    saveKey("dart", dart.trim());
    saveKey("ecos", ecos.trim());
    setStatus({ msg: "저장됨 (이 브라우저 localStorage 에만)", ok: true });
  };

  const validate = async () => {
    setBusy(true); setStatus(null);
    try {
      const d = await api.validateGeminiKey(gemini.trim());
      setStatus(d.valid
        ? { msg: "Gemini 키 유효 ✓", ok: true }
        : { msg: `Gemini 키 무효 (HTTP ${d.status ?? "?"})`, ok: false });
    } catch (e) {
      setStatus({ msg: `검증 실패: ${e.message}`, ok: false });
    } finally {
      setBusy(false);
    }
  };

  const validateDart = async () => {
    setBusy(true); setStatus(null);
    try {
      const d = await api.validateDartKey(dart.trim());
      setStatus(d.valid
        ? { msg: "DART 키 유효 ✓", ok: true }
        : { msg: `DART 키 무효 (status ${d.status ?? "?"} ${d.message ?? ""})`, ok: false });
    } catch (e) {
      setStatus({ msg: `검증 실패: ${e.message}`, ok: false });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <h2>BYOK — API 키 (클라이언트 보관, 서버 미저장)</h2>
      <div className="pad">
        <div className="grid2">
          <div className="row">
            <label>Gemini API Key (딥서치·임베딩)</label>
            <input type="password" value={gemini} placeholder="AI Studio 키"
              onChange={(e) => setGemini(e.target.value)} />
          </div>
          <div className="row">
            <label>Anthropic API Key (판단 보조 — 추후 배선)</label>
            <input type="password" value={anthropic} placeholder="sk-ant-…"
              onChange={(e) => setAnthropic(e.target.value)} />
          </div>
          <div className="row">
            <label>OpenDART API Key (재무제표 조회)</label>
            <input type="password" value={dart} placeholder="opendart.fss.or.kr 발급 키"
              onChange={(e) => setDart(e.target.value)} />
          </div>
          <div className="row">
            <label>ECOS API Key (한국은행 거시 실적 — 선택)</label>
            <input type="password" value={ecos} placeholder="ecos.bok.or.kr 발급 키"
              onChange={(e) => setEcos(e.target.value)} />
          </div>
        </div>
        <button className="primary" onClick={save}>저장</button>{" "}
        <button className="ghost" onClick={validate} disabled={busy || !gemini.trim()}>
          {busy ? "검증 중…" : "Gemini 키 검증"}
        </button>{" "}
        <button className="ghost" onClick={validateDart} disabled={busy || !dart.trim()}>
          {busy ? "검증 중…" : "DART 키 검증"}
        </button>
        {status && <div className={status.ok ? "ok" : "bad"} style={{ marginTop: 8 }}>{status.msg}</div>}
      </div>
    </div>
  );
}
