"""거시 커넥터 테스트 — vintage(look-ahead) 가드·복붙 파싱·as-of 선택·번들.

stdlib: `python tests/test_macro_client.py` (네트워크 불요, SyntheticMacroProvider).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ingest.macro_client import (  # noqa: E402
    REAL_GDP_GROWTH, MacroObservation, MacroSeries, SyntheticMacroProvider,
    build_macro_assumptions, check_macro_vintage, parse_paste_table,
    period_end, usable_as_of,
)
from ingest.validators import Severity  # noqa: E402


def _sev(findings, rule):
    return [f.severity for f in findings if f.rule == rule]


def test_period_end():
    assert period_end("2024") == "2024-12-31"
    assert period_end("2024-Q1") == "2024-03-31"
    assert period_end("2024-Q4") == "2024-12-31"
    assert period_end("2024-02") == "2024-02-29"      # 윤년


def test_actual_from_future_fails():
    # 기준일 2023-06-30 인데 2024 확정 실적을 넣음 → FAIL
    s = MacroSeries(REAL_GDP_GROWTH, "%", (
        MacroObservation(REAL_GDP_GROWTH, "2022", 0.026, vintage="2023-03-01"),
        MacroObservation(REAL_GDP_GROWTH, "2024", 0.021, vintage=None, is_forecast=False),
    ))
    fs = check_macro_vintage(s, "2023-06-30")
    assert Severity.FAIL in _sev(fs, "macro_lookahead")


def test_forecast_beyond_base_is_allowed():
    # 예측치는 참조기간이 기준일 이후여도 vintage 만 정당하면 통과(전망은 미래를 봄)
    s = MacroSeries(REAL_GDP_GROWTH, "%", (
        MacroObservation(REAL_GDP_GROWTH, "2024", 0.022, vintage="2023-04-01", is_forecast=True),
        MacroObservation(REAL_GDP_GROWTH, "2025", 0.020, vintage="2023-04-01", is_forecast=True),
    ))
    fs = check_macro_vintage(s, "2023-06-30")
    assert not any(f.severity is Severity.FAIL for f in fs)


def test_future_vintage_fails():
    # 참조기간은 과거지만 나중(기준일 이후) 공표된 개정치 → FAIL
    s = MacroSeries(REAL_GDP_GROWTH, "%", (
        MacroObservation(REAL_GDP_GROWTH, "2022", 0.026, vintage="2024-03-01"),
    ))
    fs = check_macro_vintage(s, "2023-06-30")
    assert Severity.FAIL in _sev(fs, "macro_vintage")


def test_staleness_warns():
    # 최신 usable vintage 가 기준일보다 1년 넘게 오래됨 → WARN
    s = MacroSeries(REAL_GDP_GROWTH, "%", (
        MacroObservation(REAL_GDP_GROWTH, "2021", 0.041, vintage="2022-01-15", is_forecast=True),
    ))
    fs = check_macro_vintage(s, "2023-06-30", staleness_warn_days=180)
    assert Severity.WARN in _sev(fs, "macro_staleness")


def test_usable_as_of_picks_latest_vintage():
    # 같은 2022 참조에 두 vintage → 기준일 이하 최신(2023-02) 선택, 기준일 이후(2024) 배제
    s = MacroSeries(REAL_GDP_GROWTH, "%", (
        MacroObservation(REAL_GDP_GROWTH, "2022", 0.025, vintage="2022-08-01"),
        MacroObservation(REAL_GDP_GROWTH, "2022", 0.026, vintage="2023-02-01"),   # 개정, usable
        MacroObservation(REAL_GDP_GROWTH, "2022", 0.028, vintage="2024-03-01"),   # 미래 개정, 배제
    ))
    u = usable_as_of(s, "2023-06-30")
    assert len(u.observations) == 1
    assert abs(u.observations[0].value - 0.026) < 1e-12
    assert u.observations[0].vintage == "2023-02-01"


def test_parse_paste_table():
    text = "2022\t2.6\n2023\t1.4\n2024\t2.2\n2025\t2.0"
    s = parse_paste_table(text, REAL_GDP_GROWTH, vintage="2023-05-10",
                          is_forecast_from="2023")
    assert len(s.observations) == 4
    assert abs(s.observations[0].value - 0.026) < 1e-12       # 2.6% → 0.026
    assert s.observations[0].is_forecast is False              # 2022 < 2023 = 실적
    assert s.observations[2].is_forecast is True               # 2024 ≥ 2023 = 예측
    # 붙여넣은 스냅샷이므로 기준일 이후 예측이어도 vintage 정당 → 가드 통과
    assert all(f.severity is not Severity.FAIL
               for f in check_macro_vintage(s, "2023-06-30"))


def test_build_macro_assumptions_picks_horizon():
    # mid-2023 기준일: 2023 연간치도 아직 미확정 → is_forecast_from="2023"(당해부터 전망)
    s = parse_paste_table("2022\t2.6\n2023\t1.4\n2024\t2.2\n2025\t2.0", REAL_GDP_GROWTH,
                          vintage="2023-05-10", is_forecast_from="2023")
    prov = SyntheticMacroProvider({REAL_GDP_GROWTH: s})
    asm = build_macro_assumptions({REAL_GDP_GROWTH: prov}, "2023-06-30",
                                  horizon_year="2024")
    assert asm.real_gdp_growth is not None
    assert asm.real_gdp_growth.period == "2024"
    assert abs(asm.real_gdp_growth.value - 0.022) < 1e-12
    assert not any(f.severity is Severity.FAIL for f in asm.findings)


def test_actual_full_year_before_base_ok():
    # 기준일 2024-06-30 이면 2023 연간 확정실적은 정당(연말 지남) → FAIL 없음
    s = parse_paste_table("2022\t2.6\n2023\t1.4", REAL_GDP_GROWTH,
                          vintage="2024-02-01", is_forecast_from=None)
    fs = check_macro_vintage(s, "2024-06-30")
    assert not any(f.severity is Severity.FAIL for f in fs)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    ok = 0
    for fn in fns:
        try:
            fn(); ok += 1; print(f"  ok  {fn.__name__}")
        except Exception:
            print(f"  FAIL {fn.__name__}"); traceback.print_exc()
    print(f"\n{ok}/{len(fns)} passed")
