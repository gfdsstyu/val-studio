import React, { useEffect, useMemo, useState } from "react";
import { api } from "../../api.js";
import TableTransfer from "../../TableTransfer.jsx";
import { Hint, Empty } from "../../Hint.jsx";

/* 3-0. 기업 스크리너 — peer **모집단 탐색**.
 *
 * `peer_selection` 4-step 퍼널은 Step1b(확정 코드로 풀 필터)부터 시작한다. 그 앞의
 * "후보를 눈으로 훑어 고르는" 단계가 없어서, 유사회사를 이미 알고 있어야만 쓸 수 있었다.
 *
 * 검색 대상에 **주요 제품**이 들어가는 게 핵심이다 — 실무 교정("KSIC 코드만으로 업종이
 * 완전히 갈리지 않아 코드 2~3개를 union")을 코드가 아니라 제품 문자열로 우회한다.
 * 여기서 고른 후보는 `peer_candidates` 로 저장돼 3.할인율 > 유사회사(Step2)로 넘어간다.
 *
 * DART 키가 필요 없다(FinanceDataReader 2콜로 만든 로컬 인덱스). 다만 시가총액이
 * 시변이라 `as_of` 를 항상 표시하고, 오래되면 갱신을 권한다.
 */

//: 시총 눈금(원) — 로그 스케일. 백엔드 MCAP_TICKS 와 같은 관행.
const TICKS = [
  ["0", 0], ["100억", 1e10], ["500억", 5e10],
  ["1천억", 1e11], ["5천억", 5e11], ["1조", 1e12], ["∞", null],
];
const MARKETS = ["KOSPI", "KOSDAQ", "KONEX"];
const SORTS = [["marcap_desc", "시총↓"], ["marcap_asc", "시총↑"],
  ["name", "회사명"], ["market", "시장"], ["industry", "업종"]];

const eok = (v) => (v == null ? "—" : `${Math.round(v / 1e8).toLocaleString("ko-KR")}억`);

export default function ScreenerSheet({ project, onSave }) {
  const saved = project?.data?.peer_candidates || [];
  const [q, setQ] = useState("");
  const [industry, setIndustry] = useState("");
  const [markets, setMarkets] = useState([]);
  const [lo, setLo] = useState(0);              // TICKS 인덱스
  const [hi, setHi] = useState(TICKS.length - 1);
  const [sort, setSort] = useState("marcap_desc");
  const [res, setRes] = useState(null);
  const [picked, setPicked] = useState(() => new Set(saved.map((p) => p.stock_code)));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const run = async (override = {}) => {
    setBusy(true); setErr(null);
    try {
      setRes(await api.screener({
        q, industry, markets, sort, limit: 100,
        mcap_min: TICKS[lo][1], mcap_max: TICKS[hi][1], ...override,
      }));
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  // 첫 진입 시 인덱스를 세워 업종 드롭다운을 채운다(빈 조건 = 전체).
  useEffect(() => { run(); /* eslint-disable-next-line */ }, []);

  const refresh = async () => {
    setBusy(true); setErr(null);
    try { await api.screenerRefresh(); await run(); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const rows = res?.rows || [];
  const toggle = (code) => {
    const next = new Set(picked);
    next.has(code) ? next.delete(code) : next.add(code);
    setPicked(next);
  };

  /** 선택 후보 → peer 퍼널 Step2 입력. corp_code 가 있어야 DART 로 이어진다. */
  const handOff = () => {
    const chosen = rows.filter((r) => picked.has(r.stock_code));
    const carry = saved.filter((p) => picked.has(p.stock_code)
      && !chosen.some((c) => c.stock_code === p.stock_code));
    onSave?.({ peer_candidates: [...carry, ...chosen].map((r) => ({
      stock_code: r.stock_code, name: r.name, corp_code: r.corp_code,
      market: r.market, industry: r.industry, products: r.products,
      marcap: r.marcap, listing_date: r.listing_date, settle_month: r.settle_month,
    })) });
  };

  const noCorp = useMemo(
    () => rows.filter((r) => picked.has(r.stock_code) && !r.corp_code).length, [rows, picked]);

  const tsv = () => [["회사", "종목코드", "고유번호", "시장", "업종", "주요제품", "시가총액(원)"],
    ...rows.map((r) => [r.name, r.stock_code, r.corp_code, r.market,
      r.industry, r.products, r.marcap ?? ""])];

  return (
    <div className="card">
      <h2>기업 스크리너 <span className="muted">— 유사회사 모집단 탐색(상장사)</span></h2>
      <div className="pad">
        {/* ── 조건 ─────────────────────────────────────────────── */}
        <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
          <div className="row" style={{ margin: 0, maxWidth: 260 }}>
            <label>검색어</label>
            <input type="text" value={q} onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && run()}
              placeholder="예: 미용의료기기" />
          </div>
          <div className="row" style={{ margin: 0, maxWidth: 260 }}>
            <label>업종</label>
            <select value={industry} onChange={(e) => { setIndustry(e.target.value); }}
              style={{ fontSize: 12 }}>
              <option value="">전체</option>
              {(res?.industries || []).map((s) => (
                <option key={s.name} value={s.name}>{s.name} ({s.count})</option>
              ))}
            </select>
          </div>
          <div className="row" style={{ margin: 0 }}>
            <label>시장</label>
            <span style={{ display: "flex", gap: 4 }}>
              {MARKETS.map((m) => (
                <button key={m} className={markets.includes(m) ? "primary xs" : "ghost xs"}
                  onClick={() => setMarkets(markets.includes(m)
                    ? markets.filter((x) => x !== m) : [...markets, m])}>{m}</button>
              ))}
            </span>
          </div>
          <button className="primary" onClick={() => run()} disabled={busy}>
            {busy ? "조회 중…" : "검색"}</button>
        </div>

        {/* 시총 범위 — 로그 눈금. 상·하한을 각각 고른다. */}
        <div style={{ display: "flex", gap: 8, alignItems: "center",
          marginTop: 8, flexWrap: "wrap" }}>
          <span className="muted" style={{ fontSize: 11 }}>시가총액</span>
          <select value={lo} onChange={(e) => setLo(Number(e.target.value))} style={{ fontSize: 12 }}>
            {TICKS.slice(0, -1).map(([l], i) => <option key={l} value={i}>{l}</option>)}
          </select>
          <b>~</b>
          <select value={hi} onChange={(e) => setHi(Number(e.target.value))} style={{ fontSize: 12 }}>
            {TICKS.map(([l], i) => i > 0 && <option key={l} value={i}>{l}</option>)}
          </select>
          <span className="muted" style={{ fontSize: 11 }}>· 정렬</span>
          <select value={sort} onChange={(e) => setSort(e.target.value)} style={{ fontSize: 12 }}>
            {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <Hint label="스크리너 규약">
            검색은 <b>명칭·종목코드·업종·주요 제품</b>을 함께 훑습니다 — 같은 업종코드라도
            제품이 다르면 유사회사가 아니기 때문입니다. 상장사만 수록되며(비상장 평가대상은
            공시자료 화면에서 직접 지정), DART 키 없이 동작합니다.
            시가총액은 조회 시점 값이라 <b>as_of</b> 를 확인하세요.
          </Hint>
        </div>

        {err && <div className="err" style={{ marginTop: 8 }}>{err}</div>}

        {/* ── 결과 ─────────────────────────────────────────────── */}
        {res && (
          <>
            <div className={`finding ${res.stale ? "warn" : "pass"}`} style={{ marginTop: 10 }}>
              총 <b>{res.total}</b>건
              {res.truncated && <> · 상위 {rows.length}건 표시 — 조건을 좁히세요</>}
              {" · "}유니버스 {res.universe.toLocaleString("ko-KR")}사
              {" · "}기준일 {res.as_of}
              {res.stale
                ? <> <b>({res.stale_days}일 경과 — 시가총액이 낡았습니다)</b>{" "}
                    <button className="ghost xs" onClick={refresh} disabled={busy}>갱신</button></>
                : <span className="muted"> (D+{res.stale_days ?? "?"})</span>}
            </div>

            {rows.length === 0 ? (
              <Empty action="검색어를 줄이거나 시총 범위를 넓혀 보세요">조건에 맞는 상장사가 없습니다</Empty>
            ) : (
              <>
                <div style={{ display: "flex", gap: 8, alignItems: "center",
                  margin: "8px 0", flexWrap: "wrap" }}>
                  <button className="primary" onClick={handOff} disabled={!picked.size}>
                    선택 {picked.size}사를 유사회사 후보로</button>
                  {noCorp > 0 && <span className="muted" style={{ fontSize: 11 }}>
                    ⚠ 선택 중 {noCorp}사는 고유번호 미연결 — DART 조회가 안 됩니다</span>}
                  <TableTransfer label="스크리너 결과" rows={tsv()}
                    hint={`${rows.length}행 · 기준일 ${res.as_of}`} />
                </div>
                <div style={{ overflowX: "auto", maxHeight: 460, overflowY: "auto" }}>
                  <table>
                    <thead><tr>
                      <th style={{ width: 30 }}></th><th>#</th>
                      <th style={{ textAlign: "left" }}>회사</th>
                      <th style={{ textAlign: "left" }}>업종 · 주요제품</th>
                      <th>시가총액</th>
                    </tr></thead>
                    <tbody>{rows.map((r, i) => (
                      <tr key={r.stock_code}>
                        <td><input type="checkbox" checked={picked.has(r.stock_code)}
                          onChange={() => toggle(r.stock_code)} /></td>
                        <td className="muted">{i + 1}</td>
                        <td style={{ textAlign: "left", fontSize: 12 }}>
                          <div><b>{r.name}</b></div>
                          <div className="muted" style={{ fontSize: 11 }}>
                            {r.stock_code} · {r.market}
                            {r.corp_code ? ` · ${r.corp_code}` : " · 고유번호 미연결"}
                            {r.listing_date && ` · 상장 ${r.listing_date.slice(0, 4)}`}
                            {r.settle_month && r.settle_month !== "12월" &&
                              <span style={{ color: "var(--warn)" }}> · {r.settle_month} 결산</span>}
                          </div>
                        </td>
                        <td style={{ textAlign: "left", fontSize: 12 }}>
                          <div>{r.industry || "—"}</div>
                          <div className="muted" style={{ fontSize: 11 }}>{r.products || "—"}</div>
                        </td>
                        <td style={{ textAlign: "right" }}>{eok(r.marcap)}</td>
                      </tr>))}
                    </tbody>
                  </table>
                </div>
                <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>
                  결산월이 12월이 아니면 비교 시 기간 정합을 확인하세요 · 상장연도는
                  베타 추정기간(유사회사 선정 Step4)에 쓰입니다.
                  {res.notes?.length > 0 && <> · {res.notes.join(" / ")}</>}
                </div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
