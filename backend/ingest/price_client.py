"""주가 커넥터 — 베타 회귀·시가총액. WACC 트랙의 최우선 데이터 공급원.

설계(사용자 확정 데이터 조달 §): **베타 수학은 stdlib(테스트 가능)·네트워크 공급자는
pluggable**(OCR TextExtractor·임베더와 동일 패턴). FinanceDataReader/pykrx 는 lazy import —
미설치여도 SyntheticProvider 로 전 로직 테스트 가능, 로컬 실사용 시 `pip install`.

방법론([[DCF_교육_정본]] §3.2): Bloomberg 2년 Weekly 또는 5년 Monthly 조정베타.
조정베타 = 0.67·raw + 0.33·1.0(Marshall Blume). 회귀 Raw β = Cov(주식,시장)/Var(시장).

⭐ look-ahead 가드(vintage 원칙): 회귀 구간은 **평가기준일에서 끝난다** — 기준일 이후
가격은 잘라낸다(그 시점 없던 데이터 = 미래정보 유입, 감사 치명적). β·Rf·거시 vintage 는
모두 같은 평가기준일 창에 정렬돼야 함(plan §거시 vintage 가드).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class PriceProvider(Protocol):
    name: str
    def closes(self, ticker: str, start: str, end: str) -> list[tuple[str, float]]:
        """[(YYYY-MM-DD, 종가)] 일별 오름차순. end 포함(≤ end)."""
        ...


def _simple_returns(closes: list[float]) -> list[float]:
    """단순수익률 r_t = c_t/c_{t-1} − 1. 직전 종가 ≤ 0 은 건너뜀(정의불가)."""
    out = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0:
            out.append(closes[i] / closes[i - 1] - 1.0)
    return out


def bloomberg_adjusted_beta(raw: float) -> float:
    """Bloomberg/Marshall Blume 조정베타 = 0.67·raw + 0.33·1.0 (시장평균 1.0 회귀)."""
    return 0.67 * raw + 0.33 * 1.0


@dataclass(frozen=True)
class BetaResult:
    raw: float                      # 회귀 기울기(Levered β)
    adjusted: float                 # 조정베타
    r_squared: float                # 회귀 설명력
    n: int                          # 사용 수익률 관측치 수
    freq: str                       # 'W' | 'M'
    window_end: str                 # 회귀 종료일(= 평가기준일에 정렬)


def compute_beta(stock_closes: list[float], market_closes: list[float],
                 *, freq: str = "W", window_end: str = "") -> BetaResult:
    """정렬된 두 종가 시계열 → OLS 베타(Cov/Var). 길이 동일 가정.

    Raw β = Cov(r_stock, r_market) / Var(r_market). R² = corr². stdlib 만.
    """
    rs, rm = _simple_returns(stock_closes), _simple_returns(market_closes)
    n = min(len(rs), len(rm))
    if n < 2:
        raise ValueError(f"베타 회귀 관측치 부족(n={n}) — 기간·빈도 확인")
    rs, rm = rs[-n:], rm[-n:]
    mean_s = sum(rs) / n
    mean_m = sum(rm) / n
    cov = sum((rs[i] - mean_s) * (rm[i] - mean_m) for i in range(n)) / n
    var_m = sum((rm[i] - mean_m) ** 2 for i in range(n)) / n
    var_s = sum((rs[i] - mean_s) ** 2 for i in range(n)) / n
    if var_m <= 0:
        raise ValueError("시장 수익률 분산 0 — 회귀 불가")
    raw = cov / var_m
    r2 = (cov * cov) / (var_m * var_s) if var_s > 0 else 0.0
    return BetaResult(raw=raw, adjusted=bloomberg_adjusted_beta(raw),
                      r_squared=r2, n=n, freq=freq, window_end=window_end)


def _resample_last(series: list[tuple[str, float]], freq: str) -> list[tuple[str, float]]:
    """일별 → 주(W)·월(M) 말 종가. 같은 버킷의 마지막 관측만 남긴다(stdlib).

    주 버킷 = ISO 연-주(date[:4]+주차 근사 = 통년 일련일//7), 월 버킷 = YYYY-MM.
    """
    if freq == "M":
        keyf = lambda d: d[:7]                       # YYYY-MM
    else:                                            # W — ISO 주 근사
        import datetime
        def keyf(d):
            y, m, dd = int(d[:4]), int(d[5:7]), int(d[8:10])
            iso = datetime.date(y, m, dd).isocalendar()
            return f"{iso[0]}-W{iso[1]:02d}"
    bucket: dict[str, tuple[str, float]] = {}
    for d, c in series:
        bucket[keyf(d)] = (d, c)                      # 오름차순이므로 마지막이 버킷 말
    return [bucket[k] for k in sorted(bucket)]


def _align(a: list[tuple[str, float]], b: list[tuple[str, float]]
           ) -> tuple[list[float], list[float]]:
    """두 (date, close) 를 공통 날짜로 정렬 → (a종가들, b종가들)."""
    bmap = dict(b)
    common = sorted(d for d, _ in a if d in bmap)
    amap = dict(a)
    return [amap[d] for d in common], [bmap[d] for d in common]


def beta_from_prices(
    provider: PriceProvider,
    ticker: str,
    market_ticker: str,
    base_date: str,
    *,
    freq: str = "W",
    years: float = 2.0,
) -> BetaResult:
    """공급자에서 주가·시장지수 조회 → 재표본 → 정렬 → 베타. 평가기준일 look-ahead 가드.

    회귀 구간 = [base_date − years, base_date]. 공급자가 base_date 이후를 줘도 잘라낸다.
    freq='W'+years=2 또는 freq='M'+years=5 가 교육 표준.
    """
    import datetime
    ed = datetime.date.fromisoformat(base_date)
    sd = ed.replace(year=ed.year - int(years)) if years >= 1 else ed
    start, end = sd.isoformat(), base_date
    sc = [(d, c) for d, c in provider.closes(ticker, start, end) if d <= base_date]
    mc = [(d, c) for d, c in provider.closes(market_ticker, start, end) if d <= base_date]
    sc, mc = _resample_last(sc, freq), _resample_last(mc, freq)
    sa, ma = _align(sc, mc)
    return compute_beta(sa, ma, freq=freq, window_end=base_date)


@dataclass(frozen=True)
class MarketCap:
    value: float                    # 시가총액
    price: float                    # 기준일 이하 최신 종가
    price_date: str
    shares: float


def market_cap(provider: PriceProvider, ticker: str, shares: float,
               base_date: str) -> MarketCap:
    """시가총액 = (평가기준일 이하 최신 종가) × 발행주식수. look-ahead 가드 동일."""
    start = datetime_minus(base_date, days=14)       # 휴장 대비 2주 여유
    rows = [(d, c) for d, c in provider.closes(ticker, start, base_date) if d <= base_date]
    if not rows:
        raise ValueError(f"{ticker}: 평가기준일 이하 종가 없음")
    d, c = rows[-1]
    return MarketCap(value=c * shares, price=c, price_date=d, shares=shares)


def datetime_minus(date_str: str, *, days: int) -> str:
    import datetime
    return (datetime.date.fromisoformat(date_str) - datetime.timedelta(days=days)).isoformat()


# ── 공급자 구현 ──────────────────────────────────────────────────────────────
@dataclass
class SyntheticProvider:
    """테스트·데모용 — {ticker: [(date, close)]} 미리 주입. 네트워크 불요."""
    data: dict[str, list[tuple[str, float]]]
    name: str = "synthetic"

    def closes(self, ticker: str, start: str, end: str) -> list[tuple[str, float]]:
        return [(d, c) for d, c in self.data.get(ticker, []) if start <= d <= end]


def pykrx_fundamentals(ticker: str, base_date: str) -> dict:
    """pykrx 재무배수(PER·PBR·EPS·BPS·DIV) — 평가기준일 이하 최신(look-ahead 가드).

    상대가치평가(multiples) 입력. pykrx lazy import(미설치 RuntimeError). 종목코드 6자리.
    """
    try:
        from pykrx import stock
    except ImportError:
        raise RuntimeError(
            "pykrx 미설치 — `pip install pykrx` 후 재시도.") from None
    import datetime
    ed = datetime.date.fromisoformat(base_date)
    sd = ed - datetime.timedelta(days=14)          # 휴장 대비 2주 여유
    df = stock.get_market_fundamental_by_date(
        sd.strftime("%Y%m%d"), ed.strftime("%Y%m%d"), ticker)
    if df is None or len(df) == 0:
        raise ValueError(f"{ticker}: pykrx 재무배수 없음(기준일 {base_date})")
    row = df.iloc[-1]                               # 기준일 이하 최신
    idx = df.index[-1]
    def g(k):
        try:
            v = float(row[k])
            return v if v == v and v != 0 else None    # NaN·0 제외
        except (KeyError, TypeError, ValueError):
            return None
    return {"ticker": ticker, "date": idx.strftime("%Y-%m-%d"),
            "per": g("PER"), "pbr": g("PBR"), "eps": g("EPS"),
            "bps": g("BPS"), "div": g("DIV")}


@dataclass
class FinanceDataReaderProvider:
    """실사용 — FinanceDataReader lazy import. 미설치면 RuntimeError(안내)."""
    name: str = "fdr"

    def closes(self, ticker: str, start: str, end: str) -> list[tuple[str, float]]:
        try:
            import FinanceDataReader as fdr
        except ImportError as e:                     # noqa: F841
            raise RuntimeError(
                "FinanceDataReader 미설치 — `pip install finance-datareader` 후 재시도. "
                "(테스트·데모는 SyntheticProvider 사용)") from None
        df = fdr.DataReader(ticker, start, end)
        return [(idx.strftime("%Y-%m-%d"), float(row["Close"]))
                for idx, row in df.iterrows() if row["Close"] == row["Close"]]  # NaN 제외
