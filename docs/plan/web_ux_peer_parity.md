# ③ 웹 UX 강화 — 유사회사 선정 skill↔web 패리티 명세

| 항목 | 내용 |
|------|------|
| **문서 ID** | SPEC-EXCEL-SKILL-002-③ |
| **상위 명세** | [skill_peer_selection_and_sheet_detail.md](skill_peer_selection_and_sheet_detail.md) §3 |
| **정본** | `backend/ingest/peer_selection.py`(`codes_from_seed_peers`·`select_peers`) · `reference/리포트예시_클래시스.md` §E |
| **작성일** | 2026-07-19 |
| **상태** | Draft → 구현 착수 |

---

## 0. 목표 — 패리티 갭 해소

skill `peer.py`는 **Step1a KSIC 역산**(`seed_peers` → `codes_from_seed_peers`)을 지원하는데, 웹 `/api/peer/select`·`PeerSheet.jsx`는 **산업코드 직접 입력만** 가능. 실무 정본(peer_selection.py §15 교정)은 "코드 2~3개를 rough 유사회사에서 역산"이 표준 → 웹도 이를 지원해야 skill과 동일 방법론.

**갭 목록**:
| 기능 | skill(peer.py) | web(현재) | ③ |
|---|---|---|---|
| Step1a KSIC 역산(seed_peers) | ✅ | ❌ | **API + PeerSheet 배선** |
| 확정 peer 5-10 rule | ✅ size_note | ✅ | — |
| 탈락 사유·퍼널·⚖️큐 | ✅ | ✅ | — |
| 베타포인트(상장연수) 근거 | 데이터만 | 입력만 | **탈락 사유에 표시(엔진이 이미 생성)** |

> 단일 엔진 원칙: 세 표면(skill·API·PeerSheet)이 `peer_selection.py` 하나를 소비 → 결과 동일. ③은 **입력 경로(seed_peers)만 웹에 노출**, 로직 신규 없음.

---

## 1. 백엔드 — `/api/peer/select` seed_peers 지원

`main.py` 핸들러에 `seed_peers` 처리 추가(로직은 `codes_from_seed_peers` 재사용):
```python
codes = set(d.get("target_industry_codes") or [])
if not codes and d.get("seed_peers"):
    from ingest.peer_selection import codes_from_seed_peers
    codes = codes_from_seed_peers([PeerCandidate(ticker=s["ticker"], name=s.get("name",""),
                                                 industry_code=s.get("industry_code")) for s in d["seed_peers"]])
codes = codes or None
```
응답에 `codes_used`(역산 결과) 추가 — 어떤 코드가 모집단에 쓰였는지 감사 추적.

---

## 2. 프론트 — `PeerSheet.jsx` seed_peers 입력

- **모집단 코드 확보 2경로 토글**:
  1. **직접 입력**(현행): KSIC 코드 콤마 구분.
  2. **역산(seed_peers)**: rough 유사회사(Ticker·KSIC) 입력 → 서버가 코드 union 산출.
- seed 후보는 **Research ⑦⑨ 경쟁사**가 시드(안내 문구). KSIC 미상 seed 는 `ksic/search`로 조회 보조(기존 KsicLookup 재사용).
- 결과 카드에 `codes_used` 표시("모집단 코드: 2710, 2711 (역산)").

**UX(색 통제·고밀도 유지, design_system 준수)**: 기존 4-step 카드 위에 "모집단 코드 확보" 섹션. 역산 모드면 seed 테이블(Ticker·회사·KSIC) + "코드 역산" 버튼. 산출 코드가 기존 `codes` 필드를 채움(이후 4-step 실행 동일).

---

## 3. 프론트 — 탈락 사유 명확화 (엔진 산출 노출)

- `dropped` 의 `dropped_at`(step1~4)·`reason`(코드불일치/저비중/베타포인트 부족/거래정지)을 스텝별 색으로 표시(현재 텍스트 나열 → 스텝 배지).
- 베타포인트: Step4 탈락 사유에 "상장 N년 < 2년(베타포인트 부족)"이 이미 엔진 reason 에 포함 → 그대로 표면화.

---

## 4. 범위 밖 (이번 ③ 제외 — 향후)

- **unlever 테이블 PeerSheet 통합**: 현재 `DiscountSheet`(WACC)가 담당. 이동은 UX 대수술이라 별도 사이클(패리티 핵심 아님 — skill Peer 시트는 통합, 웹은 분리 유지해도 방법론 동일).

---

## 5. 테스트

- `test_api.py`(또는 신규): `/api/peer/select` seed_peers → codes_used 역산·모집단 필터 정상.
- 프론트: 수동(로컬 웹) — seed 입력 → 코드 역산 → 4-step 실행 E2E.

---

## 6. 원칙

- **단일 엔진**: 로직 신규 0 — `codes_from_seed_peers`/`select_peers` 재사용, 웹은 입력 경로만 노출.
- **design_system 준수**: 버건디+웜뉴트럴·rounded-none·고밀도·색 통제.
- **판단 보조**: seed 는 rough(Research 경쟁사), 확정은 4-step 결정론 + Step2 판정.

---

## 7. 변경 이력

| 버전 | 날짜 | 변경 |
|------|------|------|
| 1.0 | 2026-07-19 | ③ 웹 패리티 명세 — seed_peers KSIC 역산(API+PeerSheet)·탈락사유 명확화. unlever 통합은 범위 밖 |
