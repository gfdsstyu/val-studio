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

## 알려진 제약

- **상태 비영속.** `var/projects/*.json`(프로젝트 저장)과 `var/dart_corpcode.json`
  (캐시)은 인스턴스별 인메모리다. 재시작·스케일아웃 시 사라지고 인스턴스 간 공유도
  안 된다. 데모용으로는 무해하나, 실사용 전환 시 GCS/Firestore 로 옮겨야 한다.
  `--max-instances 1` 로 두면 세션 내 일관성은 유지된다.
- **키 없는 방문자.** DART/거시 키가 없으면 해당 커넥터만 실패한다. 키 없이도 보여줄
  경로로 `fixtures/viol`·`fixtures/classys` 골든 케이스를 Home 에 노출하는 것을 권장.
- **선택 의존성.** `finance-datareader`·`pykrx` 는 pandas/numpy 를 끌어와 이미지를
  ~250MB 늘린다. 전부 함수 내부 lazy import 라 **제거해도 프로세스는 정상 기동**하고
  해당 엔드포인트만 안내 메시지와 함께 실패한다. 이미지를 줄이려면
  `requirements.txt` 의 `[선택]` 블록을 주석 처리.
- **`pdftotext`.** PDF 인제스트는 파이썬 패키지가 아니라 poppler 바이너리에 의존한다.
  Dockerfile 의 `poppler-utils` 설치를 지우면 PDF 경로만 조용히 깨진다.
