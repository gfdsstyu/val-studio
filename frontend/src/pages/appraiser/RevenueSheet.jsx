import React, { useState } from "react";
import { api } from "../../api.js";

/* 2.가정 > 매출(트리) — /api/revenue/build 배선(bottom_up).
   디렉토리형 상-하위 트리(제품군>제품 등). 리프=P×Q 또는 base+growth. 내부노드=자식합계
   (서버 validate_tree_sums 검증). 확정 매출 벡터는 DCF 입력으로 반영.
   LLM 제안(사업보고서 RAG)은 후속 — 지금은 유저 편집 + 서버 합계검증. */

let _uid = 0;
const uid = () => `n${++_uid}`;
const parseSeries = (s) => String(s).split(/[\s,]+/).filter(Boolean).map(Number);
const fmt = (v) => (v == null || Number.isNaN(v) ? "-" : Math.round(v).toLocaleString("ko-KR"));

const DEMO_TREE = {
  id: uid(), name: "총매출", mode: "internal", children: [
    // 장비(razor) 판매 = P×Q. 소모품(blade)은 이 장비의 누적 설치base 에 연동.
    { id: uid(), name: "장비", mode: "pxq", price: "50, 50, 50", qty: "10, 20, 30", children: [] },
    { id: uid(), name: "소모품", mode: "razor", equipment_new: "10, 20, 30",
      consumable_per_unit: "3, 3, 3", installed_base0: "0", retirement_rate: "0", children: [] },
  ],
};

/** 트리 → 서버 페이로드(재귀). 리프 모드별로 price×qty | base+growth | razor(설치base 연동). */
function toPayload(n) {
  if (n.mode === "internal")
    return { name: n.name, children: n.children.map(toPayload) };
  if (n.mode === "pxq")
    return { name: n.name, price: parseSeries(n.price), qty: parseSeries(n.qty) };
  if (n.mode === "razor")
    return { name: n.name, equipment_new: parseSeries(n.equipment_new),
      consumable_per_unit: parseSeries(n.consumable_per_unit),
      installed_base0: Number(n.installed_base0) || 0,
      retirement_rate: Number(n.retirement_rate) || 0 };
  return { name: n.name, base: Number(n.base), growth: parseSeries(n.growth) };
}

/** 재귀 노드 편집기. depth 로 들여쓰기. */
function Node({ node, onChange, onRemove, depth }) {
  const patch = (p) => onChange({ ...node, ...p });
  const setChild = (i, c) => {
    const children = node.children.slice();
    if (c === null) children.splice(i, 1); else children[i] = c;
    patch({ children });
  };
  const addChild = (mode) =>
    patch({ children: [...node.children, mode === "internal"
      ? { id: uid(), name: "새 그룹", mode: "internal", children: [] }
      : { id: uid(), name: "새 항목", mode, price: "0", qty: "0", base: "0", growth: "0",
          equipment_new: "0", consumable_per_unit: "0", installed_base0: "0",
          retirement_rate: "0", children: [] }] });

  return (
    <div style={{ marginLeft: depth * 16, borderLeft: depth ? "1px solid var(--line)" : "none",
      paddingLeft: depth ? 10 : 0, marginTop: 6 }}>
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
        <input type="text" value={node.name} onChange={(e) => patch({ name: e.target.value })}
          style={{ width: 130, fontWeight: node.mode === "internal" ? 600 : 400 }} />
        <select value={node.mode} onChange={(e) => patch({ mode: e.target.value })}
          style={{ padding: "4px", fontSize: 12 }}>
          <option value="internal">그룹(자식합계)</option>
          <option value="pxq">리프 P×Q</option>
          <option value="growth">리프 성장률</option>
          <option value="razor">리프 소모품(장비 설치base 연동)</option>
        </select>
        {node.mode === "pxq" && (
          <>
            <input type="text" value={node.price} onChange={(e) => patch({ price: e.target.value })}
              placeholder="단가(연도별)" style={{ width: 120 }} />
            <span className="muted" style={{ fontSize: 11 }}>×</span>
            <input type="text" value={node.qty} onChange={(e) => patch({ qty: e.target.value })}
              placeholder="수량(연도별)" style={{ width: 120 }} />
          </>
        )}
        {node.mode === "growth" && (
          <>
            <input type="text" value={node.base} onChange={(e) => patch({ base: e.target.value })}
              placeholder="기준매출" style={{ width: 90 }} />
            <span className="muted" style={{ fontSize: 11 }}>×(1+g)</span>
            <input type="text" value={node.growth} onChange={(e) => patch({ growth: e.target.value })}
              placeholder="성장률(연도별)" style={{ width: 120 }} />
          </>
        )}
        {node.mode === "razor" && (
          <>
            <span className="muted" style={{ fontSize: 11 }}>장비판매</span>
            <input type="text" value={node.equipment_new} onChange={(e) => patch({ equipment_new: e.target.value })}
              placeholder="신규대수(연도별)" style={{ width: 110 }} />
            <span className="muted" style={{ fontSize: 11 }}>×대당</span>
            <input type="text" value={node.consumable_per_unit} onChange={(e) => patch({ consumable_per_unit: e.target.value })}
              placeholder="대당 소모품매출(연도별)" style={{ width: 130 }} />
            <span className="muted" style={{ fontSize: 11 }}>기초base</span>
            <input type="text" value={node.installed_base0} onChange={(e) => patch({ installed_base0: e.target.value })}
              placeholder="0" style={{ width: 54 }} />
            <span className="muted" style={{ fontSize: 11 }}>폐기율</span>
            <input type="text" value={node.retirement_rate} onChange={(e) => patch({ retirement_rate: e.target.value })}
              placeholder="0" style={{ width: 44 }} />
          </>
        )}
        {depth > 0 && <button className="ghost xs" title="삭제" onClick={() => onRemove()}>✕</button>}
      </div>
      {node.mode === "internal" && (
        <>
          {node.children.map((c, i) => (
            <Node key={c.id} node={c} depth={depth + 1}
              onChange={(nc) => setChild(i, nc)} onRemove={() => setChild(i, null)} />
          ))}
          <div style={{ marginLeft: (depth + 1) * 16, marginTop: 4 }}>
            <button className="ghost xs" onClick={() => addChild("pxq")}>+ P×Q</button>{" "}
            <button className="ghost xs" onClick={() => addChild("growth")}>+ 성장률</button>{" "}
            <button className="ghost xs" onClick={() => addChild("internal")}>+ 그룹</button>
          </div>
        </>
      )}
    </div>
  );
}

export default function RevenueSheet({ project, onSave }) {
  const [tree, setTree] = useState(project?.data?.revenue_tree || DEMO_TREE);
  const [years, setYears] = useState(project?.data?.revenue_years || 3);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const build = async () => {
    setBusy(true); setErr(null); setRes(null);
    try {
      const d = await api.revenueBuild({ method: "bottom_up", years: Number(years),
        tree: toPayload(tree) });
      setRes(d);
      onSave?.({ revenue_tree: tree, revenue_years: Number(years), revenue_built: d.revenue });
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const pushToDcf = () => {
    if (!res) return;
    const prev = project?.data?.dcf_input || {};
    onSave?.({ dcf_input: { ...prev, revenue: res.revenue.map(Math.round).join(", ") } });
  };

  return (
    <>
      <div className="card">
        <h2>매출 트리 <span className="muted">— bottom-up(제품군&gt;제품, P×Q 또는 성장률)</span></h2>
        <div className="pad">
          <div className="row" style={{ maxWidth: 160 }}>
            <label>추정 연수</label>
            <input type="text" value={years} onChange={(e) => setYears(e.target.value)} />
          </div>
          <div className="muted" style={{ margin: "8px 0" }}>
            리프의 단가/수량/성장률은 <b>연도별 콤마 구분</b>(길이=추정연수). 내부 그룹은
            자식 합계로 자동 검증됩니다. <b>소모품 리프</b>는 장비 누적 설치base(폐기율 차감)에
            연동돼 razor-and-blades 동학을 반영합니다.
          </div>
          <Node node={tree} depth={0} onChange={setTree} onRemove={() => {}} />
          <button className="primary" onClick={build} disabled={busy} style={{ marginTop: 12 }}>
            {busy ? "계산 중…" : "매출 계산·검증"}
          </button>
          {err && <div className="err">{err}</div>}
        </div>
      </div>

      {res && (
        <div className="card">
          <h2>매출 결과</h2>
          <div className="pad">
            {res.errors.length > 0 ? (
              <div className="finding fail"><b>합계검증 실패</b> — {res.errors.length}건
                <ul>{res.errors.slice(0, 6).map((e, i) => <li key={i}>{e}</li>)}</ul></div>
            ) : (
              <div className="finding pass">합계검증 통과 — 내부노드 = 자식 합계</div>
            )}
            <table style={{ marginTop: 10 }}>
              <thead><tr><th style={{ textAlign: "left" }}>구성</th>
                {res.revenue.map((_, i) => <th key={i}>Y{i + 1}</th>)}</tr></thead>
              <tbody>
                {Object.entries(res.breakdown).map(([name, vec]) => (
                  <tr key={name}><th style={{ textAlign: "left" }}>{name}</th>
                    {vec.map((v, i) => <td key={i}>{fmt(v)}</td>)}</tr>
                ))}
                <tr style={{ borderTop: "2px solid var(--line)" }}>
                  <th style={{ textAlign: "left" }}>총매출</th>
                  {res.revenue.map((v, i) => <td key={i}><b>{fmt(v)}</b></td>)}
                </tr>
              </tbody>
            </table>
            <button className="primary" onClick={pushToDcf} style={{ marginTop: 12 }}>
              이 매출을 DCF 입력에 반영
            </button>
          </div>
        </div>
      )}
    </>
  );
}
