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


def test_impairment_routes_to_viu():
    r = recommend_method("financial_reporting", "impairment")
    assert r.primary == ["viu"]
    d = r.to_dict()
    # 이 단언은 원래 `is False`(미구현 표기)였다 — VIU 엔진(calc_core.viu)·
    # /api/viu·test_viu.py 가 뒤늦게 들어오면서 사실과 어긋났고, 카탈로그가 그대로라
    # 테스트가 낡은 주장을 고정하고 있었다. 실재하므로 True 가 맞다.
    assert d["primary"][0]["available"] is True
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


def _resolve(engine: str):
    """engine 문자열 선두의 점표기 경로를 실제 객체로 해석. 경로가 없으면 None."""
    import importlib

    token = engine.split()[0]
    if "." not in token or not token.replace(".", "").replace("_", "").isalnum():
        return None                                   # "⏳ 미구현" 등 — 경로 아님
    parts = token.split(".")
    for cut in range(len(parts), 0, -1):               # 모듈/속성 경계 탐색
        try:
            mod = importlib.import_module(".".join(parts[:cut]))
        except ImportError:
            continue
        obj = mod
        for attr in parts[cut:]:
            obj = getattr(obj, attr, None)
            if obj is None:
                return None
        return obj
    return None


def test_availability_matches_reality_both_directions():
    """정직 표기 드리프트 가드 — 과대·과소 주장 양방향.

    ① available=True 인데 엔진이 없으면 = 과대 주장(없는 기능을 판다).
    ② available=False 인데 engine 에 실재 경로가 적혀 있으면 = 과소 주장.
    ②는 실제로 발생했다(2026-08-01): comps·viu 는 엔진·API·테스트가 다 있는데
    '⏳ 트랙 예정'으로 남아 셋업 위저드가 "미구현(정직 표기)"로 표시했다 —
    있는 기능을 못 쓰게 만드는, 반대 방향의 부정직.
    """
    for mid, meta in METHODS.items():
        obj = _resolve(meta["engine"])
        if meta["available"]:
            assert obj is not None, f"{mid}: available=True 인데 엔진 해석 불가 — {meta['engine']}"
        else:
            assert obj is None, f"{mid}: 엔진이 실재하는데 available=False — 표기 갱신 필요"


def test_implemented_methods_are_pinned():
    """회귀 핀 — 이 5종은 엔진·API·테스트가 실재하므로 False 로 되돌아가면 안 된다."""
    for mid in ("dcf", "base_price", "intrinsic", "comps", "viu"):
        assert METHODS[mid]["available"] is True, mid


def test_ui_axis_is_declared_and_implies_engine():
    """화면 축(ui)은 전 항목 필수 + ui=True 면 반드시 engine 도 가동이어야 한다.

    (화면만 있고 엔진이 없다 = 계산 없는 껍데기. 역은 허용 — VIU 처럼 엔진·API 만
    가동하고 전용 시트는 준비중일 수 있다.)
    """
    for mid, meta in METHODS.items():
        assert isinstance(meta.get("ui"), bool), f"{mid}: ui 축 미선언"
        if meta["ui"]:
            assert meta["available"], f"{mid}: 화면은 있는데 엔진 미가동"
    # 실측 핀: 평가인 워크스페이스에 전용 시트가 있는 것은 DCF·상대가치뿐
    assert {m for m, v in METHODS.items() if v["ui"]} == {"dcf", "comps"}


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
