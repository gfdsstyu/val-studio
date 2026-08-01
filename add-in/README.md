# Val-Studio DCF — Excel Add-in (Task Pane) sideload·배포 runbook

Add-in 본체는 **웹 페이지**다(우리 HTTPS 앱 `?embed=1`). manifest 는 "Task Pane URL =
우리 앱"을 Excel 에 등록하는 얇은 파일. 상세 설계: [../docs/prd_excel_addin.md](../docs/prd_excel_addin.md).

## 파일

| 파일 | 용도 |
|------|------|
| `manifest.xml` | **Prod — Cloud Run 실주소 결선 완료(2026-08-01)**: `https://val-studio-789315789234.asia-northeast3.run.app/?embed=1` |
| `manifest.dev.xml` | 로컬 단일 프로세스(`http://localhost:8000` — uvicorn 이 dist 정적 서빙) |
| `manifest.staging.xml` | Vite HTTPS dev(`https://localhost:5173`) |

## 결선 상태 (사전조건 체크 — 전부 실측 확인됨)

- [x] `<Id>` GUID 프로덕션 고정값(`fad3c5ee-…`) — dev 와 별도 GUID 로 공존
- [x] SourceLocation·AppDomain·아이콘 URL → Cloud Run 실주소 치환
- [x] `GET /api/health` → `{"ok":true,"engine":"calc_core","mode":"local-byok"}` (2026-08-01)
- [x] `/logo.png`·`/logo@2x.png` → 200 image/png (frontend/public → dist 정적 서빙)
- [x] `/?embed=1` → 200, SPA 로드(LNB 숨김·헤더 드롭다운 — FR-M2.7)
- [x] 앱·API 동일 오리진(단일 컨테이너) → 프로덕션 CORS 설정 자체가 불요

## sideload 검증 절차 — 3경로 (쉬운 순)

### A. Excel Online 개인 업로드 (관리자 불요 — 최속, 여기부터)

⚠️ 경로가 **삽입 탭이 아니라 홈 탭**이다(구 UI 는 삽입 → Office 추가 기능이었으나 개편됨
— 공식 sideload 문서 2025-12 기준).

1. https://office.com → Excel → **새 통합 문서 생성**(시작 화면이 아니라 편집 화면이어야 리본에 버튼이 있다)
2. **홈(Home) 탭 → 오른쪽 끝 "추가 기능(Add-ins)"**(퍼즐 아이콘) → 패널 하단 **"더 많은 설정(More Settings)"**
3. "Office 추가 기능" 대화상자에서 **"내 추가 기능 업로드(Upload My Add-in)"** → `add-in/manifest.xml` 업로드
4. 리본/작업창에 "Val-Studio DCF" Task Pane 로드 확인
   - 빈 화면이면: F12 콘솔 확인 → 대개 SourceLocation 오타·mixed content(https 필수)
   - 사이드로드는 **브라우저 localStorage 저장** — 캐시 삭제·브라우저 변경 시 재업로드 필요
   - "추가 기능" 버튼 자체가 없으면: ①문서 편집 모드인지 ②조직 계정이면 관리자의 스토어
     차단 여부(개인 Microsoft 계정으로 우회 테스트 가능) ③삽입 탭(구 UI) 순으로 확인

### B. Excel Desktop (Microsoft 365)

같은 manifest·같은 GUID 가 그대로 동작한다(이식 불요 — Add-in 본체는 호스팅된 웹 페이지).
⚠️ 요건: **M365 구독 데스크톱**(Task Pane = Edge WebView2/Chromium). 영구 라이선스
2016/2019 는 구형 IE 엔진이라 React 빌드(ES2020)가 미지원. 데스크톱 장점: Task Pane
여러 개 병렬 도킹(Claude for Excel 과 동시 표시), 등록이 영구적(웹은 localStorage 휘발).
BYOK 키는 WebView2 저장소가 브라우저와 별개라 데스크톱 패널에서 1회 재입력.

- 방법 1(공유 폴더): 임의 폴더를 네트워크 공유 → Excel 옵션 → 보안 센터 → 보안 센터 설정
  → **신뢰할 수 있는 추가 기능 카탈로그**에 공유 경로 등록·"메뉴에 표시" 체크 → Excel 재시작
  → 삽입 → 내 추가 기능 → **공유 폴더** 탭 → Val-Studio DCF
- 방법 2(CLI, Node 필요): `npx office-addin-debugging start add-in/manifest.xml desktop`
  (Excel 자동 실행·sideload; 종료는 `npx office-addin-debugging stop add-in/manifest.xml`)

### C. 사내 M365 관리 센터 (테넌트 배포 — MVP 이후)

1. 관리 센터 → 설정 → **통합 앱** → 사용자 지정 앱 업로드 → manifest 업로드/URL
2. 배포 대상 사용자 지정 → 동의 → 최대 수 시간 전파 대기

### (선택) manifest 스키마 사전 검증

```bash
npx office-addin-manifest validate add-in/manifest.xml
```

## 로컬 개발 sideload

```bash
# 단일 프로세스(권장): dist 빌드 후 uvicorn 이 API+정적 동시 서빙 → manifest.dev.xml
cd frontend && npm run build && cd ..
py -3.12 -m uvicorn backend.api.main:app --port 8000
# Excel Online 개인 업로드는 https 필수 → dev 는 Desktop 공유폴더/CLI 경로 사용
# Vite HMR 로 UI 작업 시: vite.config.js server.https 켠 뒤 manifest.staging.xml
```

## 검증 (Definition of Done — PRD §13.1)

- [ ] **A 경로**: Excel Online 에서 Task Pane 로드
- [ ] **B 경로**: Excel Desktop(M365)에서 동일 manifest 동작
- [ ] Task Pane 에서 프로젝트 생성 → 데모 골든 케이스(비올) 열기 → DCF 계산
- [ ] 주당가치 **8,413.38원**(±1e-6)·EV·findings·민감도(3×3) 표시 확인
- [ ] TV 비중 WARN 등 `audit_dcf` findings 노출
- [ ] BYOK: 키 없이 골든 데모 동작 / DART 패널은 키 안내 배너 표시
- [ ] (보안) 키가 서버 로그에 남지 않음 — Cloud Run 로그에서 `X-Dart-Key` 등 부재 확인

## CORS 주의 (참고)

Task Pane fetch 의 Origin 은 `SourceLocation` 도메인(우리 앱)이지 `excel.office.com` 이
아니다. 현재는 앱·API 가 **동일 오리진**이라 CORS 이슈 자체가 없다. 커스텀 도메인 분리
시에만 FastAPI `allow_origins` 재검토. 상세: PRD §10.3.

## v1.2 — 현재 워크북 직접 검증 (2026-08-01)

Task Pane 안(5.산출물 export·diff·audit)에 **"현재 워크북 …" 버튼**이 추가됐다:
`Document.getFileAsync` 로 열려 있는 워크북 바이트를 그대로 `/api/xlsx/audit·import·diff`
에 태운다 — **다운로드→업로드 셔틀 불요**. 일반 웹(비 embed)에서는 버튼이 안 보인다.
설계 근거: [../docs/plan/addin_two_panel_ux.md](../docs/plan/addin_two_panel_ux.md).

⚠️ **권한이 ReadDocument → ReadWriteDocument 로 상향**됐다 — 기존 sideload 사용자는
manifest 를 **다시 업로드**해야 한다(A경로 재수행; 사이드로드는 브라우저 localStorage
저장이라 이전 등록이 새 권한을 모른다).

## 남은 것 (v1.2 잔여+)

- Office.js Range 쓰기: DART 숫자→`r_DART` 시트 주입·KPI 결과 기록 (PRD FR-M4.2/M4.3)
- 패널 DART 결과 "TSV 복사" 버튼 (Office.js 불요 경로)
- 웹 엑셀 Task Pane 2개 동시 표시 여부 실측 (addin_two_panel_ux.md §4-④)
- Cloud Run URL 이 바뀌는 경우(커스텀 도메인): manifest 3곳(SourceLocation·AppDomain·아이콘) 동시 교체, GUID 는 유지
