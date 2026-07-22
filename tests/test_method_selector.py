"""평가방법론 셀렉터 테스트 — 법제 매핑(북 정본) 결정론 검증.

stdlib: `python tests/test_method_selector.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from calc_core.method_selector import METHODS, recommend_method  # noqa: E402


def test_listed_merger_is_base_price_band():
    r = recommend_method("regulatory", "merger", target_listed=True, counterparty_listed=True)
    assert r.primary == ["base_price"] and not r.uncertain
    assert "±30%" in r.legal_basis and "10%" in r.legal_basis      # 밴드·계열사 특칙


def test_unlisted_merger_is_intrinsic_with_comps_disclosure():
    r = recommend_method("regulatory", "merger", target_listed=False, counterparty_listed=True)
    assert r.primary == ["intrinsic"] and "comps" in r.secondary
    assert "0.4" in r.legal_basis and "0.6" in r.legal_basis
    assert any("DCF" in n for n in r.notes)                        # 수익가치=DCF 투입


def test_merger_unknown_listing_is_uncertain():
    # 판단보조 원칙: 상장여부 미확정이면 결론 강제 대신 uncertain
    r = recommend_method("regulatory", "merger")
    assert r.uncertain


def test_unlisted_share_purchase_is_dcf():
    r = recommend_method("regulatory", "share_purchase", target_listed=False)
    assert r.primary == ["dcf"] and "11/13" in r.legal_basis       # 공시 실측 근거


def test_impairment_routes_to_viu_future_track():
    r = recommend_method("financial_reporting", "impairment")
    assert r.primary == ["viu"]
    d = r.to_dict()
    assert d["primary"][0]["available"] is False                   # 미구현 정직 표기
    assert any("entity-specific" in n for n in r.notes)


def test_tax_is_supplementary_with_expert_note():
    r = recommend_method("tax", "inheritance_gift")
    assert r.primary == ["tax_supplementary"]
    assert any("전문가" in n for n in r.notes)


def test_unknown_combo_is_uncertain_not_invented():
    r = recommend_method("???", None)
    assert r.uncertain and any("임의 추천하지 않습니다" in n for n in r.notes)


def test_catalog_integrity():
    # 모든 추천 id 가 카탈로그에 존재 + available 은 bool
    for m, meta in METHODS.items():
        assert isinstance(meta["available"], bool), m
    for args in [("regulatory", "merger", True, True), ("transaction", "investment"),
                 ("regulatory", "business_transfer"), ("financial_reporting", "ppa")]:
        r = recommend_method(*args)
        for mid in r.primary + r.secondary:
            assert mid in METHODS, mid


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
