# Val-Studio DCF — Excel Add-in (Task Pane) sideload·배포 runbook

Add-in 본체는 **웹 페이지**다(우리 HTTPS 앱 `?embed=1`). manifest 는 "Task Pane URL =
우리 앱"을 Excel 에 등록하는 얇은 파일. 상세 설계: [../docs/prd_excel_addin.md](../docs/prd_excel_addin.md).

## 파일

| 파일 | 용도 |
|------|------|
| `manifest.xml` | Prod (app.example.com — 배포 시 도메인·GUID 치환) |
| `manifest.staging.xml` | 로컬 dev(localhost:5173) / 테스트 테넌트 |

## 배포 전 필수 치환

1. **`<Id>` GUID**: `00000000-...` → 실제 GUID(예: `uuidgen` / PowerShell `[guid]::NewGuid()`). **배포 후 변경 금지**(같은 앱 식별자).
2. **URL**: `app.example.com`·`api.example.com` → 실제 프론트·API 도메인. staging 은 localhost.
3. **아이콘**: `logo.png`·`logo@2x.png` 를 해당 도메인에 배치.

## 로컬 sideload (개발)

전제: 프론트가 **HTTPS**로 떠야 한다(Office dev certs). Vite dev 를 https 로:
```bash
# frontend/vite.config.js 에 server.https 설정 후
cd frontend && npm run dev   # https://localhost:5173
# API
py -3.12 -m uvicorn backend.api.main:app --reload
```
그다음:
```bash
npx office-addin-debugging start add-in/manifest.staging.xml
```
Excel 이 열리며 리본에 "Val-Studio DCF (staging)" Task Pane 이 뜬다. 패널은
`https://localhost:5173/?embed=1` (embed 모드 — LNB·헤더 축소).

## 사내 MVP 배포 (M365 관리 센터)

1. 프론트 HTTPS 배포(Vercel 등), API HTTPS 배포(Railway/Render).
2. `manifest.xml` 의 URL·GUID 치환 후 접근 가능한 위치에 업로드.
3. Microsoft 365 관리 센터 → 설정 → **통합 앱** → 사용자 지정 앱 추가 → manifest URL.
4. FastAPI `allow_origins` 에 프론트 origin 추가(CORS). `<AppDomains>` 는 CORS 아님.

## CORS 주의

Task Pane fetch 의 Origin 은 `SourceLocation` 도메인(우리 앱)이지 `excel.office.com` 이
아니다. `allow_origins` 의 핵심은 **자기 프론트 origin**. 상세: PRD §10.3.

## 검증 (Definition of Done)

- [ ] Excel Online 에서 Task Pane 로드
- [ ] Excel Desktop(M365)에서 동일 manifest 동작
- [ ] 데모 입력 → `/api/dcf` → 주당가치·EV·findings·민감도(3×3)
- [ ] `fixtures/viol/inputs.json` 동등 입력 시 주당가치 **8,413.38원**
- [ ] BYOK 키가 서버 로그에 남지 않음
