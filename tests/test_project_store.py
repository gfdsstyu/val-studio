"""프로젝트 영속화 스토어 — 로컬 왕복 + GCS 모드(가짜 urlopen, 네트워크 0).

핵심 시나리오 = Cloud Run 재시작: 로컬 캐시 소실 후 GCS 폴백으로 복원되는가.
실패 의미론: 저장·삭제의 GCS 실패는 StoreError(삼키면 '영속됐다고 믿는' 원래
버그가 재발) / 조회 404 는 부재(None).
"""
from __future__ import annotations

import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from api.project_store import ProjectStore, StoreError  # noqa: E402

PID = "abcdef012345"
TOKEN_BODY = json.dumps({"access_token": "T", "expires_in": 3600})


class FakeResp:
    def __init__(self, body: str):
        self._b = body.encode("utf-8")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _router(monkeypatch, routes, calls):
    """(method, url조각) 첫 매칭 응답을 주는 가짜 urlopen. 미매칭=테스트 실패."""
    def fake(req, timeout=None):
        url, method = req.full_url, req.get_method()
        calls.append({"method": method, "url": url, "data": req.data,
                      "auth": req.headers.get("Authorization")})
        for (m, frag), resp in routes:
            if m == method and frag in url:
                if isinstance(resp, Exception):
                    raise resp
                return FakeResp(resp)
        raise AssertionError(f"미정의 요청: {method} {url}")
    monkeypatch.setattr(urllib.request, "urlopen", fake)


def _http404():
    return urllib.error.HTTPError("u", 404, "nf", {}, io.BytesIO(b""))


# ── 로컬 모드(버킷 미설정) — 기존 동작 보존 ──────────────────────────────────
def test_local_roundtrip(tmp_path):
    st = ProjectStore(tmp_path)
    assert st.load(PID) is None
    st.save(PID, '{"id":"x"}')
    assert st.load(PID) == '{"id":"x"}'
    assert st.list_ids() == [PID]
    assert st.delete(PID) is True
    assert st.delete(PID) is False


# ── GCS 모드 ─────────────────────────────────────────────────────────────────
def test_gcs_save_uploads_with_token(tmp_path, monkeypatch):
    calls = []
    _router(monkeypatch, [
        (("GET", "metadata.google.internal"), TOKEN_BODY),
        (("POST", "/upload/storage/v1/b/bkt/o"), "{}"),
    ], calls)
    st = ProjectStore(tmp_path, "bkt")
    st.save(PID, '{"id":"x"}')
    assert (tmp_path / f"{PID}.json").exists()          # 로컬 캐시 동시 기록
    up = next(c for c in calls if c["method"] == "POST")
    assert f"name=projects/{PID}.json" in up["url"].replace("%2F", "/")
    assert up["auth"] == "Bearer T" and up["data"] == b'{"id":"x"}'


def test_gcs_load_restores_cache_after_restart(tmp_path, monkeypatch):
    """재시작 시나리오: 로컬 공백 → GCS 조회 → 로컬 미러 적재.

    ⚠️ 종전 계약은 '2회차는 캐시 히트(네트워크 0)' 였다. 다중 인스턴스에서 그 캐시가
    남의 최신 저장을 가려 유실을 만들기 때문에(test_gcs_load_ignores_stale_local_cache)
    **매 조회가 GCS 를 본다**로 바꿨다. 로컬은 읽기 캐시가 아니라 쓰기 미러다.""" 
    calls = []
    _router(monkeypatch, [
        (("GET", "metadata.google.internal"), TOKEN_BODY),
        (("GET", "alt=media"), '{"id":"restored"}'),
    ], calls)
    st = ProjectStore(tmp_path, "bkt")
    assert st.load(PID) == '{"id":"restored"}'
    assert (tmp_path / f"{PID}.json").exists()
    n = len(calls)
    assert st.load(PID) == '{"id":"restored"}'
    assert len(calls) > n, "2회차가 GCS 를 안 봤다 — 낡은 로컬본을 돌려줄 위험"


def test_gcs_load_ignores_stale_local_cache(tmp_path, monkeypatch):
    """⚠️ 다중 인스턴스 유실 경로 — 로컬 캐시를 먼저 읽으면 남의 최신 저장을 덮어쓴다.

    ① 인스턴스 A 저장 → GCS 갱신  ② 인스턴스 B 는 예전에 읽어둔 로컬본 보유
    ③ B 가 로컬을 돌려주면 사용자는 낡은 상태에서 편집·저장 → A 의 작업이 사라진다.
    버킷이 설정된 이상 GCS 가 읽기 정본이어야 한다.
    """
    calls = []
    (tmp_path / f"{PID}.json").write_text('{"name":"낡은 로컬본"}', encoding="utf-8")
    _router(monkeypatch, [
        (("GET", "metadata.google.internal"), TOKEN_BODY),
        (("GET", "alt=media"), '{"name":"GCS 최신본"}'),
    ], calls)
    got = ProjectStore(tmp_path, bucket="b").load(PID)
    assert '"GCS 최신본"' in got, "낡은 로컬 캐시가 GCS 최신본을 가렸다"
    assert any("alt=media" in c["url"] for c in calls), "GCS 를 조회하지 않았다"
    # 조회 성공분은 로컬 미러로 갱신된다.
    assert "GCS 최신본" in (tmp_path / f"{PID}.json").read_text(encoding="utf-8")


def test_gcs_list_excludes_stale_local_only_ids(tmp_path, monkeypatch):
    """다른 인스턴스가 지운 프로젝트가 낡은 로컬 캐시로 되살아나면 안 된다."""
    calls = []
    (tmp_path / "deadbeef0000.json").write_text("{}", encoding="utf-8")   # GCS 엔 없음
    _router(monkeypatch, [
        (("GET", "metadata.google.internal"), TOKEN_BODY),
        (("GET", "/o?prefix="), json.dumps({"items": [{"name": f"projects/{PID}.json"}]})),
    ], calls)
    ids = ProjectStore(tmp_path, bucket="b").list_ids()
    assert ids == [PID], f"로컬 잔여물이 목록에 샜다: {ids}"


def test_local_mode_still_reads_local(tmp_path):
    """버킷 미설정(로컬 dev·테스트)은 종전 동작 그대로 — 회귀 방지."""
    (tmp_path / f"{PID}.json").write_text('{"name":"로컬"}', encoding="utf-8")
    s = ProjectStore(tmp_path)
    assert '"로컬"' in s.load(PID) and s.list_ids() == [PID]


def test_gcs_load_404_is_absence(tmp_path, monkeypatch):
    _router(monkeypatch, [
        (("GET", "metadata.google.internal"), TOKEN_BODY),
        (("GET", "alt=media"), _http404()),
    ], [])
    assert ProjectStore(tmp_path, "bkt").load(PID) is None


def test_gcs_failures_raise_store_error(tmp_path, monkeypatch):
    _router(monkeypatch, [
        (("GET", "metadata.google.internal"), TOKEN_BODY),
        (("POST", "/upload/"), urllib.error.URLError("down")),
    ], [])
    st = ProjectStore(tmp_path, "bkt")
    with pytest.raises(StoreError):
        st.save(PID, "{}")
    # 토큰 획득 실패(Cloud Run 밖) 도 StoreError 로 표면화
    _router(monkeypatch, [
        (("GET", "metadata.google.internal"), urllib.error.URLError("no metadata")),
    ], [])
    with pytest.raises(StoreError):
        ProjectStore(tmp_path, "bkt2").save(PID, "{}")


def test_gcs_list_is_authoritative_and_paginates(tmp_path, monkeypatch):
    """버킷 설정 시 목록은 **GCS 만** — 합집합은 지워진 프로젝트를 되살린다.

    로컬 전용 id('aaaa…')는 업로드 실패 잔여물이거나 다른 인스턴스가 지운 것이다.
    목록에 남기면 열었을 때 404 가 나고, '저장된 것처럼' 보인다."""
    (tmp_path / "aaaaaaaaaaaa.json").write_text("{}", encoding="utf-8")
    calls = []
    page1 = json.dumps({"items": [{"name": "projects/bbbbbbbbbbbb.json"}],
                        "nextPageToken": "t2"})
    page2 = json.dumps({"items": [{"name": "projects/cccccccccccc.json"}]})
    _router(monkeypatch, [
        (("GET", "metadata.google.internal"), TOKEN_BODY),
        (("GET", "pageToken=t2"), page2),
        (("GET", "prefix="), page1),
    ], calls)
    ids = ProjectStore(tmp_path, "bkt").list_ids()
    assert ids == ["bbbbbbbbbbbb", "cccccccccccc"]   # 로컬 전용 aaaa 는 제외
    assert any("pageToken=t2" in c["url"] for c in calls)


def test_gcs_delete_both_sides(tmp_path, monkeypatch):
    (tmp_path / f"{PID}.json").write_text("{}", encoding="utf-8")
    _router(monkeypatch, [
        (("GET", "metadata.google.internal"), TOKEN_BODY),
        (("DELETE", f"/b/bkt/o/"), ""),
    ], [])
    st = ProjectStore(tmp_path, "bkt")
    assert st.delete(PID) is True
    assert not (tmp_path / f"{PID}.json").exists()
    # 양쪽 모두 부재(GCS 404) → False
    _router(monkeypatch, [
        (("GET", "metadata.google.internal"), TOKEN_BODY),
        (("DELETE", "/o/"), _http404()),
    ], [])
    assert ProjectStore(tmp_path, "bkt").delete(PID) is False
