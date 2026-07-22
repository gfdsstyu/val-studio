"""거시경제 커넥터 — GDP·CPI·명목임금 성장률 + vintage(look-ahead) 가드.

Assumption 시트 상단(거시가정)의 공급원. price_client 와 같은 패턴:
**정규화·가드 로직은 stdlib(테스트 가능)·네트워크 공급자는 pluggable**.
ECOS(한국은행)는 lazy urllib(stdlib) — 미설치 의존 없음. EIU 는 구독제라 복붙 경로.

⭐ vintage(look-ahead) 가드 — 주가 가드보다 한 겹 미묘:
  거시값엔 날짜가 둘이다. ① 참조기간(값이 설명하는 시점) ② vintage(공표 시점).
  - 예측치(forecast)는 정당하게 기준일 이후를 본다(EIU 미래 GDP 예측 = 정상 입력).
  - 금지: 기준일 이후 공표된 **실적/개정치**를 과거 밸류에이션에 주입(= 사후정보).
  → 이중 가드: (a) 실적인데 참조기간이 기준일 이후 = FAIL,
              (b) vintage 가 기준일 이후(나중 개정판) = FAIL, (c) staleness = WARN.

  ⚠️ ECOS API 는 항상 *최신 개정치*만 반환 → vintage 를 알 수 없다(효과적 vintage=조회시점).
  따라서 엄격한 as-of 규율에서 **예측치는 ECOS 가 아니라 EIU 복붙 스냅샷**으로 받아야
  한다(그 시점 값이 그대로 보존됨). ECOS 는 기준일 훨씬 이전의 확정 실적에만 안전.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ingest.validators import Finding, Severity, ValidationReport, parse_number

# 표준 거시 지표 키(Assumption 스키마와 정합). 값은 연율(비율, 0.024 = 2.4%).
REAL_GDP_GROWTH = "real_gdp_growth"
CPI_INFLATION = "cpi_inflation"
NOMINAL_WAGE_GROWTH = "nominal_wage_growth"
RISK_FREE_10Y = "risk_free_10y"                 # 국고채 10년 무위험이자율(Rf)
BASE_RATE = "base_rate"                          # 한은 기준금리
EXCHANGE_RATE_USD = "exchange_rate_usd"         # 원/미국달러 매매기준율(레벨)
EXCHANGE_RATE_JPY = "exchange_rate_jpy"         # 원/100엔(레벨)
EXCHANGE_RATE_EUR = "exchange_rate_eur"         # 원/유로(레벨)

# 레벨 지표(환율·지수 등) = %가 아니므로 /100 정규화 제외. 그 외는 비율(%→소수).
_LEVEL_INDICATORS = frozenset({EXCHANGE_RATE_USD, EXCHANGE_RATE_JPY, EXCHANGE_RATE_EUR})

# staleness 경고 임계: 최신 usable vintage 와 평가기준일 간격(일). 거시 예측은 통상 분기
# 갱신 → 6개월(180일) 초과 시 오래된 전망 사용 경고.
STALENESS_WARN_DAYS = 180


@dataclass(frozen=True)
class MacroObservation:
    """단일 거시 관측치. period(참조기간)와 vintage(공표시점)를 분리 보존한다.

    period 포맷: 'YYYY'(연) | 'YYYY-Qn'(분기) | 'YYYY-MM'(월).
    vintage: 이 값이 공표/확정된 날짜(YYYY-MM-DD). 예측치 스냅샷의 발행일. 미상이면 None.
    is_forecast: 참조기간 시점의 예측치(True) vs 확정 실적(False).
    """
    indicator: str
    period: str
    value: float
    vintage: str | None = None
    source: str = ""
    is_forecast: bool = False


@dataclass(frozen=True)
class MacroSeries:
    indicator: str
    unit: str                                   # '%' | 'ratio' | 'index'
    observations: tuple[MacroObservation, ...] = ()


class MacroProvider(Protocol):
    name: str
    def fetch(self, indicator: str, start: str, end: str) -> MacroSeries:
        """지표 시계열 조회. start/end 는 참조기간 경계(YYYY 또는 YYYY-MM-DD)."""
        ...


# ── 참조기간 → 종료일(그 기간의 마지막 날) ─────────────────────────────────────
def period_end(period: str) -> str:
    """참조기간 문자열의 마지막 날짜(YYYY-MM-DD). look-ahead 판정 기준.

    'YYYY' → 12-31, 'YYYY-Qn' → 분기말, 'YYYY-MM' → 월말, 'YYYY-MM-DD' → 그날. stdlib 만.
    """
    import calendar
    import datetime
    p = period.strip().upper()
    if p.count("-") == 2:                        # YYYY-MM-DD (일별 — 그날이 종료일)
        return datetime.date.fromisoformat(p).isoformat()
    if "-Q" in p:
        y, q = p.split("-Q")
        month = int(q) * 3
    elif "-" in p:                              # YYYY-MM
        y, m = p.split("-", 1)
        month = int(m)
    else:                                       # YYYY
        y, month = p, 12
    year = int(y)
    last = calendar.monthrange(year, month)[1]
    return datetime.date(year, month, last).isoformat()


# ── vintage(look-ahead) 가드 — 결정론 게이트 ───────────────────────────────────
def check_macro_vintage(
    series: MacroSeries,
    base_date: str,
    *,
    staleness_warn_days: int = STALENESS_WARN_DAYS,
    report: ValidationReport | None = None,
) -> list[Finding]:
    """거시 시계열의 look-ahead 위반 감지 — 평가기준일 as-of 규율 강제.

    (a) 실적(is_forecast=False)인데 참조기간 종료 > 기준일  → FAIL(미래 실적)
    (b) vintage 가 기준일 이후                              → FAIL(나중 개정치)
    (c) usable 관측 최신 vintage 가 기준일보다 staleness 초과 → WARN(오래된 전망)
    (d) usable 관측 0                                        → WARN(as-of 데이터 없음)
    각 위반을 개별 Finding 으로 방출(감사인이 어느 관측이 문제인지 추적).
    """
    out: list[Finding] = []
    lookahead_actual, future_vintage = [], []
    usable_vintages: list[str] = []

    for ob in series.observations:
        pe = period_end(ob.period)
        # (b) 나중 공표된 개정치 — 예측이든 실적이든 그 시점 없던 데이터
        if ob.vintage is not None and ob.vintage > base_date:
            future_vintage.append(ob)
            continue
        # (a) 확정 실적인데 참조기간이 기준일 이후 → 미래를 확정으로 앎(vintage 미상이어도 잡힘)
        if (not ob.is_forecast) and pe > base_date:
            lookahead_actual.append(ob)
            continue
        if ob.vintage is not None:
            usable_vintages.append(ob.vintage)

    if lookahead_actual:
        worst = max(lookahead_actual, key=lambda o: period_end(o.period))
        out.append(Finding(
            "macro_lookahead", Severity.FAIL,
            f"{series.indicator}: 기준일({base_date}) 이후 확정실적 {len(lookahead_actual)}건 "
            f"(최신 참조 {worst.period}) — 사후정보 유입, 당시 예측치로 대체 필요",
            {"count": len(lookahead_actual), "worst_period": worst.period,
             "base_date": base_date}))
    for ob in future_vintage:
        out.append(Finding(
            "macro_vintage", Severity.FAIL,
            f"{series.indicator}: vintage {ob.vintage} > 기준일 {base_date} "
            f"(참조 {ob.period}) — 나중 공표된 개정치, as-of 스냅샷 사용 필요",
            {"period": ob.period, "vintage": ob.vintage, "base_date": base_date}))

    if not usable_vintages and not any(
        (not o.is_forecast) and period_end(o.period) <= base_date
        for o in series.observations
    ):
        out.append(Finding(
            "macro_staleness", Severity.WARN,
            f"{series.indicator}: 기준일 이전 사용가능 관측 없음 — 거시 입력 확보 필요",
            {"base_date": base_date}))
    elif usable_vintages:
        import datetime
        latest = max(usable_vintages)
        gap = (datetime.date.fromisoformat(base_date)
               - datetime.date.fromisoformat(latest)).days
        if gap > staleness_warn_days:
            out.append(Finding(
                "macro_staleness", Severity.WARN,
                f"{series.indicator}: 최신 vintage {latest} 가 기준일 {base_date} 대비 "
                f"{gap}일 경과(>{staleness_warn_days}일) — 갱신된 전망 확인",
                {"latest_vintage": latest, "gap_days": gap, "base_date": base_date}))

    if not out:
        out.append(Finding("macro_vintage", Severity.PASS,
                           f"{series.indicator}: as-of 규율 통과({base_date})",
                           {"base_date": base_date, "n": len(series.observations)}))
    if report is not None:
        for f in out:
            report.add(f)
    return out


def usable_as_of(series: MacroSeries, base_date: str) -> MacroSeries:
    """평가기준일에 실제로 쓸 수 있는 관측만 남긴 시계열.

    가드 (a)(b) 를 통과하는 관측만 유지하고, 같은 참조기간에 여러 vintage 가 있으면
    기준일 이하 **최신 vintage**(그 시점 최선의 추정)만 남긴다. 예측치는 참조기간이
    기준일 이후여도 vintage 만 정당하면 유지(전망은 미래를 보는 게 정상).
    """
    kept: dict[str, MacroObservation] = {}
    for ob in series.observations:
        if ob.vintage is not None and ob.vintage > base_date:
            continue
        if (not ob.is_forecast) and period_end(ob.period) > base_date:
            continue
        prev = kept.get(ob.period)
        # 같은 period 중복 시: vintage 최신 우선(None 은 미상 → 후순위)
        if prev is None or (ob.vintage or "") > (prev.vintage or ""):
            kept[ob.period] = ob
    ordered = tuple(sorted(kept.values(), key=lambda o: o.period))
    return MacroSeries(series.indicator, series.unit, ordered)


# ── EIU 등 복붙 경로 (구독제 as-of 스냅샷) ────────────────────────────────────
def parse_paste_table(
    text: str,
    indicator: str,
    *,
    vintage: str,
    is_forecast_from: str | None = None,
    source: str = "EIU(paste)",
    unit: str = "%",
    report: ValidationReport | None = None,
) -> MacroSeries:
    """복붙한 '기간<TAB/공백>값' 표 → MacroSeries. 값은 validators 로 정규화.

    vintage: 이 스냅샷을 붙여넣은/발행된 날짜(그 시점 전망으로 고정 보존).
    is_forecast_from: 이 참조연도(YYYY) 이상은 예측치로 태깅(예 기준일 이후 연도).
    % 값은 비율로(2.4% → 0.024). 파싱 실패 행은 validators 가 fail 기록 후 스킵.
    """
    obs: list[MacroObservation] = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.replace("\t", " ").split()
        if len(parts) < 2:
            continue
        period, raw = parts[0], parts[-1]
        val = parse_number(raw if raw.endswith("%") else raw + "%",
                           report=report, field_name=f"{indicator}:{period}")
        if val is None:
            continue
        year = int(period[:4]) if period[:4].isdigit() else None
        is_fc = (is_forecast_from is not None and year is not None
                 and year >= int(is_forecast_from[:4]))
        obs.append(MacroObservation(indicator, period, float(val),
                                    vintage=vintage, source=source, is_forecast=is_fc))
    return MacroSeries(indicator, unit, tuple(obs))


# ── 공급자 구현 ──────────────────────────────────────────────────────────────
@dataclass
class SyntheticMacroProvider:
    """테스트·데모 — {indicator: MacroSeries} 미리 주입. 네트워크 불요."""
    data: dict[str, MacroSeries]
    name: str = "synthetic"

    def fetch(self, indicator: str, start: str, end: str) -> MacroSeries:
        s = self.data.get(indicator, MacroSeries(indicator, "%"))
        lo, hi = start[:4], end[:4]
        obs = tuple(o for o in s.observations if lo <= o.period[:4] <= hi)
        return MacroSeries(s.indicator, s.unit, obs)


# ECOS 통계표코드 (stat_code, cycle[, item_code]). 3번째=만기물/세부항목 필터.
# ⚠️ 아이템 코드는 ECOS '통계코드검색'으로 확정 필요(계정별 상이) — 아래는 관용 후보.
_ECOS_STATS = {
    REAL_GDP_GROWTH: ("200Y102", "A"),          # 국민계정 연간, 실질 성장률
    CPI_INFLATION: ("901Y009", "M"),            # 소비자물가지수 월
    # 국고채 10년(일별). item 미지정 시 통계표 전 항목이 섞여 나오므로 만기물 코드 필수.
    RISK_FREE_10Y: ("817Y002", "D", "010210000"),   # 시장금리 일별 / 국고채 10년
    BASE_RATE: ("722Y001", "D", "0101000"),         # 한국은행 기준금리(일별)
    # 환율(731Y001 원/각국통화, 일별) — 레벨값. item: 원/달러·원/100엔·원/유로.
    EXCHANGE_RATE_USD: ("731Y001", "D", "0000001"),
    EXCHANGE_RATE_JPY: ("731Y001", "D", "0000002"),
    EXCHANGE_RATE_EUR: ("731Y001", "D", "0000003"),
}


@dataclass
class EcosProvider:
    """한국은행 ECOS OpenAPI — lazy urllib(stdlib). BYOK 키.

    ⚠️ ECOS 는 **최신 개정치**만 반환(당시 as-of 아님) → 모든 관측 is_forecast=False,
    vintage=None(효과적으로 조회시점). check_macro_vintage 의 (a) 실적 look-ahead 가
    참조기간 기준으로 걸러주지만, **과거 개정** 위험은 못 잡는다. 예측치·최근연도는
    ECOS 대신 EIU 복붙(parse_paste_table)을 쓰라는 것이 설계 규칙.
    """
    api_key: str
    name: str = "ecos"

    def fetch(self, indicator: str, start: str, end: str) -> MacroSeries:
        import json
        import urllib.request
        stat = _ECOS_STATS.get(indicator)
        if stat is None:
            raise ValueError(f"ECOS 통계코드 미매핑 지표: {indicator} (복붙 경로 사용)")
        stat_code, cycle = stat[0], stat[1]
        item_code = stat[2] if len(stat) > 2 else None
        s, e = _ecos_period(start, cycle), _ecos_period(end, cycle)
        url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{self.api_key}/json/kr/"
               f"1/1000/{stat_code}/{cycle}/{s}/{e}")
        if item_code:                                    # 만기물/세부항목 필터(END 뒤)
            url += f"/{item_code}"
        with urllib.request.urlopen(url, timeout=30) as resp:      # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
        rows = payload.get("StatisticSearch", {}).get("row", [])
        is_level = indicator in _LEVEL_INDICATORS
        obs: list[MacroObservation] = []
        for r in rows:
            period = _ecos_time_to_period(str(r.get("TIME", "")), cycle)
            try:
                v = float(r.get("DATA_VALUE"))
            except (TypeError, ValueError):
                continue
            # 레벨(환율·지수)은 원값, 그 외(%금리·성장률)는 소수 비율로.
            obs.append(MacroObservation(indicator, period, v if is_level else v / 100.0,
                                        vintage=None, source="ECOS", is_forecast=False))
        unit = "KRW" if is_level else "%"
        return MacroSeries(indicator, unit, tuple(obs))


def _ecos_period(date_str: str, cycle: str) -> str:
    """조회 경계(YYYY 또는 YYYY-MM-DD) → ECOS 주기별 포맷(A=YYYY, M=YYYYMM, D=YYYYMMDD)."""
    digits = date_str.replace("-", "")
    if cycle == "A":
        return digits[:4]
    if cycle == "M":
        return (digits[:6] if len(digits) >= 6 else digits[:4] + "01")
    return (digits[:8] if len(digits) >= 8 else digits[:6].ljust(6, "0") + "01")


def _ecos_time_to_period(t: str, cycle: str) -> str:
    """ECOS TIME(YYYY/YYYYMM/YYYYMMDD) → MacroObservation.period(YYYY/YYYY-MM/YYYY-MM-DD)."""
    if cycle == "A":
        return t[:4]
    if cycle == "M":
        return f"{t[:4]}-{t[4:6]}"
    return f"{t[:4]}-{t[4:6]}-{t[6:8]}"


# ── Assumption 번들 (calc_core 소비) ──────────────────────────────────────────
@dataclass
class MacroAssumptions:
    """DCF Assumption 시트 거시 블록 — 가드 통과 후 확정된 as-of 값 묶음.

    각 필드는 (value, vintage, source) 로 provenance 를 달고 다닌다(감사추적).
    """
    base_date: str
    real_gdp_growth: MacroObservation | None = None
    cpi_inflation: MacroObservation | None = None
    nominal_wage_growth: MacroObservation | None = None
    findings: list[Finding] = field(default_factory=list)


def build_macro_assumptions(
    providers: dict[str, MacroProvider],
    base_date: str,
    *,
    horizon_year: str | None = None,
) -> MacroAssumptions:
    """지표별 공급자에서 조회 → vintage 가드 → 기준일 최신 usable 값으로 번들 구성.

    horizon_year(YYYY) 주면 그 연도 예측치를 선택(추정 첫 해 거시 전망), 없으면 기준일
    직전 최신 관측. fail 이 있으면 findings 에 남기되 값은 채우지 않는다(게이트).
    """
    result = MacroAssumptions(base_date=base_date)
    target = horizon_year or base_date[:4]
    for indicator, provider in providers.items():
        series = provider.fetch(indicator, f"{int(target)-6}", target)
        result.findings.extend(check_macro_vintage(series, base_date))
        usable = usable_as_of(series, base_date)
        pick = next((o for o in usable.observations if o.period[:4] == target), None)
        if pick is None and usable.observations:
            pick = usable.observations[-1]          # 기준일 직전 최신
        if pick is not None:
            setattr(result, indicator, pick)
    return result


# ── PGR 거시 앵커링(R2) ──────────────────────────────────────────────────────
# 근거: docs/reference/모델러스_통합모델_5.4.md §2.3(e) — 원본 `F33 =
# AVERAGE(rInflation!B2:K2)/100 = 1.62%`. 영구성장률을 감(感)이 아니라 **장기 물가상승률
# 평균의 함수**로 만들어 출처 추적을 가능하게 한다. PGR 은 TV 최고민감 파라미터이므로
# 무근거 하드코드는 감사 방어가 불가능하다.
PGR_ANCHOR_YEARS = 10
# 앵커 결과가 이 값을 넘으면 % 스케일 오투입 의심(비율 규약 위반) — 조용한
# 100배 오차를 막는 2차 방어선.
PGR_SCALE_SANITY = 0.20


@dataclass(frozen=True)
class PgrSuggestion:
    """앵커링된 영구성장률 제안 — 값 + 산출근거(감사추적)."""
    value: float                       # 비율(0.0162 = 1.62%)
    basis: str                         # 산출식 설명
    n_observations: int
    periods: tuple[str, ...]
    source: str
    findings: list[Finding] = field(default_factory=list)


def suggest_pgr_from_inflation(
    series: MacroSeries,
    base_date: str,
    *,
    years: int = PGR_ANCHOR_YEARS,
) -> PgrSuggestion:
    """장기 물가상승률 평균 → 영구성장률 제안(R2). **제안일 뿐 확정은 평가인 몫.**

    vintage 가드(`usable_as_of`)를 먼저 통과시켜 평가기준일 이후 공표된 값이 섞이지
    않게 한다 — look-ahead 방지는 여기서도 동일하게 적용된다.

    ⚠️ **단위 규약**: 이 모듈의 `MacroObservation.value` 는 **항상 비율**이다
    (`parse_paste_table` 은 "1.3%" → 0.013, `EcosProvider` 는 v/100 로 저장).
    `MacroSeries.unit` 은 **출처 라벨**이지 스케일 플래그가 아니다 — 값이 이미 비율인데
    unit 이 '%' 인 것이 정상. 따라서 여기서 추가로 나누지 않는다.
    (이 함수는 처음에 unit=='%' 를 보고 /100 했다가 라이브에서 1.62% → 0.0162% 로
    100배 축소되는 버그가 났다. 단위 테스트는 잘못된 가정에 맞춘 픽스처라 통과했음.)

    관측치가 없으면 value=0.0 + FAIL finding(임의 기본값을 지어내지 않는다).
    """
    # ⚠️ 파이썬 슬라이싱 함정: `lst[-0:]` 는 빈 리스트가 아니라 **전체 리스트**다.
    # years=0/음수를 그대로 흘리면 요청하지 않은 윈도우의 평균이 나오면서 basis 문자열은
    # 그럴듯하게 찍히고 finding 은 PASS — 감사추적이 거짓이 된다. 입구에서 막는다.
    if not isinstance(years, int) or isinstance(years, bool) or years < 1:
        raise ValueError(f"years 는 1 이상 정수여야 한다: {years!r}")
    usable = usable_as_of(series, base_date)
    obs = list(usable.observations)[-years:]
    findings: list[Finding] = []
    if not obs:
        findings.append(Finding(
            "pgr_anchor", Severity.FAIL,
            f"물가 관측치 없음(기준일 {base_date} 이하) — PGR 앵커링 불가",
            {"indicator": series.indicator, "base_date": base_date},
        ))
        return PgrSuggestion(0.0, "관측치 없음", 0, (), usable.indicator, findings)

    value = sum(o.value for o in obs) / len(obs)      # 값은 이미 비율(위 단위 규약)
    periods = tuple(o.period for o in obs)
    basis = f"AVERAGE({series.indicator}, {periods[0]}~{periods[-1]}, n={len(obs)})"
    if abs(value) > PGR_SCALE_SANITY:
        findings.append(Finding(
            "pgr_anchor", Severity.WARN,
            f"앵커 {value:.1%} 가 비현실적 — 값이 비율이 아니라 %(예 1.62)로 들어온 것은"
            f" 아닌지 확인(이 모듈의 value 는 항상 비율)",
            {"value": value, "sanity": PGR_SCALE_SANITY}))
    if len(obs) < years:
        findings.append(Finding(
            "pgr_anchor", Severity.WARN,
            f"물가 관측 {len(obs)}년 < 요청 {years}년 — 장기평균 대표성 취약",
            {"n": len(obs), "requested": years},
        ))
    else:
        findings.append(Finding(
            "pgr_anchor", Severity.PASS,
            f"PGR 앵커 {value:.2%} ← {basis}", {"value": value, "basis": basis},
        ))
    return PgrSuggestion(value, basis, len(obs), periods,
                         obs[-1].source or usable.indicator, findings)
