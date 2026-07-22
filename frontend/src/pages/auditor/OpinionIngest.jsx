import React, { useState } from "react";
import { api, fileToBase64 } from "../../api.js";

/* 감사인 1. 의견서 인제스트 — 외부평가의견서에서 유의적 가정 후보 추출.

   ISA 540 대응: 경영진(평가자)이 사용한 유의적 가정·방법·데이터를 감사인이 식별하는
   단계. 추출은 결정론(고정양식 앵커 — `WACC = Ke`·`(1+B)`·Size Risk Premium·iso4217)
   이고, **확정은 감사인 판단**이다. 한글 라벨이 CID 로 깨져도 영문·수식 앵커는 살아남는
   전제이므로, 뽑힌 값은 confidence 와 함께 후보로만 제시한다. */

function FileSheet({ project, onSave }) {
  const [text, setText] = useState(project?.data?.opinion_text || "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [out, setOut] = useState(project?.data?.opinion_extract || null);

  const run = async (body) => {
    setBusy(true); setErr(null);
    try {
      const d = await api.opinionExtract(body);
      setOut(d);
      onSave?.({ opinion_extract: d, ...(body.text ? { opinion_text: body.text } : {}) });
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const onPdf = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    run({ pdf_b64: await fileToBase64(f) });
  };

  return (
    <>
      <div className="card">
        <h2>의견서 투입 <span className="muted">— 텍스트 붙여넣기 또는 PDF</span></h2>
        <div className="pad">
          <div className="muted" style={{ marginBottom: 10 }}>
            평가자가 제출한 외부평가의견서를 투입합니다. PDF 는 로컬에 pdftotext 가
            있을 때만 직접 읽히며, 없으면 의견서 텍스트를 복사해 붙여넣으세요
            (DART PDF 는 한글이 CID 로 깨질 수 있어 신뢰도를 함께 표기합니다).
          </div>
          <textarea rows={10} style={{ width: "100%" }} value={text}
            placeholder="의견서 텍스트를 붙여넣으세요…"
            onChange={(e) => setText(e.target.value)} />
          <div className="row" style={{ gap: 16, marginTop: 10 }}>
            <button className="primary" disabled={busy || !text.trim()}
              onClick={() => run({ text })}>
              {busy ? "추출 중…" : "가정 추출"}
            </button>
            <label>PDF 업로드 <input type="file" accept=".pdf" onChange={onPdf} /></label>
          </div>
          {err && <div className="err" style={{ marginTop: 10 }}>{err}</div>}
        </div>
      </div>
      {out && <ExtractCard out={out} />}
    </>
  );
}

function ExtractCard({ out }) {
  const pct = (v) => `${(v * 100).toFixed(2)}%`;
  return (
    <div className="card">
      <h2>추출된 유의적 가정 <span className="muted">— 후보(감사인 확정 필요)</span></h2>
      <div className="pad">
        <table>
          <tbody>
            <tr><th>평가대상 개수</th>
              <td>{out.entity_count} {out.is_sotp && <b>— SOTP(다개체) 의심</b>}</td></tr>
            <tr><th>영구성장률 후보</th>
              <td>{out.terminal_growths?.length
                ? out.terminal_growths.map(pct).join(", ")
                : <span className="muted">앵커 실패 — 수기 입력 필요</span>}</td></tr>
            <tr><th>규모프리미엄 후보</th>
              <td>{out.size_premiums?.length
                ? out.size_premiums.map(pct).join(", ")
                : <span className="muted">미검출</span>}</td></tr>
            <tr><th>통화</th><td>{out.currencies?.join(", ") || "-"}</td></tr>
            <tr><th>추출 신뢰도</th>
              <td className={out.confidence < 0.6 ? "warn" : "ok"}>
                {out.confidence} {out.confidence < 0.6 && "— 한글 CID 손실 의심"}
              </td></tr>
          </tbody>
        </table>
        {out.note && <div className="warn-box" style={{ marginTop: 10 }}>{out.note}</div>}
        <div className="muted" style={{ marginTop: 10 }}>
          다음: <b>2. 독립 재계산 › 입력 재구성</b> 에서 이 가정과 재무제표로 감사인의
          독립 추정치를 세웁니다.
        </div>
      </div>
    </div>
  );
}

function ExtractedSheet({ project }) {
  const out = project?.data?.opinion_extract;
  if (!out)
    return (
      <div className="card"><div className="pad muted">
        먼저 <b>1. 의견서 인제스트 › 의견서 투입</b> 에서 의견서를 투입하세요.
      </div></div>
    );
  return <ExtractCard out={out} />;
}

export default function OpinionIngest({ project, sheet, onSave }) {
  return sheet === "extracted"
    ? <ExtractedSheet project={project} />
    : <FileSheet project={project} onSave={onSave} />;
}
