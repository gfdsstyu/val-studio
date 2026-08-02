# val-studio 단일 컨테이너 — FastAPI 1프로세스가 /api/* 와 React dist 를 같은
# 오리진으로 서빙한다(backend/api/main.py 말미의 StaticFiles mount).
# 프론트 배포처를 따로 두지 않으므로 CORS 도 관여하지 않는다.
#
# 빌드:  docker build -t val-studio .
# 실행:  docker run --rm -p 8080:8080 val-studio

# ─────────────────────────────────────────────────────────────
# stage 1 — 프론트 빌드 (Vite)
# ─────────────────────────────────────────────────────────────
FROM node:20-slim AS web
WORKDIR /web

# package*.json 만 먼저 복사해 npm ci 레이어를 캐싱한다.
# (소스만 바뀐 재빌드에서 의존성 설치를 건너뛰기 위함)
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build          # → /web/dist


# ─────────────────────────────────────────────────────────────
# stage 2 — 런타임 (Python)
# ─────────────────────────────────────────────────────────────
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# pdftotext — ingest/parsers/pdf.py 가 subprocess 로 직접 호출하는 외부 바이너리.
# 파이썬 의존성이 아니라서 requirements.txt 로는 안 들어온다. 빠지면 PDF 인제스트만 실패.
RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

# 디렉터리 레이아웃 고정 —
# main.py 는 _ROOT = Path(__file__).resolve().parents[2] 로 루트를 잡고
# _DIST = _ROOT/"frontend"/"dist" 를 마운트한다. 즉 /app/backend/api/main.py 와
# /app/frontend/dist 가 동시에 성립해야 정적 서빙이 켜진다. 경로를 바꾸지 말 것.
COPY backend/ ./backend/
COPY --from=web /web/dist ./frontend/dist

# 골든 픽스처 — /api/demo/cases 가 런타임에 읽는다(키 없는 방문자용 데모 진입점).
# .dockerignore 에서 제외를 푸는 것만으로는 부족하다. 그건 "복사 가능 대상"을 정할
# 뿐이고, 실제로 이미지에 넣으려면 이 COPY 가 있어야 한다(실측으로 확인한 함정).
COPY fixtures/ ./fixtures/

# 런타임 쓰기 경로(프로젝트 저장 · DART corpCode 캐시).
# Cloud Run 의 컨테이너 파일시스템은 인메모리이고 인스턴스마다 독립이다 →
# 여기 쓰인 내용은 재시작/스케일아웃 시 사라지고 메모리를 점유한다.
# 영속이 필요해지면 GCS 나 Firestore 로 옮길 것(docs/deploy.md 참조).
RUN mkdir -p var/projects && useradd -m -u 1000 app && chown -R app:app /app
USER app

# Cloud Run 은 $PORT 를 주입한다(기본 8080). 로컬 docker run 대비 기본값을 둔다.
ENV PORT=8080
EXPOSE 8080

# shell 형식 — ${PORT} 확장이 필요하다. exec 로 감싸 uvicorn 이 PID 1 이 되게 해
# Cloud Run 의 SIGTERM(graceful shutdown)이 그대로 전달되도록 한다.
#
# --timeout-keep-alive 75: Cloud Run 프론트엔드 LB 의 유휴 커넥션 유지시간이 60초인데
# uvicorn 기본값은 5초다. 서버가 먼저 끊은 커넥션을 LB 가 재사용하면 간헐 502 가 난다.
# LB 값보다 크게 잡아 경합을 없앤다(감린이 services/rag-inference 와 같은 규약).
CMD exec uvicorn backend.api.main:app --host 0.0.0.0 --port ${PORT} --timeout-keep-alive 75
