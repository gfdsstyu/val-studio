import React, { useState } from "react";
import { api } from "../../api.js";
import { loadKey } from "../Byok.jsx";

/* 대상회사 선택 — DART 를 쓰는 모든 화면의 **단일 진입점**.
 *
 * 왜 공용인가: corp_code 입력이 자료함(다년도 FS·단년 FS)·공시자료·원가(직원현황) 네 군데에
 * 흩어져 있었고 검색도 세 벌로 중복돼 있었다. 각자 로컬 state 라 한 화면에서 회사를 찾아도
 * 다른 화면에서 또 검색·입력해야 했고, 애드인을 닫으면 그마저 사라졌다.
 * 여기서 고른 회사는 `project.data.dart_target` 에 **즉시 저장**되므로 전 화면이 공유하고
 * 재실행 후에도 남는다(조회까지 성공해야 저장되던 종전 `dart_query` 와 다른 점).
 *
 * ⚠️ 검색 필터로는 옳은 회사를 고를 수 없다 — **검증으로만 된다.**
 * 종전 세 화면은 `listed_only=true` 하드코딩이라 비상장 평가대상이 검색에서 사라졌다.
 * 그런데 필터를 걷어내도 문제가 남는다. 실측('비올'):
 *   01124398 (주)비올      설립 2009 · 비상장 · 정기공시 0건  ← 정확일치라 1순위
 *   01406618 (주)비올메디컬 설립 2019 · 335890 · 사업보고서 3건
 * 사업회사와 공시 법인이 분리돼 있어, 이름만 보면 앞의 것이 맞아 보이지만 **조회는 전부
 * 빈손**이 된다. 정렬(정확일치 > 상장 여부)이 하필 조회 불가 후보를 위로 올린다.
 * 그래서 필터를 되돌리는 대신(→ 비상장 평가대상이 다시 사라진다) **고르는 즉시
 * 사업보고서 존재를 확인**한다(`pick`). 필터는 보조 수단으로만 남긴다.
 */

/** 프로젝트에 확정된 대상회사. 구 키(dart_query·disclosure)도 읽어 하위호환. */
export function dartTarget(project) {
  const d = project?.data || {};
  if (d.dart_target?.corp_code) return d.dart_target;
  const legacy = d.dart_query?.corp_code || d.disclosure?.corp_code;
  return legacy ? { corp_code: legacy, corp_name: project?.company || "", stock_code: "" } : null;
}

export default function CompanyPicker({ project, onSave, label = "대상회사" }) {
  const target = dartTarget(project);
  const [open, setOpen] = useState(!target);
  const [q, setQ] = useState(project?.company || "");
  const [listedOnly, setListedOnly] = useState(false);
  const [hits, setHits] = useState(null);
  const [meta, setMeta] = useState(null);          // {total, truncated, by, limit}
  const [manual, setManual] = useState(target?.corp_code || "");
  const [check, setCheck] = useState(null);        // company-check 결과(공시 주체 판정)
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const key = loadKey("dart");

  /** 한 칸으로 3-way 검색 — 회사명 / 종목코드(6자리) / 고유번호(8자리).
   *
   * 축 판정은 서버(`by="auto"`)가 한다. 클라에서 정규식을 또 쓰면 두 곳이 갈라진다.
   * 축이 `corp`·`stock` 이고 후보가 하나면 곧바로 확정한다 — 코드로 찾았다는 건
   * 이미 대상을 특정했다는 뜻이라, 한 번 더 누르게 할 이유가 없다.
   */
  const search = async () => {
    if (!key) { setErr("BYOK 탭에서 OpenDART API 키를 먼저 저장하세요."); return; }
    if (!q.trim()) return;
    setBusy(true); setErr(null); setCheck(null);
    try {
      const r = await api.dartCorpSearch(key, q.trim(), listedOnly);
      setHits(r.results); setMeta(r);
      if (r.results.length === 1 && (r.by === "corp" || r.by === "stock")) {
        await pick(r.results[0]);
      }
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  /** 선택 = 확정 + **검증**.
   *
   * 회사명만으로는 조회 가능 여부를 알 수 없다. 실측: '비올'은 동명 후보가 둘인데
   * 사업회사 `01124398 (주)비올`(비상장)은 **정기공시 0건**이고 공시 의무는 상장사
   * `01406618 (주)비올메디컬`에 있다. 앞의 것을 고르면 이후 모든 조회가 빈손인데
   * 화면에는 '결과 없음'으로만 보여 원인을 알 수 없었다.
   * 그래서 고르는 즉시 사업보고서 존재를 확인해 알려준다. 막지는 않는다(판단은 사람) —
   * 다만 usable=false 면 후보 목록을 열어둬 바로 다른 후보로 갈아탈 수 있게 한다.
   */
  const pick = async (h) => {
    const target = { corp_code: h.corp_code, corp_name: h.corp_name,
                     stock_code: h.stock_code || "" };
    onSave?.({ dart_target: target });
    setErr(null); setCheck(null);
    if (!key) { setHits(null); setOpen(false); return; }
    setBusy(true);
    try {
      const v = await api.dartCompanyCheck(key, { corp_code: h.corp_code });
      setCheck(v);
      // 개황에서 정식 상호·상장코드를 받아 저장값을 보정한다(검색 인덱스가 낡을 수 있다).
      const co = v.company || {};
      if (co.corp_name) {
        onSave?.({ dart_target: { corp_code: h.corp_code,
                                  corp_name: co.corp_name,
                                  stock_code: co.stock_code || "" } });
      }
      if (v.usable) { setHits(null); setOpen(false); }
    } catch (e) {
      setErr(`확인 실패: ${e.message}`);
      setHits(null); setOpen(false);
    } finally { setBusy(false); }
  };

  const pickManual = () => {
    const code = manual.trim();
    if (!/^\d{8}$/.test(code)) { setErr("고유번호(corp_code)는 숫자 8자리입니다."); return; }
    pick({ corp_code: code, corp_name: "", stock_code: "" });
  };

  if (!open && target) {
    return (
      <div className={`finding ${check && !check.usable ? "warn" : "pass"}`}
        style={{ marginBottom: 10 }}>
        <b>{label}</b> — {target.corp_name || "(이름 미확인)"}
        {target.stock_code ? ` (${target.stock_code})` : " · 비상장"}
        {" · "}<code>{target.corp_code}</code>
        {check && (check.usable
          ? <span className="muted" style={{ fontSize: 11 }}>
              {" "}· 사업보고서 {check.annual_count}건 확인
              {check.latest_annual ? ` (최근 ${check.latest_annual.report_nm})` : ""}</span>
          : <b> · 최근 3년 사업보고서 0건 — 공시 주체가 아닐 수 있습니다</b>)}
        {" "}<button className="ghost xs" onClick={() => setOpen(true)}>변경</button>
        <span className="muted" style={{ fontSize: 11 }}>
          {" "}— 이 프로젝트의 DART 화면 전체가 이 회사를 씁니다.
        </span>
      </div>
    );
  }

  return (
    <div className="card" style={{ marginBottom: 10 }}>
      <div className="pad">
        <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
          <div className="row" style={{ margin: 0, maxWidth: 240 }}>
            <label>{label} 검색</label>
            <input type="text" value={q} onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && search()}
              placeholder="회사명 · 종목코드(6자리) · 고유번호(8자리)" />
          </div>
          <button className="primary" onClick={search} disabled={busy}>
            {busy ? "검색 중…" : "검색"}</button>
          <label className="muted" style={{ fontSize: 12, display: "flex", gap: 4, alignItems: "center" }}>
            <input type="checkbox" checked={listedOnly}
              onChange={(e) => { setListedOnly(e.target.checked); setHits(null); }} />
            상장사만
          </label>
          {target && <button className="ghost xs" onClick={() => setOpen(false)}>취소</button>}
        </div>
        <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
          비상장 평가대상도 검색됩니다(정확일치·상장사가 위로 정렬). 고르면 프로젝트에 바로
          저장되어 자료함·공시자료·원가 화면이 함께 씁니다.
          <br />
          <b>고르는 즉시 사업보고서 존재를 확인</b>합니다 — 같은 이름이라도 공시 주체가 아닌
          법인이 있어(사업회사 ↔ 상장 법인 분리) 잘못 고르면 이후 조회가 전부 빈손이 됩니다.
        </div>

        {hits && (
          <div style={{ marginTop: 8 }}>
            {hits.length ? (
              <>
                {/* 이름 옆 종목코드 배지 · 아래 고유번호 — 상장 여부가 한눈에 갈려야
                    '공시 주체가 아닌 동명 법인'을 고르는 사고가 줄어든다. */}
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {hits.map((h) => (
                    <button key={h.corp_code} className="ghost"
                      style={{ textAlign: "left", padding: "4px 8px", lineHeight: 1.3 }}
                      onClick={() => pick(h)} disabled={busy}>
                      <div style={{ fontSize: 13 }}>
                        {h.corp_name}
                        {h.stock_code
                          ? <span style={{ marginLeft: 6, fontSize: 11, opacity: 0.85 }}>
                              {h.stock_code}</span>
                          : <span className="muted" style={{ marginLeft: 6, fontSize: 11 }}>
                              비상장</span>}
                      </div>
                      <div className="muted" style={{ fontSize: 11 }}>{h.corp_code}</div>
                    </button>
                  ))}
                </div>
                {/* 절단을 숨기면 '결과가 이게 다'로 읽혀 엉뚱한 후보를 고르게 된다. */}
                <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>
                  총 {meta?.total ?? hits.length}건
                  {meta?.truncated && <b> · 상위 {meta.limit}건만 표시 — 검색어를 더 좁히세요</b>}
                  {meta?.by && meta.by !== "name" &&
                    <> · {meta.by === "corp" ? "고유번호" : "종목코드"}로 조회</>}
                </div>
              </>
            ) : (
              <span className="muted" style={{ fontSize: 12 }}>
                검색 결과 없음 — {listedOnly ? "'상장사만'을 해제해 보세요. " : ""}
                회사명은 일부만 넣어도 되고, 종목코드(6자리)·고유번호(8자리)도 됩니다.
              </span>
            )}
          </div>
        )}

        <div style={{ display: "flex", gap: 8, alignItems: "flex-end", marginTop: 10 }}>
          <div className="row" style={{ margin: 0 }}>
            <label>고유번호 직접 입력(8자리)</label>
            <input type="text" value={manual} onChange={(e) => setManual(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && pickManual()} style={{ width: 110 }} />
          </div>
          <button className="ghost" onClick={pickManual} disabled={busy}>
            {busy ? "확인 중…" : "이 코드로 확정"}</button>
        </div>

        {/* 검증 결과 — '고른 회사가 공시 주체인가'를 여기서 끝낸다.
            0건이면 후보 목록이 열린 채로 남아 바로 갈아탈 수 있다. */}
        {check && (
          <div className={`finding ${check.usable ? "pass" : "warn"}`} style={{ marginTop: 10 }}>
            <b>{check.company?.corp_name || check.corp_code}</b>
            {check.company?.stock_code ? ` (${check.company.stock_code})` : " · 비상장"}
            {check.company?.est_dt ? ` · 설립 ${check.company.est_dt}` : ""}
            {" — "}
            {check.usable
              ? <>최근 3년 사업보고서 <b>{check.annual_count}건</b>
                  {check.latest_annual && <> · 최근 {check.latest_annual.report_nm}
                    ({check.latest_annual.rcept_dt})</>}</>
              : <><b>정기공시 {check.filing_count}건 · 사업보고서 0건</b> —
                  이 법인은 공시 주체가 아닐 수 있습니다. 같은 이름의 상장 법인이 있으면
                  그쪽을 고르세요(예: 사업회사와 공시 법인이 분리된 경우).</>}
          </div>
        )}
        {err && <div className="err" style={{ marginTop: 8 }}>{err}</div>}
      </div>
    </div>
  );
}
