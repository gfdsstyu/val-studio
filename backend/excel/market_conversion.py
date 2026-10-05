"""Foreign amounts -> KRW range plan. No source writes or currency inference."""
from __future__ import annotations

import math
from decimal import Decimal
from sys import float_info

from ingest.market_data import MarketError, canonical, digest
from .market_binding import adoption_input_plan, column_letter, target_address
from .market_sheet import facts_plan, grid

SOURCE_SCALES = {"unit": 1, "thousand": 1000, "million": 1000000}
OUTPUT_SCALES = {"KRW": 1, "KRW_thousand": 1000, "KRW_million": 1000000}
MAX_CELLS = 2000


def box(sheet, address):
    if not isinstance(address, str) or len(address.split(":")) not in (1, 2):
        raise MarketError("MARKET_RANGE_INVALID", "A1 또는 A1:B10 형태의 연속 범위를 지정하세요.")
    parts = [target_address(sheet, part)[1] for part in address.split(":")]
    def index(cell):
        col = "".join(c for c in cell if c.isalpha())
        n = 0
        for c in col:
            n = n * 26 + ord(c) - 64
        return int(cell[len(col):]) - 1, n - 1
    r, c = index(parts[0]); end_r, end_c = index(parts[-1])
    height, width = end_r - r + 1, end_c - c + 1
    if min(height, width) < 1 or width > 100 or height * width > MAX_CELLS:
        raise MarketError("MARKET_RANGE_INVALID", "환산 범위는 최대 2,000셀·100열이며 역방향 주소는 사용할 수 없습니다.")
    return {"sheet": sheet, "address": parts[0] + (":" + parts[-1] if height * width > 1 else ""),
            "row": r, "column": c, "height": height, "width": width}


def expected_range(value, shape):
    if not isinstance(value, dict) or set(value) != {"values", "formulas"}:
        raise MarketError("MARKET_RANGE_INVALID", "범위의 값과 수식을 다시 읽으세요.")
    for key in ("values", "formulas"):
        rows = grid(value[key])
        if len(rows) != shape["height"] or any(len(row) != shape["width"] for row in rows):
            raise MarketError("MARKET_RANGE_INVALID", "읽은 값·수식의 크기가 지정한 범위와 다릅니다.")
    return value


def overlaps(a, b):
    return (a["sheet"].casefold() == b["sheet"].casefold()
            and a["row"] < b["row"] + b["height"] and b["row"] < a["row"] + a["height"]
            and a["column"] < b["column"] + b["width"] and b["column"] < a["column"] + a["width"])


def conversion_plan(view, data):
    source = box(data.get("source_sheet"), data.get("source_address"))
    target_sheet, start = target_address(data.get("output_sheet"), data.get("output_start"))
    first = box(target_sheet, start)
    last = column_letter(first["column"] + source["width"] - 1) + str(first["row"] + source["height"])
    target = box(target_sheet, start + ":" + last)
    if overlaps(source, target):
        raise MarketError("MARKET_RANGE_OVERLAP", "원본과 출력 범위가 겹칩니다. 별도 출력 범위를 지정하세요.")
    source["expected"] = expected_range(data.get("expected_source"), source)
    target["expected"] = expected_range(data.get("expected_output"), target)
    if any(v not in (None, "") for rows in target["expected"].values() for row in rows for v in row):
        raise MarketError("MARKET_OUTPUT_NOT_EMPTY", "출력 범위는 값과 수식이 없는 빈 범위여야 합니다.", 409)
    in_unit, out_unit = data.get("source_scale"), data.get("output_unit")
    if not isinstance(in_unit, str) or in_unit not in SOURCE_SCALES or not isinstance(out_unit, str) or out_unit not in OUTPUT_SCALES:
        raise MarketError("MARKET_UNIT_MISMATCH", "외화 원본 단위와 원화 출력 단위를 지정하세요.")
    conversion_id = digest(["fx_range_conversion", source["sheet"].casefold(), source["address"],
                            target["sheet"].casefold(), target["address"], data.get("source_currency"), in_unit, out_unit])
    ob, raw, inputs, rate_formula, rec = adoption_input_plan(view, data, conversion_id, "fx_range_conversion")
    if data.get("source_currency") != ob["currency"]:
        raise MarketError("MARKET_UNIT_MISMATCH", "원본 통화와 선택한 환율 통화가 다릅니다.")
    rate = Decimal(ob["normalized_value"])
    in_scale, out_scale = SOURCE_SCALES[in_unit], OUTPUT_SCALES[out_unit]
    formulas, amounts, numeric_count = [], [], 0
    for r, row in enumerate(source["expected"]["values"]):
        formula_row, amount_row = [], []
        for c, value in enumerate(row):
            blank = value is None or value == ""
            if not blank and type(value) not in (int, float):
                raise MarketError("MARKET_AMOUNT_INVALID", "원본에는 숫자·빈 셀만 사용할 수 있습니다. 텍스트·오류·논리값을 제외하세요.")
            result = ""
            if not blank:
                try:
                    base = Decimal(str(value))
                    scaled = base * in_scale
                    multiplied = scaled * rate
                    exact = multiplied / out_scale
                    result = float(exact)
                    # Check intermediate operations too; Excel does not store subnormal numbers.
                    if any(not math.isfinite(float(n)) or n != 0 and abs(float(n)) < float_info.min
                           for n in (base, scaled, multiplied, exact)):
                        raise ValueError()
                except (ValueError, OverflowError):
                    raise MarketError("MARKET_AMOUNT_INVALID", "환산 결과가 Excel 숫자 범위를 벗어납니다.") from None
                numeric_count += 1
            address = "$" + column_letter(source["column"] + c) + "$" + str(source["row"] + r + 1)
            ref = "'" + source["sheet"].replace("'", "''") + "'!" + address
            formula_row.append(f'=IF({ref}="","",{ref}*{in_scale}*{rate_formula[1:]}/{out_scale})')
            amount_row.append(result)
        formulas.append(formula_row); amounts.append(amount_row)
    if not numeric_count:
        raise MarketError("MARKET_AMOUNT_INVALID", "원본 범위에 환산할 숫자가 없습니다.")
    target.update(formulas=formulas, expected_values=amounts)
    # Keep one fact cell below Excel's text limit even for the maximum range.
    audit = {"conversion_id": conversion_id,
             "source": {k: source[k] for k in ("sheet", "address", "height", "width")},
             "output": {k: target[k] for k in ("sheet", "address", "height", "width")},
             "source_values_sha256": digest(source["expected"]["values"]),
             "source_formulas_sha256": digest(source["expected"]["formulas"]),
             "output_values_sha256": digest(amounts), "output_formulas_sha256": digest(formulas),
             "numeric_count": numeric_count,
             "currency": ob["currency"], "source_scale": in_unit, "output_unit": out_unit,
             "snapshot_id": view["snapshot_id"], "observation_id": ob["observation_id"],
             "rate": ob["normalized_value"], "effective_date": ob["effective_date"], "reason": rec["reason"]}
    facts = facts_plan(data.get("facts_grid", []), [{"key": f"market.conversion.{conversion_id}.{digest(audit)}",
                       "value": canonical(audit), "method": "explicit_fx_range_conversion",
                       "source_id": view["snapshot_id"], "locator": f"{target_sheet}!{target['address']}",
                       "as_of": rec["adopted_at"], "confidence": "formula_value_verified", "approval": "adopted"}])
    return {"conversion_id": conversion_id, "snapshot_id": view["snapshot_id"], "observation_id": ob["observation_id"],
            "expected_market_grid": raw, "inputs": inputs, "source": source, "output": target,
            "currency": ob["currency"], "source_scale": in_unit, "output_unit": out_unit,
            "expected_rate": ob["normalized_value"], "effective_date": ob["effective_date"], "facts": facts}
