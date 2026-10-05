"""FX amounts/units/range contract tests. All rate/date evidence is synthetic."""
import copy
import json

import pytest

from excel.market_conversion import conversion_plan
from ingest.market_data import DateContract, MarketError
from test_market_data import apply, binding_data, view


def data(v):
    return {**binding_data(v), "source_sheet": "Sales O'Brien", "source_address": "$B$3:$C$4",
            "output_sheet": "Model", "output_start": "E6", "source_currency": "USD",
            "source_scale": "thousand", "output_unit": "KRW_million",
            "expected_source": {"values": [[1, 0], [-2, ""]], "formulas": [[1, 0], [-2, ""]]},
            "expected_output": {"values": [["", ""], ["", ""]], "formulas": [["", ""], ["", ""]]}}


def test_conversion_scales_negative_zero_blank_and_quoted_sheet():
    v = view(); request = data(v); before = copy.deepcopy(request)
    p = conversion_plan(v, request)
    assert request == before
    assert p["output"]["address"] == "E6:F7"
    assert p["output"]["expected_values"] == [[1.4, 0], [-2.8, ""]]
    assert p["output"]["formulas"][0][0] == '=IF(\'Sales O\'\'Brien\'!$B$3="","",\'Sales O\'\'Brien\'!$B$3*1000*\'MarketInputs\'!$D$5/1000000)'
    assert p["inputs"]["rows"][0][1] == "fx_range_conversion"
    audit = json.loads(p["facts"]["rows"][0][2])
    assert audit["source_values_sha256"] and audit["numeric_count"] == 3
    assert audit["currency"] == "USD" and audit["effective_date"] == "2026-10-02"


@pytest.mark.parametrize("source_scale,output_unit,expected", [
    ("unit", "KRW", 1400), ("unit", "KRW_thousand", 1.4),
    ("thousand", "KRW_million", 1.4), ("million", "KRW_million", 1400)])
def test_unit_matrix(source_scale, output_unit, expected):
    v = view(); request = data(v)
    request.update(source_scale=source_scale, output_unit=output_unit)
    assert conversion_plan(v, request)["output"]["expected_values"][0][0] == expected


def test_jpy_100_quote_applies_only_one_normalization_and_stable_rate_row():
    v = view(); request = data(v)
    request.update(observation_id=v["observations"][1]["observation_id"], source_currency="JPY",
                   expected_unit="KRW_per_1_JPY", source_scale="unit", output_unit="KRW")
    p = conversion_plan(v, request)
    assert p["expected_rate"] == "9.5" and p["output"]["expected_values"][0][0] == 9.5
    request["inputs_grid"] = apply(p["inputs"])
    assert conversion_plan(v, request)["inputs"]["start_row"] == 5


@pytest.mark.parametrize("patch", [
    {"source_currency": "JPY"}, {"source_scale": "hundred"}, {"output_unit": "USD"},
    {"output_sheet": "_VS_STATE"}, {"source_sheet": "MarketInputs"},
    {"source_address": "A:A"}, {"source_address": "A1,B2"}, {"source_address": "C4:B3"},
    {"source_address": "A1:CV21"}, {"output_start": "XFD1048576"},
    {"output_sheet": "sales o'brien", "output_start": "C4"},
    {"expected_source": {"values": [[1]], "formulas": [[1]]}},
    {"expected_output": {"values": [[0, ""], ["", ""]], "formulas": [[0, ""], ["", ""]]}},
    {"expected_output": {"values": [["", ""], ["", ""]], "formulas": [['=""', ""], ["", ""]]}},
    {"acknowledge_warnings": False}, {"market_grid": []},
])
def test_unsafe_conversion_rejected(patch):
    v = view(); request = data(v); request.update(patch)
    with pytest.raises(MarketError):
        conversion_plan(v, request)


@pytest.mark.parametrize("amount", [True, "100", "#VALUE!", "=1+1", float("nan"), float("inf"), 1e308, 1e-320])
def test_invalid_or_unrepresentable_amount_rejected(amount):
    v = view(); request = data(v)
    request["expected_source"]["values"][0][0] = amount
    if amount == 1e-320:
        request.update(source_scale="unit", output_unit="KRW_million")
    with pytest.raises(MarketError):
        conversion_plan(v, request)


def test_blank_only_and_unverified_or_strict_rate_blocked():
    v = view(); request = data(v)
    request["expected_source"]["values"] = [["", ""], [None, ""]]
    with pytest.raises(MarketError):
        conversion_plan(v, request)
    for invalid in (view(DateContract()), view(asof_mode="strict_snapshot")):
        with pytest.raises(MarketError) as err:
            conversion_plan(invalid, data(invalid))
        assert err.value.code == "MARKET_ADOPTION_BLOCKED"


def test_maximum_range_has_compact_fact_and_preserves_source_formula():
    v = view(); request = data(v)
    values = [[1] * 100 for _ in range(20)]
    request.update(source_address="A1:CV20", output_start="A30",
                   expected_source={"values": values, "formulas": copy.deepcopy(values)},
                   expected_output={"values": [[""] * 100 for _ in range(20)], "formulas": [[""] * 100 for _ in range(20)]})
    request["expected_source"]["formulas"][0][0] = "=SUM(D1:D2)"
    p = conversion_plan(v, request)
    assert len(p["facts"]["rows"][0][2]) < 32767
    assert p["source"]["expected"]["formulas"][0][0] == "=SUM(D1:D2)"
