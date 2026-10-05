"""Key-scoped KEXIM HTTP access. Exceptions never contain upstream URLs/keys."""
from __future__ import annotations

import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from .market_data import ENDPOINTS, MarketError, canonical, unpack_payload

BASE_URL = "https://oapi.koreaexim.go.kr/site/program/financial/"
MAX_BYTES = 2 * 1024 * 1024


def urllib_http(url: str, params: dict, timeout: float) -> bytes:
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params),
                                 headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read(MAX_BYTES + 1)


class KeximClient:
    def __init__(self, http: Callable = urllib_http, sleep: Callable = time.sleep,
                 monotonic: Callable = time.monotonic):
        self.http, self.sleep, self.monotonic = http, sleep, monotonic

    def fetch(self, dataset: str, requested_date: str, api_key: str, *,
              deadline: float, before_call: Callable = lambda: None) -> bytes:
        if not isinstance(api_key, str) or not api_key.strip() or len(api_key) > 512:
            raise MarketError("KEXIM_AUTH_REQUIRED", "수출입은행 API 키를 설정하세요.", 401)
        if dataset not in ENDPOINTS:
            raise MarketError("MARKET_INPUT_INVALID", "지원하지 않는 자료입니다.")
        endpoint, code, _ = ENDPOINTS[dataset]
        params = {"authkey": api_key.strip(), "searchdate": requested_date.replace("-", ""), "data": code}
        for attempt in range(3):
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                raise MarketError("KEXIM_TIMEOUT", "시장자료 요청 시간이 초과되었습니다.", 504)
            before_call()
            try:
                raw = self.http(BASE_URL + endpoint, params, min(15.0, remaining))
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    raise MarketError("KEXIM_QUOTA_EXHAUSTED", "수출입은행 호출 한도를 확인하세요.", 429) from None
                if exc.code not in (408, 500, 502, 503, 504):
                    raise MarketError("KEXIM_UNAVAILABLE", "수출입은행 서버가 요청을 거부했습니다.", 503) from None
                timed_out = exc.code == 408
            except (TimeoutError, socket.timeout):
                timed_out = True
            except (urllib.error.URLError, OSError):
                timed_out = False
            else:
                if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
                    raise MarketError("KEXIM_PAYLOAD_INVALID", "시장자료 응답 크기·형식을 확인하세요.", 502)
                if api_key.strip().encode() in raw:
                    raise MarketError("KEXIM_PAYLOAD_INVALID", "응답에 인증정보가 포함되어 저장하지 않았습니다.", 502)
                rows = unpack_payload(raw)  # result 2/3/4 are terminal, not retryable network failures.
                if api_key.strip() in canonical(rows):
                    raise MarketError("KEXIM_PAYLOAD_INVALID", "응답에 인증정보가 포함되어 저장하지 않았습니다.", 502)
                return raw
            if attempt == 2:
                raise MarketError("KEXIM_TIMEOUT" if timed_out else "KEXIM_UNAVAILABLE",
                                  "수출입은행 응답을 받지 못했습니다.", 504 if timed_out else 503) from None
            delay = attempt + 1
            if self.monotonic() + delay >= deadline:
                raise MarketError("KEXIM_TIMEOUT", "시장자료 요청 시간이 초과되었습니다.", 504) from None
            self.sleep(delay)
        raise AssertionError("unreachable")
