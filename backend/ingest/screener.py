"""기업 스크리너 — peer **모집단 탐색**. `peer_selection` 4-step 퍼널의 Step1 앞단.

우리 퍼널은 Step1b(확정 코드로 풀 필터)부터 시작하는데, 그 앞의 "후보를 눈으로 훑어
고르는" 단계가 없었다. 실무 교정(`peer_selection` 도입부)이 이미 지적한 문제 —
*"KSIC 코드만으로 업종이 완전히 갈리지 않아 코드 2~3개를 union"* — 을 코드가 아니라
**주요 제품 문자열**로 우회한다. 같은 업종코드라도 제품이 다르면 peer 가 아니다.

데이터(실측 2026-08-04): FinanceDataReader 두 번의 호출로 전량이 나온다.
    StockListing("KRX-DESC") → Code·Name·Market·Sector·Industry·Products·
                               ListingDate·SettleMonth·Representative·HomePage·Region
    StockListing("KRX")      → Code·Name·Market·Marcap·Stocks·Close
**DART 쿼터 0 · 사업보고서 파싱 0.** (당초 계획은 사업보고서에서 제품을 뽑는 것이었고
5,000+ 콜로 추정했다 — DART 에서만 뽑을 생각을 한 오판이었다.)

설계:
  - 조회는 **주입(DI)**. 코어는 stdlib + 평문 dict 만 다룬다(pandas 는 fetch 경계에서만).
    → 네트워크 없이 전량 테스트 가능. `calc_core` 무의존 철학과 같다.
  - **as_of vintage 필수**. 시가총액은 시변이라 날짜 없는 비교는 거짓이다
    (`macro_client` 이중가드와 같은 사상). staleness 초과 시 호출부가 경고한다.
  - corp_code(DART 고유번호)는 기존 corp 인덱스의 `stock_code` 로 조인해 붙인다 —
    스크리너에서 고른 회사를 그대로 DART 흐름(`company-check`→FS)으로 넘기기 위해서다.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

#: 시장 구분 표기 정규화(FDR 은 KOSPI/KOSDAQ/KONEX 를 그대로 준다).
MARKETS = ("KOSPI", "KOSDAQ", "KONEX")
#: 시총 눈금(원) — 화면 슬라이더와 공유. 로그 스케일 관행(동종 툴 동일).
MCAP_TICKS = (0, 1e10, 5e10, 1e11, 5e11, 1e12)      # 0/100억/500억/1천억/5천억/1조
#: 인덱스 신선도 한계(일). 넘으면 호출부가 갱신을 권한다.
STALE_DAYS = 7

SORTS = ("marcap_desc", "marcap_asc", "name", "market", "industry")


@dataclass(frozen=True)
class ScreenerRow:
    """상장사 1건 — peer 판단에 필요한 최소 축만."""
    stock_code: str
    name: str
    market: str
    #: ⚠️ FDR 의 `Sector` 는 업종이 아니라 **코스닥 소속부**다(중견기업부·벤처기업부·
    #: 기술성장기업부…). 이름만 보고 업종 필터에 쓰면 드롭다운이 통째로 엉뚱해진다(실측).
    sector: str = ""            # 소속부(KOSDAQ 구분) — 업종 아님
    industry: str = ""          # **업종**(KSIC 서술) — 필터·드롭다운은 이쪽
    products: str = ""          # 주요 제품 — **판별력의 핵심**
    marcap: float | None = None     # 원
    shares: float | None = None
    listing_date: str = ""      # peer_selection Step4 상장연수
    settle_month: str = ""      # 결산월 정합
    homepage: str = ""
    region: str = ""
    corp_code: str = ""         # DART 고유번호(조인으로 채움)


@dataclass
class ScreenerIndex:
    as_of: str
    rows: list[ScreenerRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"as_of": self.as_of, "notes": list(self.notes),
                "rows": [asdict(r) for r in self.rows]}

    @staticmethod
    def from_json(d: dict) -> "ScreenerIndex":
        return ScreenerIndex(as_of=str(d.get("as_of", "")),
                             notes=list(d.get("notes") or []),
                             rows=[ScreenerRow(**r) for r in d.get("rows") or []])


def _s(v) -> str:
    """NaN·None 을 빈 문자열로. FDR 은 결측을 float('nan') 으로 준다."""
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none", "nat") else s


def _f(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f          # NaN 배제


def build_index(desc_rows: list[dict], cap_rows: list[dict], *, as_of: str,
                corp_index: list[dict] | None = None) -> ScreenerIndex:
    """두 목록 + corp 인덱스 → 스크리너 인덱스.

    desc_rows / cap_rows 는 FDR DataFrame 을 `to_dict("records")` 한 평문 목록이다
    (여기서는 pandas 를 모른다 — 경계 밖에서 변환해 넣는다).
    조인 키는 종목코드. 한쪽에만 있는 종목은 **버리지 않고** 있는 정보만으로 남긴다
    (우선주·신규상장이 한쪽에 늦게 반영되는 일이 있다).
    """
    notes: list[str] = []
    by_code: dict[str, dict] = {}
    for r in desc_rows:
        code = _s(r.get("Code"))
        if code:
            by_code[code] = dict(r)
    cap_only = 0
    for r in cap_rows:
        code = _s(r.get("Code"))
        if not code:
            continue
        if code in by_code:
            by_code[code].update({k: v for k, v in r.items() if k not in ("Name",)})
        else:
            by_code[code] = dict(r)
            cap_only += 1
    if cap_only:
        notes.append(f"시총 목록에만 있는 종목 {cap_only}건 — 업종·제품 없이 수록")

    # 종목코드 → DART 고유번호(스크리너 결과를 그대로 DART 흐름으로 넘기기 위해).
    code_to_corp = {}
    for c in corp_index or []:
        sc = _s(c.get("stock_code"))
        if sc:
            code_to_corp[sc] = _s(c.get("corp_code"))
    matched = 0

    rows: list[ScreenerRow] = []
    for code, r in by_code.items():
        corp = code_to_corp.get(code, "")
        matched += 1 if corp else 0
        rows.append(ScreenerRow(
            stock_code=code, name=_s(r.get("Name")), market=_s(r.get("Market")),
            sector=_s(r.get("Sector")), industry=_s(r.get("Industry")),
            products=_s(r.get("Products")),
            marcap=_f(r.get("Marcap")), shares=_f(r.get("Stocks")),
            listing_date=_s(r.get("ListingDate")), settle_month=_s(r.get("SettleMonth")),
            homepage=_s(r.get("HomePage")), region=_s(r.get("Region")),
            corp_code=corp,
        ))
    if corp_index:
        notes.append(f"고유번호 연결 {matched}/{len(rows)}건")
    rows.sort(key=lambda x: (-(x.marcap or 0), x.name))
    return ScreenerIndex(as_of=as_of, rows=rows, notes=notes)


def _market_matches(market: str, want: tuple[str, ...]) -> bool:
    """시장 표기는 세분된다 — 실측 `KOSDAQ GLOBAL` **50종목**(클래시스 등 우량 코스닥사).

    정확일치로 거르면 KOSDAQ 을 골랐을 때 이 50종목이 조용히 사라진다 —
    peer 모집단에서 하필 우량 종목만 빠지는 최악의 편향이다. 접두 일치로 본다.
    """
    m = market.upper()
    return any(m == w or m.startswith(w + " ") for w in want)


def _hay(r: ScreenerRow) -> str:
    """검색 대상 = 명칭 · 종목코드 · 세부업종 · **주요 제품**(동종 툴 규약 채택)."""
    return f"{r.name}\n{r.stock_code}\n{r.sector}\n{r.industry}\n{r.products}".lower()


def search(index: ScreenerIndex, *, q: str = "", markets: tuple[str, ...] = (),
           mcap_min: float | None = None, mcap_max: float | None = None,
           industry: str = "", limit: int = 100,
           sort: str = "marcap_desc") -> tuple[list[ScreenerRow], int]:
    """조건 필터 → (상위 limit 건, 전체 매칭 건수).

    매칭 건수를 함께 주는 이유는 회사 검색과 같다 — 잘린 사실을 숨기면 '이게 전부'로
    읽혀 모집단을 좁게 잡는다(peer 선정에서는 그게 곧 잘못된 배수로 이어진다).
    """
    needle = q.strip().lower()
    want = tuple(m.upper() for m in markets)
    ind = industry.strip().lower()
    # 상·하한이 뒤집혀 들어오면 **조용히 0건**이 된다 — 화면은 '조건에 맞는 회사 없음'
    # 으로만 보여 원인을 알 수 없다. 연도 구간과 같은 규약으로 뒤바꿔 받는다.
    if mcap_min is not None and mcap_max is not None and mcap_min > mcap_max:
        mcap_min, mcap_max = mcap_max, mcap_min
    hits = []
    for r in index.rows:
        if want and not _market_matches(r.market, want):
            continue
        if ind and ind not in r.industry.lower():
            continue
        if mcap_min is not None and (r.marcap is None or r.marcap < mcap_min):
            continue
        if mcap_max is not None and (r.marcap is None or r.marcap > mcap_max):
            continue
        if needle and needle not in _hay(r):
            continue
        hits.append(r)

    key = {
        "marcap_desc": lambda x: (-(x.marcap or 0), x.name),
        "marcap_asc": lambda x: ((x.marcap if x.marcap is not None else float("inf")), x.name),
        "name": lambda x: x.name,
        "market": lambda x: (x.market, -(x.marcap or 0)),
        "industry": lambda x: (x.industry, -(x.marcap or 0)),
    }.get(sort if sort in SORTS else "marcap_desc")
    hits.sort(key=key)
    return hits[:max(1, limit)], len(hits)


def rows_by_code(index: ScreenerIndex) -> dict[str, ScreenerRow]:
    """종목코드 → 행. 티커를 여러 건 조회할 때 선형 탐색 반복을 피한다.

    같은 코드가 두 번 오면 앞선 행을 남긴다(build_index 가 코드로 dict 를 만들어
    이미 유일하므로 실제로는 발생하지 않는다 — 방어적 규약).
    """
    out: dict[str, ScreenerRow] = {}
    for r in index.rows:
        out.setdefault(r.stock_code, r)
    return out


def industries(index: ScreenerIndex) -> list[tuple[str, int]]:
    """업종 드롭다운용 — (업종, 종목수) 내림차순.

    ⚠️ `sector`(소속부)가 아니라 `industry`(KSIC 서술)를 센다 — 이름이 그럴듯해
    `sector` 를 쓰면 '중견기업부·벤처기업부' 가 업종 목록으로 나온다(실측 오류).
    """
    counts: dict[str, int] = {}
    for r in index.rows:
        if r.industry:
            counts[r.industry] = counts.get(r.industry, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def staleness_days(as_of: str, today: str) -> int | None:
    """as_of 로부터 경과일. 형식이 어긋나면 None(판단 불가를 0으로 위장하지 않는다)."""
    from datetime import date

    def parse(s: str):
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None
    a, t = parse(as_of), parse(today)
    return None if (a is None or t is None) else (t - a).days


# ── FDR 경계(여기서만 pandas·네트워크를 안다) ────────────────────────────────
def fetch_listing_rows() -> tuple[list[dict], list[dict]]:
    """FinanceDataReader 2콜 → (설명 목록, 시총 목록). 평문 dict 로 변환해 반환."""
    import FinanceDataReader as fdr
    desc = fdr.StockListing("KRX-DESC").to_dict("records")
    cap = fdr.StockListing("KRX").to_dict("records")
    return desc, cap
