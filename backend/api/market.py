"""KEXIM routes. BYOK keys are transient headers, never project/snapshot fields."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException

from excel.market_binding import binding_plan
from excel.market_conversion import conversion_plan
from excel.market_sheet import append_plan
from ingest.market_data import DateContract, ENDPOINTS, MarketError, MarketQuery
from ingest.market_service import MarketService
from ingest.market_store import MarketSnapshotStore

router = APIRouter(prefix="/api/market", tags=["market"])
ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def get_service():
    contracts = {}
    path = os.environ.get("KEXIM_DATE_CONTRACT_FILE")
    if path:
        try:
            config = json.loads(Path(path).read_text(encoding="utf-8"))
            for dataset, item in config.items():
                if dataset not in ENDPOINTS or item.get("verified") is not True:
                    continue
                if not isinstance(item.get("version"), str) or not item["version"].strip() or item["version"] == DateContract().version:
                    raise ValueError("date contract must have a new evidence version")
                contracts[dataset] = DateContract(True, item["evidence"], item["version"])
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise HTTPException(503, detail={"code": "MARKET_CONFIG_INVALID", "message": "날짜 검증 설정을 확인하세요."}) from None
    root = Path(os.environ.get("KEXIM_SNAPSHOT_DIR", str(ROOT / "var" / "market" / "kexim")))
    return MarketService(MarketSnapshotStore(root, persistence="ephemeral" if os.environ.get("K_SERVICE") else "local"), contracts=contracts)


def enabled():
    # Hosted deployments opt in after persistence/date evidence review. Local MVP is visible.
    value = os.environ.get("FEATURE_KEXIM_MARKET_DATA", "0" if os.environ.get("K_SERVICE") else "1")
    return value == "1"


def invoke(fn):
    if not enabled():
        raise HTTPException(503, detail={"code": "MARKET_DISABLED", "message": "시장자료 기능이 비활성화되어 있습니다."})
    try:
        return fn()
    except MarketError as exc:
        raise HTTPException(exc.status, detail={"code": exc.code, "message": exc.message}) from None


@router.get("/capabilities")
def capabilities(service: MarketService = Depends(get_service)):
    return {"enabled": enabled(), "provider": "kexim", "currencies": ["USD", "JPY", "EUR"],
            "datasets": list(ENDPOINTS), "persistence": service.store.persistence,
            "date_contracts": {k: {"verified": service.contracts.get(k, DateContract()).verified,
                                  "evidence": service.contracts.get(k, DateContract()).evidence} for k in ENDPOINTS},
            "interest_adoption": False, "quota_scope": "process_local", "daily_call_budget": service.daily_limit}


@router.post("/quotes")
def quotes(body: dict, x_kexim_key: str = Header(default=""), service: MarketService = Depends(get_service)):
    return invoke(lambda: service.query(MarketQuery.parse(body), x_kexim_key))


def restore(body, service):
    return service.restore(body.get("snapshot_id"), MarketQuery.parse(body))


@router.post("/restore")
def restore_route(body: dict, service: MarketService = Depends(get_service)):
    return invoke(lambda: restore(body, service))


@router.post("/sheet-plan")
def sheet_plan_route(body: dict, service: MarketService = Depends(get_service)):
    return invoke(lambda: append_plan(restore(body, service), body.get("market_grid", []), body.get("facts_grid", [])))


@router.post("/binding-plan")
def binding_plan_route(body: dict, service: MarketService = Depends(get_service)):
    return invoke(lambda: binding_plan(restore(body, service), body))


@router.post("/conversion-plan")
def conversion_plan_route(body: dict, service: MarketService = Depends(get_service)):
    return invoke(lambda: conversion_plan(restore(body, service), body))
