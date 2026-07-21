"""footnote_costs.py 단위 검증 — 주석 성격별 추출 + 드라이버 제안 + tie-out (W2.5 ①단).

vendored ingest.footnote_costs 를 _bootstrap 경유로 소비하므로, 이 테스트는 **vendor 트리가
동기 상태인지도 간접 검증**한다(미vendoring 이면 import 실패).
`python tests/skill/test_footnote_costs.py` 또는 `pytest tests/skill/test_footnote_costs.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SKILL = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "excel-valuation-workbook" / "scripts"
sys.path.insert(0, str(_SKILL))

import footnote_costs  # noqa: E402
import fs_disagg  # noqa: E402

_TABLE = (
    "구분        2024      2023\n"
    "급여        12,340    11,200\n"
    "퇴직급여     1,500     1,300\n"
    "감가상각비   3,200     3,000\n"
    "지급수수료   2,000     1,900\n"
)
# sga 확정 성격 합(2024) = 12,340 + 1,500 + 2,000 = 15,840 (감가상각비는 uncertain 제외)
_SGA_2024 = 15840


def test_extract_natures_and_years():
    out = footnote_costs.run_footnote_costs({"text": _TABLE, "note_no": 24})
    assert out["gate_ok"] is True
    assert out["years"] == ["2024", "2023"]
    by = {n["name"]: n for n in out["natures"]}
    assert set(by) == {"급여", "퇴직급여", "감가상각비", "지급수수료"}
    assert by["급여"]["amounts"]["2024"] == 12340.0
    assert by["급여"]["amounts"]["2023"] == 11200.0


def test_driver_suggestion():
    """성격 → W4 드라이버 제안(판정은 평가인, 여기선 제안값 확인)."""
    out = footnote_costs.run_footnote_costs({"text": _TABLE})
    by = {n["name"]: n for n in out["natures"]}
    assert by["급여"]["method"] == "headcount" and by["급여"]["category"] == "sga"
    assert by["퇴직급여"]["method"] == "headcount"
    assert by["지급수수료"]["method"] == "cpi"
    assert by["감가상각비"]["method"] == "fa_dep"


def test_ambiguous_category_is_uncertain():
    """감가상각비 = 제조/판관 배분 애매 → uncertain, 자동확정 금지(롤업 제외)."""
    out = footnote_costs.run_footnote_costs({"text": _TABLE})
    dep = next(n for n in out["natures"] if n["name"] == "감가상각비")
    assert dep["uncertain"] is True and dep["category"] is None
    # sga 블록 children 에 감가상각비가 들어가면 안 된다(평가인이 배분 지정 전)
    blk = next(b for b in out["disagg_payload"]["blocks"] if b["parent"] == "판매비와관리비")
    assert "감가상각비" not in blk["periods"]["2024"]["children"]


def test_tieout_pass():
    """Σ성격별(sga) == IS 표기 판관비 → sum FAIL 없음, gate 통과."""
    out = footnote_costs.run_footnote_costs(
        {"text": _TABLE, "year": "2024", "stated_sga": _SGA_2024})
    assert out["gate_ok"] is True
    assert not any(i["code"] == "sum" and i["severity"] == "FAIL" for i in out["issues"])
    # 미확정 카테고리는 롤업 불가 → WARN 으로 표면화
    assert any(i["code"] == "by_nature_tieout" and i["severity"] == "WARN"
               for i in out["issues"])


def test_tieout_fail_blocks_gate():
    """표기 판관비를 조작(20,000) → Σ성격별 ≠ 표기 → FAIL, gate 차단."""
    out = footnote_costs.run_footnote_costs(
        {"text": _TABLE, "year": "2024", "stated_sga": 20000})
    assert out["gate_ok"] is False
    assert any(i["code"] == "sum" and i["severity"] == "FAIL" for i in out["issues"])


def test_chain_into_fs_disagg():
    """①추출 → ②세분검증 사슬: disagg_payload 를 fs_disagg 가 그대로 소비, 합보존 통과."""
    out = footnote_costs.run_footnote_costs(
        {"text": _TABLE, "year": "2024", "stated_sga": _SGA_2024})
    dis = fs_disagg.run_disagg(out["disagg_payload"])
    assert dis["gate_ok"] is True
    row = dis["disaggregated"]["판매비와관리비"]["2024"]
    assert row["_total"] == float(_SGA_2024)
    assert row["_residual"] == 0.0                     # 추출값이 원계정을 정확히 재구성
    mix = dis["mix"]["판매비와관리비"]["2024"]
    assert abs(mix["급여"] - 12340 / _SGA_2024) < 1e-6


def test_chain_detects_injected_error():
    """추출 후 값이 오염되면 ②가 잡는다(clean-truth 오라클 — 사슬의 존재 이유)."""
    out = footnote_costs.run_footnote_costs(
        {"text": _TABLE, "year": "2024", "stated_sga": _SGA_2024})
    blk = out["disagg_payload"]["blocks"][0]
    blk["periods"]["2024"]["children"]["급여"] = "10000"   # 12,340 → 10,000 오염
    dis = fs_disagg.run_disagg({"blocks": [blk]})
    assert dis["gate_ok"] is False
    assert any(i["code"] == "disagg_imbalance" for i in dis["issues"])


def test_cost_line_drafts_seed_w4():
    """W4 드라이버 초안: base=최근연도(열 순서 무관), method=제안."""
    out = footnote_costs.run_footnote_costs({"text": _TABLE})
    d = {x["name"]: x for x in out["drafts"]}
    assert d["급여"]["base"] == 12340.0 and d["급여"]["method"] == "headcount"
    assert d["감가상각비"]["uncertain"] is True


def test_cogs_block_when_manufacturing_natures():
    """제조원가명세서(재료비·노무비) → cogs 블록 방출."""
    text = "구분  2024\n원재료비  5,000\n"
    out = footnote_costs.run_footnote_costs(
        {"text": text, "year": "2024", "stated_cogs": 5000})
    blk = next(b for b in out["disagg_payload"]["blocks"] if b["parent"] == "매출원가")
    assert blk["periods"]["2024"]["children"]["원재료비"] == "5000"
    assert out["gate_ok"] is True


def test_empty_text_gate_false():
    out = footnote_costs.run_footnote_costs({"text": "   "})
    assert out["gate_ok"] is False
    assert any(i["code"] == "no_input" for i in out["issues"])


def test_no_nature_warns_not_forced():
    """성격 행을 못 읽으면 WARN — 억지 분해 금지(총액 유지 + 미확보 표면화)."""
    out = footnote_costs.run_footnote_costs({"text": "머리말만 있고 값이 없음\n"})
    assert any(i["code"] == "no_nature" and i["severity"] == "WARN" for i in out["issues"])
    assert out["natures"] == []


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed.")
