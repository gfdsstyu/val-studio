"""의존성 그래프(P0) 테스트 — 합성 픽스처(CI) + 비올 3파일 실측(로컬 전용).

비올 검증 세트는 계획 문서 §4의 "정답이 알려진 세트":
  · 진본: WACC 시트 끊김 **검출**(reaching 0) + DCF!H37 상수(0.113) 경로상 존재
  · 포폴판: WACC 연결 **미검출**(reaching>0, 거짓양성 방지) + H37 이 수식(=WACC!F43)

실측이 추가로 드러낸 사실(2026-08-01, 이 테스트로 고정):
  · 진본·포폴판 **모두** EBIT·WC·매출추정 시트가 결과에 미도달 — DCF 스파인이
    `DCF!M15`(EBIT) 같은 **중간 상수에서 재시작**한다("값으로 죽은 수식" 실사례).
    WACC 수정(포폴판)은 그 끊김 중 하나만 이은 것이고 나머지는 남아 있다.
    이는 도구 오탐이 아니라 모델의 실제 구조다 — 리뷰노트의 "검산행 없는 시트
    (WC·FA·EBIT)에서 결함 집중" 관찰과 정합(연결 안 된 시트는 틀려도 결과가 안
    변하니 검산이 사후에만 가능했던 것).

stdlib: `python tests/test_dependency_graph.py`
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from excel.dependency_graph import (  # noqa: E402
    BreaksReport, ancestors, build_graph, cycles, descendants, find_breaks,
    formula_ratio, propose_reconnections,
)
from excel.xlsx_reader import RCell  # noqa: E402

VIOL_ORIG = Path(r"D:\Valuation\DCF_비올\(DCF연수1기)정종범_비올_DCF Model_최종본.xlsx")
VIOL_PORT = Path(r"D:\Valuation\DCF_비올\portfolio_final\비올_DCF_Model_포트폴리오.xlsx")
TARGET = "DCF!H49"                       # 주당가치 = IFERROR(H47/H48*10^6,"")


# ── 합성 픽스처 (CI 에서도 도는 최소 검증) ─────────────────────────────────
def _wb(sheets: dict) -> dict:
    """{sheet: {ref: (value, formula)}} → read_workbook 호환 구조."""
    return {s: {r: RCell(v, f) for r, (v, f) in cells.items()}
            for s, cells in sheets.items()}


def test_reachability_and_break_detection():
    """끊김의 최소 재현: 계산 시트가 있는데 소비자는 상수를 참조."""
    wb = _wb({
        "OUT": {"A1": (100.0, "B1*2"), "B1": (50.0, None)},          # B1 = 상수(끊김 지점)
        "CALC": {"A1": (50.0, "A2+A3"), "A2": (30.0, None), "A3": (20.0, None)},
    })
    g = build_graph(wb)
    b = find_breaks(g, "OUT!A1")
    assert "OUT!B1" in b.reach and g.nodes["OUT!B1"].kind == "constant"
    assert "OUT!B1" in b.constant_inputs_in_path
    assert b.sheet_summary["CALC"] == {"reaching": 0, "not_reaching": 1}
    assert b.dead_sheets == ["CALC"]
    # CALC!A1 은 아무도 참조하지 않는 고아 수식
    assert b.orphan_formulas == ["CALC!A1"]


def test_range_reference_expansion():
    """SUM(A1:A3) 범위 참조가 멤버로 확장되어 도달성에 반영된다."""
    wb = _wb({"S": {
        "A1": (1.0, None), "A2": (2.0, None), "A3": (3.0, None),
        "B1": (6.0, "SUM(A1:A3)"),
    }})
    g = build_graph(wb)
    r = ancestors(g, "S!B1")
    assert {"S!A1", "S!A2", "S!A3"} <= r
    assert descendants(g, "S!A2") == {"S!A2", "S!B1"}


def test_cross_sheet_and_absolute_refs():
    wb = _wb({
        "A": {"C3": (0.1, None)},
        "B": {"D1": (0.2, "A!$C$3*2"), "D2": (0.3, "'A'!C3+1")},
    })
    g = build_graph(wb)
    assert descendants(g, "A!C3") == {"A!C3", "B!D1", "B!D2"}


def test_dynamic_refs_surface_as_unknown():
    """INDIRECT/OFFSET 은 조용히 무시하지 않고 unknown 으로 표면화한다."""
    wb = _wb({"S": {
        "A1": (1.0, 'INDIRECT("B"&ROW())'), "A2": (2.0, "OFFSET(B1,0,1)"),
        "B1": (3.0, "A1+1"),
    }})
    g = build_graph(wb)
    assert g.unknown_cells == {"S!A1", "S!A2"}
    b = find_breaks(g, "S!B1")
    assert b.unknown_cells == ["S!A1", "S!A2"]     # 진단이 과소평가될 수 있음을 알림


def test_external_workbook_refs_surface():
    wb = _wb({"S": {"A1": (1.0, "[다른파일.xlsx]Sheet1!B2+1")}})
    g = build_graph(wb)
    assert g.external_cells == {"S!A1"}
    # 외부 참조 토큰 자체는 노드가 아니다(열 수 없는 파일) — 파싱이 죽지 않아야 함
    assert g.precedents["S!A1"] == []


def test_cycles_detected_and_whitelisted():
    """순환 검출 + 정상 순환(3표 이자 등) 화이트리스트."""
    wb = _wb({"Model": {"A1": (1.0, "A2+1"), "A2": (2.0, "A1*0.5")},
              "DCF": {"B1": (3.0, "B1+1")}})            # 자기참조
    g = build_graph(wb)
    cs = cycles(g)
    assert len(cs) == 2
    only_dcf = cycles(g, whitelist_sheets=frozenset({"Model"}))
    assert only_dcf == [["DCF!B1"]]


def test_formula_ratio_flags_values_only():
    live = _wb({"S": {"A1": (1.0, "A2+1"), "A2": (1.0, None)}})
    dead = _wb({"S": {"A1": (1.0, None), "A2": (2.0, None), "A3": (3.0, None)}})
    assert formula_ratio(build_graph(live)) == 0.5
    assert formula_ratio(build_graph(dead)) == 0.0     # 값-only → 감사인 복원 모드 신호


def test_string_literals_do_not_create_refs():
    wb = _wb({"S": {"A1": (1.0, 'IF(B1>0,"A2 참조 아님",C1)'),
                    "B1": (1.0, None), "C1": (2.0, None)}})
    g = build_graph(wb)
    keys = {t[1] for t in g.precedents["S!A1"] if t[0] == "cell"}
    assert keys == {"S!B1", "S!C1"}                    # "A2" 문자열은 참조가 아니다


def test_reconnect_proposal_matches_dead_formula():
    """재연결 제안: 상수 잎 ↔ 미도달 수식의 캐시값 매칭 + tie-out 판정.

    비올 서명 재현: 소비자가 상수(50)를 쓰는데, 죽은 계산 시트에 같은 값을 내는
    수식이 존재 → "그 수식을 참조하라" 제안. 값이 근사(49.8)하면 value_change —
    자동 적용 금지 신호(원래 상수가 낡았다는 뜻).
    """
    wb = _wb({
        "OUT": {"A1": (100.0, "B1*2"), "B1": (50.0, None), "C1": (0.0, None)},
        "CALC": {"A9": (50.0, "A2+A3"), "A2": (30.0, None), "A3": (20.0, None)},
        "OLD": {"Z1": (49.8, "Z2*2"), "Z2": (24.9, None)},
    })
    g = build_graph(wb)
    b = find_breaks(g, "OUT!A1")
    props = propose_reconnections(g, b)
    assert len(props) == 1                          # 0 값 상수(C1)는 제안 대상 아님
    p = props[0]
    assert p.constant_cell == "OUT!B1"
    assert p.candidate_cell == "CALC!A9"            # 정확 일치(50)가 근사(49.8)를 이긴다
    assert p.tie_out == "pass" and p.suggested_formula == "=CALC!A9"


def test_reconnect_value_change_flagged():
    """근사 매칭만 있으면 value_change — 변화율이 그대로 노출된다."""
    wb = _wb({
        "OUT": {"A1": (100.0, "B1*2"), "B1": (0.113, None)},        # 비올 H37 서명
        "WACC": {"F43": (0.11252, "F41*F42"), "F41": (1.0, None), "F42": (0.11252, None)},
    })
    g = build_graph(wb)
    props = propose_reconnections(g, find_breaks(g, "OUT!A1"))
    assert [p.candidate_cell for p in props] == ["WACC!F43"]
    assert props[0].tie_out == "value_change"
    assert abs(props[0].diff_ratio - abs(0.11252 - 0.113) / 0.113) < 1e-12


def test_reconnect_quotes_sheet_names_with_spaces():
    wb = _wb({
        "OUT": {"A1": (10.0, "B1+1"), "B1": (7.0, None)},
        "peer 비용": {"C3": (7.0, "C1+C2"), "C1": (3.0, None), "C2": (4.0, None)},
    })
    g = build_graph(wb)
    props = propose_reconnections(g, find_breaks(g, "OUT!A1"))
    assert props[0].suggested_formula == "='peer 비용'!C3"


# ── 비올 실측 (로컬 전용 — 파일 없으면 이유를 밝히고 skip) ──────────────────
def test_viol_original_detects_wacc_break():
    """진본: WACC 시트 전체가 결과 미도달 + DCF!H37 이 상수(0.113)로 경로상."""
    if not VIOL_ORIG.exists():
        print("  (skip: 비올 진본 없음)"); return
    from excel.xlsx_reader import read_workbook
    t0 = time.time()
    g = build_graph(read_workbook(str(VIOL_ORIG)))
    b = find_breaks(g, TARGET)
    assert time.time() - t0 < 10                      # DoD: 대형 워크북 수 초 내
    assert "WACC" in b.dead_sheets                    # 끊김 검출
    h37 = g.nodes["DCF!H37"]
    assert h37.kind == "constant" and abs(h37.value - 0.113) < 1e-9
    assert "DCF!H37" in b.constant_inputs_in_path     # 승격 후보로 지목
    # 실측 고정: 스파인이 중간 상수에서 재시작 — EBIT·WC·매출추정 미도달("값으로 죽은 수식")
    assert {"EBIT", "WC", "매출추정"} <= set(b.dead_sheets)
    assert g.nodes["DCF!M15"].kind == "constant"
    assert b.sheet_summary["FA"]["reaching"] > 0      # FA 는 진짜 연결돼 있다(대조군)


def test_viol_portfolio_wacc_connected_no_false_positive():
    """포폴판: WACC 연결(H37=WACC!F43) → 끊김으로 **잡히면 안 된다**(거짓양성 방지)."""
    if not VIOL_PORT.exists():
        print("  (skip: 비올 포폴판 없음)"); return
    from excel.xlsx_reader import read_workbook
    g = build_graph(read_workbook(str(VIOL_PORT)))
    b = find_breaks(g, TARGET)
    assert "WACC" not in b.dead_sheets
    assert b.sheet_summary["WACC"]["reaching"] > 0
    h37 = g.nodes["DCF!H37"]
    assert h37.kind == "formula" and "WACC" in h37.formula
    assert "WACC!F43" in b.reach                      # 빌드업 결과가 실제로 흘러든다
    # WACC 만 이었고 나머지 끊김(EBIT 스파인 상수 재시작)은 그대로 — 도구가 구분해야 함
    assert {"EBIT", "WC", "매출추정"} <= set(b.dead_sheets)


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
