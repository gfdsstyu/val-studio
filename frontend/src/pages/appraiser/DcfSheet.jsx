import React, { useState } from "react";
import { api } from "../../api.js";

/* 4.밸류에이션 > DCF 시트 — 결정론 엔진 호출. 결과는 항상 KPI+게이트 동반.
   ⚠️ 과도기: 입력이 아직 이 시트에 있다 — IA 확정안(hard number 는 2.가정에만)대로
   가정 화면 구현 시 입력부는 그쪽으로 이관하고 여기는 읽기전용+참조 점프가 된다. */

const parseSeries = (s) => s.split(/[\s,]+/).filter(Boolean).map(Number);

const DEMO = {
  wacc: "0.10", terminal_growth: "0.01",
  revenue: "100000, 115000, 132000, 149000, 165000",
  cogs: "40000, 46000, 52800, 59600, 66000",
  sga: "20000, 23000, 26400, 29800, 33000",
  dep_amort: "5000, 5000, 5000, 5000, 5000",
  capex: "5000, 5000, 5000, 5000, 5000",
  delta_nwc_cash_adj: "0, 0, 0, 0, 0",
  non_operating_assets: "20000", net_debt: "10000", non_controlling_interest: "0",
  shares_outstanding: "10000000", claimed_per_share: "", terminal_wc_ratio: "",
  fade_years: "", fade_growth: "", terminal_from_last_fcff: false,
  pgr_source: "", pgr_basis: "",
  terminal_discount_period: "",
};

const FIELD_LABELS = [
  ["revenue", "매출액"],
  ["cogs", "매출원가"],
  ["sga", "판관비"],
  ["dep_amort", "감가상각비"],
  ["capex", "CAPEX"],
  ["delta_nwc_cash_adj", "운전자본 변동(ΔNWC)"],
];

const fmt = (v, d = 0) =>
  v == null || Number.isNaN(v) ? "-" : v.toLocaleString("ko-KR", { maximumFractionDigits: d });

function SensitivityTable({ sens }) {
  if (!sens?.per_share) return null;
  const { wacc_axis, g_axis, per_share } = sens;
  const mid = { r: Math.floor(wacc_axis.length / 2), c: Math.floor(g_axis.length / 2) };
  return (
    <table>
      <thead>
        <tr>
          <th>WACC \ PGR</th>
          {g_axis.map((g, i) => <th key={i}>{(g * 100).toFixed(1)}%</th>)}
        </tr>
      </thead>
      <tbody>
        {per_share.map((row, r) => (
          <tr key={r}>
            <th>{(wacc_axis[r] * 100).toFixed(1)}%</th>
            {row.map((v, c) => (
              <td key={c} className={r === mid.r && c === mid.c ? "center-cell" : ""}>
                {fmt(v)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function DcfSheet({ project, onSave }) {
  const saved = project?.data?.dcf_input;
  // 3.할인율 > WACC 빌드업에서 조립·저장된 WACC 를 이어받는다(front-back 배선).
  const assembledWacc = project?.data?.wacc_result?.wacc;
  const [form, setForm] = useState(() => {
    const init = saved || DEMO;
    return assembledWacc != null ? { ...init, wacc: String(assembledWacc) } : init;
  });
  // 시리즈는 연도=열 그리드로 편집(콤마 문자열 → 셀 배열). 저장 시 다시 조인해 하류 호환.
  const [grid, setGrid] = useState(() => {
    const src = saved || DEMO;
    return Object.fromEntries(
      FIELD_LABELS.map(([k]) => [k, parseSeries(src[k] ?? DEMO[k]).map(String)]));
  });
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  // 거시 시트가 남긴 PGR 앵커 제안(R2) — 있으면 한 번에 값+출처를 채운다.
  const rawAnchor = project?.data?.pgr_suggestion || null;
  // ⚠️ FAIL 앵커(관측치 없음 → value 0)는 **적용 불가**. 객체가 truthy 라는 이유로
  // 적용하면 PGR=0 에 pgr_source='derived' 가 붙어 R2 게이트가 자기 실패 산출물에
  // 통과 도장을 찍는다.
  const anchorFailed = !!rawAnchor
    && (rawAnchor.findings || []).some((f) => f.severity === "fail");
  const anchor = rawAnchor && !anchorFailed ? rawAnchor : null;
  const applyAnchor = () => setForm((f) => ({
    ...f, terminal_growth: String(anchor.value),
    pgr_source: "derived", pgr_basis: anchor.basis || "",
  }));

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const years = grid.revenue.length;
  const setCell = (k, i) => (e) => {
    const next = grid[k].slice();
    next[i] = e.target.value;
    setGrid({ ...grid, [k]: next });
  };
  const addYear = () =>
    setGrid(Object.fromEntries(FIELD_LABELS.map(([k]) => [k, [...grid[k], "0"]])));
  const rmYear = (i) =>
    setGrid(Object.fromEntries(FIELD_LABELS.map(([k]) => [k, grid[k].filter((_, j) => j !== i)])));

  const runDcf = async () => {
    setBusy(true); setErr(null); setRes(null);
    for (const [k, label] of FIELD_LABELS) {
      if (grid[k].some((v) => v.trim() === "" || Number.isNaN(Number(v)))) {
        setErr(`${label}: 숫자가 아닌/빈 셀이 있습니다.`); setBusy(false); return;
      }
    }
    const body = {
      wacc: Number(form.wacc),
      terminal_growth: Number(form.terminal_growth),
      non_operating_assets: Number(form.non_operating_assets),
      net_debt: Number(form.net_debt),
      non_controlling_interest: Number(form.non_controlling_interest || 0),
      shares_outstanding: Number(form.shares_outstanding),
    };
    for (const [k] of FIELD_LABELS) body[k] = grid[k].map(Number);
    if (form.claimed_per_share.trim()) body.claimed_per_share = Number(form.claimed_per_share);
    // 터미널 정규화 WC 재조정(정본): 있으면 터미널 ΔWC=추정말매출×g×비율(과대계상 방어).
    if (form.terminal_wc_ratio?.trim()) body.terminal_wc_ratio = Number(form.terminal_wc_ratio);
    // 페이드(R1): 명시 → 페이드 → Gordon 3단. 비우면 기존 2단.
    if (form.fade_years?.toString().trim()) body.fade_years = Number(form.fade_years);
    if (form.fade_growth?.toString().trim()) body.fade_growth = Number(form.fade_growth);
    if (form.terminal_from_last_fcff) body.terminal_from_last_fcff = true;
    // R15: 터미널 할인기간 명시 선언(비우면 audit 가 WARN + 대안 영향 제시)
    if (form.terminal_discount_period?.toString().trim())
      body.terminal_discount_period = Number(form.terminal_discount_period);
    // R2: PGR 출처 — 없으면 audit 이 '무근거 하드코드' WARN
    if (form.pgr_source?.trim()) body.pgr_source = form.pgr_source.trim();
    if (form.pgr_basis?.trim()) body.pgr_basis = form.pgr_basis.trim();
    try {
      const d = await api.dcf(body);
      setRes(d);
      // 시리즈는 콤마 문자열로 직렬화해 저장(시나리오·export 가 그대로 소비).
      const seriesStr = Object.fromEntries(FIELD_LABELS.map(([k]) => [k, grid[k].join(", ")]));
      onSave?.({ dcf_input: { ...form, ...seriesStr }, dcf_result_summary: {
        per_share: d.per_share, tv_weight: d.tv_weight,
        warn: d.findings.filter((f) => f.severity !== "pass").length,
      }, dcf_findings: d.findings.filter((f) => f.severity !== "pass") });
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="card">
        <h2>DCF 입력 <span className="muted">— 결정론 엔진(calc_core)</span></h2>
        <div className="pad">
          <div className="grid2">
            <div className="row"><label>WACC (소수, 예 0.10)</label>
              <input type="text" value={form.wacc} onChange={set("wacc")} />
              {assembledWacc != null && (
                <div className="muted" style={{ fontSize: "0.8rem", marginTop: 2 }}>
                  ↳ 3.할인율 빌드업에서 조립됨: <b>{(assembledWacc * 100).toFixed(2)}%</b> (수정 가능)
                </div>
              )}</div>
            <div className="row"><label>영구성장률 PGR (소수)</label>
              <input type="text" value={form.terminal_growth} onChange={set("terminal_growth")} />
              {anchorFailed && (
                <div className="muted" style={{ marginTop: 4, fontSize: "0.8rem",
                  color: "var(--warn,#c49b47)" }}>
                  ⚠ 거시 앵커 산출 실패({rawAnchor.basis}) — 적용할 수 없습니다.
                  3.할인율 › 거시에서 물가 자료·평가기준일을 확인하세요.
                </div>
              )}
              {anchor && (
                <div style={{ marginTop: 4, fontSize: "0.82rem" }}>
                  <button type="button" onClick={applyAnchor}>
                    앵커 적용 ({(anchor.value * 100).toFixed(2)}%)
                  </button>
                  <span className="muted" style={{ marginLeft: 6 }}>
                    3.할인율 › 거시에서 산출한 물가 앵커
                  </span>
                </div>
              )}
            </div>
            <div className="row"><label>PGR 출처 (감사 방어 — 비우면 WARN)</label>
              <select value={form.pgr_source} onChange={set("pgr_source")}>
                <option value="">(미기재)</option>
                <option value="derived">derived — 거시 앵커링(권장)</option>
                <option value="research">research — 문서·리포트 근거</option>
                <option value="user">user — 평가인 확정</option>
              </select>
              <input type="text" value={form.pgr_basis} onChange={set("pgr_basis")}
                placeholder="산출식·근거 (derived 는 필수)" style={{ marginTop: 4 }} />
              <div className="muted" style={{ fontSize: "0.8rem", marginTop: 2 }}>
                PGR 은 TV 최고민감 파라미터 — <b>어디서 온 숫자인지</b>가 값 자체만큼 중요하다.
              </div></div>
            <div className="row"><label>터미널 운전자본비율 (선택 — 정규화 WC/매출)</label>
              <input type="text" value={form.terminal_wc_ratio} onChange={set("terminal_wc_ratio")}
                placeholder="예 0.30 (비우면 ΔWC=0)" />
              <div className="muted" style={{ fontSize: "0.8rem", marginTop: 2 }}>
                터미널 ΔWC = 추정말매출 × PGR × 이 비율 (정본 과대계상 방어). 비우면 g&gt;2%서 F1 경고.
              </div></div>
            <div className="row"><label>페이드(수렴) 연수 (선택 — 명시→페이드→Gordon 3단)</label>
              <input type="text" value={form.fade_years} onChange={set("fade_years")}
                placeholder="예 5 (비우면 기존 2단)" />
              <div className="muted" style={{ fontSize: "0.8rem", marginTop: 2 }}>
                마지막 명시연도의 <b>모든 비율(마진·세율·CAPEX/매출·ΔWC/매출)이 동결</b>된 채 성장률만
                수렴하는 구간. 명시말기 고성장에서 PGR 로 급단절하면 TV 가 왜곡되고 TV 비중이 치솟는다.
                <br />실측(모델러스 Hugel): 페이드 5년 → TV비중 57.8%(PASS) / 없으면 84.6%(WARN)·주당 9% 과대.
              </div></div>
            <div className="row"><label>페이드 성장률 (선택 — 비우면 자동)</label>
              <input type="text" value={form.fade_growth} onChange={set("fade_growth")}
                placeholder="비우면 AVERAGE(마지막 명시 성장률, PGR)" /></div>
            <div className="row">
              <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <input type="checkbox" checked={!!form.terminal_from_last_fcff}
                  onChange={(e) => setForm((f) => ({ ...f, terminal_from_last_fcff: e.target.checked }))} />
                터미널을 <b>마지막 연도 FCFF × (1+g)</b> 로 산출
              </label>
              <div className="muted" style={{ fontSize: "0.8rem", marginTop: 2 }}>
                끄면 EBIT_T 재구축(D&amp;A=CAPEX, ΔWC=0) — 재투자 0 가정이라 g&gt;0 에서 FCFF 과대.
                켜면 마지막 해의 실제 재투자 강도를 영구 승계(페이드와 함께 쓸 때 정합적).
              </div></div>
            <div className="row"><label>터미널 할인기간 t (선택 — 명시 선언 권장)</label>
              <input type="text" value={form.terminal_discount_period}
                onChange={set("terminal_discount_period")}
                placeholder="비우면 마지막 명시연도 계수(mid-year)" />
              <div className="muted" style={{ fontSize: "0.8rem", marginTop: 2 }}>
                기말 t=n 과 mid-year t=n−0.5 모두 통용되나 <b>선택은 밝혀야 한다</b>(실측 영향 주당 −2.1%).
                비우면 audit 이 대안 컨벤션의 금액 영향을 계산해 WARN 으로 제시한다.
              </div></div>
          </div>
          <label style={{ marginTop: 6 }}>추정 시계열 (백만원, 연도=열)</label>
          <div style={{ overflowX: "auto" }}>
            <table className="grid-input">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>항목</th>
                  {Array.from({ length: years }, (_, i) => (
                    <th key={i}>
                      Y{i + 1}
                      {years > 1 && (
                        <button className="ghost xs" title="열 삭제" onClick={() => rmYear(i)}>✕</button>
                      )}
                    </th>
                  ))}
                  <th><button className="ghost xs" title="연도 추가" onClick={addYear}>+</button></th>
                </tr>
              </thead>
              <tbody>
                {FIELD_LABELS.map(([k, label]) => (
                  <tr key={k}>
                    <th style={{ textAlign: "left", whiteSpace: "nowrap" }}>{label}</th>
                    {grid[k].map((v, i) => (
                      <td key={i}><input type="text" value={v} onChange={setCell(k, i)} /></td>
                    ))}
                    <td></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="grid2">
            <div className="row"><label>비영업자산 (백만원)</label>
              <input type="text" value={form.non_operating_assets} onChange={set("non_operating_assets")} /></div>
            <div className="row"><label>순차입부채 (백만원)</label>
              <input type="text" value={form.net_debt} onChange={set("net_debt")} /></div>
            <div className="row"><label>비지배지분 NCI (연결, 백만원)</label>
              <input type="text" value={form.non_controlling_interest} onChange={set("non_controlling_interest")} /></div>
            <div className="row"><label>발행주식수 (주)</label>
              <input type="text" value={form.shares_outstanding} onChange={set("shares_outstanding")} /></div>
            <div className="row"><label>주장 주당가치 (선택 — 감사인 괴리 진단)</label>
              <input type="text" value={form.claimed_per_share} onChange={set("claimed_per_share")}
                placeholder="의견서 주장값(원)" /></div>
          </div>
          <button className="primary" onClick={runDcf} disabled={busy}>
            {busy ? "계산 중…" : "DCF 계산"}
          </button>
          {err && <div className="err">{err}</div>}
        </div>
      </div>

      {res && (
        <div className="card">
          <h2>결과</h2>
          <div className="pad">
            <div className="kpis">
              <div className="kpi hero"><div className="v">{fmt(res.per_share)} 원</div><div className="k">주당가치</div></div>
              <div className="kpi"><div className="v">{fmt(res.enterprise_value)}</div><div className="k">EV (백만원)</div></div>
              <div className="kpi"><div className="v">{fmt(res.equity_value)}</div><div className="k">지분가치 (백만원)</div></div>
              <div className="kpi"><div className="v">{res.tv_weight != null ? (res.tv_weight * 100).toFixed(1) + "%" : "-"}</div><div className="k">TV 비중</div></div>
            </div>

            <h2 style={{ marginTop: 18 }}>가정 타당성 (audit)</h2>
            {res.findings.filter((f) => f.severity !== "pass").length === 0 && (
              <div className="finding pass">경고 없음 — 전 게이트 통과</div>
            )}
            {res.findings.filter((f) => f.severity !== "pass").map((f, i) => (
              <div key={i} className={`finding ${f.severity}`}>
                <b>[{f.severity.toUpperCase()}] {f.rule}</b> — {f.message}
              </div>
            ))}

            {res.gap_diagnosis && (
              <>
                <h2 style={{ marginTop: 18 }}>괴리 구조버그 진단</h2>
                <div className={`finding ${res.gap_diagnosis.severity}`}>{res.gap_diagnosis.message}</div>
              </>
            )}

            <h2 style={{ marginTop: 18 }}>민감도 (WACC × PGR) <span className="muted">— 강조 셀 = base</span></h2>
            <SensitivityTable sens={res.sensitivity} />
          </div>
        </div>
      )}
    </>
  );
}
