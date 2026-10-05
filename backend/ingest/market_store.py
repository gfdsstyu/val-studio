"""Local immutable snapshots; hosting persistence is reported separately."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from .market_data import ENDPOINTS, MarketError, canonical, digest, iso_date


class MarketSnapshotStore:
    def __init__(self, root: Path, *, persistence: str = "local"):
        self.root, self.persistence = Path(root), persistence

    @staticmethod
    def _id(value: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
            raise MarketError("MARKET_INPUT_INVALID", "잘못된 스냅샷 식별자입니다.")
        return value

    def _index(self, dataset: str, requested_date: str) -> Path:
        if dataset not in ENDPOINTS:
            raise MarketError("MARKET_INPUT_INVALID", "지원하지 않는 자료입니다.")
        return self.root / "index" / f"{dataset}-{iso_date(requested_date)}.json"

    def _write(self, path: Path, data: bytes):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
                tmp = Path(f.name)
                f.write(data)
            os.replace(tmp, path)
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)

    def save(self, snapshot: dict, raw: bytes) -> dict:
        sid = self._id(snapshot["snapshot_id"])
        if hashlib.sha256(raw).hexdigest() != snapshot["payload_sha256"]:
            raise MarketError("MARKET_SNAPSHOT_CORRUPT", "원본 해시가 일치하지 않습니다.", 409)
        try:
            existing = self.load(sid, missing_ok=True)
            if existing is None:
                self._write(self.root / "raw" / (snapshot["payload_sha256"] + ".bin"), raw)
                envelope = {"snapshot": snapshot, "checksum": digest(snapshot)}
                self._write(self.root / "snapshots" / (sid + ".json"), canonical(envelope).encode("utf-8"))
            self._write(self._index(snapshot["dataset"], snapshot["requested_date"]),
                        canonical({"snapshot_id": sid, "checked_at": snapshot["fetched_at"]}).encode("utf-8"))
            return existing or snapshot
        except OSError:
            raise MarketError("MARKET_SNAPSHOT_STORE_FAILED", "시장자료를 저장하지 못했습니다.", 503) from None

    def load(self, sid: str, *, missing_ok: bool = False) -> dict | None:
        path = self.root / "snapshots" / (self._id(sid) + ".json")
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            if missing_ok:
                return None
            raise MarketError("MARKET_SNAPSHOT_NOT_FOUND", "시장자료 스냅샷을 다시 조회하세요.", 404) from None
        except (OSError, ValueError):
            raise MarketError("MARKET_SNAPSHOT_CORRUPT", "시장자료 스냅샷을 읽을 수 없습니다.", 409) from None
        snapshot = envelope.get("snapshot") if isinstance(envelope, dict) else None
        if (not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1
                or snapshot.get("snapshot_id") != sid or envelope.get("checksum") != digest(snapshot)):
            raise MarketError("MARKET_SNAPSHOT_CORRUPT", "시장자료 스냅샷 검증에 실패했습니다.", 409)
        try:
            raw = (self.root / "raw" / (self._id(snapshot["payload_sha256"]) + ".bin")).read_bytes()
        except (OSError, KeyError, MarketError):
            raise MarketError("MARKET_SNAPSHOT_CORRUPT", "시장자료 원본이 없습니다.", 409) from None
        if hashlib.sha256(raw).hexdigest() != snapshot["payload_sha256"]:
            raise MarketError("MARKET_SNAPSHOT_CORRUPT", "시장자료 원본이 변경되었습니다.", 409)
        return snapshot

    def latest(self, dataset: str, requested_date: str) -> tuple[dict | None, str | None]:
        try:
            index = json.loads(self._index(dataset, requested_date).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None, None
        except (OSError, ValueError):
            raise MarketError("MARKET_SNAPSHOT_CORRUPT", "시장자료 캐시를 읽을 수 없습니다.", 409) from None
        if not isinstance(index, dict):
            raise MarketError("MARKET_SNAPSHOT_CORRUPT", "시장자료 캐시 구조가 잘못되었습니다.", 409)
        snapshot = self.load(index.get("snapshot_id"))
        if snapshot["dataset"] != dataset or snapshot["requested_date"] != requested_date:
            raise MarketError("MARKET_SNAPSHOT_CORRUPT", "시장자료 캐시의 날짜·종류가 다릅니다.", 409)
        return snapshot, index.get("checked_at")
