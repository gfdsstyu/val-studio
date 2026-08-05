import React, { useState } from "react";

/* 접이식 도움말(ⓘ)과 빈 상태 문구 — 화면 세로를 되찾기 위한 두 규약.
 *
 * 왜 필요한가: 설명문을 muted 로 상시 노출하면 읽는 사람은 한 번 읽고 마는데
 * 자리는 영구히 차지한다. **Task Pane(~350px)** 에서는 그 몇 줄이 표 하나만큼 비싸다.
 * 그렇다고 지우면 규약(단위·게이트 의미·함정)이 사라져 오해가 늘어난다.
 * → 기본은 접고, 필요할 때 펴는 ⓘ 로 옮긴다.
 */

/** ⓘ 토글 도움말. children 은 접힌 채 시작한다. */
export function Hint({ children, label = "설명", defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <span className="hint">
      <button className="linklike" onClick={() => setOpen(!open)}
        aria-expanded={open} title={open ? "설명 접기" : "설명 보기"}
        style={{ fontSize: 12, padding: "0 4px" }}>ⓘ</button>
      {open && (
        <div className="muted" style={{ fontSize: 11, marginTop: 4, lineHeight: 1.5 }}>
          {children}
          <button className="linklike" onClick={() => setOpen(false)}
            style={{ marginLeft: 6, fontSize: 11 }}>접기</button>
        </div>
      )}
      {!open && <span className="muted" style={{ fontSize: 11 }}> {label}</span>}
    </span>
  );
}

/** 빈 상태 — **상태 + 다음 행동**을 함께 말한다.
 *
 * "결과 없음"만 띄우면 원인(조건이 좁은가/권한인가/애초에 없는가)을 알 수 없어
 * 사용자가 같은 조작을 반복한다. `action` 에 다음에 할 일을 적는다.
 */
export function Empty({ children, action }) {
  return (
    <div className="muted" style={{ fontSize: 12, padding: "8px 0" }}>
      {children}
      {action && <> — {action}</>}
    </div>
  );
}

export default Hint;
