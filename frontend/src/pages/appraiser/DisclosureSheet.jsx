import React, { useMemo, useState } from "react";
import { api } from "../../api.js";
import { loadKey } from "../Byok.jsx";
import CompanyPicker, { dartTarget } from "./CompanyPicker.jsx";
import DocumentPanel from "./DocumentPanel.jsx";
import TableTransfer from "../../TableTransfer.jsx";
import { Hint, Empty } from "../../Hint.jsx";

/* 0-2. 공시자료 — 정기보고서 주요정보 5종 + 공시목록·원문 zip.
   재무 숫자(자료함의 fnlttSinglAcntAll)와 달리 여기는 구조·귀속 정보:
   개황(결산월) · 감사의견·KAM · 주식총수/최대주주(D7 게이트) · 타법인출자(NOA) · 배당.
   숫자는 콤마 문자열 원문 보존(감사추적) — 숫자화는 반영 버튼에서만 명시적으로. */

const TABS = [
  { id: "filings", label: "공시목록" },
  // 원문 파싱 — 주석 본문·계정↔주석번호는 재무 API 로 못 얻고 원문에만 있다.
  { id: "doc", label: "원문·주석" },
  { id: "audit", label: "감사의견·KAM" },
  { id: "shares", label: "주식수·최대주주" },
  { id: "invest", label: "타법인 출자" },
  { id: "div", label: "배당" },
];
const REPRT = [["11011", "사업보고서"], ["11012", "반기"], ["11013", "1분기"], ["11014", "3분기"]];
const PBLNTF = [["", "전체"], ["A", "정기공시"], ["B", "주요사항"], ["F", "외부감사"], ["I", "거래소"]];

const num = (v) => { const n = Number(String(v ?? "").replace(/,/g, "")); return Number.isFinite(n) ? n : null; };
const fmt = (v) => { const n = num(v); return n == null ? (v || "—") : n.toLocaleString("ko-KR"); };
/* 날짜는 **문자열(YYYY-MM-DD)로만** 다룬다 — 입력칸도 DART 도 그 형태를 원한다.
   ⚠️ Date 로 왕복시키면 하루가 밀린다: `new Date("2026-08-04T00:00:00")` 은 KST 자정이고
   `toISOString()` 이 UTC 로 바꿔 2026-08-03T15:00Z → slice(0,10)="2026-08-03".
   입력칸 값이 되먹임되므로 **고칠 때마다 하루씩 더 밀리는** 형태였다(실측). */
const localISO = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const ymd = (s) => String(s).replace(/-/g, "");     // "2026-08-04" → "20260804"
//: 조회기간 프리셋 — [라벨, 개월수]. 사업보고서(연 1회)는 3년이면 3건이 잡힌다.
const PERIOD_PRESETS = [["1개월", 1], ["3개월", 3], ["6개월", 6],
  ["1년", 12], ["3년", 36], ["5년", 60], ["10년", 120]];

export default function DisclosureSheet({ project, onSave }) {
  const saved = project?.data?.disclosure || {};
  // 대상회사는 프로젝트 단일값(CompanyPicker) — 화면마다 다시 찾지 않는다.
  const target = dartTarget(project);
  const corp = target?.corp_code || "";
  const [year, setYear] = useState(saved.year || project?.data?.dart_query?.year || "2023");
  const [reprt, setReprt] = useState(saved.reprt_code || "11011");
  const [tab, setTab] = useState("filings");
  const [pblntf, setPblntf] = useState("A");
  /* 공시목록 조회기간 — 종전 '최근 1년' 하드코딩은 **사업보고서를 놓치는 결함**이었다.
     사업보고서는 이듬해 3월 제출이라, 조회 시점에 따라 창 밖으로 나간다.
     기본 3년(사업보고서 3건 확보) + 프리셋. `ymd()` 는 YYYYMMDD 문자열. */
  const [range, setRange] = useState(() => {
    const end = new Date(); const bgn = new Date(end);
    bgn.setFullYear(end.getFullYear() - 3);
    return { bgn: localISO(bgn), end: localISO(end) };   // 문자열로만 보관
  });
  // 공시목록에서 '파싱'을 누르면 접수번호를 원문 탭으로 넘긴다(탭 간 손입력 제거).
  const [pendingRcept, setPendingRcept] = useState("");
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
    if (!corp) { setErr("위에서 대상회사를 먼저 선택하세요."); return false; }
    setErr(null); return true;
  };

  // 개황 + 현재 탭 로드. 탭 전환 시 미로드분만 lazy 호출(일 20,000건 쿼터 절약).
  const loadTab = async (t) => {
    if (!guard()) return;
    const body = { corp_code: corp, bsns_year: year.trim(), reprt_code: reprt };
    setBusy(true);
    try {
      if (!data.company) {
        const r = await api.dartCompany(key, { corp_code: corp });
        // 라벨·순서는 서버가 정본 — 값과 함께 받아 둔다(프론트 복제 금지).
        setData((s) => ({ ...s, company: r.company,
          company_labels: r.labels, company_url_fields: r.url_fields }));
      }
      if (t === "filings" && !data.filings) {
        const r = await api.dartFilings(key, { corp_code: corp,
          bgn_de: ymd(range.bgn), end_de: ymd(range.end),
          ...(pblntf ? { pblntf_ty: pblntf } : {}) });
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

  /** 프리셋/직접입력으로 기간을 바꾸면 캐시를 버린다 — 안 버리면 옛 결과가 남아
      기간을 넓혔는데 화면이 그대로인 것처럼 보인다. */
  const setPreset = (months) => {
    const end = new Date(); const bgn = new Date(end);
    bgn.setMonth(end.getMonth() - months);
    setRange({ bgn: localISO(bgn), end: localISO(end) }); patch("filings", null);
  };
  // 입력칸 값이 이미 YYYY-MM-DD 다 — Date 로 바꾸지 않고 그대로 보관한다.
  const setRangeAt = (which, value) => {
    if (!value) return;
    setRange((r) => ({ ...r, [which]: value }));
    patch("filings", null);
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
    corp_code: corp, year: year.trim(), reprt_code: reprt, ...data } });

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

  /* 개황 라벨·순서는 **백엔드 응답의 labels** 를 정본으로 쓴다(프론트에 복제하면
     필드가 늘 때 화면만 낡는다). 저장분에는 labels 가 없을 수 있어 폴백을 둔다. */
  const labels = data.company_labels || {};
  const urlFields = data.company_url_fields || [];
  const labelToKey = useMemo(
    () => Object.fromEntries(Object.entries(labels).map(([k, l]) => [l, k])), [data.company_labels]);
  const companyRows = useMemo(() => {
    if (!co) return [];
    const keys = Object.keys(labels).length ? Object.keys(labels) : Object.keys(co);
    return keys
      .filter((k) => k !== "corp_cls")            // 코드 대신 corp_cls_nm 로 보여준다
      .map((k) => [labels[k] || k, co[k] || "—"])
      .concat(co.corp_cls_nm ? [["상장시장", co.corp_cls_nm]] : []);
  }, [co, data.company_labels]);

  /** DART 는 스킴 없는 URL(`www.samsung.com/sec`)을 준다 — 그대로 쓰면 상대경로로 깨진다. */
  const href = (u) => (/^https?:\/\//i.test(u) ? u : `https://${u}`);

  return (
    <>
      {/* ── 회사·조회조건 + 개황 카드 ─────────────────────────────────── */}
      <div className="card">
        <h2>공시자료 조회 <span className="muted">— OpenDART 정기보고서 주요정보(BYOK 키)</span></h2>
        <div className="pad">
          {!key && <div className="finding warn">BYOK 탭에서 OpenDART API 키를 저장해야 조회됩니다.</div>}
          <CompanyPicker project={project} onSave={onSave} />
          <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
            <div className="row" style={{ margin: 0 }}><label>사업연도</label>
              <input type="text" value={year} onChange={(e) => setYear(e.target.value)} style={{ width: 64 }} /></div>
            <div className="row" style={{ margin: 0 }}><label>보고서</label>
              <select value={reprt} onChange={(e) => setReprt(e.target.value)} style={{ fontSize: 12 }}>
                {REPRT.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></div>
            <button className="primary" onClick={() => loadTab(tab)} disabled={busy}>
              {busy ? "조회 중…" : "조회"}</button>
            <button className="ghost" onClick={save}>저장</button>
          </div>
          {err && <div className="err" style={{ marginTop: 8 }}>{err}</div>}
          {co && (
            <>
              {/* 한 줄 요약 — DCF 기간 정합(결산월)만 즉시 눈에 띄면 된다. */}
              <div className="finding pass" style={{ marginTop: 10 }}>
                <b>{co.corp_name}</b>{co.stock_code ? ` (${co.stock_code} · ${co.corp_cls_nm || ""})` : ""} ·
                대표 {co.ceo_nm || "—"} · 설립 {co.est_dt || "—"} ·
                <b> 결산월 {co.acc_mt || "?"}월</b>
                {co.acc_mt && co.acc_mt !== "12" &&
                  <span style={{ color: "var(--warn)" }}> ⚠ 12월 결산 아님 — DCF 기간 정합 확인</span>}
              </div>
              {/* 전량 표시 — 백엔드가 이미 수집하던 필드를 화면이 6개만 보여주고 있었다.
                  특히 홈페이지·IR사이트는 자료 수집 동선에 직결된다. */}
              <details style={{ marginTop: 6 }} open>
                <summary style={{ cursor: "pointer", fontSize: 13 }}>
                  기업 개황 전체 <span className="muted">— DART 공시 기준</span></summary>
                <div style={{ display: "flex", gap: 8, alignItems: "center", margin: "6px 0" }}>
                  <TableTransfer label="기업 개황" rows={companyRows}
                    hint="라벨·값 2열 — 조서에 그대로 붙일 수 있습니다" />
                </div>
                <table><tbody>
                  {companyRows.map(([k, v], i) => (
                    <tr key={i}>
                      <th style={{ textAlign: "left", width: 130 }}>{k}</th>
                      <td style={{ textAlign: "left" }}>
                        {urlFields.includes(labelToKey[k]) && v && v !== "—"
                          ? <a href={href(v)} target="_blank" rel="noreferrer">{v}</a>
                          : v}
                      </td>
                    </tr>
                  ))}
                  <tr><th style={{ textAlign: "left" }}>고유번호</th>
                    <td style={{ textAlign: "left" }}><code>{corp}</code></td></tr>
                </tbody></table>
              </details>
            </>
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
              <div style={{ display: "flex", gap: 8, alignItems: "center",
                marginBottom: 6, flexWrap: "wrap" }}>
                <input type="date" value={range.bgn} style={{ fontSize: 12 }}
                  onChange={(e) => setRangeAt("bgn", e.target.value)} aria-label="조회 시작일" />
                <b>~</b>
                <input type="date" value={range.end} style={{ fontSize: 12 }}
                  onChange={(e) => setRangeAt("end", e.target.value)} aria-label="조회 종료일" />
                <select value={pblntf} onChange={(e) => { setPblntf(e.target.value); patch("filings", null); }}
                  style={{ fontSize: 12 }}>
                  {PBLNTF.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
                <button className="ghost xs" onClick={() => { patch("filings", null); loadTab("filings"); }}
                  disabled={busy}>다시 조회</button>
              </div>
              <div style={{ display: "flex", gap: 6, alignItems: "center",
                marginBottom: 8, flexWrap: "wrap" }}>
                <span className="muted" style={{ fontSize: 11 }}>기간</span>
                {PERIOD_PRESETS.map(([label, months]) => (
                  <button key={label} className="ghost xs" onClick={() => setPreset(months)}>
                    {label}</button>
                ))}
                <Hint label="기간·원문 규약">
                  사업보고서는 이듬해 3월 제출이라 기간이 짧으면 창 밖으로 나갑니다(기본 3년).
                  원문 zip 은 재무제표·주석 원본(UTF-8 XML)이고, <b>파싱</b>은 그걸 서버가
                  구조화해 본표·주석·계정↔주석 매핑·정합성까지 돌려줍니다.
                </Hint>
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
                      <td style={{ whiteSpace: "nowrap" }}>
                        <button className="ghost xs" onClick={() => downloadZip(f.rcept_no)}>zip</button>{" "}
                        <button className="ghost xs" title="원문을 서버에서 구조화(재무제표+주석)"
                          onClick={() => { setPendingRcept(f.rcept_no); setTab("doc"); }}>파싱</button>
                      </td>
                    </tr>))}</tbody>
                </table></div>
              ) : <Empty action="위 기간·공시유형을 정하고 '다시 조회'를 누르세요">아직 조회하지 않았습니다</Empty>}
            </>
          )}

          {tab === "doc" && (
            <DocumentPanel project={project} onSave={onSave}
              filings={data.filings} initialRcept={pendingRcept} />
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
          ) : <Empty action="사업연도·보고서를 확인하고 '조회'를 누르세요">감사인·감사의견·강조사항·KAM(사업보고서 3개년)을 가져옵니다</Empty>)}

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
          ) : <Empty action="'조회'를 누르면 D7 주식수 게이트가 자동 계산됩니다">발행/유통 주식수 대조 + 최대주주 지분율을 가져옵니다</Empty>)}

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
          ) : <Empty action="'조회'를 누르세요 — 장부가액 합계가 BS 의 NOA 소계와 대조됩니다">타법인 출자현황을 가져옵니다</Empty>)}

          {tab === "div" && (data.div ? (
            <div style={{ overflowX: "auto" }}><table>
              <thead><tr><th style={{ textAlign: "left" }}>구분</th><th>당기</th>
                <th>전기</th><th>전전기</th></tr></thead>
              <tbody>{data.div.map((r, i) => (
                <tr key={i}><td style={{ textAlign: "left" }}>{r.se}{r.stock_kind ? ` (${r.stock_kind})` : ""}</td>
                  <td>{fmt(r.thstrm)}</td><td>{fmt(r.frmtrm)}</td><td>{fmt(r.lwfr)}</td></tr>))}</tbody>
            </table></div>
          ) : <Empty action="'조회'를 누르세요">주당배당·배당성향·수익률(당기/전기/전전기)을 가져옵니다</Empty>)}

          <div className="muted" style={{ fontSize: 11, marginTop: 10 }}>
            출처: 금융감독원 OpenDART(정확성 무보증) · 조회값은 콤마 원문 보존(감사추적) ·
            분·반기 보고서는 간소화로 일부 항목이 빈 결과일 수 있습니다(status 013).</div>
        </div>
      </div>
    </>
  );
}
