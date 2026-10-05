"""KEXIM observations: decimal values, immutable identities, explicit date evidence.

No network calls here. A parsed observation is not an approved model assumption.
The request-date contract defaults to unverified until a live comparison is recorded.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

KST = timezone(timedelta(hours=9))
SCHEMA_VERSION = 1
PARSER_VERSION = "kexim-1"
SUPPORTED_FX = ("USD", "JPY", "EUR")
ENDPOINTS = {
    "exchange": ("exchangeJSON", "AP01", 2),
    "lending": ("interestJSON", "AP02", 3),
    "international": ("internationalJSON", "AP03", 4),
}


class MarketError(Exception):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def iso_date(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise MarketError("MARKET_INPUT_INVALID", "날짜는 YYYY-MM-DD 형식이어야 합니다.")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise MarketError("MARKET_INPUT_INVALID", "유효하지 않은 날짜입니다.") from None


@dataclass(frozen=True)
class MarketQuery:
    dataset: str
    valuation_date: str
    requested_date: str
    date_policy: str = "exact"
    max_lookback_days: int = 7
    asof_mode: str = "historical_reference"
    currencies: tuple[str, ...] = SUPPORTED_FX
    cache_policy: str = "prefer_cache"

    @classmethod
    def parse(cls, data: dict, *, today: date | None = None) -> "MarketQuery":
        if not isinstance(data, dict):
            raise MarketError("MARKET_INPUT_INVALID", "요청은 JSON 객체여야 합니다.")
        dataset = data.get("dataset", "exchange")
        if not isinstance(dataset, str) or dataset not in ENDPOINTS:
            raise MarketError("MARKET_INPUT_INVALID", "지원하지 않는 시장자료 종류입니다.")
        base = iso_date(data.get("valuation_date"))
        requested = iso_date(data.get("requested_date") or base)
        if requested > base or requested > (today or datetime.now(KST).date()).isoformat():
            raise MarketError("MARKET_INPUT_INVALID", "평가기준일 또는 오늘 이후 자료는 조회할 수 없습니다.")
        enums = {"date_policy": ("exact", "previous_available"),
                 "asof_mode": ("historical_reference", "strict_snapshot"),
                 "cache_policy": ("prefer_cache", "refresh", "cache_only")}
        chosen = {}
        for field, values in enums.items():
            chosen[field] = data.get(field, values[0])
            if chosen[field] not in values:
                raise MarketError("MARKET_INPUT_INVALID", f"{field} 값이 올바르지 않습니다.")
        lookback = data.get("max_lookback_days", 7)
        if type(lookback) is not int or not 0 <= lookback <= 7:
            raise MarketError("MARKET_INPUT_INVALID", "이전 관측 탐색은 0~7일만 가능합니다.")
        currencies = data.get("currencies", list(SUPPORTED_FX))
        if (not isinstance(currencies, list) or not currencies
                or any(c not in SUPPORTED_FX for c in currencies)):
            raise MarketError("MARKET_INPUT_INVALID", "통화는 USD·JPY·EUR 중 선택하세요.")
        return cls(dataset, base, requested, max_lookback_days=lookback,
                   currencies=tuple(dict.fromkeys(currencies)), **chosen)


@dataclass(frozen=True)
class DateContract:
    verified: bool = False
    evidence: str = ""
    version: str = "request-date-unverified-1"

    def __post_init__(self):
        if self.verified and not self.evidence.strip():
            raise ValueError("날짜 계약 검증에는 근거가 필요합니다.")


def finding(rule: str, message: str, severity: str = "fail", **detail) -> dict:
    return {"rule": rule, "severity": severity, "message": message, "detail": detail}


def decimal_value(raw: object) -> Decimal | None:
    if raw is None or isinstance(raw, bool):
        return None
    text = str(raw).strip()
    if len(text) > 128:
        return None
    # Market APIs do not use accounting amounts/units; do not accept arbitrary suffixes.
    if not re.fullmatch(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", text):
        return None
    try:
        value = Decimal(text.replace(",", ""))
        return value if value.is_finite() else None
    except InvalidOperation:
        return None


def unpack_payload(raw: bytes) -> list[dict]:
    try:
        data = json.loads(raw.decode("utf-8-sig"),
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError):
        raise MarketError("KEXIM_PAYLOAD_INVALID", "수출입은행 응답을 읽을 수 없습니다.", 502) from None
    if data is None or data == []:
        return []
    rows = [data] if isinstance(data, dict) else data
    if not isinstance(rows, list) or not rows or any(not isinstance(r, dict) for r in rows):
        raise MarketError("KEXIM_PAYLOAD_INVALID", "수출입은행 응답 구조가 변경되었습니다.", 502)
    rows = [{str(k).lower(): v for k, v in row.items()} for row in rows]
    errors = {"2": ("KEXIM_DATA_CODE_INVALID", "수출입은행 API 코드 오류입니다.", 502),
              "3": ("KEXIM_AUTH_INVALID", "수출입은행 인증키를 확인하세요.", 401),
              "4": ("KEXIM_QUOTA_EXHAUSTED", "수출입은행 일일 호출 한도가 소진되었습니다.", 429)}
    for row in rows:
        code = str(row.get("result", ""))
        if code in errors:
            raise MarketError(*errors[code])
        if code != "1":
            raise MarketError("KEXIM_PAYLOAD_INVALID", "알 수 없는 수출입은행 결과 코드입니다.", 502)
    if not isinstance(data, list):
        raise MarketError("KEXIM_PAYLOAD_INVALID", "정상 응답은 관측 배열이어야 합니다.", 502)
    return rows


def normalize_snapshot(raw: bytes, dataset: str, requested_date: str, fetched_at: str,
                       contract: DateContract = DateContract()) -> dict:
    rows = unpack_payload(raw)
    payload_hash = hashlib.sha256(raw).hexdigest()
    snapshot_id = digest(["kexim", dataset, requested_date, payload_hash, PARSER_VERSION,
                          contract.version, contract.verified, contract.evidence])
    observations = []
    for index, row in enumerate(rows):
        issues = []
        field = "deal_bas_r" if dataset == "exchange" else "int_r"
        raw_value = row.get(field)
        value = decimal_value(raw_value)
        if value is None:
            issues.append(finding("market_numeric_invalid", "숫자를 정규화할 수 없습니다."))
        currency, quote_unit, unit = None, None, None
        if dataset == "exchange":
            match = re.fullmatch(r"([A-Z]{3})(?:\((\d{1,4})\))?", str(row.get("cur_unit", "")))
            if match:
                currency, quote_unit = match[1], int(match[2] or 1)
            if not match or quote_unit not in (1, 100):
                issues.append(finding("market_unit_unknown", "환율 통화·배율을 확인해야 합니다."))
            else:
                unit = f"KRW_per_1_{currency}"
                if value is not None:
                    value /= Decimal(quote_unit)
            if value is not None and value <= 0:
                issues.append(finding("market_fx_nonpositive", "환율은 0보다 커야 합니다."))
            if currency not in SUPPORTED_FX:
                issues.append(finding("market_currency_unsupported", "초기 지원 통화가 아닙니다."))
        else:
            # Do not invent a benchmark/currency/percent scale from incomplete labels.
            issues.extend([finding("market_benchmark_unknown", "금리 종류·통화·만기 매핑을 확인해야 합니다."),
                           finding("market_unit_unknown", "금리 표시단위를 확인해야 합니다.")])
        if not contract.verified:
            issues.append(finding("market_date_unverified", "검색일과 적용일의 대응은 아직 실검증 전입니다."))
        observations.append({
            "observation_id": digest([snapshot_id, index, field]), "snapshot_id": snapshot_id,
            "provider": "kexim", "dataset": dataset, "requested_date": requested_date,
            "effective_date": requested_date if contract.verified else None,
            "effective_date_basis": "validated_request_contract" if contract.verified else "unverified_request_contract",
            "date_evidence": contract.evidence, "published_at": None, "fetched_at": fetched_at,
            "currency": currency, "currency_label": str(row.get("cur_unit", row.get("cur_fund", ""))),
            "benchmark": None, "tenor_label": str(row.get("sfln_intrc_nm", "")),
            "rate_type": None, "quote_unit": quote_unit, "source_field": field,
            "raw_value": "" if raw_value is None else str(raw_value),
            "normalized_value": str(value) if value is not None and unit else None,
            "value_unit": unit, "observation_status": "quarantined" if value is None else "parsed",
            "vintage_status": "unknown", "findings": issues,
        })
    return {"schema_version": SCHEMA_VERSION, "provider": "kexim", "dataset": dataset,
            "requested_date": requested_date, "fetched_at": fetched_at,
            "snapshot_id": snapshot_id, "payload_sha256": payload_hash,
            "parser_version": PARSER_VERSION, "date_policy_version": contract.version,
            "source_url": f"https://www.koreaexim.go.kr/ir/HPHKIR020M01?apino={ENDPOINTS[dataset][2]}&viewtype=C",
            "observations": observations}


def assess_snapshot(snapshot: dict, query: MarketQuery) -> dict:
    """Return a per-valuation view without changing the stored observations."""
    out = copy.deepcopy(snapshot)
    kept = []
    for ob in out["observations"]:
        if query.dataset == "exchange" and ob["currency"] not in query.currencies:
            continue
        issues = ob["findings"]
        if ob["effective_date"] and ob["effective_date"] > query.valuation_date:
            issues.append(finding("market_lookahead", "평가기준일 이후 관측입니다."))
        issues.append(finding("market_publication_unknown", "당시 공표·개정 이력은 확인되지 않았습니다.",
                              "fail" if query.asof_mode == "strict_snapshot" else "warn"))
        if snapshot["requested_date"] != query.requested_date:
            issues.append(finding("market_date_fallback", "선택한 정책에 따라 이전 날짜 자료를 사용합니다.", "warn",
                                  requested=query.requested_date, selected=snapshot["requested_date"]))
        ob["blocking_rules"] = [f["rule"] for f in issues if f["severity"] == "fail"]
        ob["adoption_eligible"] = not ob["blocking_rules"]
        kept.append(ob)
    out["observations"] = kept
    out["valuation_date"] = query.valuation_date
    out["asof_mode"] = query.asof_mode
    out["selected_request_date"] = snapshot["requested_date"]
    out["requested_date"] = query.requested_date
    out["findings"] = []
    if query.dataset == "exchange":
        missing = sorted(set(query.currencies) - {o["currency"] for o in kept})
        if missing:
            out["findings"].append(finding("market_currency_missing", "일부 요청 통화가 응답에 없습니다.", currencies=missing))
    out["status"] = ("no_data" if not snapshot["observations"] else
                     "partial" if out["findings"] or any(not o["adoption_eligible"] for o in kept) else "ok")
    out["source_status"] = "api_response"
    return out
