"""Route integration with synthetic upstream; never claims live evidence."""
from fastapi.testclient import TestClient
import pytest

from backend.api.main import app
from backend.api.market import get_service
from ingest.kexim_client import KeximClient
from ingest.market_service import MarketService
from ingest.market_store import MarketSnapshotStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FEATURE_KEXIM_MARKET_DATA", "1")
    svc = MarketService(MarketSnapshotStore(tmp_path), KeximClient(http=lambda *a: b'[{"result":1,"cur_unit":"USD","deal_bas_r":"1400"}]'))
    app.dependency_overrides[get_service] = lambda: svc
    yield TestClient(app)
    app.dependency_overrides.pop(get_service, None)


BODY = {"valuation_date": "2026-10-04", "requested_date": "2026-10-02", "currencies": ["USD"]}


def test_routes_preview_record_restore_and_guard(client):
    res = client.post("/api/market/quotes", json=BODY, headers={"X-Kexim-Key": "fake-secret-key"})
    assert res.status_code == 200, res.text
    data = res.json(); body = {**BODY, "snapshot_id": data["snapshot_id"]}
    assert data["status"] == "partial" and not data["observations"][0]["adoption_eligible"]
    assert client.post("/api/market/restore", json=body).status_code == 200
    plan = client.post("/api/market/sheet-plan", json=body)
    assert plan.status_code == 200 and len(plan.json()["market"]["rows"]) == 1
    blocked = client.post("/api/market/binding-plan", json={**body, "observation_id": data["observations"][0]["observation_id"]})
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "MARKET_ADOPTION_BLOCKED"
    assert "fake-secret-key" not in res.text + plan.text + blocked.text
    conversion = client.post("/api/market/conversion-plan", json={**body,
      "observation_id": data["observations"][0]["observation_id"], "source_sheet": "Sales", "source_address": "A1",
      "output_sheet": "Sales", "output_start": "B1", "source_scale": "unit", "output_unit": "KRW",
      "expected_source": {"values": [[1]], "formulas": [[1]]},
      "expected_output": {"values": [[""]], "formulas": [[""]]}})
    assert conversion.status_code == 409 and conversion.json()["detail"]["code"] == "MARKET_ADOPTION_BLOCKED"


def test_route_missing_key_and_input_errors(client):
    res = client.post("/api/market/quotes", json=BODY)
    assert res.status_code == 401 and res.json()["detail"]["code"] == "KEXIM_AUTH_REQUIRED"
    assert client.post("/api/market/quotes", json={**BODY, "dataset": []}).status_code == 422
    assert client.post("/api/market/restore", json={**BODY, "snapshot_id": "../bad"}).status_code == 422


def test_feature_switch_and_capabilities(client, monkeypatch):
    monkeypatch.setenv("FEATURE_KEXIM_MARKET_DATA", "0")
    assert not client.get("/api/market/capabilities").json()["enabled"]
    assert client.post("/api/market/quotes", json=BODY).status_code == 503
    assert client.post("/api/market/conversion-plan", json=BODY).status_code == 503


def test_conversion_route_restores_server_snapshot_and_rechecks_contract(client):
    from ingest.market_data import DateContract
    from test_market_data import apply
    svc = app.dependency_overrides[get_service]()
    svc.contracts = {"exchange": DateContract(True, "MOCK route evidence", "mock-date-1")}
    v = client.post("/api/market/quotes", json=BODY, headers={"X-Kexim-Key": "fake-key"}).json()
    request = {**BODY, "snapshot_id": v["snapshot_id"]}
    p = client.post("/api/market/sheet-plan", json=request).json()
    request.update(observation_id=v["observations"][0]["observation_id"], market_grid=apply(p["market"]),
      facts_grid=apply(p["facts"]), source_sheet="Sales", source_address="A1", output_sheet="Sales", output_start="B1",
      source_currency="USD", source_scale="unit", output_unit="KRW", expected_unit="KRW_per_1_USD",
      expected_source={"values": [[2]], "formulas": [[2]]}, expected_output={"values": [[""]], "formulas": [[""]]},
      reason="MOCK route conversion", acknowledge_warnings=True, normalized_value="9999")
    response = client.post("/api/market/conversion-plan", json=request)
    assert response.status_code == 200, response.text
    assert response.json()["output"]["expected_values"] == [[2800]]
    svc.contracts = {}
    assert client.post("/api/market/conversion-plan", json=request).status_code == 409
