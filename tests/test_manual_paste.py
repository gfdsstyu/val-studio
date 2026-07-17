"""수동 복붙 커넥터 테스트 — 범위 sanity·Kd 매트릭스·provenance·게이트.

stdlib: `python tests/test_manual_paste.py`.
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ingest.manual_paste import (  # noqa: E402
    PasteParser, check_range, paste_beta, paste_mrp, paste_risk_free,
)
from ingest.provenance import ExtractMethod, SourceKind  # noqa: E402
from ingest.validators import Severity  # noqa: E402


def _sev(report, rule):
    return [f.severity for f in report.findings if f.rule == rule]


def test_beta_in_range_passes():
    r = paste_beta("1.15", source_id="Bloomberg", pasted_at="2023-06-30", user="jjb")
    pv = r.by_name("beta")
    assert pv.value == Decimal("1.15")
    assert r.ok                                        # FAIL 없음
    assert Severity.PASS in _sev(r.report, "range")
    # provenance: MANUAL 출처 + 붙여넣은 날짜/사용자
    assert pv.provenance.source_kind is SourceKind.MANUAL
    assert pv.provenance.method is ExtractMethod.MANUAL
    assert "2023-06-30" in pv.provenance.note and "jjb" in pv.provenance.note
    assert pv.provenance.confidence == 0.9             # 복붙 <1


def test_beta_out_of_range_fails():
    # 복붙 오타(4.5) → hard 경계 밖 FAIL, 게이트 차단
    r = paste_beta("4.5", source_id="Bloomberg", pasted_at="2023-06-30")
    assert not r.ok
    assert Severity.FAIL in _sev(r.report, "range")


def test_beta_unusual_warns():
    # 통상범위(0.2~2.0) 밖이지만 hard(0~3) 안 → WARN(통과하되 확인권장)
    r = paste_beta("2.6", source_id="Bloomberg", pasted_at="2023-06-30")
    assert r.ok
    assert Severity.WARN in _sev(r.report, "range")


def test_mrp_percent_to_ratio():
    # 8% → 0.08, 통상 5~11% 안 → PASS
    r = paste_mrp("8", source_id="한공회", pasted_at="2024-01-01")
    assert r.by_name("mrp").value == Decimal("0.08")
    assert Severity.PASS in _sev(r.report, "range")


def test_mrp_too_high_fails():
    r = paste_mrp("20", source_id="한공회", pasted_at="2024-01-01")   # 20% > 15% hard
    assert not r.ok


def test_risk_free_parses():
    r = paste_risk_free("3.45%", source_id="KOFIABOND", pasted_at="2023-06-30")
    assert r.by_name("risk_free").value == Decimal("0.0345")
    assert r.ok


def test_bond_matrix_with_header():
    text = (
        "등급 1Y 2Y 3Y 5Y\n"
        "AAA 3.21 3.35 3.48 3.72\n"
        "AA+ 3.45 3.60 3.75 4.01\n"
        "BBB 5.10 5.40 5.80 6.50\n"
    )
    p = PasteParser("KOFIABOND", pasted_at="2023-06-30", user="jjb")
    m = p.parse_bond_matrix(text)
    assert m.tenors == ["1Y", "2Y", "3Y", "5Y"]
    assert m.yield_of("AAA", "1Y") == Decimal("0.0321")     # 3.21% → 비율
    assert m.yield_of("BBB", "5Y") == Decimal("0.0650")
    assert set(m.grades()) == {"AAA", "AA+", "BBB"}
    assert p.result.ok                                       # 전 셀 범위 OK
    # 각 셀이 provenance 부착돼 방출됨
    pv = p.result.by_name("AAA_1Y")
    assert pv.provenance.source_kind is SourceKind.MANUAL
    assert "AAA×1Y" in pv.provenance.note


def test_bond_matrix_bad_cell_fails_gate():
    # 한 셀이 금리 범위 밖(35% > 30%) → 게이트 차단, 어느 셀인지 추적
    text = "등급 1Y 2Y\nAAA 3.21 35.0\n"
    p = PasteParser("KOFIABOND", pasted_at="2023-06-30")
    p.parse_bond_matrix(text)
    assert not p.result.ok
    fails = [f for f in p.result.report.fails if f.rule == "range"]
    assert any("AAA_2Y" in f.message for f in fails)


def test_check_range_none_value_warns():
    f = check_range("beta", None, "beta")
    assert f.severity is Severity.WARN


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
