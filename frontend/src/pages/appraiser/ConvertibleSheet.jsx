import React, { useState } from "react";
import { api } from "../../api.js";
import TableTransfer from "../../TableTransfer.jsx";
import { Hint } from "../../Hint.jsx";

/* 4-x. 전환사채(CB)·RCPS 평가 — T-F 격자 + with-without 분해 + S1 게이트.
 *
 * 엔진(`calc_core/convertible.py`)은 TF 워크북 골든까지 검증돼 있었는데 화면이 없어
 * 능력이 드러나지 않던 부분이다(정직 표기 2축의 'engine 有 · ui 無').
 *
 * 이 화면의 핵심은 값 하나가 아니라 **분해가 정합한가**이다:
 *   with(전체 CB) − without(옵션 제거 host 사채) = 내재파생
 * 양변이 같은 모델·같은 가정이어야 성립한다. 실무에서 흔한 오류가 이종 가정 차감
 * (연속할인 트리 − 이산할인 채권)을 '내재옵션'이라 부르는 것이고, 그걸 게이트가 잡는다.
 */

const FIELDS = [
  ["face", "액면(상환금액)", "10000", "사채 1단위 상환금액"],
  ["stock_price", "현재 주가", "12000", ""],
  ["conversion_ratio", "전환비율(주/사채)", "1", "사채 1단위당 전환 주식수"],
  ["maturity_years", "만기(년)", "3", ""],
  ["volatility", "변동성 σ", "0.4", "연 변동성. 0.4 = 40%"],
  ["risk_free", "무위험이자율", "0.03", "연속복리 근사"],
  ["credit_spread", "신용스프레드", "0.05", "발행자 신용가산 — 채권성분 할인율"],
  ["coupon_rate", "표면이자율", "0.02", "연 쿠폰(액면 대비)"],
  ["dividend_yield", "배당수익률 q", "0", ""],
];
const OPTIONAL = [
  ["put_price", "풋 행사가", "", "투자자 조기상환 청구가(고정형)"],
  ["put_accrual_rate", "풋 보장수익률", "", "설정 시 face×(1+r)^t — RCPS 관행. 고정가보다 우선"],
  ["call_price", "콜 행사가", "", "발행자 수의상환가(고정형)"],
  ["call_accrual_rate", "콜 보장수익률", "", "설정 시 face×(1+r)^t"],
  ["baseline_value", "신용악화 전 가치", "", "입력하면 상쇄효과(408) 판정 — 스프레드 급등에도 가치가 안 변하면 경고"],
];

const won = (v) => (v == null ? "—" : Math.round(v).toLocaleString("ko-KR"));
const SEV = { fail: "err", warn: "warn", pass: "pass" };

export default function ConvertibleSheet({ project, onSave }) {
  const saved = project?.data?.convertible_input || {};
  const [f, setF] = useState(() => {
    const init = {};
    for (const [k, , def] of FIELDS) init[k] = saved[k] ?? def;
    for (const [k] of OPTIONAL) init[k] = saved[k] ?? "";
    return init;
  });
  const [res, setRes] = useState(project?.data?.convertible_result || null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  const run = async () => {
    setBusy(true); setErr(null);
    try {
      const body = {};
      for (const [k] of FIELDS) body[k] = Number(f[k]);
      // 선택 입력은 **빈칸을 0으로 보내지 않는다** — 0원 풋과 '풋 없음'은 전혀 다르다.
      for (const [k] of OPTIONAL) if (String(f[k]).trim() !== "") body[k] = Number(f[k]);
      const d = await api.convertible(body);
      setRes(d);
      onSave?.({ convertible_input: f, convertible_result: d });
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const r = res?.result;
  const ww = res?.with_without;
  const bad = (res?.findings || []).filter((x) => x.severity !== "pass");

  const tsv = () => !r ? [] : [
    ["항목", "값"],
    ["CB 공정가치", r.value], ["주식성분", r.equity_component], ["채권성분", r.debt_component],
    ["일반사채(옵션 제거)", r.straight_bond], ["현재 전환가치", r.conversion_value_now],
    ["with(전체)", ww.with_value], ["without(host 사채)", ww.without_value],
    ["내재파생", ww.embedded_value],
  ];

  return (
    <div className="card">
      <h2>전환사채·RCPS 평가 <span className="muted">— T-F 격자 · with-without 분해</span></h2>
      <div className="pad">
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
          {FIELDS.map(([k, label, , hint]) => (
            <div className="row" key={k} style={{ margin: 0, width: 150 }}>
              <label title={hint}>{label}</label>
              <input type="text" value={f[k]} onChange={set(k)} />
            </div>
          ))}
        </div>

        <details style={{ marginTop: 10 }}>
          <summary style={{ cursor: "pointer", fontSize: 13 }}>
            콜·풋·보장수익률 <span className="muted">— 비우면 해당 옵션 없음</span></summary>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 8 }}>
            {OPTIONAL.map(([k, label, , hint]) => (
              <div className="row" key={k} style={{ margin: 0, width: 170 }}>
                <label title={hint}>{label}</label>
                <input type="text" value={f[k]} onChange={set(k)} placeholder="(없음)" />
              </div>
            ))}
          </div>
          <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>
            보장수익률을 넣으면 고정 행사가보다 <b>우선</b>합니다(RCPS 관행:
            face×(1+r)<sup>t</sup>). 빈칸은 0 이 아니라 <b>옵션 없음</b>으로 전달됩니다.
          </div>
        </details>

        <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 10 }}>
          <button className="primary" onClick={run} disabled={busy}>
            {busy ? "계산 중…" : "평가 실행"}</button>
          <Hint label="분해 규약">
            <b>with(전체 CB) − without(옵션 제거 host 사채) = 내재파생</b>. 양변이 같은 모델·
            같은 가정이어야 성립합니다. 실무에서 흔한 오류는 연속할인 트리에서 이산할인
            채권을 빼고 그 잔차를 '내재옵션'이라 부르는 것으로, 아래 게이트가 잡습니다.
            신용스프레드가 임계를 넘으면 T-F 기계 산출값을 그대로 회계에 반영하기 전
            질적분석(DP·RR 하향, 유사등급 시장가 대조)이 필요합니다.
          </Hint>
        </div>
        {err && <div className="err" style={{ marginTop: 8 }}>{err}</div>}

        {r && (
          <>
            <div className={`finding ${bad.length ? "warn" : "pass"}`} style={{ marginTop: 12 }}>
              CB 공정가치 <b>{won(r.value)}</b>
              {" · "}주식성분 {won(r.equity_component)} + 채권성분 {won(r.debt_component)}
              {bad.length > 0 && <> · 검토 필요 {bad.length}건</>}
            </div>

            <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 10 }}>
              <table style={{ minWidth: 260 }}>
                <thead><tr><th style={{ textAlign: "left" }}>구성</th><th>금액</th></tr></thead>
                <tbody>
                  <tr><th style={{ textAlign: "left" }}>CB 공정가치</th>
                    <td style={{ textAlign: "right" }}><b>{won(r.value)}</b></td></tr>
                  <tr><th style={{ textAlign: "left" }}>　주식성분</th>
                    <td style={{ textAlign: "right" }}>{won(r.equity_component)}</td></tr>
                  <tr><th style={{ textAlign: "left" }}>　채권성분</th>
                    <td style={{ textAlign: "right" }}>{won(r.debt_component)}</td></tr>
                  <tr><th style={{ textAlign: "left" }}>일반사채(참고)</th>
                    <td style={{ textAlign: "right" }} className="muted">{won(r.straight_bond)}</td></tr>
                  <tr><th style={{ textAlign: "left" }}>현재 전환가치</th>
                    <td style={{ textAlign: "right" }} className="muted">{won(r.conversion_value_now)}</td></tr>
                </tbody>
              </table>
              <table style={{ minWidth: 280 }}>
                <thead><tr><th style={{ textAlign: "left" }}>with-without 분해</th><th>금액</th></tr></thead>
                <tbody>
                  <tr><th style={{ textAlign: "left" }}>with (전체 CB)</th>
                    <td style={{ textAlign: "right" }}>{won(ww.with_value)}</td></tr>
                  <tr><th style={{ textAlign: "left" }}>− without (host 사채)</th>
                    <td style={{ textAlign: "right" }}>{won(ww.without_value)}</td></tr>
                  <tr><th style={{ textAlign: "left" }}><b>= 내재파생</b></th>
                    <td style={{ textAlign: "right" }}><b>{won(ww.embedded_value)}</b></td></tr>
                </tbody>
              </table>
            </div>

            <div style={{ margin: "10px 0" }}>
              <TableTransfer label="CB 평가 결과" rows={tsv()} hint="조서 첨부용" />
            </div>

            <h3 style={{ margin: "12px 0 6px", fontSize: 13 }}>게이트</h3>
            {(res.findings || []).map((x, i) => (
              <div key={i} className={`finding ${SEV[x.severity]}`}>
                <b>[{x.severity.toUpperCase()}] {x.rule}</b> — {x.message}
              </div>
            ))}
            <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>
              '신용악화 전 가치'를 입력하면 상쇄효과(스프레드가 급등해도 변동성이 전환가치를
              떠받쳐 총가치가 거의 안 변하는 현상)까지 판정합니다 — 부실기업 주식의
              휴지화 가능성이 모델에 반영되지 않았을 신호입니다.
            </div>
          </>
        )}
      </div>
    </div>
  );
}
