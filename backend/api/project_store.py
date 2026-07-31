"""프로젝트 영속화 스토어 — 로컬 파일(기본) + GCS 원본(Cloud Run 재시작 생존).

Cloud Run 컨테이너 파일시스템은 휘발성이라 var/projects/*.json 이 재시작마다 증발한다
(미해결 1순위 '저장 비영속'). `PROJECTS_GCS_BUCKET` 환경변수가 설정되면 GCS 를
원본(SSOT)으로 쓰고 로컬 디렉터리는 읽기 캐시가 된다. 미설정(로컬 dev·테스트)이면
기존 로컬 동작 그대로 — 기존 호출부·테스트 무영향.

의존 0 원칙(xlsx_reader 와 동일 철학): google-cloud-storage 대신 stdlib urllib +
Cloud Run 메타데이터 서버 토큰(기본 서비스계정) + GCS JSON API. 필요 권한:
서비스계정에 대상 버킷의 roles/storage.objectAdmin.

배포 체크리스트(운영):
  1) gsutil mb gs://<bucket>  (리전 = Cloud Run 리전)
  2) Cloud Run 서비스에 env PROJECTS_GCS_BUCKET=<bucket> 설정
  3) 기본 SA 에 버킷 objectAdmin 부여

실패 의미론: GCS 설정 시 저장/삭제 실패는 **삼키지 않는다**(StoreError) — 조용히
로컬만 쓰면 '영속됐다고 믿는' 최악의 형태로 원래 버그가 재발한다. 읽기는 로컬 캐시
우선, 미스 시 GCS 조회(404=부재, 그 외 오류=StoreError).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_METADATA_TOKEN_URL = ("http://metadata.google.internal/computeMetadata/v1/"
                       "instance/service-accounts/default/token")
_GCS = "https://storage.googleapis.com"
_PREFIX = "projects/"                      # 버킷 내 오브젝트 프리픽스


class StoreError(RuntimeError):
    """GCS 통신/권한 실패 — 호출부(api)가 5xx 로 표면화한다."""


class ProjectStore:
    """save/load/list/delete 4연산. bucket=None 이면 순수 로컬 모드."""

    def __init__(self, local_dir: Path, bucket: str | None = None):
        self.local_dir = local_dir
        self.bucket = bucket or None
        self._token: str | None = None
        self._token_exp = 0.0

    # ── GCS 저수준 ──────────────────────────────────────────────────────────
    def _get_token(self) -> str:
        """메타데이터 서버 토큰(만료 60초 전 갱신). Cloud Run 밖이면 StoreError."""
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        req = urllib.request.Request(_METADATA_TOKEN_URL,
                                     headers={"Metadata-Flavor": "Google"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                d = json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise StoreError(
                f"GCS 토큰 획득 실패(메타데이터 서버) — Cloud Run 밖에서 "
                f"PROJECTS_GCS_BUCKET 을 설정했는지 확인: {e}") from e
        self._token = d["access_token"]
        self._token_exp = time.time() + float(d.get("expires_in", 300))
        return self._token

    def _gcs(self, method: str, url: str, body: bytes | None = None,
             content_type: str | None = None):
        headers = {"Authorization": f"Bearer {self._get_token()}"}
        if content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        return urllib.request.urlopen(req, timeout=15)

    def _obj(self, pid: str) -> str:
        return urllib.parse.quote(f"{_PREFIX}{pid}.json", safe="")

    # ── 4연산 ───────────────────────────────────────────────────────────────
    def save(self, pid: str, text: str) -> None:
        self.local_dir.mkdir(parents=True, exist_ok=True)
        (self.local_dir / f"{pid}.json").write_text(text, encoding="utf-8")
        if not self.bucket:
            return
        url = (f"{_GCS}/upload/storage/v1/b/{self.bucket}/o"
               f"?uploadType=media&name={urllib.parse.quote(_PREFIX + pid + '.json')}")
        try:
            self._gcs("POST", url, text.encode("utf-8"), "application/json").read()
        except urllib.error.URLError as e:
            raise StoreError(f"GCS 업로드 실패({pid}): {e}") from e

    def load(self, pid: str) -> str | None:
        """로컬 캐시 우선 → GCS 폴백(성공 시 캐시 적재). 부재=None."""
        p = self.local_dir / f"{pid}.json"
        if p.exists():
            return p.read_text(encoding="utf-8")
        if not self.bucket:
            return None
        url = f"{_GCS}/storage/v1/b/{self.bucket}/o/{self._obj(pid)}?alt=media"
        try:
            text = self._gcs("GET", url).read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise StoreError(f"GCS 조회 실패({pid}): HTTP {e.code}") from e
        except urllib.error.URLError as e:
            raise StoreError(f"GCS 조회 실패({pid}): {e}") from e
        self.local_dir.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return text

    def list_ids(self) -> list[str]:
        """로컬 ∪ GCS id 집합 — 재시작 직후(로컬 공백)에도 목록이 살아있어야 한다."""
        ids = ({f.stem for f in self.local_dir.glob("*.json")}
               if self.local_dir.is_dir() else set())
        if self.bucket:
            page = None
            while True:
                url = (f"{_GCS}/storage/v1/b/{self.bucket}/o"
                       f"?prefix={urllib.parse.quote(_PREFIX)}&fields="
                       f"items(name),nextPageToken")
                if page:
                    url += f"&pageToken={urllib.parse.quote(page)}"
                try:
                    d = json.loads(self._gcs("GET", url).read().decode("utf-8"))
                except urllib.error.URLError as e:
                    raise StoreError(f"GCS 목록 실패: {e}") from e
                for it in d.get("items", []):
                    name = it.get("name", "")
                    if name.startswith(_PREFIX) and name.endswith(".json"):
                        ids.add(name[len(_PREFIX):-len(".json")])
                page = d.get("nextPageToken")
                if not page:
                    break
        return sorted(ids)

    def delete(self, pid: str) -> bool:
        """양쪽 모두 삭제. 어느 한쪽이라도 있었으면 True."""
        p = self.local_dir / f"{pid}.json"
        existed = p.exists()
        if existed:
            p.unlink()
        if self.bucket:
            url = f"{_GCS}/storage/v1/b/{self.bucket}/o/{self._obj(pid)}"
            try:
                self._gcs("DELETE", url).read()
                existed = True
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise StoreError(f"GCS 삭제 실패({pid}): HTTP {e.code}") from e
            except urllib.error.URLError as e:
                raise StoreError(f"GCS 삭제 실패({pid}): {e}") from e
        return existed
