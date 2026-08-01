import React, { useState } from "react";
import { excelWriteAvailable, writeToSelection } from "./officeBridge.js";

/** 조회 결과 표 → 엑셀로 옮기는 공통 전송 버튼 (docs/plan/addin_two_panel_ux.md '다리 1').
 *
 * 두 경로를 같은 데이터로 제공한다:
 *   ① **TSV 복사** — 어디서나 동작(브라우저 탭 포함). 엑셀에 Ctrl+V 하면 셀로 분해된다.
 *   ② **선택 셀에 쓰기** — Task Pane 에서만 노출(Office.js). 클립보드를 거치지 않는다.
 *
 * rows 계약: `(string|number)[][]`, 첫 행 = 헤더. **숫자는 number 로 넘길 것** —
 * 문자열로 넘기면 엑셀에서 텍스트 셀이 되어 계산에 못 쓴다(전송의 존재 이유가 사라짐).
 */
export default function TableTransfer({ rows, label = "표", hint }) {
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const n = Array.isArray(rows) ? rows.length : 0;

  const flash = (t) => { setMsg(t); setTimeout(() => setMsg(null), 3000); };

  const copyTsv = async () => {
    const tsv = rows
      .map((r) => r.map((c) => (c == null ? "" : String(c))).join("\t"))
      .join("\n");
    try {
      await navigator.clipboard.writeText(tsv);
      flash(`복사됨 (${n}행) — 엑셀에서 Ctrl+V`);
    } catch {
      // Task Pane iframe·비보안 컨텍스트에서 clipboard API 가 막히는 경우가 있다.
      const ta = document.createElement("textarea");
      ta.value = tsv;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      flash(ok ? `복사됨 (${n}행) — 엑셀에서 Ctrl+V` : "복사 실패 — 표를 직접 선택해 복사하세요");
    }
  };

  const write = async () => {
    setBusy(true); setMsg(null);
    try {
      const r = await writeToSelection(rows);
      flash(`${r.sheet} 에 기입 (${r.rows}행 × ${r.cols}열)`);
    } catch (e) { flash(e.message); } finally { setBusy(false); }
  };

  if (!n) return null;
  return (
    <span className="transfer">
      <button className="ghost xs" onClick={copyTsv} title={`${label} ${n}행을 TSV 로 클립보드에 복사`}>
        TSV 복사
      </button>
      {excelWriteAvailable() && (
        <button className="ghost xs" onClick={write} disabled={busy}
          title="현재 선택한 셀을 좌상단으로 표를 기입합니다(덮어쓰기 주의)">
          {busy ? "기입 중…" : "선택 셀에 쓰기"}
        </button>
      )}
      {hint && !msg && <span className="muted transfer-msg">{hint}</span>}
      {msg && <span className="muted transfer-msg">{msg}</span>}
    </span>
  );
}
