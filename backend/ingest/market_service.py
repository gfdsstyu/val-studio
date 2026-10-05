"""One-process coordination and bounded date lookup; no silent provider fallback."""
from __future__ import annotations

import hashlib
import threading
import time
from datetime import datetime, timedelta

from .kexim_client import KeximClient
from .market_data import (KST, DateContract, MarketError, MarketQuery, PARSER_VERSION,
                          assess_snapshot, finding, normalize_snapshot)
from .market_store import MarketSnapshotStore


class MarketService:
    def __init__(self, store: MarketSnapshotStore, client=None, *, contracts=None,
                 now=lambda: datetime.now(KST), monotonic=time.monotonic, daily_limit=900):
        self.store, self.client = store, client or KeximClient()
        self.contracts, self.now, self.monotonic = contracts or {}, now, monotonic
        # Serializing requests bounds local quota and folds simultaneous cache misses.
        # This is deliberately NOT a distributed lock or a provider quota guarantee.
        self.lock = threading.Lock()
        self.counts, self.quota_day, self.daily_limit = {}, None, daily_limit

    def _count_call(self, key):
        day = self.now().astimezone(KST).date().isoformat()
        if self.quota_day != day:
            self.counts, self.quota_day = {}, day
        identity = hashlib.sha256(key.encode()).hexdigest()
        count = self.counts.get(identity, 0)
        if count >= self.daily_limit:
            raise MarketError("KEXIM_LOCAL_BUDGET_EXHAUSTED", "이 서버의 일일 호출 예산이 소진되었습니다.", 429)
        self.counts[identity] = count + 1

    def query(self, query: MarketQuery, key: str = "") -> dict:
        started = self.monotonic()
        if not self.lock.acquire(timeout=45):
            raise MarketError("KEXIM_TIMEOUT", "다른 시장자료 요청이 처리 중입니다.", 504)
        try:
            deadline = started + 45
            steps = query.max_lookback_days if query.date_policy == "previous_available" else 0
            attempted = []
            for offset in range(steps + 1):
                day = (datetime.fromisoformat(query.requested_date) - timedelta(days=offset)).date().isoformat()
                attempted.append(day)
                cached, checked = self.store.latest(query.dataset, day)
                contract = self.contracts.get(query.dataset, DateContract())
                usable = cached is not None and cached["parser_version"] == PARSER_VERSION and cached["date_policy_version"] == contract.version
                if usable:
                    usable = all(o["date_evidence"] == contract.evidence and bool(o["effective_date"]) == contract.verified
                                 for o in cached["observations"])
                fresh = False
                if usable and checked:
                    try:
                        age = (self.now() - datetime.fromisoformat(checked)).total_seconds()
                        # Today's data and empty historical responses must be rechecked.
                        ttl = 300 if not cached["observations"] or day == self.now().astimezone(KST).date().isoformat() else 86400
                        fresh = 0 <= age < ttl
                    except (ValueError, TypeError):
                        pass
                if query.cache_policy == "cache_only":
                    if not usable:
                        # Unknown is not evidence of an empty date; don't silently jump over it.
                        raise MarketError("MARKET_CACHE_MISS", "이 날짜의 호환되는 저장 자료가 없습니다. 다시 조회하세요.", 404)
                    snapshot, cache_status = cached, "cache_only"
                elif query.cache_policy != "refresh" and usable and fresh:
                    snapshot, cache_status = cached, "hit"
                else:
                    raw = self.client.fetch(query.dataset, day, key, deadline=deadline,
                                            before_call=lambda: self._count_call(key.strip()))
                    snapshot = normalize_snapshot(raw, query.dataset, day, self.now().isoformat(), contract)
                    snapshot = self.store.save(snapshot, raw)
                    cache_status = "refreshed" if cached else "miss"
                view = assess_snapshot(snapshot, query)
                view.update(persistence=self.store.persistence, cache_status=cache_status,
                            attempted_dates=attempted.copy())
                if cached and snapshot["snapshot_id"] != cached["snapshot_id"]:
                    view["findings"].append(finding("market_snapshot_changed", "동일 날짜의 응답이 변경되어 새 스냅샷으로 보존했습니다.", "warn", previous_snapshot_id=cached["snapshot_id"]))
                if snapshot["observations"] or offset == steps:
                    return view
            raise AssertionError("unreachable")
        finally:
            self.lock.release()

    def restore(self, sid: str, query: MarketQuery) -> dict:
        snapshot = self.store.load(sid)
        if snapshot["dataset"] != query.dataset:
            raise MarketError("MARKET_INPUT_INVALID", "스냅샷의 자료 종류가 다릅니다.")
        delta = (datetime.fromisoformat(query.requested_date) - datetime.fromisoformat(snapshot["requested_date"])).days
        if delta < 0 or delta > (query.max_lookback_days if query.date_policy == "previous_available" else 0):
            raise MarketError("MARKET_INPUT_INVALID", "스냅샷 날짜가 선택한 조회 정책과 맞지 않습니다.")
        view = assess_snapshot(snapshot, query)
        contract = self.contracts.get(query.dataset, DateContract())
        if (snapshot["parser_version"] != PARSER_VERSION or snapshot["date_policy_version"] != contract.version
                or not contract.verified or any(o["date_evidence"] != contract.evidence for o in snapshot["observations"])):
            for ob in view["observations"]:
                if "market_date_unverified" not in ob["blocking_rules"]:
                    ob["findings"].append(finding("market_contract_changed", "현재 서버의 날짜 검증 근거로 다시 조회해야 합니다."))
                    ob["blocking_rules"].append("market_contract_changed")
                ob["adoption_eligible"] = False
            if view["observations"]:
                view["status"] = "partial"
        view.update(persistence=self.store.persistence, cache_status="restored")
        return view
