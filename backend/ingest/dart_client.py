"""OpenDART 클라이언트 — 공시 재무제표를 출처추적 값으로 인제스트.

설계:
  - HTTP 주입(DI): `http` 콜러블(url, params)->dict 를 받아 기본은 stdlib urllib.
    테스트는 canned JSON 을 주입해 API 키·네트워크 없이 파싱 로직 전량 검증.
  - 단위 자동정규화: DART 는 전부 '원' → parse_number(unit='원')이 백만원 환산 →
    calc_core(백만원 기준)에 바로 투입.
  - 출처: SourceKind.DART, method STRUCTURED, locator(rcept_no + account_id).

API 키 발급: https://opendart.fss.or.kr (crtfc_key). 키 없이도 import·mock 테스트 가능.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from .parsers.base import BaseParser, ParseResult
from .provenance import ExtractMethod, Locator, SourceKind

if TYPE_CHECKING:
    from .dart_employee import EmployeeSnapshot

HttpFn = Callable[[str, dict], dict]

# reprt_code: 사업보고서 11011 / 반기 11012 / 1분기 11013 / 3분기 11014
REPRT_ANNUAL = "11011"
# fs_div: 연결 CFS / 별도 OFS
FS_CONSOLIDATED = "CFS"


class DartError(RuntimeError):
    """DART API 오류(status != '000'). status 코드 + 메시지 보존."""
    def __init__(self, status: str, message: str | None = None) -> None:
        super().__init__(f"DART status={status}: {message}")
        self.status = status
        self.message = message


@dataclass
class DartClient:
    """OpenDART 재무제표 조회. http 를 주입하면 네트워크 없이 테스트 가능."""
    api_key: str
    base_url: str = "https://opendart.fss.or.kr/api"
    http: HttpFn | None = None

    def __post_init__(self) -> None:
        if self.http is None:
            self.http = self._urllib_http

    # ── HTTP ─────────────────────────────────────────────────────────────────
    @staticmethod
    def _urllib_http(url: str, params: dict) -> dict:
        import json
        import urllib.parse
        import urllib.request
        qs = urllib.parse.urlencode(params)
        with urllib.request.urlopen(f"{url}?{qs}", timeout=30) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8"))

    def _get(self, endpoint: str, **params) -> dict:
        params["crtfc_key"] = self.api_key
        data = self.http(f"{self.base_url}/{endpoint}", params)  # type: ignore[misc]
        status = data.get("status")
        # '000'=정상, '013'=조회데이터없음(빈 결과로 처리 가능하나 여기선 오류로)
        if status not in (None, "000"):
            raise DartError(status, data.get("message"))
        return data

    # ── 재무제표 ──────────────────────────────────────────────────────────────
    def financial_statements(
        self,
        corp_code: str,
        bsns_year: str | int,
        *,
        reprt_code: str = REPRT_ANNUAL,
        fs_div: str = FS_CONSOLIDATED,
    ) -> ParseResult:
        """단일회사 전체 재무제표(fnlttSinglAcntAll) → 계정별 ProvenancedValue.

        당기금액(thstrm_amount)을 백만원으로 정규화해 방출. 각 값은 rcept_no·account_id
        출처를 갖는다. 반환 ParseResult 의 report.ok 로 인제스트 게이트.
        """
        data = self._get(
            "fnlttSinglAcntAll.json",
            corp_code=corp_code, bsns_year=str(bsns_year),
            reprt_code=reprt_code, fs_div=fs_div,
        )
        parser = DartFsParser(source_id=f"DART:{corp_code}:{bsns_year}")
        return parser.extract(data.get("list", []))

    # ── 직원현황 ──────────────────────────────────────────────────────────────
    def employee_status(
        self,
        corp_code: str,
        bsns_year: str | int,
        *,
        reprt_code: str = REPRT_ANNUAL,
    ) -> "EmployeeSnapshot":
        """직원현황(empSttus) → 총인원·급여총액·인당급여 집계(noumbi headcount 드라이버 시드).

        cost_build headcount 드라이버 base(인원×인당급여)와 노무비 cross-source tie-out
        (주석 급여 vs DART 급여총액)에 쓰인다. 반환 snapshot.report.ok 로 게이트.
        """
        from .dart_employee import EmployeeSnapshot, aggregate_employee_status  # 순환참조 회피
        data = self._get(
            "empSttus.json",
            corp_code=corp_code, bsns_year=str(bsns_year), reprt_code=reprt_code,
        )
        return aggregate_employee_status(
            data.get("list", []),
            source_id=f"DART:{corp_code}:{bsns_year}:emp", year=str(bsns_year),
        )


class DartFsParser(BaseParser):
    """DART fnlttSinglAcntAll 응답의 list[] 행 → 계정별 값(백만원, 출처부착).

    행 필드: account_nm(계정명·한글), account_id(표준코드), thstrm_amount(당기금액·원),
    sj_div(BS/IS/CF/CIS), rcept_no(접수번호). '-'/공백은 blank 로 기록(오제외 방지).
    """
    source_kind = SourceKind.DART
    default_method = ExtractMethod.STRUCTURED

    def extract(self, raw: object) -> ParseResult:
        rows = raw if isinstance(raw, list) else []
        for row in rows:
            name = str(row.get("account_nm", "")).strip() or row.get("account_id", "?")
            field_name = f"{row.get('sj_div', '')}:{name}".strip(":")
            self.emit_blank_aware(
                field_name,
                row.get("thstrm_amount"),
                unit="원",                       # DART 원 단위 → 백만원 자동환산
                locator=Locator(
                    rcept_no=row.get("rcept_no"),
                    account_id=row.get("account_id"),
                ),
                note=f"sj_div={row.get('sj_div')}",
            )
        return self.result


def pick(result: ParseResult, *account_substrings: str) -> dict[str, object]:
    """ParseResult 에서 계정명 부분일치로 값 골라오기(calc_core 투입용 편의).

    예: pick(fs, '수익', '영업이익') → {'매출':Decimal, '영업이익':Decimal}. 첫 매치 우선.
    """
    out: dict[str, object] = {}
    for sub in account_substrings:
        for pv in result.values:
            if sub in pv.field_name and pv.value is not None:
                out[sub] = pv.value
                break
    return out
