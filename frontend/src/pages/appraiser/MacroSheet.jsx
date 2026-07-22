import React, { useState } from "react";
import { api } from "../../api.js";
import { loadKey } from "../Byok.jsx";

/* 2.가정 › 거시 — 물가·성장률 등 거시 전망을 확정해 하류 드라이버에 공급.

   여기서 확정한 CPI 를 원가·판관비의 `cpi` 드라이버(외주비 등 물가연동)가 소비한다.
   이 시트가 없던 동안 `project.data.macro_cpi` 를 쓰는 곳이 없어, cpi 드라이버가
   조용히 물가상승 0%로 계산됐다(감사 2026-07-19 §3.2-4 죽은 참조).

   두 경로: 복붙(EIU·전망보고서 — 예측치는 이쪽이 정본) / ECOS(한국은행 실적).
   ECOS 는 최신 개정치만 주므로 예측·최근연도는 복붙을 쓰라는 게 커넥터 설계 규칙이다. */

const INDICATORS = [
  ["cpi_inflation", "소비자물가 상승률(CPI)", "macro_cpi"],
  ["real_gdp_growth", "실질 GDP 성장률", "macro_gdp"],
  ["nominal_wage_growth", "명목임금 상승률", "macro_wage"],
];

const pct = (v) => (v == null ? "-" : `${(v * 100).toFixed(2)}%`);

export default function MacroSheet({ project, onSave }) {
  const [indicator, setIndicator] = useState(INDICATORS[0][0]);
  const [text, setText] = useState("");
  const [vintage, setVintage] = useState("");
  const [forecastFrom, setForecastFrom] = useState("");
  const [source, setSource] = useState("");
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [pgr, setPgr] = useState(project?.data?.pgr_suggestion || null);

  // SSOT 키는 `valuation_date` — `base_date` 는 레포에 존재하지 않는 키였다.
  // 이 오타 때문에 vintage look-ahead 가드가 **모든 실사용 경로에서 꺼져** 있었다.
  const baseDate = project?.setup?.valuation_date || "";
  const ecosKey = loadKey("ecos");
  const dataKey = INDICATORS.find(([id]) => id === indicator)?.[2];
  const current = project?.data?.[dataKey];

  const run = async (viaEcos) => {
    setBusy(true); setErr(null); setRes(null); setSaved(false);
    try {
      setRes(await api.macroSeries(
        {
          indicator, base_date: baseDate || undefined,
          ...(viaEcos
            ? { start: String(new Date().getFullYear() - 6), end: String(new Date().getFullYear()) }
            : { text, vintage: vintage || undefined,
                is_forecast_from: forecastFrom || undefined,
                source: source || undefined }),
        },
        viaEcos ? ecosKey : null));
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  /** 물가 시계열 → 영구성장률(PGR) 앵커 제안(R2). 산식은 서버 결정론(vintage 가드 포함).
      근거: 모델러스 F33 = AVERAGE(rInflation 10년) — PGR 을 감이 아니라 출처 있는
      거시 통계의 함수로. **제안일 뿐 확정은 평가인 몫.** */
  const suggestPgr = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await api.pgrSuggest({
        text, vintage: vintage || undefined, base_date: baseDate || undefined,
        is_forecast_from: forecastFrom || undefined, source: source || undefined, years: 10,
      });
      setPgr(r);
      onSave?.({ pgr_suggestion: r });
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  /** 확정 → 연율 문자열로 저장(하류 시트가 parseSeries 로 그대로 소비). */
  const confirm = () => {
    if (!res) return;
    const years = Object.keys(res.annual).sort();
    onSave?.({
      [dataKey]: years.map((y) => res.annual[y]).join(", "),
      [`${dataKey}_meta`]: {
        years, indicator: res.indicator,
        source: res.observations[0]?.source || null,
        vintage: res.observations[0]?.vintage || null,
      },
    });
    setSaved(true);
  };

  const fails = (res?.findings || []).filter((f) => f.severity === "fail");
  const warns = (res?.findings || []).filter((f) => f.severity === "warn");

  return (
    <>
      <div className="card">
        <h2>거시 가정 <span className="muted">— 확정값이 원가 드라이버로 흐름</span></h2>
        <div className="pad">
          <div className="row" style={{ gap: 16, marginBottom: 10 }}>
            <label>지표
              <select value={indicator} onChange={(e) => { setIndicator(e.target.value); setRes(null); }}>
                {INDICATORS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
              </select>
            </label>
            {current && <span className="ok">현재 확정: {current}</span>}
          </div>

          <div className="muted" style={{ marginBottom: 10 }}>
            <b>기간 값</b> 형식으로 붙여넣으세요(예 <code>2026 2.0%</code> 한 줄씩).
            예측 스냅샷은 발행일(vintage)을 함께 남겨야 그 시점 전망으로 보존됩니다.
            {baseDate && <> 평가기준일 <b>{baseDate}</b> 이후 공표분은 look-ahead 가드가 제외합니다.</>}
          </div>
          <textarea rows={7} style={{ width: "100%" }} value={text}
            placeholder={"2024 2.3%\n2025 2.1%\n2026 2.0%"}
            onChange={(e) => setText(e.target.value)} />

          <div className="grid2" style={{ marginTop: 10 }}>
            <div className="row"><label>발행일(vintage)</label>
              <input type="text" value={vintage} placeholder="2026-01-15"
                onChange={(e) => setVintage(e.target.value)} /></div>
            <div className="row"><label>예측 시작연도</label>
              <input type="text" value={forecastFrom} placeholder="2026"
                onChange={(e) => setForecastFrom(e.target.value)} /></div>
            <div className="row"><label>출처</label>
              <input type="text" value={source} placeholder="EIU / 한은 경제전망"
                onChange={(e) => setSource(e.target.value)} /></div>
          </div>

          <div className="row" style={{ gap: 16, marginTop: 10 }}>
            <button className="primary" disabled={busy || !text.trim()} onClick={() => run(false)}>
              {busy ? "처리 중…" : "붙여넣기 반영"}
            </button>
            <button disabled={busy || !ecosKey} onClick={() => run(true)}
              title={ecosKey ? "한국은행 ECOS 실적 조회" : "BYOK 에서 ECOS 키를 먼저 입력하세요"}>
              ECOS 실적 조회
            </button>
            {!ecosKey && <span className="muted">ECOS 키 미입력 — 복붙 경로만 가능</span>}
          </div>
          {err && <div className="err" style={{ marginTop: 10 }}>{err}</div>}
        </div>
      </div>

      {res && (
        <div className="card">
          <h2>확정 후보 <span className="muted">— {res.indicator}</span></h2>
          <div className="pad">
            {fails.length > 0 && (
              <div className="err" style={{ marginBottom: 10 }}>
                <b>가드 FAIL</b>
                <ul>{fails.map((f, i) => <li key={i}>{f.message}</li>)}</ul>
              </div>
            )}
            {warns.length > 0 && (
              <div className="warn-box" style={{ marginBottom: 10 }}>
                <b>주의</b>
                <ul>{warns.map((f, i) => <li key={i}>{f.message}</li>)}</ul>
              </div>
            )}
            {res.dropped_periods?.length > 0 && (
              <div className="warn-box" style={{ marginBottom: 10 }}>
                <b>look-ahead 가드로 제외된 기간: {res.dropped_periods.join(", ")}</b> —
                전망치를 넣었다면 <b>예측 시작연도</b>를 채우세요. 비워두면 미래 연도가
                '미래 실적'으로 간주되어 기준일 시점에 알 수 없는 정보로 탈락합니다.
              </div>
            )}
            {res.observations.length === 0 && (
              <div className="warn-box">가드 통과 관측치가 없습니다 — 기준일·vintage 를 확인하세요.</div>
            )}
            <table>
              <thead><tr><th>기간</th><th>값</th><th>구분</th><th>출처</th><th>vintage</th></tr></thead>
              <tbody>
                {res.observations.map((o, i) => (
                  <tr key={i}>
                    <td>{o.period}</td><td>{pct(o.value)}</td>
                    <td>{o.is_forecast ? "예측" : "실적"}</td>
                    <td>{o.source || "-"}</td><td>{o.vintage || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <button className="primary" style={{ marginTop: 12 }}
              disabled={saved || !res.observations.length || fails.length > 0}
              onClick={confirm}>
              {saved ? "확정됨 ✓" : "이 값으로 확정"}
            </button>
            {saved && (
              <div className="muted" style={{ marginTop: 8 }}>
                2.가정 › 원가·판관비의 <b>물가연동(cpi)</b> 드라이버가 이 값을 사용합니다.
              </div>
            )}
            {indicator === "cpi_inflation" && (
              <div style={{ marginTop: 14, borderTop: "1px solid var(--line,#e5e2e0)", paddingTop: 12 }}>
                <b>영구성장률(PGR) 앵커</b>
                <div className="muted" style={{ fontSize: "0.82rem", margin: "4px 0 8px" }}>
                  장기 물가상승률 평균을 PGR 근거로 삼는다(모델러스 정본 F33). PGR 은 TV
                  최고민감 파라미터라 <b>무근거 하드코드는 감사 방어가 불가</b>하다.
                  vintage 가드 통과분만 평균한다. <b>제안일 뿐 확정은 평가인 몫.</b>
                </div>
                {!baseDate && (
                  <div style={{ color: "var(--warn,#c49b47)", fontSize: "0.8rem", marginBottom: 6 }}>
                    ⚠ 평가기준일 미설정 — look-ahead 가드가 적용되지 않습니다(기준일 이후
                    공표·전망치가 평균에 섞일 수 있음). 개요에서 평가기준일을 먼저 확정하세요.
                  </div>
                )}
                <button disabled={busy || !text.trim()} onClick={suggestPgr}>
                  10년 평균으로 PGR 앵커 산출
                </button>
                {pgr && (
                  <div style={{ marginTop: 8, fontSize: "0.85rem" }}>
                    <div>제안 PGR <b>{(pgr.value * 100).toFixed(2)}%</b>
                      <span className="muted"> · n={pgr.n_observations}</span></div>
                    <div className="muted" style={{ fontFamily: "monospace", fontSize: "0.78rem" }}>
                      {pgr.basis}</div>
                    {(pgr.findings || []).filter((f) => f.severity !== "pass").map((f, i) => (
                      <div key={i} style={{ color: "var(--warn,#c49b47)" }}>⚠ {f.message}</div>
                    ))}
                    <div className="muted" style={{ marginTop: 4 }}>
                      4.밸류에이션 › DCF 에서 <b>“앵커 적용”</b> 으로 불러올 수 있습니다.
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
