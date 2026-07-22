"""DART 정기보고서 주요정보 API — 밸류에이션 브리지·감사인 트랙에 쓰는 5종.

[[dart_client]] 이 재무 *숫자*(fnlttSinglAcntAll)를 담당한다면, 여기는 그 숫자만으로는
안 나오는 **구조·귀속 정보**를 담당한다:

  · company            기업개황 — 결산월(acc_mt)로 DCF 기간 정합 게이트
  · audit_opinion      회계감사인·감사의견·강조사항·핵심감사사항(KAM) — 감사인 트랙
  · shares_total       주식총수 — 발행/유통 주식수(D7 주당가치 게이트의 분모)
  · major_shareholders 최대주주 현황 — 지분율·기초/기말 주식수
  · investments        타법인 출자현황 — 장부가액(비영업자산 NOA 실측 시드)
  · dividends          배당에 관한 사항 — 배당성향·주당배당

설계는 [[dart_corp]] 와 동일: **순수 파서 + 네트워크 분리(http_json DI)**. canned JSON 을
주입해 키·네트워크 없이 파싱 전량을 테스트한다. status '013'(조회데이터없음)은 빈 결과로
관대 처리(분·반기 간소화로 항목이 통째로 없을 수 있음 — OpenDART FAQ).

⚠️ 이 API 들은 fnlttSinglAcntAll 과 달리 **원 단위 문자열**(콤마 포함)을 그대로 준다.
숫자화가 필요한 곳은 호출측에서 [[validators]].parse_number 로 게이트를 태운다 —
여기서는 원문 문자열을 보존해 감사추적을 남긴다.
"""
from __future__ import annotations

from typing import Callable

_BASE = "https://opendart.fss.or.kr/api"
JsonHttp = Callable[[str, dict], dict]

# reprt_code: 사업 11011 / 반기 11012 / 1Q 11013 / 3Q 11014
REPRT_ANNUAL = "11011"
# status '013'=조회데이터없음(빈 결과 허용), '000'/None=정상. 그 외는 오류.
_OK_STATUS = (None, "000", "013")


class DartReportError(RuntimeError):
    """DART 주요정보 API 오류(status not in _OK_STATUS)."""
    def __init__(self, status: str | None, message: str | None = None) -> None:
        super().__init__(f"DART status={status}: {message}")
        self.status = status
        self.message = message


def _urllib_json(url: str, params: dict) -> dict:
    import json
    import urllib.parse
    import urllib.request
    qs = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{url}?{qs}", timeout=30) as r:  # noqa: S310
        return json.loads(r.read().decode("utf-8"))


def _get(endpoint: str, params: dict, http: JsonHttp | None) -> dict:
    data = (http or _urllib_json)(f"{_BASE}/{endpoint}", params)
    status = data.get("status")
    if status not in _OK_STATUS:
        raise DartReportError(status, data.get("message"))
    return data


def _rows(data: dict) -> list[dict]:
    """status '013'(데이터없음)이면 list 가 없으므로 빈 리스트."""
    return data.get("list", []) or []


# ── 기업개황 ──────────────────────────────────────────────────────────────────
_COMPANY_FIELDS = {
    "corp_name": "회사명", "corp_name_eng": "영문명", "stock_name": "종목명",
    "stock_code": "종목코드", "ceo_nm": "대표이사", "corp_cls": "법인구분",
    "jurir_no": "법인등록번호", "bizr_no": "사업자등록번호", "adres": "주소",
    "hm_url": "홈페이지", "ir_url": "IR", "phn_no": "전화", "induty_code": "업종코드",
    "est_dt": "설립일", "acc_mt": "결산월",
}
_CORP_CLS = {"Y": "유가증권", "K": "코스닥", "N": "코넥스", "E": "기타"}


def parse_company(data: dict) -> dict:
    """company.json → 정규화 개황. acc_mt(결산월)·est_dt(설립일)는 DCF 기간 정합에 쓴다."""
    out = {k: data.get(k) for k in _COMPANY_FIELDS}
    out["corp_cls_nm"] = _CORP_CLS.get(str(data.get("corp_cls", "")), None)
    return out


def fetch_company(api_key: str, corp_code: str, *,
                  http_json: JsonHttp | None = None) -> dict:
    """기업개황(company.json). corp_code 만으로 조회(연도·보고서 무관)."""
    data = _get("company.json",
                {"crtfc_key": api_key, "corp_code": corp_code}, http_json)
    return parse_company(data)


# ── 회계감사인·감사의견 ────────────────────────────────────────────────────────
def parse_audit_opinion(data: dict) -> list[dict]:
    """accnutAdtorNmNdAdtOpinion.json → 연도별 감사인·의견·강조사항·KAM.

    사업보고서는 최근 3개년을 함께 준다(bsns_year 별 1행). KAM(core_adt_matter)은
    2018 사업연도부터 기재 — 없으면 None.
    """
    return [{
        "bsns_year": r.get("bsns_year"),
        "auditor": r.get("adtor"),
        "opinion": r.get("adt_opinion"),
        "emphasis": r.get("emphs_matter"),
        "specific_matter": r.get("adt_reprt_spcmnt_matter"),
        "kam": r.get("core_adt_matter"),
    } for r in _rows(data)]


def fetch_audit_opinion(api_key: str, corp_code: str, bsns_year: str | int, *,
                        reprt_code: str = REPRT_ANNUAL,
                        http_json: JsonHttp | None = None) -> list[dict]:
    """회계감사인의 명칭 및 감사의견(사업보고서 3개년)."""
    data = _get("accnutAdtorNmNdAdtOpinion.json",
                {"crtfc_key": api_key, "corp_code": corp_code,
                 "bsns_year": str(bsns_year), "reprt_code": reprt_code}, http_json)
    return parse_audit_opinion(data)


# ── 주식총수 (D7 게이트: 발행 vs 유통) ──────────────────────────────────────────
def parse_shares_total(data: dict) -> dict:
    """stockTotqySttus.json → 주식종류별 발행총수·유통주식수 + 합계.

    D7 결함(발행주식수 vs 유통주식수 괴리)의 원천. 주당가치 = 지분가치 / 주식수 인데
    '주식수'가 발행이냐 유통이냐로 갈리므로 **둘 다 보존**하고 괴리는 호출측이 대조한다.
    콤마 포함 원 단위 문자열 그대로 — 숫자화는 호출측 validators.parse_number.
    """
    rows = [{
        "se": r.get("se"),                        # 주식 종류(보통주 등)
        "isu_stock_totqy": r.get("isu_stock_totqy"),        # 발행한 주식의 총수
        "now_to_isu_stock_totqy": r.get("now_to_isu_stock_totqy"),  # 현재 발행주식총수
        "distb_stock_co": r.get("distb_stock_co"),          # 유통주식수
        "tesstk_co": r.get("tesstk_co"),                    # 자기주식수
    } for r in _rows(data)]
    return {"rows": rows}


def fetch_shares_total(api_key: str, corp_code: str, bsns_year: str | int, *,
                       reprt_code: str = REPRT_ANNUAL,
                       http_json: JsonHttp | None = None) -> dict:
    """주식의 총수 현황(stockTotqySttus.json)."""
    data = _get("stockTotqySttus.json",
                {"crtfc_key": api_key, "corp_code": corp_code,
                 "bsns_year": str(bsns_year), "reprt_code": reprt_code}, http_json)
    return parse_shares_total(data)


# ── 최대주주 현황 ──────────────────────────────────────────────────────────────
def parse_major_shareholders(data: dict) -> list[dict]:
    """hyslrSttus.json → 성명·관계·주식종류·기초/기말 주식수·지분율."""
    return [{
        "name": r.get("nm"),
        "relation": r.get("relate"),
        "stock_kind": r.get("stock_knd"),
        "bsis_stock_co": r.get("bsis_posesn_stock_co"),
        "bsis_rate": r.get("bsis_posesn_stock_qota_rt"),
        "trmend_stock_co": r.get("trmend_posesn_stock_co"),
        "trmend_rate": r.get("trmend_posesn_stock_qota_rt"),
    } for r in _rows(data)]


def fetch_major_shareholders(api_key: str, corp_code: str, bsns_year: str | int, *,
                             reprt_code: str = REPRT_ANNUAL,
                             http_json: JsonHttp | None = None) -> list[dict]:
    """최대주주 현황(hyslrSttus.json)."""
    data = _get("hyslrSttus.json",
                {"crtfc_key": api_key, "corp_code": corp_code,
                 "bsns_year": str(bsns_year), "reprt_code": reprt_code}, http_json)
    return parse_major_shareholders(data)


# ── 타법인 출자현황 (NOA 실측 시드) ─────────────────────────────────────────────
def parse_investments(data: dict) -> list[dict]:
    """otrCprInvstmntSttus.json → 법인명·취득일/목적·기말 장부가액·상대법인 실적.

    기말 장부가액(trmend_blce_acntbk_amount)은 비영업투자자산(NOA) 실측의 시드.
    상대법인 총자산·당기순손익은 지분법/블록 밸류에이션 교차검증에 쓴다.
    """
    return [{
        "corp_name": r.get("inv_prm"),
        "first_acqs_de": r.get("frst_acqs_de"),
        "purpose": r.get("invstmnt_purps"),
        "first_acqs_amount": r.get("frst_acqs_amount"),
        "trmend_qty": r.get("trmend_blce_qy"),
        "trmend_book_amount": r.get("trmend_blce_acntbk_amount"),
        "recent_year": r.get("recent_bsns_year"),
        "recent_net_income": r.get("recent_thstrm_ntpf"),
        "recent_total_asset": r.get("recent_total_aset"),
    } for r in _rows(data)]


def fetch_investments(api_key: str, corp_code: str, bsns_year: str | int, *,
                      reprt_code: str = REPRT_ANNUAL,
                      http_json: JsonHttp | None = None) -> list[dict]:
    """타법인 출자현황(otrCprInvstmntSttus.json)."""
    data = _get("otrCprInvstmntSttus.json",
                {"crtfc_key": api_key, "corp_code": corp_code,
                 "bsns_year": str(bsns_year), "reprt_code": reprt_code}, http_json)
    return parse_investments(data)


# ── 배당에 관한 사항 ───────────────────────────────────────────────────────────
def parse_dividends(data: dict) -> list[dict]:
    """alotMatter.json → 배당지표(당기/전기/전전기). se=지표명(주당배당·배당성향 등)."""
    return [{
        "se": r.get("se"),
        "stock_kind": r.get("stock_knd"),
        "thstrm": r.get("thstrm"),
        "frmtrm": r.get("frmtrm"),
        "lwfr": r.get("lwfr"),
    } for r in _rows(data)]


def fetch_dividends(api_key: str, corp_code: str, bsns_year: str | int, *,
                    reprt_code: str = REPRT_ANNUAL,
                    http_json: JsonHttp | None = None) -> list[dict]:
    """배당에 관한 사항(alotMatter.json)."""
    data = _get("alotMatter.json",
                {"crtfc_key": api_key, "corp_code": corp_code,
                 "bsns_year": str(bsns_year), "reprt_code": reprt_code}, http_json)
    return parse_dividends(data)
