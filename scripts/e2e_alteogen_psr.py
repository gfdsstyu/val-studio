"""알테오젠 PSR 워크플로우 재현 — 적자 바이오의 상대가치평가(미래매출 × peer PSR → 할인).

[[실전평가_상장사_사례집]] §E2E 잔여. 적자 성장기업은 PER·EV/EBITDA 불능(이익 음수)이라
**PSR** 이 정당한 대안. 칼럼(val-alteogen-halozyme-psr) 방법:
  Halozyme TTM PSR 6.7배 × 알테오젠 2028E 매출 1.1조 → 미래 EV 7.4조
  → 연 20% 할인(3년) → 현재가치 4.28조 → 주가 75,000~95,000원 (시장 23조 = 기대 선반영).

우리 재현: `multiples.relative_valuation` 의 PSR 로 미래 매출에 peer PSR 을 적용하고(미래
지분가치), 요구수익률로 현재가치 할인한다. 순수 결정론(라이브 불요 — peer PSR·미래매출은
칼럼 조사값 주입, 실무는 이 자리에 DART/시장 데이터 배선).

실행: `py -3.12 scripts/e2e_alteogen_psr.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core.multiples import PeerMultiple, relative_valuation  # noqa: E402


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    print("═" * 70)
    print("알테오젠 PSR 워크플로우 재현 — 적자 바이오 상대가치(미래매출 × peer PSR → 할인)")
    print("═" * 70)

    # [1] 가정(칼럼 조사): Halozyme PSR 6.7배(유일 대안 — 로열티 구조 유사 peer)
    peer_psr = 6.7
    future_revenue_2028 = 1_100_000.0     # 알테오젠 2028E 매출(백만원, 1.1조)
    years_to_future = 3                     # 2025 → 2028
    required_return = 0.20                  # 연 20% 할인(고위험 바이오)
    shares = 53_000_000                     # 알테오젠 발행주식수(근사)
    market_cap = 23_000_000.0               # 현재 시총(백만원, 23조) — 대조용
    print(f"\n[1] 가정: peer PSR {peer_psr}배(Halozyme) · 2028E 매출 {future_revenue_2028/1e6:.1f}조 · "
          f"할인 {required_return:.0%}·{years_to_future}년 · 발행주식 {shares:,}")

    # [2] 미래 지분가치 = peer PSR × 미래 매출 (PSR 은 시가총액/매출 = 지분 배수)
    peers = [PeerMultiple("Halozyme", psr=peer_psr)]
    fut = relative_valuation(peers, target_sps=future_revenue_2028 / shares,
                             shares_outstanding=shares)
    # implied_per_share 는 백만원 단위(sps 가 백만원/주) → ×1e6 로 원 환산
    future_per_share = fut.psr["implied_per_share"] * 1_000_000
    future_equity = fut.psr["implied_per_share"] * shares    # 백만원
    print(f"\n[2] 미래(2028) 지분가치 = PSR × 매출 = {future_equity/1e6:.2f}조 "
          f"(주당 {future_per_share:,.0f}원)")

    # [3] 현재가치 할인
    pv_factor = 1.0 / (1.0 + required_return) ** years_to_future
    present_equity = future_equity * pv_factor
    present_per_share = future_per_share * pv_factor
    print(f"\n[3] 현재가치 = 미래 × {pv_factor:.4f} = {present_equity/1e6:.2f}조 "
          f"(주당 {present_per_share:,.0f}원)")

    # [4] 칼럼 대조
    print(f"\n[4] 칼럼 대조")
    col_present = 4.28                       # 칼럼 현재가치 4.28조
    col_low, col_high = 75_000, 95_000       # 칼럼 주가 대역
    print(f"    칼럼 현재가치      : {col_present}조 (주가 {col_low:,}~{col_high:,}원)")
    print(f"    우리 재현          : {present_equity/1e6:.2f}조 (주당 {present_per_share:,.0f}원)")
    match = col_low * 0.8 <= present_per_share <= col_high * 1.2
    print(f"    주당 대역 정합     : {'✅ 정합' if match else '⚠️ 가정 차이(매출·PSR·할인율)'}")

    # [5] PSR 사용의 정당성 + 시장 괴리
    print(f"\n[5] 해석")
    print(f"    · PSR 채택 근거: 알테오젠 적자(이익 음수) → PER·EV/EBITDA 불능. 로열티 구조로")
    print(f"      매출≈영업이익이라 PSR 이 이익배수 대용으로 정당(흑자기업이면 보조지표).")
    gap = market_cap / present_equity
    print(f"    · 시장 시총 {market_cap/1e6:.0f}조 vs 재현 {present_equity/1e6:.1f}조 = {gap:.1f}배 —")
    print(f"      시장이 임상·기술이전·추가 파이프라인 기대를 크게 선반영(PSR 모델 밖 옵션가치).")
    print(f"    · Bio 성과지표는 회계이익이 아니라 계약·임상완료·소송이므로 재무제표 직접 활용 제한.")
    print("\n" + "═" * 70)


if __name__ == "__main__":
    main()
