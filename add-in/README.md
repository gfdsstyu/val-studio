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

1. https://excel.office.com → 새 통합 문서
2. **삽입 → 추가 기능(Office Add-ins) → 내 추가 기능 → 내 추가 기능 업로드**
3. `add-in/manifest.xml` 선택 → 업로드
4. 리본/작업창에 "Val-Studio DCF" Task Pane 로드 확인
   - 빈 화면이면: F12 콘솔 확인 → 대개 SourceLocation 오타·mixed content(https 필수)
   - manifest 캐시가 남으면: 다른 새 통합 문서에서 재시도(Office 캐시 수 분 지연 있음)

### B. Excel Desktop (Microsoft 365)

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

## 남은 것 (v1.2+)

- Office.js Range 읽기/쓰기 (`ReadDocument` → `ReadWriteDocument` 상향) — PRD FR-M4
- Cloud Run URL 이 바뀌는 경우(커스텀 도메인): manifest 3곳(SourceLocation·AppDomain·아이콘) 동시 교체, GUID 는 유지
