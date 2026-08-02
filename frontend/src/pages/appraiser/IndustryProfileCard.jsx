import React, { useEffect, useState } from "react";
import { api } from "../../api.js";

/* 산업 프로파일 카드 — 사용자 가정(OPM·DSO·DIO·CAPEX/매출)을 동종 산업 분포 대비 대조.
   근거: docs/reference/산업_프로파일.md + backend/calc_core/data/industry_benchmarks.json
   (내부 레퍼런스 코퍼스 횡단집계, rigor=참고 prior).
   판정: p25~p75=정상(초록) · min~max 안=주의(노랑) · 밖=이상치(빨강, 감사 red flag).
   → calc_core.checks.check_metric_vs_industry 와 동일 규칙(엔진↔UX 일관). */

const METRICS = [
  ["opm", "영업이익률", "%"],
  ["dso", "매출채권회전", "일"],
  ["dio", "재고회전", "일"],
  ["capex_sales", "CAPEX/매출", "%"],
];

// 값 → 심각도(엔진 게이트와 동일 로직)
function verdict(v, d) {
  if (v == null || !d || d.n == null) return { level: "none", label: "-" };
  if (d.n < 3) return { level: "low", label: `참고(n=${d.n})` };
  if (v >= d.p25 && v <= d.p75) return { level: "ok", label: "정상" };
  if (v >= d.min && v <= d.max) return { level: "warn", label: "주의" };
  return { level: "bad", label: v > d.max ? "이상치↑" : "이상치↓" };
}

const COLORS = {
  ok: "#137333", warn: "#b06000", bad: "#c5221f", low: "#5f6368", none: "#9aa0a6",
};

// min~max 스케일에서 값의 위치(%) — 미니 밴드용
const pos = (v, d) => {
  if (d.max === d.min) return 50;
  return Math.max(0, Math.min(100, ((v - d.min) / (d.max - d.min)) * 100));
};

export default function IndustryProfileCard({ industry, values = {}, benchmark = null }) {
  const [bench, setBench] = useState(benchmark);
  const [err, setErr] = useState(null);

  useEffect(() => {
    if (benchmark || !industry) return;
    setErr(null);
    api.benchmarksIndustry(industry)
      .then((r) => setBench(r?.metrics || {}))
      .catch((e) => setErr(String(e?.message || e)));
  }, [industry, benchmark]);

  if (err) return <div style={{ color: "#c5221f", fontSize: 13 }}>벤치마크 로드 실패: {err}</div>;
  // 산업 미입력 시 fetch 가 일어나지 않으므로 '로딩…' 이 아니라 중립 안내를 보여준다
  // (industry 있을 때만 실제 로딩 중 — 그때만 로딩 텍스트).
  if (!bench) return industry
    ? <div style={{ color: "#5f6368", fontSize: 13 }}>산업 프로파일 로딩…</div>
    : <div style={{ color: "#9aa0a6", fontSize: 13 }}>산업을 입력하면 동종 분포 대비 이상치를 표시합니다.</div>;

  const anyOutlier = METRICS.some(([k]) => verdict(values[k], bench[k]).level === "bad");

  return (
    <div style={{ border: "1px solid #dadce0", borderRadius: 8, padding: 16, maxWidth: 520 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <h4 style={{ margin: 0 }}>산업 프로파일 · {industry}</h4>
        {anyOutlier && (
          <span style={{ color: "#c5221f", fontSize: 12, fontWeight: 600 }}>⚠️ 이상치 있음</span>
        )}
      </div>
      <div style={{ fontSize: 11, color: "#5f6368", marginBottom: 10 }}>
        동종 분포 대비. 초록=정상대역[p25~p75], 노랑=주의, 빨강=이상치(사업모델 재검토).
      </div>

      {METRICS.map(([key, label, unit]) => {
        const d = bench[key];
        const v = values[key];
        const vd = verdict(v, d);
        return (
          <div key={key} style={{ marginBottom: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
              <span>{label}</span>
              <span>
                <b style={{ color: COLORS[vd.level] }}>
                  {v == null ? "—" : v}{unit}
                </b>
                <span style={{ color: COLORS[vd.level], fontSize: 11, marginLeft: 6 }}>
                  {vd.label}
                </span>
                {d && d.p50 != null && (
                  <span style={{ color: "#9aa0a6", fontSize: 11, marginLeft: 6 }}>
                    (동종 p50 {d.p50}{unit})
                  </span>
                )}
              </span>
            </div>
            {d && d.min != null && (
              <div style={{ position: "relative", height: 8, marginTop: 4,
                background: "#eef0f2", borderRadius: 4 }}>
                {/* p25~p75 정상대역 */}
                <div style={{ position: "absolute", top: 0, height: 8, borderRadius: 4,
                  left: `${pos(d.p25, d)}%`, width: `${pos(d.p75, d) - pos(d.p25, d)}%`,
                  background: "#cdeacd" }} />
                {/* 사용자 값 마커 */}
                {v != null && (
                  <div style={{ position: "absolute", top: -2, width: 3, height: 12,
                    left: `${pos(v, d)}%`, background: COLORS[vd.level], borderRadius: 2 }} />
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
