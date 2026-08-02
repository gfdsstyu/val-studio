<#
  로컬 실행 원클릭 — 데스크톱 엑셀 애드인·브라우저 탭 공용.

  하는 일: (선택) 프론트 빌드 → uvicorn 기동(FastAPI 1프로세스가 /api/* 와 dist 를
  같은 오리진으로 서빙). 이 창을 켜둔 동안만 Task Pane 이 뜬다 — Cloud Run 과 달리
  항상 떠 있지 않다는 점이 로컬 구성의 유일한 불편이라 스크립트로 줄인다.

  사용:
    powershell -ExecutionPolicy Bypass -File scripts\run_local.ps1           # 빌드 생략(빠름)
    powershell -ExecutionPolicy Bypass -File scripts\run_local.ps1 -Build    # 프론트 수정 후
    powershell -ExecutionPolicy Bypass -File scripts\run_local.ps1 -Port 8001

  애드인 등록(최초 1회)은 add-in/README.md §B(레지스트리) 참조.
#>
param(
  [switch]$Build,
  [int]$Port = 8000,
  [string]$Python = "py"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# 포트 선점 확인 — 이미 떠 있는데 또 띄우면 두 프로세스가 같은 var/projects 를 만진다.
$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
  Write-Host "포트 $Port 는 이미 사용 중입니다(서버가 떠 있을 수 있음)." -ForegroundColor Yellow
  try {
    $h = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 5
    Write-Host "  → val.studio 가 이미 가동 중: $($h.engine). 그대로 쓰시면 됩니다." -ForegroundColor Green
    exit 0
  } catch {
    Write-Host "  → 다른 프로그램이 점유 중입니다. -Port 로 다른 포트를 쓰세요." -ForegroundColor Red
    exit 1
  }
}

if ($Build) {
  Write-Host "[1/2] 프론트 빌드…" -ForegroundColor Cyan
  Push-Location (Join-Path $root "frontend")
  npm run build
  Pop-Location
} elseif (-not (Test-Path (Join-Path $root "frontend\dist\index.html"))) {
  # dist 가 없으면 SPA 가 안 뜬다(API 만 응답) — 조용히 반쪽 상태가 되지 않게 강제.
  Write-Host "[1/2] dist 없음 → 최초 빌드 수행…" -ForegroundColor Cyan
  Push-Location (Join-Path $root "frontend")
  npm install
  npm run build
  Pop-Location
} else {
  Write-Host "[1/2] 빌드 생략(dist 사용). 프론트를 고쳤다면 -Build 를 붙이세요." -ForegroundColor DarkGray
}

Write-Host "[2/2] 서버 기동 → http://127.0.0.1:$Port  (Ctrl+C 로 종료)" -ForegroundColor Cyan
Write-Host "      Task Pane: 엑셀 → 삽입 → 내 추가 기능 → 개발자 → Val-Studio DCF (dev)" -ForegroundColor DarkGray
& $Python -3.12 -m uvicorn backend.api.main:app --host 127.0.0.1 --port $Port
