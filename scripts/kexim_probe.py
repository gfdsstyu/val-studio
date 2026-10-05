"""Read-only live probe. Keys stay in environment; private responses go under var/.

Example: py -3.12 scripts/kexim_probe.py --date 2026-10-02 --dataset exchange
This records observations, but NEVER approves a request-date contract automatically.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from ingest.market_data import KST, MarketError, MarketQuery  # noqa: E402
from ingest.market_service import MarketService  # noqa: E402
from ingest.market_store import MarketSnapshotStore  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", action="append", required=True, help="ISO date; repeat up to five dates")
    parser.add_argument("--dataset", choices=["exchange", "lending", "international", "all"], default="exchange")
    args = parser.parse_args()
    key = os.environ.get("KEXIM_API_KEY", "").strip()
    if not key:
        print(json.dumps({"status": "not_run", "reason": "KEXIM_API_KEY not configured"}))
        return 2
    if len(args.date) > 5:
        parser.error("최대 5개 날짜만 지정하세요.")
    today = datetime.now(KST).date().isoformat()
    datasets = ["exchange", "lending", "international"] if args.dataset == "all" else [args.dataset]
    # Validate every request before making the first upstream call.
    try:
        queries = [MarketQuery.parse({"dataset": ds, "valuation_date": today, "requested_date": day,
                                      "cache_policy": "refresh"}) for ds in datasets for day in args.date]
    except MarketError as exc:
        print(json.dumps({"status": "not_run", "code": exc.code, "message": exc.message}, ensure_ascii=False))
        return 2
    svc = MarketService(MarketSnapshotStore(ROOT / "var" / "market" / "kexim"))
    results = []
    for q in queries:
        try:
            view = svc.query(q, key)
            results.append({"status": "live_response", "dataset": q.dataset, "requested_date": q.requested_date,
                            "snapshot_id": view["snapshot_id"], "response_status": view["status"],
                            "observations": len(view["observations"]), "date_contract": "unverified"})
        except MarketError as exc:
            results.append({"status": "live_fail", "dataset": q.dataset, "requested_date": q.requested_date,
                            "code": exc.code, "message": exc.message})
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return int(any(r["status"] == "live_fail" for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
