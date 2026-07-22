import React from "react";

/* 감사인 3. 괴리 진단 — 주장값과 독립 추정치의 차이를 구조 오류 / 가정 차이로 가른다.

   앤트로픽 audit-xls 의 DCF 버그 목록을 결정론 규칙으로 승격한 게 엔진의
   `diagnose_dcf_gap`: 흔한 구조 오류를 하나씩 가정해 재계산해보고, 주장값이 어느
   가설과 맞아떨어지는지 지목한다. 어느 가설도 안 맞으면 구조가 아니라 **가정 차이**
   이므로 민감도로 추적한다(이 단계의 두 시트가 정확히 그 갈림길이다). */

const HYPOTHESIS_LABEL = {
  end_year_discounting: "기말 할인 — mid-year 컨벤션 미적용(전 기간 0.5년 과다할인)",
  tv_undiscounted: "터미널가치 미할인 — TV 를 현재가치로 안 끌어옴",
  tv_missing: "터미널가치 누락 — 명시적 기간만 합산",
  nonop_missing: "비영업자산 누락 — EV→지분 브리지에서 가산 빠짐",
  netdebt_ignored: "순차입부채 미차감 — EV 를 그대로 지분가치로 사용",
};

const fmt = (v) =>
  v == null || Number.isNaN(v) ? "-" : Math.round(v).toLocaleString("ko-KR");

function Empty() {
  return (
    <div className="card"><div className="pad muted">
      먼저 <b>2. 독립 재계산</b> 에서 주장 주당가치와 함께 재계산을 실행하세요 —
      주장값이 있어야 괴리를 진단합니다.
    </div></div>
  );
}

function StructuralSheet({ project }) {
  const res = project?.data?.audit_result;
  const claimed = project?.data?.audit_claimed;
  const diag = res?.gap_diagnosis;
  if (!res || claimed == null || !diag) return <Empty />;

  const hyp = diag.hypotheses || {};
  // 주장값에 가장 가까운 가설을 지목(엔진 판정과 같은 기준 ±1%).
  const near = (v) => claimed && Math.abs(v - claimed) / Math.abs(claimed) <= 0.01;
  const matched = Object.entries(hyp).filter(([, v]) => near(v)).map(([k]) => k);

  return (
    <>
      <div className="card">
        <h2>구조버그 가설 <span className="muted">— 주장값이 어느 오류와 맞는가</span></h2>
        <div className="pad">
          <div className={matched.length ? "warn-box" : "ok"}>
            {diag.message}
          </div>
          <table style={{ marginTop: 12 }}>
            <thead>
              <tr><th>가설(구조 오류)</th><th>그 오류였다면</th><th>판정</th></tr>
            </thead>
            <tbody>
              <tr className="ok">
                <th>정상 — 감사인 독립 추정</th>
                <td>{fmt(res.per_share)} 원</td>
                <td>{near(res.per_share) ? "✅ 주장과 일치" : "—"}</td>
              </tr>
              {Object.entries(hyp).map(([k, v]) => (
                <tr key={k} className={near(v) ? "warn" : ""}>
                  <th>{HYPOTHESIS_LABEL[k] || k}</th>
                  <td>{fmt(v)} 원</td>
                  <td>{near(v) ? "⚠️ 주장과 일치 — 이 오류 의심" : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="muted" style={{ marginTop: 10 }}>
            주장 주당가치 <b>{fmt(claimed)} 원</b>.{" "}
            {matched.length
              ? "일치하는 가설이 있으면 평가자 모델의 해당 계산 단계를 직접 확인하세요."
              : "구조 가설이 전부 불일치 → 구조가 아니라 가정 차이입니다. 민감도 추적으로 넘어가세요."}
          </div>
        </div>
      </div>
    </>
  );
}

function SensitivitySheet({ project }) {
  const res = project?.data?.audit_result;
  const claimed = project?.data?.audit_claimed;
  if (!res?.sensitivity?.per_share) return <Empty />;

  const { wacc_axis, g_axis, per_share } = res.sensitivity;
  const mid = { r: Math.floor(wacc_axis.length / 2), c: Math.floor(g_axis.length / 2) };
  // 주장값을 재현하는 (WACC, g) 조합 — "어떤 가정이면 저 숫자가 나오는가"의 역산.
  const near = (v) => claimed && Math.abs(v - claimed) / Math.abs(claimed) <= 0.02;

  return (
    <div className="card">
      <h2>민감도 추적 <span className="muted">— 주장값을 낳는 가정 조합 역산</span></h2>
      <div className="pad">
        <div className="muted" style={{ marginBottom: 10 }}>
          구조 오류가 아니라면 차이는 가정에서 온다. 주장 주당가치
          {claimed != null && <> <b>{fmt(claimed)} 원</b></>} 과 ±2% 안에 드는 칸이
          강조됩니다 — 평가자가 그 WACC·PGR 을 쓸 근거가 있는지 확인하세요.
          중심 칸은 감사인 독립 추정({fmt(res.per_share)} 원)입니다.
        </div>
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
                  <td key={c}
                    className={
                      r === mid.r && c === mid.c ? "center-cell" : near(v) ? "warn" : ""
                    }>
                    {fmt(v)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function GapDiagnosis({ project, sheet }) {
  return sheet === "sensitivity"
    ? <SensitivitySheet project={project} />
    : <StructuralSheet project={project} />;
}
