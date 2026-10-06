"""Synthetic contract fixtures, not live KEXIM verification."""
import copy
import json
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import pytest

from ingest.kexim_client import KeximClient
from ingest.market_data import (KST, DateContract, MarketError, MarketQuery, assess_snapshot,
                                decimal_value, normalize_snapshot, unpack_payload)
from ingest.market_service import MarketService
from ingest.market_store import MarketSnapshotStore
from excel.market_binding import binding_plan
from excel.market_sheet import append_plan

NOW = datetime(2026, 10, 4, 14, tzinfo=KST)
CONTRACT = DateContract(True, "MOCK test-only request-date evidence", "mock-date-1")
KEY = "test-secret-not-a-real-credential"


def raw(usd="1,400.00"):
    return json.dumps([{"result": 1, "cur_unit": "USD", "deal_bas_r": usd},
                       {"result": 1, "cur_unit": "JPY(100)", "deal_bas_r": "950"},
                       {"result": 1, "cur_unit": "EUR", "deal_bas_r": "1550"}]).encode()


def query(**overrides):
    return MarketQuery.parse({"valuation_date": "2026-10-04", "requested_date": "2026-10-02", **overrides}, today=NOW.date())


def view(contract=CONTRACT, **overrides):
    return assess_snapshot(normalize_snapshot(raw(), "exchange", "2026-10-02", NOW.isoformat(), contract), query(**overrides))


def service(tmp_path, responses=None, contract=CONTRACT):
    calls = []
    def http(url, params, timeout):
        calls.append((url, params.copy(), timeout))
        return (responses or {}).get(params["searchdate"], raw())
    return MarketService(MarketSnapshotStore(tmp_path), KeximClient(http=http, sleep=lambda _: None),
                         now=lambda: NOW, contracts={"exchange": contract}), calls


def apply(plan):
    rows = copy.deepcopy(plan.get("expected_grid", []))
    if plan["header_rows"]:
        rows = copy.deepcopy(plan["header_rows"])
    for offset, row in enumerate(plan["rows"], plan["start_row"] - 1):
        while len(rows) <= offset:
            rows.append([])
        rows[offset] = row.copy()
    return rows


def binding_data(v):
    plan = append_plan(v, [], [])
    return {"observation_id": v["observations"][0]["observation_id"], "market_grid": apply(plan["market"]),
            "facts_grid": apply(plan["facts"]), "inputs_grid": [], "target_sheet": "Assumptions",
            "target_address": "$D$12", "expected_target": {"value": 1350, "formula": 1350},
            "expected_unit": "KRW_per_1_USD", "reason": "MOCK export conversion", "acknowledge_warnings": True}


def test_fx_normalization_preserves_raw_and_jpy_multiplier():
    v = view()
    usd, jpy = v["observations"][:2]
    assert usd["raw_value"] == "1,400.00" and float(usd["normalized_value"]) == 1400
    assert jpy["raw_value"] == "950" and jpy["normalized_value"] == "9.5"
    assert jpy["quote_unit"] == 100 and jpy["value_unit"] == "KRW_per_1_JPY"
    assert jpy["adoption_eligible"] and jpy["published_at"] is None


@pytest.mark.parametrize("value", [None, "-", "NaN", "Infinity", True, "1,40", "3.5%", "100원", "1e3", {}])
def test_bad_numbers_never_become_zero(value):
    assert decimal_value(value) is None


@pytest.mark.parametrize("value", ["0", "-1", "NaN"])
def test_invalid_fx_blocked(value):
    v = assess_snapshot(normalize_snapshot(raw(value), "exchange", "2026-10-02", NOW.isoformat(), CONTRACT), query())
    assert not v["observations"][0]["adoption_eligible"]


def test_date_and_strict_publication_gates():
    assert not view(DateContract())["observations"][0]["adoption_eligible"]
    strict = view(asof_mode="strict_snapshot")
    assert "market_publication_unknown" in strict["observations"][0]["blocking_rules"]
    assert view()["observations"][0]["adoption_eligible"]


@pytest.mark.parametrize("patch", [{"requested_date": "2026-10-05"}, {"dataset": []},
    {"requested_date": "2026-02-30"}, {"max_lookback_days": 8}, {"max_lookback_days": True},
    {"currencies": ["IDR"]}, {"date_policy": "latest"}])
def test_invalid_requests(patch):
    with pytest.raises(MarketError):
        query(**patch)


@pytest.mark.parametrize("dataset", ["lending", "international"])
def test_interest_display_does_not_invent_units_or_kd(dataset):
    payload = b'[{"result":1,"cur_fund":"USD","sfln_intrc_nm":"6M","int_r":"-0.25"}]'
    q = query(dataset=dataset)
    v = assess_snapshot(normalize_snapshot(payload, dataset, q.requested_date, NOW.isoformat(), CONTRACT), q)
    ob = v["observations"][0]
    assert ob["raw_value"] == "-0.25" and ob["normalized_value"] is None
    assert not ob["adoption_eligible"] and ob["benchmark"] is None


@pytest.mark.parametrize("code,status", [(2, 502), (3, 401), (4, 429)])
def test_result_errors_never_retry(code, status):
    calls = []
    client = KeximClient(http=lambda *args: calls.append(args) or json.dumps([{"result": code}]).encode())
    with pytest.raises(MarketError) as err:
        client.fetch("exchange", "2026-10-02", KEY, deadline=client.monotonic() + 45)
    assert err.value.status == status and len(calls) == 1 and KEY not in str(err.value)


def test_network_retry_is_bounded_and_redacted():
    calls = []
    def http(*args):
        calls.append(args)
        raise urllib.error.URLError(KEY)
    client = KeximClient(http=http, sleep=lambda _: None)
    with pytest.raises(MarketError) as err:
        client.fetch("exchange", "2026-10-02", KEY, deadline=client.monotonic() + 45)
    assert len(calls) == 3 and KEY not in str(err.value)


def test_key_echo_never_persisted(tmp_path):
    svc, _ = service(tmp_path, {"20261002": json.dumps([{"result": 1, "cur_unit": KEY}]).encode()})
    with pytest.raises(MarketError):
        svc.query(query(), KEY)
    assert not list(tmp_path.rglob("*.json"))


def test_empty_and_previous_available_are_explicit(tmp_path):
    svc, calls = service(tmp_path, {"20261004": b"null", "20261003": b"[]"})
    exact = svc.query(query(requested_date="2026-10-04"), KEY)
    assert exact["status"] == "no_data" and len(calls) == 1
    prev = svc.query(query(requested_date="2026-10-04", date_policy="previous_available"), KEY)
    assert prev["selected_request_date"] == "2026-10-02" and len(calls) == 3
    assert "market_date_fallback" in [f["rule"] for f in prev["observations"][0]["findings"]]


def test_auth_error_does_not_date_fallback(tmp_path):
    svc, calls = service(tmp_path, {"20261004": b'[{"result":3}]'})
    with pytest.raises(MarketError):
        svc.query(query(requested_date="2026-10-04", date_policy="previous_available"), KEY)
    assert len(calls) == 1


def test_singleflight_and_currency_filters_share_snapshot(tmp_path):
    svc, calls = service(tmp_path)
    with ThreadPoolExecutor(2) as pool:
        views = list(pool.map(lambda c: svc.query(query(currencies=[c]), KEY), ["USD", "JPY"]))
    assert len(calls) == 1 and views[0]["snapshot_id"] == views[1]["snapshot_id"]
    assert views[1]["observations"][0]["currency"] == "JPY"


def test_cache_only_and_quota(tmp_path):
    svc, calls = service(tmp_path)
    with pytest.raises(MarketError, match="저장 자료"):
        svc.query(query(cache_policy="cache_only"))
    svc.daily_limit = 1
    first = svc.query(query(), KEY)
    assert svc.query(query(cache_policy="cache_only"))["snapshot_id"] == first["snapshot_id"]
    with pytest.raises(MarketError) as err:
        svc.query(query(cache_policy="refresh"), KEY)
    assert err.value.code == "KEXIM_LOCAL_BUDGET_EXHAUSTED" and len(calls) == 1


@pytest.mark.parametrize("checked_at", ["original", None, "invalid timestamp"])
def test_old_nonempty_history_reuses_snapshot_without_key_network_or_quota(tmp_path, checked_at):
    svc, calls = service(tmp_path)
    first = svc.query(query(), KEY)
    if checked_at != "original":
        index = tmp_path / "index" / "exchange-2026-10-02.json"
        entry = json.loads(index.read_text(encoding="utf-8"))
        entry["checked_at"] = checked_at
        index.write_text(json.dumps(entry), encoding="utf-8")
    svc.now = lambda: NOW + timedelta(days=30)
    svc.daily_limit = 0
    counts_before = svc.counts.copy()
    cached = svc.query(query())  # No authentication key; any fetch would fail.
    assert cached["cache_status"] == "hit" and len(calls) == 1
    assert cached["snapshot_id"] == first["snapshot_id"] and cached["fetched_at"] == first["fetched_at"]
    assert svc.counts == counts_before


def test_historical_explicit_refresh_fetches_revision_and_keeps_old_snapshot(tmp_path):
    responses = {"20261002": raw()}
    svc, calls = service(tmp_path, responses)
    original = svc.query(query(), KEY)
    svc.now = lambda: NOW + timedelta(days=30)
    responses["20261002"] = raw("1401")
    assert svc.query(query())["snapshot_id"] == original["snapshot_id"]
    refreshed = svc.query(query(cache_policy="refresh"), KEY)
    assert len(calls) == 2 and refreshed["cache_status"] == "refreshed"
    assert refreshed["snapshot_id"] != original["snapshot_id"]
    assert svc.store.load(original["snapshot_id"])["observations"][0]["raw_value"] == "1,400.00"
    assert refreshed["findings"][-1]["rule"] == "market_snapshot_changed"


@pytest.mark.parametrize("day,payload", [("2026-10-04", raw()), ("2026-10-04", b"[]"), ("2026-10-02", b"[]")])
def test_today_or_empty_cache_still_expires_after_five_minutes(tmp_path, day, payload):
    svc, calls = service(tmp_path, {day.replace("-", ""): payload})
    q = query(requested_date=day)
    svc.query(q, KEY)
    svc.now = lambda: NOW + timedelta(seconds=299)
    assert svc.query(q)["cache_status"] == "hit" and len(calls) == 1
    svc.now = lambda: NOW + timedelta(seconds=300)
    with pytest.raises(MarketError) as err:
        svc.query(q)
    assert err.value.code == "KEXIM_AUTH_REQUIRED"
    assert svc.query(q, KEY)["cache_status"] == "refreshed" and len(calls) == 2


def test_current_nonempty_snapshot_becomes_persistent_history_after_day_rollover(tmp_path):
    svc, calls = service(tmp_path)
    q = query(requested_date="2026-10-04")
    first = svc.query(q, KEY)
    svc.now = lambda: NOW + timedelta(days=1)
    assert svc.query(q)["snapshot_id"] == first["snapshot_id"] and len(calls) == 1


@pytest.mark.parametrize("contract", [DateContract(), DateContract(True, CONTRACT.evidence, "new-version"),
                                    DateContract(True, "new evidence", CONTRACT.version)])
def test_old_history_with_incompatible_date_contract_is_not_a_cache_hit(tmp_path, contract):
    svc, calls = service(tmp_path)
    svc.query(query(), KEY)
    svc.now = lambda: NOW + timedelta(days=30)
    svc.contracts = {"exchange": contract}
    with pytest.raises(MarketError) as err:
        svc.query(query())
    assert err.value.code == "KEXIM_AUTH_REQUIRED" and len(calls) == 1


def test_immutable_snapshots_revision_and_corruption(tmp_path):
    svc, _ = service(tmp_path)
    one = svc.query(query(), KEY)
    again = svc.query(query(cache_policy="refresh"), KEY)
    assert one["snapshot_id"] == again["snapshot_id"]
    svc.client = KeximClient(http=lambda *args: raw("1401"))
    two = svc.query(query(cache_policy="refresh"), KEY)
    assert one["snapshot_id"] != two["snapshot_id"]
    assert svc.store.load(one["snapshot_id"])["observations"][0]["raw_value"] == "1,400.00"
    assert two["findings"][-1]["rule"] == "market_snapshot_changed"
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert KEY.encode() not in path.read_bytes()
    (tmp_path / "raw" / (one["payload_sha256"] + ".bin")).write_bytes(b"tampered")
    with pytest.raises(MarketError) as err:
        svc.restore(one["snapshot_id"], query())
    assert err.value.code == "MARKET_SNAPSHOT_CORRUPT"


def test_revoked_contract_blocks_existing_snapshot(tmp_path):
    svc, _ = service(tmp_path)
    first = svc.query(query(), KEY)
    svc.contracts = {}
    restored = svc.restore(first["snapshot_id"], query())
    assert not restored["observations"][0]["adoption_eligible"]


def test_append_idempotent_and_modified_row_rejected():
    v = view()
    first = append_plan(v, [], [])
    raw_grid, facts = apply(first["market"]), apply(first["facts"])
    retry = append_plan(v, raw_grid, facts)
    assert retry["market"]["rows"] == retry["facts"]["rows"] == []
    raw_grid[4][16] = 999
    with pytest.raises(MarketError) as err:
        append_plan(v, raw_grid, facts)
    assert err.value.code == "MARKET_OBSERVATION_CONFLICT"


def test_facts_same_value_new_source_keeps_both():
    v = view()
    one = append_plan(v, [], [])
    payload = raw() + b" "  # Different upstream bytes, identical values.
    revised = assess_snapshot(normalize_snapshot(payload, "exchange", "2026-10-02", NOW.isoformat(), CONTRACT), query())
    two = append_plan(revised, apply(one["market"]), apply(one["facts"]))
    assert len(two["facts"]["rows"]) == 3 and two["market"]["start_row"] == 8


def test_foreign_sheets_block_without_overwrite():
    for raw_grid, facts in [([["personal worksheet"]], []), ([], [["personal facts"]])]:
        with pytest.raises(MarketError):
            append_plan(view(), raw_grid, facts)


def test_reordered_market_columns_are_supported():
    v = view()
    plan = append_plan(v, [], [])
    rows = apply(plan["market"])
    for row in rows[3:]:
        row[0], row[16] = row[16], row[0]
    assert append_plan(v, rows, apply(plan["facts"]))["market"]["rows"] == []
    data = binding_data(v); data["market_grid"] = rows
    assert binding_plan(v, data)["inputs"]["rows"][0][3] == "='rMarket'!$A$5"


def test_binding_stable_cell_and_explicit_unit_guard():
    v = view(); data = binding_data(v)
    first = binding_plan(v, data)
    assert first["inputs"]["rows"][0][3] == "='rMarket'!$Q$5"
    assert first["target"]["formula"] == "='MarketInputs'!$D$5"
    data["inputs_grid"] = apply(first["inputs"])
    second = binding_plan(v, data)
    assert second["inputs"]["start_row"] == 5
    data["expected_unit"] = "KRW_per_100_JPY"
    with pytest.raises(MarketError) as err:
        binding_plan(v, data)
    assert err.value.code == "MARKET_UNIT_MISMATCH"


@pytest.mark.parametrize("changes", [{"acknowledge_warnings": False}, {"target_sheet": "_VS_STATE"},
    {"target_sheet": "rMarket"}, {"target_address": "A1:B2"}, {"target_address": "XFE1"},
    {"target_address": "A1048577"}, {"reason": ""}, {"market_grid": []}])
def test_binding_rejects_unsafe_or_incomplete_input(changes):
    v = view(); data = binding_data(v); data.update(changes)
    with pytest.raises(MarketError):
        binding_plan(v, data)


def test_unverified_observation_cannot_bind():
    v = view(DateContract())
    with pytest.raises(MarketError) as err:
        binding_plan(v, binding_data(v))
    assert err.value.code == "MARKET_ADOPTION_BLOCKED"
