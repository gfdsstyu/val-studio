import React, { useMemo, useState } from "react";
import { api } from "../../api.js";
import { loadKey } from "../Byok.jsx";

/* 0-2. 공시자료 — 정기보고서 주요정보 5종 + 공시목록·원문 zip.
   재무 숫자(자료함의 fnlttSinglAcntAll)와 달리 여기는 구조·귀속 정보:
   개황(결산월) · 감사의견·KAM · 주식총수/최대주주(D7 게이트) · 타법인출자(NOA) · 배당.
   숫자는 콤마 문자열 원문 보존(감사추적) — 숫자화는 반영 버튼에서만 명시적으로. */

const TABS = [
  { id: "filings", label: "공시목록" },
  { id: "audit", label: "감사의견·KAM" },
  { id: "shares", label: "주식수·최대주주" },
  { id: "invest", label: "타법인 출자" },
  { id: "div", label: "배당" },
];
const REPRT = [["11011", "사업보고서"], ["11012", "반기"], ["11013", "1분기"], ["11014", "3분기"]];
const PBLNTF = [["", "전체"], ["A", "정기공시"], ["B", "주요사항"], ["F", "외부감사"], ["I", "거래소"]];

const num = (v) => { const n = Number(String(v ?? "").replace(/,/g, "")); return Number.isFinite(n) ? n : null; };
const fmt = (v) => { const n = num(v); return n == null ? (v || "—") : n.toLocaleString("ko-KR"); };
const ymd = (d) => d.toISOString().slice(0, 10).replace(/-/g, "");

export default function DisclosureSheet({ project, onSave }) {
  const saved = project?.data?.disclosure || {};
  const [corp, setCorp] = useState(saved.corp_code || project?.data?.dart_query?.corp_code || "");
  const [year, setYear] = useState(saved.year || project?.data?.dart_query?.year || "2023");
  const [reprt, setReprt] = useState(saved.reprt_code || "11011");
  const [q, setQ] = useState(project?.company || "");
  const [hits, setHits] = useState(null);
  const [tab, setTab] = useState("filings");
  const [pblntf, setPblntf] = useState("A");
  // 탭별 결과 — 저장분을 시드로(재방문 시 재호출 없이 표시).
  const [data, setData] = useState({
    company: saved.company || null, filings: saved.filings || null,
    audit: saved.audit || null, shares: saved.shares || null,
    invest: saved.invest || null, div: saved.div || null,
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const key = loadKey("dart");

  const patch = (k, v) => setData((d) => ({ ...d, [k]: v }));

  const guard = () => {
    if (!key) { setErr("BYOK 탭에서 DART API 키를 먼저 저장하세요."); return false; }
    if (!corp.trim()) { setErr("corp_code(8자리)를 입력하세요."); return false; }
    setErr(null); return true;
  };

  const searchCorp = async () => {
    if (!key || !q.trim()) return;
    setBusy(true); setErr(null);
    try { setHits((await api.dartCorpSearch(key, q.trim(), true)).results); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  // 개황 + 현재 탭 로드. 탭 전환 시 미로드분만 lazy 호출(일 20,000건 쿼터 절약).
  const loadTab = async (t) => {
    if (!guard()) return;
    const body = { corp_code: corp.trim(), bsns_year: year.trim(), reprt_code: reprt };
    setBusy(true);
    try {
      if (!data.company)
        patch("company", (await api.dartCompany(key, { corp_code: corp.trim() })).company);
      if (t === "filings" && !data.filings) {
        const end = new Date(); const bgn = new Date(end); bgn.setFullYear(end.getFullYear() - 1);
        const r = await api.dartFilings(key, { corp_code: corp.trim(), bgn_de: ymd(bgn),
          end_de: ymd(end), ...(pblntf ? { pblntf_ty: pblntf } : {}) });
        patch("filings", r.filings);
      }
      if (t === "audit" && !data.audit) patch("audit", (await api.dartAuditOpinion(key, body)).opinions);
      if (t === "shares" && !data.shares) {
        const r = await api.dartShares(key, body);
        patch("shares", { rows: r.shares.rows, holders: r.major_shareholders });
      }
      if (t === "invest" && !data.invest) patch("invest", (await api.dartInvestments(key, body)).investments);
      if (t === "div" && !data.div) patch("div", (await api.dartDividends(key, body)).dividends);
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const go = (t) => { setTab(t); loadTab(t); };
  const refetch = () => { patch(tab === "shares" ? "shares" : tab, null); setData((d) => ({ ...d, [tab]: null })); loadTab(tab); };

  const downloadZip = async (rcept) => {
    if (!guard()) return;
    setBusy(true);
    try {
      const b = await api.dartDocument(key, { rcept_no: rcept });
      const url = URL.createObjectURL(b);
      const a = document.createElement("a");
      a.href = url; a.download = `dart_${rcept}.zip`; a.click();
      URL.revokeObjectURL(url);
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const save = () => onSave?.({ disclosure: {
    corp_code: corp.trim(), year: year.trim(), reprt_code: reprt, ...data } });

  // ── D7 게이트: 발행 vs 유통 주식수 대조(보통주 우선 행) ──────────────────────
  const d7 = useMemo(() => {
    const rows = data.shares?.rows || [];
    const r = rows.find((x) => /보통주/.test(x.se || "")) || rows[0];
    if (!r) return null;
    const issued = num(r.now_to_isu_stock_totqy) ?? num(r.isu_stock_totqy);
    const distb = num(r.distb_stock_co);
    if (issued == null || distb == null || !issued) return { row: r, gap: null };
    return { row: r, issued, distb, gap: (issued - distb) / issued };
  }, [data.shares]);

  const pushShares = () => {
    if (!d7?.distb) return;
    const prev = project?.data?.dcf_input || {};
    onSave?.({ dcf_input: { ...prev, shares_outstanding: String(d7.distb) } });
  };

  const viewer = (rcept) => `https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${rcept}`;
  const co = data.company;

  return (
    <>
      {/* ── 회사·조회조건 + 개황 카드 ─────────────────────────────────── */}
      <div className="card">
        <h2>공시자료 조회 <span className="muted">— OpenDART 정기보고서 주요정보(BYOK 키)</span></h2>
        <div className="pad">
          {!key && <div className="finding warn">BYOK 탭에서 OpenDART API 키를 저장해야 조회됩니다.</div>}
          <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
            <div className="row" style={{ margin: 0, maxWidth: 220 }}><label>회사명 검색</label>
              <input type="text" value={q} onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && searchCorp()} placeholder="예: 삼성전자" /></div>
            <button className="ghost" onClick={searchCorp} disabled={busy}>검색</button>
            <div className="row" style={{ margin: 0 }}><label>corp_code</label>
              <input type="text" value={corp} onChange={(e) => setCorp(e.target.value)} style={{ width: 100 }} /></div>
            <div className="row" style={{ margin: 0 }}><label>사업연도</label>
              <input type="text" value={year} onChange={(e) => setYear(e.target.value)} style={{ width: 64 }} /></div>
            <div className="row" style={{ margin: 0 }}><label>보고서</label>
              <select value={reprt} onChange={(e) => setReprt(e.target.value)} style={{ fontSize: 12 }}>
                {REPRT.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></div>
            <button className="primary" onClick={() => loadTab(tab)} disabled={busy}>
              {busy ? "조회 중…" : "조회"}</button>
            <button className="ghost" onClick={save}>저장</button>
          </div>
          {hits && (
            <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>
              {hits.length ? hits.slice(0, 8).map((h) => (
                <button key={h.corp_code} className="ghost xs" style={{ margin: "2px 4px 2px 0" }}
                  onClick={() => { setCorp(h.corp_code); setHits(null); }}>
                  {h.corp_name}{h.stock_code ? `(${h.stock_code})` : ""}</button>
              )) : "검색 결과 없음"}</div>
          )}
          {err && <div className="err" style={{ marginTop: 8 }}>{err}</div>}
          {co && (
            <div className="finding pass" style={{ marginTop: 10 }}>
              <b>{co.corp_name}</b>{co.stock_code ? ` (${co.stock_code} · ${co.corp_cls_nm || ""})` : ""} ·
              대표 {co.ceo_nm || "—"} · 설립 {co.est_dt || "—"} ·
              <b> 결산월 {co.acc_mt || "?"}월</b>
              {co.acc_mt && co.acc_mt !== "12" &&
                <span style={{ color: "var(--warn)" }}> ⚠ 12월 결산 아님 — DCF 기간 정합 확인</span>}
              {co.induty_code && <span className="muted"> · 업종 {co.induty_code}</span>}
            </div>
          )}
        </div>
      </div>

      {/* ── 탭 본문 ──────────────────────────────────────────────────── */}
      <div className="card">
        <h2>
          {TABS.map((t) => (
            <button key={t.id} className={tab === t.id ? "primary xs" : "ghost xs"}
              style={{ marginRight: 6 }} onClick={() => go(t.id)}>{t.label}</button>
          ))}
          <button className="ghost xs" onClick={refetch} disabled={busy} title="현재 탭 다시 조회">↻</button>
        </h2>
        <div className="pad">

          {tab === "filings" && (
            <>
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
                <span className="muted" style={{ fontSize: 12 }}>최근 1년 ·</span>
                <select value={pblntf} onChange={(e) => { setPblntf(e.target.value); patch("filings", null); }}
                  style={{ fontSize: 12 }}>
                  {PBLNTF.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
                <span className="muted" style={{ fontSize: 11 }}>
                  원문 zip 은 사업의 내용·주석 텍스트 원본(EUC-KR XML) — 후속 주석 추출 파이프의 입력.</span>
              </div>
              {data.filings ? (
                <div style={{ overflowX: "auto" }}><table>
                  <thead><tr><th>접수일</th><th style={{ textAlign: "left" }}>보고서명</th>
                    <th>제출인</th><th>원문</th></tr></thead>
                  <tbody>{data.filings.map((f) => (
                    <tr key={f.rcept_no}>
                      <td>{f.rcept_dt}</td>
                      <td style={{ textAlign: "left" }}>
                        <a href={viewer(f.rcept_no)} target="_blank" rel="noreferrer">{f.report_nm}</a></td>
                      <td>{f.flr_nm}</td>
                      <td><button className="ghost xs" onClick={() => downloadZip(f.rcept_no)}>zip</button></td>
                    </tr>))}</tbody>
                </table></div>
              ) : <div className="muted">조회 버튼으로 공시목록을 불러옵니다.</div>}
            </>
          )}

          {tab === "audit" && (data.audit ? (
            <div style={{ overflowX: "auto" }}><table>
              <thead><tr><th>사업연도</th><th>감사인</th><th>감사의견</th>
                <th style={{ textAlign: "left" }}>강조사항</th>
                <th style={{ textAlign: "left" }}>핵심감사사항(KAM)</th></tr></thead>
              <tbody>{data.audit.map((r, i) => (
                <tr key={i}>
                  <td>{r.bsns_year}</td><td>{r.auditor || "—"}</td>
                  <td>{/적정/.test(r.opinion || "") ? r.opinion
                    : <b style={{ color: "var(--warn)" }}>{r.opinion || "—"}</b>}</td>
                  <td style={{ textAlign: "left", maxWidth: 260, fontSize: 12 }}>{r.emphasis || "—"}</td>
                  <td style={{ textAlign: "left", maxWidth: 320, fontSize: 12 }}>{r.kam || "—"}</td>
                </tr>))}</tbody>
            </table></div>
          ) : <div className="muted">감사인·감사의견·강조사항·KAM(사업보고서 3개년).</div>)}

          {tab === "shares" && (data.shares ? (
            <>
              {d7 && (
                <div className={`finding ${d7.gap != null && Math.abs(d7.gap) > 0.01 ? "warn" : "pass"}`}
                  style={{ marginBottom: 10 }}>
                  <b>D7 주식수 게이트</b> — 발행 {fmt(d7.issued)}주 vs 유통 {fmt(d7.distb)}주
                  {d7.gap != null && <> (자기주식 등 괴리 <b>{(d7.gap * 100).toFixed(1)}%</b>
                    {Math.abs(d7.gap) > 0.01 && " — 주당가치 분모 확인 필요"})</>}
                  {" "}<button className="ghost xs" onClick={pushShares} disabled={!d7.distb}
                    title="주당가치 분모 = 유통주식수(자기주식 제외)로 반영">
                    유통주식수를 DCF 입력에 반영</button>
                </div>
              )}
              <div style={{ overflowX: "auto" }}><table>
                <thead><tr><th>구분</th><th>발행총수</th><th>현재 발행주식수</th>
                  <th>자기주식</th><th>유통주식수</th></tr></thead>
                <tbody>{data.shares.rows.map((r, i) => (
                  <tr key={i}><td>{r.se}</td><td>{fmt(r.isu_stock_totqy)}</td>
                    <td>{fmt(r.now_to_isu_stock_totqy)}</td><td>{fmt(r.tesstk_co)}</td>
                    <td><b>{fmt(r.distb_stock_co)}</b></td></tr>))}</tbody>
              </table></div>
              <h3 style={{ margin: "14px 0 6px", fontSize: 13 }}>최대주주 현황</h3>
              <div style={{ overflowX: "auto" }}><table>
                <thead><tr><th>성명</th><th>관계</th><th>주식종류</th>
                  <th>기말 주식수</th><th>기말 지분율(%)</th></tr></thead>
                <tbody>{(data.shares.holders || []).map((h, i) => (
                  <tr key={i}><td>{h.name}</td><td>{h.relation || "—"}</td>
                    <td>{h.stock_kind || "—"}</td><td>{fmt(h.trmend_stock_co)}</td>
                    <td>{h.trmend_rate || "—"}</td></tr>))}</tbody>
              </table></div>
            </>
          ) : <div className="muted">발행/유통 주식수 대조(D7 게이트) + 최대주주 지분율.</div>)}

          {tab === "invest" && (data.invest ? (
            <>
              <div className="finding pass" style={{ marginBottom: 8 }}>
                기말 장부가액 합계 <b>{fmt(data.invest.reduce((s, r) => s + (num(r.trmend_book_amount) || 0), 0))}</b>
                <span className="muted"> — 비영업투자자산(NOA) 실측 시드. BS 매핑의 NOA 소계와 대조.</span></div>
              <div style={{ overflowX: "auto" }}><table>
                <thead><tr><th style={{ textAlign: "left" }}>법인명</th><th>출자목적</th>
                  <th>기말 장부가액</th><th>상대 총자산</th><th>상대 당기순손익</th></tr></thead>
                <tbody>{data.invest.map((r, i) => (
                  <tr key={i}><td style={{ textAlign: "left" }}>{r.corp_name}</td>
                    <td style={{ fontSize: 12 }}>{r.purpose || "—"}</td>
                    <td>{fmt(r.trmend_book_amount)}</td><td>{fmt(r.recent_total_asset)}</td>
                    <td>{fmt(r.recent_net_income)}</td></tr>))}</tbody>
              </table></div>
            </>
          ) : <div className="muted">타법인 출자현황 — 장부가액은 NOA 실측 시드.</div>)}

          {tab === "div" && (data.div ? (
            <div style={{ overflowX: "auto" }}><table>
              <thead><tr><th style={{ textAlign: "left" }}>구분</th><th>당기</th>
                <th>전기</th><th>전전기</th></tr></thead>
              <tbody>{data.div.map((r, i) => (
                <tr key={i}><td style={{ textAlign: "left" }}>{r.se}{r.stock_kind ? ` (${r.stock_kind})` : ""}</td>
                  <td>{fmt(r.thstrm)}</td><td>{fmt(r.frmtrm)}</td><td>{fmt(r.lwfr)}</td></tr>))}</tbody>
            </table></div>
          ) : <div className="muted">주당배당·배당성향·수익률(당기/전기/전전기).</div>)}

          <div className="muted" style={{ fontSize: 11, marginTop: 10 }}>
            출처: 금융감독원 OpenDART(정확성 무보증) · 조회값은 콤마 원문 보존(감사추적) ·
            분·반기 보고서는 간소화로 일부 항목이 빈 결과일 수 있습니다(status 013).</div>
        </div>
      </div>
    </>
  );
}
