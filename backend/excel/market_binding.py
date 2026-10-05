"""Explicit FX adoption into a stable input cell, with optimistic preconditions."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from ingest.market_data import MarketError, canonical, digest
from .market_sheet import (MARKET_COLUMNS, clean_grid, facts_plan, find_observation,
                           grid, headers, owned)

INPUT_COLUMNS = ["binding_id", "purpose", "currency", "adopted_value", "value_unit",
                 "observation_id", "snapshot_id", "effective_date", "adoption_state", "adopted_at", "reason"]


def target_address(sheet, address):
    if (not isinstance(sheet, str) or not sheet or len(sheet) > 31 or re.search(r"[\[\]:*?/\\\x00-\x1f]", sheet)
            or sheet.lower().startswith("_vs_") or sheet.lower() in ("rmarket", "marketinputs", "claude log")):
        raise MarketError("MARKET_TARGET_INVALID", "일반 모델 시트의 이름을 지정하세요.")
    if not isinstance(address, str) or not re.fullmatch(r"\$?[A-Za-z]{1,3}\$?[1-9][0-9]{0,6}", address):
        raise MarketError("MARKET_TARGET_INVALID", "대상은 A1 형태의 단일 셀이어야 합니다.")
    address = address.upper().replace("$", "")
    col, row = re.fullmatch(r"([A-Z]+)([0-9]+)", address).groups()
    col_no = 0
    for char in col:
        col_no = col_no * 26 + ord(char) - 64
    if col_no > 16384 or int(row) > 1048576:
        raise MarketError("MARKET_TARGET_INVALID", "Excel 주소 범위를 벗어났습니다.")
    return sheet, address


def column_letter(index):
    value, result = index + 1, ""
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(65 + remainder) + result
    return result


def binding_plan(view, data):
    matches = [o for o in view["observations"] if o["observation_id"] == data.get("observation_id")]
    if len(matches) != 1 or not matches[0]["adoption_eligible"] or view["dataset"] != "exchange":
        raise MarketError("MARKET_ADOPTION_BLOCKED", "날짜·단위가 검증된 환율 관측만 반영할 수 있습니다.", 409)
    ob = matches[0]
    if data.get("acknowledge_warnings") is not True:
        raise MarketError("MARKET_ACK_REQUIRED", "관측 경고와 모델 입력 단위를 확인해야 합니다.")
    reason = data.get("reason")
    if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 1000:
        raise MarketError("MARKET_INPUT_INVALID", "채택 사유를 3~1000자로 입력하세요.")
    if data.get("expected_unit") != ob["value_unit"]:
        raise MarketError("MARKET_UNIT_MISMATCH", "대상 셀은 외화 1단위당 원화 단위여야 합니다.")
    sheet, address = target_address(data.get("target_sheet"), data.get("target_address"))
    expected = data.get("expected_target")
    if not isinstance(expected, dict) or set(expected) != {"value", "formula"}:
        raise MarketError("MARKET_INPUT_INVALID", "기존 대상 셀의 값·수식을 다시 읽으세요.")
    grid([[expected["value"], expected["formula"]]])
    raw, inputs = grid(data.get("market_grid", [])), grid(data.get("inputs_grid", []))
    source_row = find_observation(raw, view, ob)
    if source_row is None:
        raise MarketError("MARKET_RAW_REQUIRED", "관측을 먼저 원자료 시트에 기록하세요.", 409)
    has = owned(inputs, "market_inputs_schema", INPUT_COLUMNS)
    columns = inputs[3] if has else INPUT_COLUMNS
    binding_id = digest(["fx_translation", sheet.casefold(), address])
    found = [i + 1 for i, row in enumerate(inputs[4:], 4)
             if len(row) > columns.index("binding_id") and row[columns.index("binding_id")] == binding_id]
    if len(found) > 1:
        raise MarketError("MARKET_BINDING_CONFLICT", "같은 연결 ID가 여러 행에 있습니다.", 409)
    row_no = found[0] if found else max(5, len(clean_grid(inputs)) + 1)
    raw_col = column_letter(raw[3].index("normalized_value"))
    input_col = column_letter(columns.index("adopted_value"))
    source_formula = f"='rMarket'!${raw_col}${source_row}"
    target_formula = f"='MarketInputs'!${input_col}${row_no}"
    rec = dict(binding_id=binding_id, purpose="fx_translation", currency=ob["currency"],
               adopted_value=source_formula, value_unit=ob["value_unit"], observation_id=ob["observation_id"],
               snapshot_id=view["snapshot_id"], effective_date=ob["effective_date"],
               adoption_state="explicit_selection", adopted_at=datetime.now(timezone.utc).isoformat(), reason=reason.strip())
    audit = {"binding_id": binding_id, "old": expected, "new_formula": target_formula,
             "snapshot_id": view["snapshot_id"], "observation_id": ob["observation_id"],
             "target": [sheet, address], "reason": reason.strip(), "unit": ob["value_unit"]}
    # Separate event keys: same numeric value with a new source is still a new decision.
    facts = facts_plan(data.get("facts_grid", []), [{"key": f"market.binding.{binding_id}.{digest(audit)}",
            "value": canonical(audit), "method": "explicit_fx_adoption", "source_id": view["snapshot_id"],
            "locator": f"{sheet}!{address}", "as_of": rec["adopted_at"],
            "confidence": "readback_required", "approval": "adopted"}])
    return {"binding_id": binding_id, "snapshot_id": view["snapshot_id"], "observation_id": ob["observation_id"],
            "expected_market_grid": raw, "inputs": {"sheet": "MarketInputs", "create": not has,
            "header_rows": [] if has else headers("market_inputs_schema", columns), "expected_grid": inputs,
            "start_row": row_no, "rows": [[rec[c] for c in columns]], "formula_column": columns.index("adopted_value")},
            "target": {"sheet": sheet, "address": address, "expected": expected, "formula": target_formula},
            "expected_value": ob["normalized_value"], "facts": facts}
