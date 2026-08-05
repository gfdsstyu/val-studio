"""DART 보조 API — 기업코드 검색(corpCode.xml) · 공시목록(list.json) · 원본문서(document.xml).

- corp_code 검색: DART 는 종목코드가 아니라 8자리 corp_code 로 조회한다. corpCode.xml
  (~10만사 매핑 zip)을 한 번 받아 캐시하고 회사명으로 검색한다(BYOK 키는 최초 1회만).
- 공시목록: list.json 으로 corp_code 의 제출 공시(rcept_no·보고서명·접수일)를 조회.
- 원본문서: document.xml 은 접수번호(rcept_no)의 원본 공시를 zip 으로 반환(바이너리).

파싱은 순수 함수로 분리 — 네트워크·키 없이 canned 입력으로 테스트(DartClient DI 패턴).
"""
from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import Callable

_BASE = "https://opendart.fss.or.kr/api"
BytesHttp = Callable[[str, dict], bytes]
JsonHttp = Callable[[str, dict], dict]


# ── 순수 파서 (테스트 가능) ───────────────────────────────────────────────────
def parse_corp_index(xml_bytes: bytes) -> list[dict]:
    """CORPCODE.xml 원문 → [{corp_code, corp_name, stock_code, modify_date}].

    DART corpCode.xml 구조: <result><list><corp_code/><corp_name/><stock_code/>
    <modify_date/></list>...</result>. stock_code 공백=비상장.
    """
    root = ET.fromstring(xml_bytes)
    out: list[dict] = []
    for el in root.iter("list"):
        out.append({
            "corp_code": (el.findtext("corp_code") or "").strip(),
            "corp_name": (el.findtext("corp_name") or "").strip(),
            "stock_code": (el.findtext("stock_code") or "").strip(),
            "modify_date": (el.findtext("modify_date") or "").strip(),
        })
    return out


def extract_corpcode_zip(zip_bytes: bytes) -> list[dict]:
    """corpCode.xml API 응답(zip) → 파싱된 인덱스. zip 내 CORPCODE.xml 을 찾아 파싱."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        name = next((n for n in zf.namelist() if n.lower().endswith(".xml")), None)
        if name is None:
            raise ValueError("corpCode zip 에 XML 없음")
        return parse_corp_index(zf.read(name))


#: 검색 축. `auto` 는 입력 모양으로 판정한다 — 실무자는 회사명·종목코드·고유번호를
#: 구분 없이 한 칸에 친다(동종 상용 툴의 "OO주식회사 (또는 종목/고유번호)" 입력 관행).
SEARCH_BY = ("auto", "name", "stock", "corp")


def infer_search_by(query: str) -> str:
    """입력 모양 → 검색 축. 숫자 8자리=고유번호, 6자리=종목코드, 그 외=회사명."""
    q = query.strip()
    if q.isdigit():
        if len(q) == 8:
            return "corp"
        if len(q) == 6:
            return "stock"
    return "name"


def search_corp(index: list[dict], query: str, *, limit: int = 30,
                listed_only: bool = False, by: str = "auto") -> tuple[list[dict], int, str]:
    """회사 검색 → (상위 limit 건, **전체 매칭 건수**, 실제 사용한 축).

    매칭 건수를 함께 돌려주는 이유: limit 로 잘렸는지를 호출부가 알아야 한다.
    잘린 사실을 숨기면 "결과가 이게 다"로 읽혀 엉뚱한 후보를 고르게 된다.
    """
    q = query.strip()
    if not q:
        return [], 0, "name"
    axis = infer_search_by(q) if by == "auto" else by
    if axis == "corp":
        hits = [c for c in index if c["corp_code"] == q]
    elif axis == "stock":
        hits = [c for c in index if c["stock_code"] and c["stock_code"] == q]
    else:
        hits = [c for c in index if q in c["corp_name"]]
    if listed_only:
        hits = [c for c in hits if c["stock_code"]]

    def rank(c: dict) -> tuple:
        return (c["corp_name"] != q,          # 정확일치 먼저
                not c["stock_code"],           # 상장사 먼저
                len(c["corp_name"]))           # 짧은 이름 먼저
    return sorted(hits, key=rank)[:limit], len(hits), axis


def search_corp_index(index: list[dict], query: str, *, limit: int = 30,
                      listed_only: bool = False) -> list[dict]:
    """회사명 부분일치 검색(하위호환 래퍼) — 결과 목록만."""
    return search_corp(index, query, limit=limit, listed_only=listed_only, by="name")[0]


# ── 네트워크 (BYOK 키 주입) ───────────────────────────────────────────────────
def _urllib_bytes(url: str, params: dict) -> bytes:
    import urllib.parse
    import urllib.request
    qs = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{url}?{qs}", timeout=60) as r:  # noqa: S310
        return r.read()


def _urllib_json(url: str, params: dict) -> dict:
    import json
    import urllib.parse
    import urllib.request
    qs = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{url}?{qs}", timeout=30) as r:  # noqa: S310
        return json.loads(r.read().decode("utf-8"))


def fetch_corp_index(api_key: str, *, http_bytes: BytesHttp | None = None) -> list[dict]:
    """corpCode.xml 다운로드 → 파싱된 인덱스(~10만사). 캐시는 상위(API)에서."""
    http = http_bytes or _urllib_bytes
    return extract_corpcode_zip(http(f"{_BASE}/corpCode.xml", {"crtfc_key": api_key}))


def list_filings(api_key: str, corp_code: str, *, bgn_de: str, end_de: str | None = None,
                 pblntf_ty: str | None = None, page_count: int = 30,
                 http_json: JsonHttp | None = None) -> list[dict]:
    """list.json 공시검색 → [{rcept_no, report_nm, rcept_dt, flr_nm}].

    bgn_de/end_de = YYYYMMDD. pblntf_ty: 'A'(정기공시) 등 공시유형 필터(선택).
    """
    http = http_json or _urllib_json
    params = {"crtfc_key": api_key, "corp_code": corp_code, "bgn_de": bgn_de,
              "page_count": page_count}
    if end_de:
        params["end_de"] = end_de
    if pblntf_ty:
        params["pblntf_ty"] = pblntf_ty
    data = http(f"{_BASE}/list.json", params)
    status = data.get("status")
    if status not in (None, "000", "013"):        # 013=조회데이터없음(빈 목록 허용)
        raise RuntimeError(f"DART list status={status}: {data.get('message')}")
    return [{"rcept_no": r.get("rcept_no"), "report_nm": r.get("report_nm"),
             "rcept_dt": r.get("rcept_dt"), "flr_nm": r.get("flr_nm")}
            for r in data.get("list", [])]


#: 사업보고서 표제의 결산기준일 — '사업보고서 (2025.12)'. **접수일이 아니다**
#: (2025 사업보고서는 2026-03 에 접수된다). 사업연도를 접수일로 잡으면 한 해씩 밀린다.
_ANNUAL_PERIOD = re.compile(r"\((\d{4})\.(\d{2})\)")


def find_annual_reports(api_key: str, corp_code: str, *, years: list[int] | None = None,
                        http_json: "JsonHttp | None" = None) -> dict[int, dict]:
    """corp_code → {사업연도: {rcept_no, report_nm, rcept_dt, amended}}.

    주석·본표는 사업보고서 접수번호의 원문 zip 에만 있는데(감사보고서 첨부),
    그 번호를 사람이 공시목록에서 눈으로 찾아야 했다. 여기서 자동으로 푼다.

    두 가지를 조심한다:
      · **사업연도는 표제의 (YYYY.MM) 이지 접수일이 아니다** — 2025 사업보고서는
        2026-03 에 접수된다. 접수일로 귀속하면 전 연도가 한 칸씩 밀린다.
      · **정정본이 있으면 정정본을 쓴다** — 같은 사업연도에 '[기재정정]사업보고서'가
        따로 접수된다(실측: 리노공업 2022 사업연도에 원본 20230321000231 과
        정정 20230814000718 이 함께 있다). 접수일이 늦은 쪽을 채택하고 amended 로 표시한다.
    """
    want = sorted({int(y) for y in years}) if years else None
    # 사업보고서는 사업연도 이듬해 초에 접수된다 → 조회 창을 한 해 넓게 잡는다.
    bgn = f"{(min(want) if want else 2015)}0101"
    end = f"{((max(want) + 2) if want else 2100)}1231"
    rows = list_filings(api_key, corp_code, bgn_de=bgn, end_de=end,
                        pblntf_ty="A", page_count=100, http_json=http_json)
    out: dict[int, dict] = {}
    for r in rows:
        name = str(r.get("report_nm") or "")
        if "사업보고서" not in name:
            continue
        m = _ANNUAL_PERIOD.search(name)
        if not m:
            continue
        year = int(m.group(1))
        if want and year not in want:
            continue
        prev = out.get(year)
        # 접수일이 늦은 쪽 = 정정본. 같은 날이면 접수번호가 큰 쪽.
        if prev is None or (str(r.get("rcept_dt") or ""), str(r.get("rcept_no") or "")) > (
                str(prev["rcept_dt"]), str(prev["rcept_no"])):
            out[year] = {"rcept_no": r.get("rcept_no"), "report_nm": name,
                         "rcept_dt": r.get("rcept_dt"),
                         "amended": "정정" in name or (prev is not None)}
    return out


def download_document(api_key: str, rcept_no: str, *,
                      http_bytes: BytesHttp | None = None) -> bytes:
    """document.xml → 접수번호 원본 공시 zip(바이너리). 그대로 다운로드/추출."""
    http = http_bytes or _urllib_bytes
    return http(f"{_BASE}/document.xml", {"crtfc_key": api_key, "rcept_no": rcept_no})
