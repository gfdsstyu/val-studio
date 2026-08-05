# 배포 — Cloud Run 단일 컨테이너

## 왜 이 형태인가

`backend/api/main.py` 말미가 `frontend/dist` 를 `StaticFiles` 로 마운트한다. 즉
**FastAPI 1프로세스가 `/api/*` 와 SPA 를 같은 오리진으로 서빙**한다. 결과적으로

- 프론트 배포처(Vercel 등)를 따로 둘 필요가 없다 — 배포 단위는 컨테이너 1개.
- 같은 오리진이라 CORS 가 관여하지 않는다. `main.py` 의 `allow_origins` 는
  Vite dev(5173) 전용이며 프로덕션에서 수정할 필요가 없다.
- BYOK 설계(LLM·DART 키를 요청 헤더로만 받고 서버에 저장·로깅하지 않음) 덕분에
  **서버에 주입할 시크릿이 0개**다. Secret Manager 연동이 필요 없다.

## 사전 조건 (배포 전 반드시)

1. **`backend/calc_core/data/industry_benchmarks.json` 을 커밋할 것.**
   `calc_core/checks.py` 의 `load_benchmarks()` 가 런타임에 읽는 필수 파일인데
   현재 git untracked 다. 로컬 `docker build` 는 빌드 컨텍스트에 파일이 있어
   성공하지만, **GitHub 연동 Cloud Build 는 이 파일이 없어 산업 대조·감사 게이트가
   런타임에 깨진다.** 로컬 성공이 원격 성공을 보장하지 않는 전형적인 함정.
2. `docs/` 공개 범위 정리 — origin 이 public 레포(`gfdsstyu/val-studio`)다.
   `docs/reference/smic/`, `docs/reference/industry/` 등 코퍼스 계열이 untracked 로
   남아있다. 공개/비공개 선별 후 `.gitignore` 를 보강할 것.

## 로컬 검증

```bash
docker build -t val-studio .
docker run --rm -p 8080:8080 val-studio
# → http://localhost:8080        SPA
# → http://localhost:8080/api/docs   OpenAPI
curl -s localhost:8080/api/health   # {"ok":true,"engine":"calc_core","mode":"local-byok"}
```

## Cloud Run 배포

```bash
PROJECT=<gcp-project-id>
REGION=asia-northeast3          # 서울

gcloud run deploy val-studio \
  --source . \
  --project $PROJECT \
  --region $REGION \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --timeout 300 \
  --max-instances 3
```

`--source .` 는 Cloud Build 가 레포의 `Dockerfile` 을 그대로 쓴다.

### 파라미터 근거

| 값 | 이유 |
|---|---|
| `--memory 1Gi` | 컨테이너 파일시스템이 **인메모리**다. DART `corpCode` 캐시(~10만 사)와 `var/projects` 쓰기가 전부 RAM 을 먹는다. 512Mi 는 위험. |
| `--timeout 300` | 엑셀 왕복·DART 다건 조회가 기본 60초를 넘길 수 있다. |
| `--max-instances 3` | 포폴 데모 기준 비용 상한. BYOK라 폭주 위험은 낮다. |
| `--allow-unauthenticated` | 공개 데모 전제. 비공개로 두려면 이 플래그를 빼고 IAM 초대. |

## 저장 영속화 (GCS) — 실사용 전 필수

기본 상태(버킷 미설정)에서 `var/projects/*.json` 은 **인스턴스 인메모리**라 재시작·스케일
아웃에 사라진다. 데모는 무해하지만 **엑셀 왕복 diff 는 "저장본"을 기준선으로 재생성**하므로
(Task Pane 의 "현재 워크북으로 비교" 포함), 기준선이 날아가면 그 기능 자체가 못 쓰게 된다.

코드는 이미 준비되어 있다(`backend/api/project_store.py` — stdlib urllib + 메타데이터 서버
토큰, google-cloud-storage 의존 0). `PROJECTS_GCS_BUCKET` 만 주입하면 GCS 가 **읽기·쓰기·
목록 모두의 SSOT** 가 되고 로컬 디렉터리는 **쓰기 미러**가 된다(읽기 캐시가 아니다).
**미설정 시 동작은 종전과 완전히 동일**(로컬 전용).

> 로컬을 읽기 캐시로 쓰면 스케일아웃 시 조용한 유실이 난다: 인스턴스 A 가 저장한 뒤
> 인스턴스 B 가 예전 로컬본을 돌려주면, 사용자가 낡은 상태에서 편집·저장해 A 의 작업을
> 덮는다. 그래서 매 조회가 GCS 를 본다(회귀: `test_gcs_load_ignores_stale_local_cache`).

```bash
PROJECT=<gcp-project-id>
REGION=asia-northeast3
BUCKET=<프로젝트-고유-버킷명>          # GCS 버킷명은 전역 유일. 예: val-studio-projects-8f2a

# 1) 버킷 생성 — Cloud Run 과 같은 리전(레이턴시), 균일 액세스 권장
gcloud storage buckets create gs://$BUCKET \
  --project $PROJECT --location $REGION --uniform-bucket-level-access

# 2) 서비스 런타임 SA 확인 (비어 있으면 기본 컴퓨트 SA)
SA=$(gcloud run services describe val-studio --region $REGION --project $PROJECT \
      --format='value(spec.template.spec.serviceAccountName)')
[ -z "$SA" ] && SA=$(gcloud projects describe $PROJECT \
      --format='value(projectNumber)')-compute@developer.gserviceaccount.com
echo $SA

# 3) 권한 — 프로젝트 전역이 아니라 **이 버킷에만** objectAdmin(최소권한)
gcloud storage buckets add-iam-policy-binding gs://$BUCKET \
  --member=serviceAccount:$SA --role=roles/storage.objectAdmin

# 4) 환경변수 주입 — 재빌드 없이 새 리비전만 생성된다
gcloud run services update val-studio --region $REGION --project $PROJECT \
  --update-env-vars PROJECTS_GCS_BUCKET=$BUCKET
```

**검증** (둘 다 통과해야 실제로 영속된 것):

```bash
# ① 웹에서 프로젝트 하나 만든 뒤 — 오브젝트가 실제로 올라갔는지
gcloud storage ls gs://$BUCKET/projects/

# ② 강제로 새 인스턴스를 띄워도 목록이 살아있는지(진짜 시험)
gcloud run services update val-studio --region $REGION --project $PROJECT \
  --update-env-vars _RESTART=$(date +%s)   # 리비전 교체 → 콜드 스타트
# 그 후 웹 새로고침 → 프로젝트 목록에 그대로 있으면 성공
```

> **실패는 조용하지 않다.** 버킷을 설정했는데 권한·통신이 실패하면 `StoreError` → API 5xx 로
> 표면화된다(로컬에만 쓰고 "영속된 줄 아는" 최악의 형태를 의도적으로 배제). 저장 시 502 가
> 뜨면 3)의 권한 부여를 먼저 확인할 것.

**콘솔로 하려면**: Cloud Storage → 버킷 만들기(리전 일치) → 권한 탭에서 Cloud Run 런타임
SA 에 `Storage 객체 관리자` 부여 → Cloud Run 서비스 → 새 버전 수정·배포 → 변수 및 보안
비밀에 `PROJECTS_GCS_BUCKET` 추가.

## 알려진 제약

- **DART corpCode 캐시 비영속.** `var/dart_corpcode.json`(~10만 사)은 여전히 인스턴스별
  인메모리다. 재시작하면 첫 조회 때 키를 가진 방문자가 한 번 다시 받아온다(그 뒤로는 공유).
  프로젝트 저장과 달리 유실 비용이 낮아 GCS 로 옮기지 않았다.
- **키 없는 방문자.** DART/거시 키가 없으면 해당 커넥터만 실패한다. 키 없이도 보여줄
  경로로 `fixtures/viol`·`fixtures/classys` 골든 케이스를 Home 에 노출하는 것을 권장.
- **선택 의존성.** `finance-datareader`·`pykrx` 는 pandas/numpy 를 끌어와 이미지를
  ~250MB 늘린다. 전부 함수 내부 lazy import 라 **제거해도 프로세스는 정상 기동**하고
  해당 엔드포인트만 안내 메시지와 함께 실패한다. 이미지를 줄이려면
  `requirements.txt` 의 `[선택]` 블록을 주석 처리.
- **`pdftotext`.** PDF 인제스트는 파이썬 패키지가 아니라 poppler 바이너리에 의존한다.
  Dockerfile 의 `poppler-utils` 설치를 지우면 PDF 경로만 조용히 깨진다.
