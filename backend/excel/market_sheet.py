"""Append-only market observations and facts. Plans never delete worksheets."""
from __future__ import annotations

import math

from ingest.market_data import MarketError
from .facts_sheet import build_append, header_rows as facts_header

MARKET_COLUMNS = ["observation_id", "snapshot_id", "provider", "dataset", "requested_date",
                  "effective_date", "effective_date_basis", "published_at", "fetched_at",
                  "currency", "benchmark", "tenor_label", "rate_type", "quote_unit",
                  "source_field", "raw_value", "normalized_value", "value_unit",
                  "observation_status", "vintage_status", "rule_ids", "source_url", "payload_sha256"]


def grid(value) -> list[list]:
    if not isinstance(value, list) or len(value) > 20000:
        raise MarketError("MARKET_GRID_INVALID", "시트 격자 크기·형식이 올바르지 않습니다.")
    for row in value:
        if not isinstance(row, list) or len(row) > 100:
            raise MarketError("MARKET_GRID_INVALID", "시트 열 형식이 올바르지 않습니다.")
        for cell in row:
            if not (cell is None or type(cell) in (str, int, float, bool)):
                raise MarketError("MARKET_GRID_INVALID", "시트 셀은 단일 값이어야 합니다.")
            if isinstance(cell, str) and len(cell) > 32767 or isinstance(cell, float) and not math.isfinite(cell):
                raise MarketError("MARKET_GRID_INVALID", "시트 셀 값이 올바르지 않습니다.")
    return value


def cells(row):
    out = ["" if v is None else str(v) if not isinstance(v, float) or not v.is_integer() else str(int(v)) for v in row]
    while out and out[-1] == "":
        out.pop()
    return out


def clean_grid(rows):
    out = [cells(row) for row in grid(rows)]
    while out and not out[-1]:
        out.pop()
    return out


def owned(existing, schema, columns):
    rows = clean_grid(existing)
    if not rows:
        return False
    if len(rows) < 4 or rows[0] != [schema, "1"] or rows[1] != ["owner", "val-studio"]:
        raise MarketError("MARKET_SHEET_OWNER_CONFLICT", "시트 소유자·스키마가 달라 기록하지 않았습니다.", 409)
    if len(rows[3]) != len(columns) or set(rows[3]) != set(columns):
        raise MarketError("MARKET_SHEET_HEADER_CONFLICT", "시트 열 이름이 변경되어 기록을 중단했습니다.", 409)
    return True


def headers(schema, columns):
    return [[schema, 1], ["owner", "val-studio"], ["ValStudio 시장자료"], columns]


def observation_record(view, ob):
    # Store intrinsic findings only: changing valuation/date mode must not rewrite raw rows.
    rec = dict(ob)
    rec["requested_date"] = view.get("selected_request_date", ob["requested_date"])
    rec["rule_ids"] = ",".join(f["rule"] for f in ob["findings"] if f["rule"] not in
                             ("market_publication_unknown", "market_date_fallback", "market_lookahead", "market_contract_changed"))
    rec.update(source_url=view["source_url"], payload_sha256=view["payload_sha256"])
    rec["normalized_value"] = float(ob["normalized_value"]) if ob["normalized_value"] is not None else ""
    if isinstance(rec["normalized_value"], float) and not math.isfinite(rec["normalized_value"]):
        raise MarketError("MARKET_NUMERIC_RANGE", "Excel에 기록할 수 있는 숫자 범위를 벗어났습니다.")
    return rec


def find_observation(existing, view, ob):
    if not owned(existing, "market_schema", MARKET_COLUMNS):
        return None
    cols = existing[3]
    rec = observation_record(view, ob)
    expected = [rec.get(c) if rec.get(c) is not None else "" for c in cols]
    hits = [(i + 1, row) for i, row in enumerate(existing[4:], 4)
            if len(row) > cols.index("observation_id") and row[cols.index("observation_id")] == ob["observation_id"]]
    if len(hits) > 1 or any(cells(row) != cells(expected) for _, row in hits):
        raise MarketError("MARKET_OBSERVATION_CONFLICT", "같은 관측 ID의 셀이 원본과 다릅니다. 원자료를 확인하세요.", 409)
    return hits[0][0] if hits else None


def facts_plan(existing, facts):
    grid(existing)
    rows = clean_grid(existing)
    if rows and (len(rows) < 4 or rows[0] != ["facts_schema", "1"] or rows[1] != ["owner", "val-studio"]
                 or rows[3] != cells(facts_header()[3])):
        raise MarketError("MARKET_FACTS_CONFLICT", "사실 원장의 소유자·열을 확인하세요.", 409)
    plan = build_append(existing, facts)
    if plan["blocked"]:
        raise MarketError("MARKET_FACTS_CONFLICT", plan["reason"], 409)
    plan["expected_grid"] = existing
    return plan


def append_plan(view, existing, facts_existing):
    existing = grid(existing)
    has = owned(existing, "market_schema", MARKET_COLUMNS)
    columns = existing[3] if has else MARKET_COLUMNS
    start = max(len(clean_grid(existing)) + 1, 5)
    rows, facts = [], []
    for ob in view["observations"]:
        row_no = find_observation(existing, view, ob) if has else None
        if row_no is None:
            rec = observation_record(view, ob)
            row_no = start + len(rows)
            rows.append([rec.get(c) if rec.get(c) is not None else "" for c in columns])
        facts.append({"key": f"market.kexim.{ob['dataset']}.{ob['snapshot_id']}.{ob['observation_id']}",
                      "value": ob["normalized_value"] if ob["normalized_value"] is not None else ob["raw_value"],
                      "method": "kexim_observation", "source_id": ob["snapshot_id"],
                      "locator": f"rMarket!{row_no};{ob['source_field']};{ob.get('value_unit') or 'unit_unknown'}",
                      "as_of": ob["fetched_at"], "confidence": "source_response", "approval": "suggested"})
    return {"market": {"sheet": "rMarket", "create": not has,
                        "header_rows": [] if has else headers("market_schema", columns),
                        "expected_grid": existing, "start_row": start, "rows": rows},
            "facts": facts_plan(facts_existing, facts), "snapshot_id": view["snapshot_id"]}
