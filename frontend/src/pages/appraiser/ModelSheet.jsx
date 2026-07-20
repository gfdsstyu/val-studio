import React, { useState } from "react";
import { api } from "../../api.js";

/* 3표 정합성 — IS·BS·CF 를 조립해 **조립 배관을 검증**하는 시트.

   우리 DCF 는 무차입 FCFF 라 3표가 가치산정엔 불필요하다. 목적은 회계 항등식
   (자산=부채+자본, Δ현금=CFO+CFI+CFF)으로 상류 모듈(FA·WC·원가) 조립이 정합한지
   독립 검증하는 것 — 잔차가 뜨면 어딘가 배관이 틀린 것이다.

   ⚠️ 계산·검증은 전부 서버 결정론(/api/three-statement). 여기서 산식을 재구현하지 않는다.
   근거: docs/reference/모델링_워크플로우_기초.md §7, 앤트로픽_금융스킬_벤치마크 §2 audit-xls */

const parseSeries = (s) =>
  (s || "").split(/[\s,]+/).filter(Boolean).map(Number);

const won = (v) =>
  v == null || Number.isNaN(v) ? "-" : Math.round(v).toLocaleString("ko-KR");

/** 잔차 표기 — 허용오차(0.001) 내면 TRUE, 아니면 **잔차 금액**을 보여준다.
    ⚠️ 정확일치 비교 금지(부동소수 노이즈로 맞는 연도가 FALSE 로 뜬다). */
const CHECK_TOL = 0.001;
const checkCell = (v) =>
  Math.abs(v) < CHECK_TOL
    ? { text: "TRUE", ok: true }
    : { text: won(v), ok: false };

const OPENING_FIELDS = [
  ["cash", "현금및현금성자산"],
  ["short_term_investments", "단기금융자산 (이자부·NOA)"],
  ["net_working_capital", "순운전자본 (WC)"],
  ["net_fixed_assets", "순유형자산 (FA)"],
  ["other_assets", "기타자산 (무이자)"],
  ["interest_bearing_debt", "이자부부채 (IBD)"],
  ["other_liabilities", "기타부채 (OAL)"],
  ["paid_in_capital", "자본금·자본잉여금"],
  ["retained_earnings", "이익잉여금"],
  ["other_equity", "기타자본"],
];
const ASSET_KEYS = ["cash", "short_term_investments", "net_working_capital",
  "net_fixed_assets", "other_assets"];
const LIAB_KEYS = ["interest_bearing_debt", "other_liabilities"];
const EQ_KEYS = ["paid_in_capital", "retained_earnings", "other_equity"];

const DEMO_OPENING = {
  cash: "500", short_term_investments: "200", net_working_capital: "300",
  net_fixed_assets: "1000", other_assets: "50", interest_bearing_debt: "800",
  other_liabilities: "100", paid_in_capital: "600", retained_earnings: "550",
  other_equity: "0",
};

export default function ModelSheet({ project, onSave }) {
  const d = project?.data || {};
  const saved = d.three_statement_input;

  // DCF 시트가 이미 채운 값이 있으면 그대로 재사용 — **같은 벡터**여야 검증이 성립한다.
  const dcf = d.dcf_input || {};
  const initOps = () => ({
    ebit: saved?.ebit ?? "",
    dep_amort: saved?.dep_amort ?? dcf.dep_amort ?? "",
    capex: saved?.capex ?? dcf.capex ?? "",
    net_working_capital: saved?.net_working_capital ?? "",
    effective_tax_rate: saved?.effective_tax_rate ?? "0.242",
  });

  const [ops, setOps] = useState(initOps);
  const [opening, setOpening] = useState(saved?.opening || DEMO_OPENING);
  const [fin, setFin] = useState(saved?.financing || {
    debt_issuance: "", debt_repayment: "", interest_rate_debt: "0.04",
    interest_rate_cash: "0.03", dividend_payout_ratio: "0.3",
  });
  const [basis, setBasis] = useState(saved?.interest_basis || "average");
  const [circuit, setCircuit] = useState(saved?.circularity_enabled !== false);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const setOp = (k) => (e) => setOps((f) => ({ ...f, [k]: e.target.value }));
  const setOpen = (k) => (e) => setOpening((f) => ({ ...f, [k]: e.target.value }));
  const setF = (k) => (e) => setFin((f) => ({ ...f, [k]: e.target.value }));

  // 기초 BS 대차 — 서버가 최종 판정하지만, 입력 중에도 즉시 보이도록 표시만 한다.
  const sum = (keys) => keys.reduce((a, k) => a + (Number(opening[k]) || 0), 0);
  const openResidual = sum(ASSET_KEYS) - (sum(LIAB_KEYS) + sum(EQ_KEYS));

  const run = async () => {
    setBusy(true); setErr(null); setRes(null);
    try {
      const body = {
        ebit: parseSeries(ops.ebit),
        dep_amort: parseSeries(ops.dep_amort),
        capex: parseSeries(ops.capex),
        net_working_capital: parseSeries(ops.net_working_capital),
        effective_tax_rate: ops.effective_tax_rate,
        opening: Object.fromEntries(OPENING_FIELDS.map(([k]) => [k, opening[k]])),
        financing: {
          debt_issuance: parseSeries(fin.debt_issuance),
          debt_repayment: parseSeries(fin.debt_repayment),
          interest_rate_debt: fin.interest_rate_debt,
          interest_rate_cash: fin.interest_rate_cash,
          dividend_payout_ratio: fin.dividend_payout_ratio,
        },
        interest_basis: basis,
        circularity_enabled: circuit,
      };
      const out = await api.threeStatement(body);
      setRes(out);
      onSave?.({
        three_statement_input: { ...ops, opening, financing: fin,
          interest_basis: basis, circularity_enabled: circuit },
        three_statement_summary: {
          ok: out.ok, converged: out.circularity.converged,
          worst_balance: Math.max(...out.residuals.balance.map(Math.abs)),
        },
        three_statement_findings: out.findings.filter((f) => f.severity !== "pass"),
      });
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const years = res ? res.income_statement.ebit.length : 0;
  const cols = Array.from({ length: years }, (_, i) => i);

  const Row = ({ label, vals, strong, indent }) => (
    <tr>
      <td style={{ paddingLeft: indent ? 18 : 4, fontWeight: strong ? 700 : 400 }}>{label}</td>
      {vals.map((v, i) => (
        <td key={i} style={{ textAlign: "right", fontWeight: strong ? 700 : 400 }}>{won(v)}</td>
      ))}
    </tr>
  );

  const CheckRow = ({ label, vals }) => (
    <tr>
      <td style={{ fontWeight: 700 }}>{label}</td>
      {vals.map((v, i) => {
        const c = checkCell(v);
        return (
          <td key={i} style={{ textAlign: "right", fontWeight: 700,
            color: c.ok ? "var(--ok,#5b7c65)" : "var(--err,#cf3a36)" }}>{c.text}</td>
        );
      })}
    </tr>
  );

  const Table = ({ title, children }) => (
    <div style={{ marginTop: 14 }}>
      <b>{title}</b>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", marginTop: 4 }}>
          <thead>
            <tr>
              <th style={{ textAlign: "left" }}>항목</th>
              {cols.map((i) => <th key={i} style={{ textAlign: "right" }}>{i + 1}년차</th>)}
            </tr>
          </thead>
          <tbody>{children}</tbody>
        </table>
      </div>
    </div>
  );

  return (
    <>
      <div className="card">
        <h2>3표 정합성 <span className="muted">— 조립 배관 검증</span></h2>
        <div className="pad">
          <div className="muted" style={{ fontSize: "0.85rem", marginBottom: 10 }}>
            우리 DCF 는 <b>무차입 FCFF</b> 라 3표가 가치산정엔 필요 없습니다. 이 시트의 목적은
            회계 항등식(<b>자산=부채+자본</b>, <b>Δ현금=CFO+CFI+CFF</b>)으로 FA·WC·원가 조립이
            정합한지 <b>독립 검증</b>하는 것입니다. 잔차가 뜨면 어딘가 배관이 틀린 것이며,
            차액을 &lsquo;대차조정&rsquo;으로 메우지 않고 그대로 노출합니다.
          </div>

          <div className="grid2">
            <div>
              <b>영업 산출 (DCF 와 <u>같은 벡터</u>여야 함)</b>
              <div className="muted" style={{ fontSize: "0.8rem", margin: "2px 0 6px" }}>
                다른 숫자를 넣으면 &ldquo;다른 모델&rdquo;을 검증하는 셈이라 결과가 무의미합니다.
              </div>
              {[["ebit", "EBIT"], ["dep_amort", "D&A"], ["capex", "CAPEX"],
                ["net_working_capital", "순운전자본 잔액"]].map(([k, label]) => (
                <div className="row" key={k}>
                  <label>{label} (콤마 구분)</label>
                  <input type="text" value={ops[k]} onChange={setOp(k)}
                    placeholder="예 300, 330, 360" />
                </div>
              ))}
              <div className="row"><label>유효세율 (비우면 구간세율)</label>
                <input type="text" value={ops.effective_tax_rate}
                  onChange={setOp("effective_tax_rate")} /></div>
            </div>

            <div>
              <b>기초 재무상태표</b>
              <div className="muted" style={{ fontSize: "0.8rem", margin: "2px 0 6px" }}>
                <b>스스로 대차가 맞아야</b> 합니다 — 안 맞으면 그 불균형이 전 추정기간에
                상수로 지속됩니다(추정 로직이 아니라 기초 자료를 먼저 고쳐야 함).
              </div>
              {OPENING_FIELDS.map(([k, label]) => (
                <div className="row" key={k}>
                  <label>{label}</label>
                  <input type="text" value={opening[k]} onChange={setOpen(k)} />
                </div>
              ))}
              <div style={{ marginTop: 6, fontWeight: 700,
                color: Math.abs(openResidual) < CHECK_TOL ? "var(--ok,#5b7c65)" : "var(--err,#cf3a36)" }}>
                기초 대차 잔차: {Math.abs(openResidual) < CHECK_TOL ? "TRUE" : won(openResidual)}
              </div>
            </div>
          </div>

          <div className="grid2" style={{ marginTop: 10 }}>
            <div>
              <b>재무활동</b>
              {[["debt_issuance", "차입 발행 (연도별)"], ["debt_repayment", "차입 상환 (연도별)"],
                ["interest_rate_debt", "차입 이자율"], ["interest_rate_cash", "예금 이자율"],
                ["dividend_payout_ratio", "배당성향 (순이익 대비)"]].map(([k, label]) => (
                <div className="row" key={k}>
                  <label>{label}</label>
                  <input type="text" value={fin[k]} onChange={setF(k)} />
                </div>
              ))}
            </div>

            <div>
              <b>순환참조 처리</b>
              <div className="muted" style={{ fontSize: "0.8rem", margin: "2px 0 6px" }}>
                3표는 필연적으로 <code>이자수익 → 순이익 → 현금 → 이자부자산 → 이자수익</code>
                순환을 만듭니다. 엑셀은 &ldquo;반복계산 켜기&rdquo;로 넘기지만, 여기서는
                <b> 고정점 반복을 직접 돌리고 수렴을 검증</b>합니다.
              </div>
              <div className="row">
                <label>이자 기준</label>
                <select value={basis} onChange={(e) => setBasis(e.target.value)}>
                  <option value="average">평균잔액 (기본 — 더 정확)</option>
                  <option value="opening">기초잔액 (단순화 — 순환 없음)</option>
                </select>
                <div className="muted" style={{ fontSize: "0.78rem", marginTop: 2 }}>
                  이자는 <b>연중 잔액</b>에 붙습니다. 기초잔액만 쓰면 연중 변화를 통째로
                  무시(좌단점 근사)하고, 평균잔액은 사다리꼴 근사라 더 정확합니다.
                </div>
              </div>
              <div className="row">
                <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <input type="checkbox" checked={circuit}
                    onChange={(e) => setCircuit(e.target.checked)} />
                  순환 스위치 (Circuit Switch) — 켜짐
                </label>
                <div className="muted" style={{ fontSize: "0.78rem", marginTop: 2 }}>
                  끄면 이자수익을 0으로 강제해 고리를 끊습니다(진단·대조용).
                  <b> 순이익이 과소</b>되므로 최종 산출에 쓰면 안 됩니다.
                </div>
              </div>
            </div>
          </div>

          <button className="primary" style={{ marginTop: 12 }} disabled={busy} onClick={run}>
            {busy ? "계산 중…" : "3표 조립 + 정합성 검증"}
          </button>
          {err && <div style={{ color: "var(--err,#cf3a36)", marginTop: 8 }}>{err}</div>}
        </div>
      </div>

      {res && (
        <>
          <div className="card">
            <h2>검증 결과
              <span className="muted"> — {res.ok ? "정합" : "불일치 발견"}</span></h2>
            <div className="pad">
              <div className="muted" style={{ fontSize: "0.82rem", marginBottom: 6 }}>
                순환 처리: <b>{res.circularity.interest_basis === "average" ? "평균잔액" : "기초잔액"}</b>
                {" · "}반복 {res.circularity.iterations.join("/")}회
                {" · "}{res.circularity.converged ? "수렴" : "미수렴"}
              </div>
              {res.findings.map((f, i) => (
                <div key={i} style={{ marginBottom: 4, fontSize: "0.85rem",
                  color: f.severity === "fail" ? "var(--err,#cf3a36)"
                    : f.severity === "warn" ? "var(--warn,#c49b47)" : "var(--ok,#5b7c65)" }}>
                  {f.severity === "pass" ? "✓" : f.severity === "warn" ? "⚠" : "✗"} {f.message}
                  {f.detail?.bs_unreliable && (
                    <span className="muted"> (대차 불일치로 이 판정은 신뢰 불가)</span>
                  )}
                </div>
              ))}
            </div>
          </div>

          <div className="card">
            <h2>3표</h2>
            <div className="pad">
              <Table title="손익계산서">
                <Row label="영업이익 (EBIT)" vals={res.income_statement.ebit} />
                <Row label="이자수익" vals={res.income_statement.interest_income} indent />
                <Row label="(−) 이자비용" vals={res.income_statement.interest_expense} indent />
                <Row label="세전이익 (EBT)" vals={res.income_statement.ebt} strong />
                <Row label="(−) 법인세" vals={res.income_statement.tax} indent />
                <Row label="순이익" vals={res.income_statement.net_income} strong />
              </Table>

              <Table title="재무상태표">
                <Row label="현금" vals={res.balance_sheet.cash} indent />
                <Row label="단기금융자산" vals={res.balance_sheet.short_term_investments} indent />
                <Row label="순운전자본" vals={res.balance_sheet.net_working_capital} indent />
                <Row label="순유형자산" vals={res.balance_sheet.net_fixed_assets} indent />
                <Row label="기타자산" vals={res.balance_sheet.other_assets} indent />
                <Row label="자산 계" vals={res.balance_sheet.total_assets} strong />
                <Row label="이자부부채" vals={res.balance_sheet.interest_bearing_debt} indent />
                <Row label="기타부채" vals={res.balance_sheet.other_liabilities} indent />
                <Row label="부채 계" vals={res.balance_sheet.total_liabilities} strong />
                <Row label="이익잉여금" vals={res.balance_sheet.retained_earnings} indent />
                <Row label="자본 계" vals={res.balance_sheet.total_equity} strong />
                <CheckRow label="CHECK 대차 (자산−부채−자본)" vals={res.residuals.balance} />
              </Table>

              <Table title="현금흐름표">
                <Row label="영업활동 (CFO)" vals={res.cash_flow.cfo} />
                <Row label="투자활동 (CFI)" vals={res.cash_flow.cfi} />
                <Row label="재무활동 (CFF)" vals={res.cash_flow.cff} />
                <Row label="현금 순증감" vals={res.cash_flow.net_change_in_cash} strong />
                <CheckRow label="CHECK 현금연결 (Δ현금−CF합)" vals={res.residuals.cash_tie} />
                <CheckRow label="CHECK 이익잉여금 롤포워드" vals={res.residuals.re_rollforward} />
              </Table>

              <div className="muted" style={{ fontSize: "0.8rem", marginTop: 10 }}>
                CHECK 행은 허용오차({CHECK_TOL}) 비교입니다 — 정확일치로 비교하면 부동소수
                노이즈 때문에 <b>맞는 연도가 오류로 뜹니다</b>. 불일치 시 TRUE/FALSE 가 아니라
                <b> 잔차 금액</b>을 표시해 원인 추적이 가능하게 했습니다.
                <br />⚠️ 대차는 <b>D&amp;A·CAPEX 오류를 흡수</b>합니다(CFO+ 와 FA롤− 로 상쇄) —
                대차 TRUE 를 &ldquo;모델이 맞다&rdquo;로 읽으면 안 됩니다.
              </div>
            </div>
          </div>
        </>
      )}
    </>
  );
}
