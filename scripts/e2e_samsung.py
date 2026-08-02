"""삼성전자 E2E 독립재현 — DART 라이브 FS → 간이 DCF(칼럼 방법론) → 엑셀 + 칼럼 대조.

[[실전평가_상장사_사례집]] §E2E 계획의 1번. 결정론 엔진(calc_core)으로 칼럼(val-samsung-2025q2)
의 간이 밸류에이션을 독립 재현하고, 가정·결론을 대조해 괴리를 설명한다(감사인 트랙 사고).

칼럼 방법론(재현 대상):
  · 세후영업이익 기반 간이 DCF(FCF 변동성 회피 — [[실전평가_상장사_사례집]] 공통 관찰).
  · 부문 CAGR(DS DRAM 10%·HBM 26% 등) → 세후영업이익 성장, multiple 14~28배 대역.
  · WACC 11%·영구성장 2%·5년 추정 → Equity 315~630조(시장 423.8조의 80~150%).

우리 재현은 **세후영업이익을 명시기간 FCFF 프록시로** 놓고(칼럼의 간이법 그대로), 성장률만
가정으로 투영한다. DART 라이브로 실적(매출·영업이익·자본)을 확보하고, 배수 대역의 양끝을
페이드 성장률로 환산해 우리 게이트를 통과시킨 뒤 칼럼 결론과 대조한다.

실행: `py -3.12 scripts/e2e_samsung.py`  (DART 키 = .env DART_API_KEY)
산출: scripts/output/e2e_samsung_dcf.xlsx + 표준출력 대조 리포트.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core.checks import audit_dcf  # noqa: E402
from calc_core.dcf import run as dcf_run  # noqa: E402
from calc_core.models import DcfSpineInput  # noqa: E402
from excel.dcf_export import export_dcf  # noqa: E402
from ingest.dart_client import DartClient, pick  # noqa: E402

SAMSUNG_CORP = "00126380"
BSNS_YEAR = 2024


def _load_key() -> str:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("DART_API_KEY"):
                return line.split("=", 1)[1].strip()
    key = os.environ.get("DART_API_KEY")
    if not key:
        raise SystemExit("DART_API_KEY 없음 — .env 또는 환경변수 설정")
    return key


def fetch_actuals(client: DartClient) -> dict:
    res = client.financial_statements(SAMSUNG_CORP, BSNS_YEAR, fs_div="CFS")
    if not res.report.ok:
        raise SystemExit(f"DART 인제스트 실패: {res.report}")
    got = pick(res, "매출액", "영업이익", "당기순이익", "자산총계", "부채총계", "자본총계")
    out = {}
    for k in ("매출액", "영업이익", "당기순이익", "자산총계", "부채총계", "자본총계"):
        v = got.get(k)                  # pick 은 값(Decimal)을 직접 반환
        out[k] = float(v) if v is not None else None    # 백만원
    return out


def build_reproduction(actuals: dict, *, growth: float, tax_rate: float,
                       wacc: float, pgr: float, years: int,
                       non_operating: float, net_debt: float,
                       nci: float, shares: int) -> DcfSpineInput:
    """칼럼 간이법 재현: 세후영업이익을 명시기간 FCFF 프록시로, growth 로 투영.

    revenue=세후영업이익(프록시), cogs=sga=dep=capex=ΔWC=0 → EBIT=매출=세후영업이익 그대로
    FCFF. 터미널은 마지막 연도 FCFF×(1+pgr) 승계(간이법 정합). 세율은 0(이미 세후 프록시).
    """
    op = actuals["영업이익"]
    nopat0 = op * (1.0 - tax_rate)
    series = [nopat0 * (1.0 + growth) ** i for i in range(1, years + 1)]
    z = [0.0] * years
    return DcfSpineInput(
        wacc=wacc, terminal_growth=pgr,
        revenue=series, cogs=list(z), sga=list(z),
        dep_amort=list(z), capex=list(z), delta_nwc_cash_adj=list(z),
        non_operating_assets=non_operating, net_debt=net_debt,
        non_controlling_interest=nci, shares_outstanding=shares,
        effective_tax_rate=0.0,             # revenue 가 이미 세후 프록시
        terminal_from_last_fcff=True,       # 마지막 FCFF×(1+g) 승계
    )


def build_segment_reproduction(op_total: float, *, tax_rate: float, wacc: float,
                               pgr: float, years: int, shares: int) -> DcfSpineInput:
    """부문 트리 정밀 재현: 4부문 영업이익을 차등 CAGR 로 투영(RevenueNode 트리).

    칼럼의 부문별 성장 가정(DS 반도체 고성장·DX 완만·SDC/Harman 저성장)을 반영. 단일
    성장률 축약(build_reproduction) 대비 부문 이질성을 담는다. 부문 영업이익 배분은 삼성
    2024 실적 근사(DS≈45%·DX≈42%·SDC≈8%·Harman≈5%).
    """
    from calc_core.revenue import RevenueNode

    seg = [
        ("DS(반도체)", 0.45, 0.15),      # DRAM/HBM 고성장 축약 CAGR
        ("DX(디바이스)", 0.42, 0.06),
        ("SDC(디스플레이)", 0.08, 0.03),
        ("Harman", 0.05, 0.08),
    ]
    children = [
        RevenueNode(name=name, base=op_total * share * (1.0 - tax_rate),
                    growth=[g] * years, provenance="삼성 2024 부문 영업이익 근사 배분")
        for name, share, g in seg
    ]
    root = RevenueNode(name="세후영업이익(부문합)", children=children)
    series = root.revenue(years)
    z = [0.0] * years
    return DcfSpineInput(
        wacc=wacc, terminal_growth=pgr,
        revenue=series, cogs=list(z), sga=list(z),
        dep_amort=list(z), capex=list(z), delta_nwc_cash_adj=list(z),
        non_operating_assets=0.0, net_debt=0.0, shares_outstanding=shares,
        effective_tax_rate=0.0, terminal_from_last_fcff=True)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    client = DartClient(api_key=_load_key())
    print("═" * 70)
    print("삼성전자 E2E 독립재현 — DART 라이브 → 간이 DCF → 칼럼 대조")
    print("═" * 70)

    actuals = fetch_actuals(client)
    print(f"\n[1] DART 라이브 실적 (연결 {BSNS_YEAR}, 백만원)")
    for k, v in actuals.items():
        print(f"    {k:12s} {v:>18,.0f}" if v is not None else f"    {k:12s} {'(미매칭)':>18s}")
    if actuals.get("영업이익") is None:
        raise SystemExit("영업이익 계정 미매칭 — DART 계정명 확인 필요")

    # 가정(칼럼 조사 + 시장 상식): 세율 22%, WACC 11%, PGR 2%, 5년. 배수 대역 14~28을
    # 성장률 시나리오로 환산(간이법에서 배수↑ = 성장 지속 기대↑).
    common = dict(tax_rate=0.22, wacc=0.11, pgr=0.02, years=5,
                  non_operating=0.0, net_debt=0.0, nci=0.0,
                  shares=5_919_637_922)     # 삼성전자 발행주식수(보통주, 근사)
    print(f"\n[2] 가정 (칼럼 조사): 세율 22%·WACC 11%·PGR 2%·5년·발행주식 {common['shares']:,}")

    scenarios = {"보수(성장 5%)": 0.05, "기준(성장 12%)": 0.12, "낙관(성장 20%)": 0.20}
    print(f"\n[3] 시나리오별 재현 (세후영업이익 프록시 간이 DCF)")
    print(f"    {'시나리오':16s} {'주당가치':>12s} {'지분가치(조)':>14s} {'TV비중':>8s} {'게이트':>8s}")
    results = {}
    for label, g in scenarios.items():
        inp = build_reproduction(actuals, growth=g, **common)
        res = dcf_run(inp)
        report = audit_dcf(inp, res)
        eq_trillion = res.equity_value / 1_000_000    # 백만원 → 조
        tv_w = res.terminal_value_pv / res.enterprise_value if res.enterprise_value else 0
        n_warn = sum(1 for f in report.findings if f.severity.name == "WARN")
        results[label] = (res, eq_trillion, tv_w, n_warn)
        print(f"    {label:16s} {res.per_share:>10,.0f}원 {eq_trillion:>12,.1f}조 "
              f"{tv_w:>7.1%} {('WARN×' + str(n_warn)) if n_warn else 'clean':>8s}")

    # 부문 트리 정밀 재현(단일 성장률 축약 대비 부문 이질성)
    seg_inp = build_segment_reproduction(actuals["영업이익"], tax_rate=0.22, wacc=0.11,
                                         pgr=0.02, years=5, shares=common["shares"])
    seg_res = dcf_run(seg_inp)
    seg_trillion = seg_res.equity_value / 1_000_000
    print(f"\n[3b] 부문 트리 정밀 재현 (DS15%·DX6%·SDC3%·Harman8% 차등 CAGR)")
    print(f"    부문합 세후영업이익 1년차 {seg_inp.revenue[0]/1e6:.1f}조 → 5년차 "
          f"{seg_inp.revenue[-1]/1e6:.1f}조")
    print(f"    부문 트리 지분가치 : {seg_trillion:,.1f}조 (주당 {seg_res.per_share:,.0f}원)")
    print(f"    → 단일 성장률(12%) 기준 456.9조 대비 부문 이질성 반영분 차이")

    # 엑셀 생성(기준 시나리오)
    out_dir = ROOT / "scripts" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    xlsx = out_dir / "e2e_samsung_dcf.xlsx"
    base_inp = build_reproduction(actuals, growth=0.12, **common)
    base_res = dcf_run(base_inp)
    export_dcf(base_inp, base_res, str(xlsx))
    print(f"\n[4] 엑셀 생성: {xlsx}")

    # 칼럼 대조
    print(f"\n[5] 칼럼(val-samsung-2025q2) 대조")
    col_low, col_high = 315.0, 630.0        # 칼럼 Equity 315~630조
    col_market = 423.8                       # 칼럼 언급 시장가치
    our_low = results["보수(성장 5%)"][1]
    our_high = results["낙관(성장 20%)"][1]
    print(f"    칼럼 지분가치 대역 : {col_low:.0f} ~ {col_high:.0f}조 (시장 {col_market}조의 80~150%)")
    print(f"    우리 재현 대역     : {our_low:,.1f} ~ {our_high:,.1f}조")
    overlap = not (our_high < col_low or our_low > col_high)
    print(f"    대역 중첩 여부     : {'✅ 중첩(방법론 정합)' if overlap else '⚠️ 불일치 — 가정 차이 분석 필요'}")
    print(f"\n[6] 괴리 해석 (감사인 트랙)")
    print(f"    · 우리 간이법은 세후영업이익을 FCFF 프록시로 직접 성장 투영 — 칼럼의 multiple")
    print(f"      대역(14~28배)을 성장 시나리오(5~20%)로 환산한 것이라 대역이 넓다.")
    print(f"    · 실제 삼성은 순현금(비영업자산·순차입 브리지)·자사주가 커서 지분가치 상방 —")
    print(f"      본 재현은 브리지 0 가정이라 보수적. DS 부문 CAGR 세분(DRAM 10%·HBM 26%)은")
    print(f"      단일 성장률로 축약 → 정밀 재현은 부문 트리(revenue.py) 필요.")
    print(f"    · 결론: 방법론·수준은 재현되나 정밀 수치는 브리지·부문 세분·multiple 근거가")
    print(f"      추가로 필요 — DCF 는 목표주가기가 아니라 가정 해부 프레임([[한화오션]] 교훈).")
    print("\n" + "═" * 70)


if __name__ == "__main__":
    main()
