"""`_VS_FACTS` 공유 원장 — append-only · 읽기시점 fold · 멱등.

조정 프리미티브가 없는 다중작성자 환경의 해법을 자료구조로 검증한다:
  · 갱신유실 없음(지우지 않고 덧붙인다)
  · 인과성(작성자별 단조 seq) — 벽시계로는 복원 못 한다
  · 멱등(같은 값 재기록은 새 행을 만들지 않는다)
  · 모르는 내용은 **덮지 않는다**(공유면에서 남의 기록을 지우지 않는다)

stdlib: `py -3.12 tests/test_facts_sheet.py` 또는 pytest.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from excel.facts_sheet import (  # noqa: E402
    FACTS_ORDER, FACTS_SCHEMA_VERSION, FACTS_SHEET, FIRST_DATA_ROW, WRITER,
    build_append, header_rows, parse_facts,
)
from excel.workbook_diff import is_known_state_sheet, is_state_sheet  # noqa: E402
from excel.vs_state import parse_vs_state  # noqa: E402

_FACT = {"key": "peer.145020.business", "value": "보툴리눔 톡신",
         "method": "structured", "source_id": "screener",
         "locator": "FDR/KRX-DESC:Products", "as_of": "2026-08-04",
         "confidence": 0.8, "approval": "suggested"}


def _grid(plan: dict) -> list[list]:
    """계획을 실제 시트 격자로 실현 — 왕복 검증용."""
    rows = [[] for _ in range(plan["start_row"] - 1)]
    for i, h in enumerate(plan["header_rows"]):
        rows[i] = list(h)
    return rows + [list(r) for r in plan["rows"]]


# ── 등재·소유 ────────────────────────────────────────────────────────────────
def test_registered_as_known_ledger():
    assert is_state_sheet(FACTS_SHEET) and is_known_state_sheet(FACTS_SHEET)


def test_facts_sheet_is_not_parsed_as_skill_state(tmp_path):
    """아는 원장이라고 전부 같은 파서에 넣으면 없는 키가 생긴다 — 소유자가 다르다."""
    from excel.xlsx_reader import read_workbook
    from excel.xlsx_writer import Workbook
    wb = Workbook()
    s = wb.add_sheet(FACTS_SHEET)
    s.text("A1", "facts_schema"); s.num("B1", 1)
    p = tmp_path / "f.xlsx"; wb.save(str(p))
    st = parse_vs_state(read_workbook(str(p)))
    assert not st.present and "facts_schema" not in st.keys


# ── 첫 기록 ──────────────────────────────────────────────────────────────────
def test_first_write_creates_header_and_starts_after_it():
    plan = build_append([], [_FACT])
    assert plan["create"] and not plan["blocked"]
    assert plan["start_row"] == FIRST_DATA_ROW
    assert plan["header_rows"][-1][0] == "순번"          # 마지막 머리행 = 열이름
    assert len(plan["rows"]) == 1
    assert plan["rows"][0][FACTS_ORDER.index("seq")] == 1
    assert plan["rows"][0][FACTS_ORDER.index("approval")] == "suggested"
    assert plan["rows"][0][FACTS_ORDER.index("writer")] == WRITER


def test_round_trip_parse_reads_back_what_was_written():
    grid = _grid(build_append([], [_FACT]))
    log = parse_facts(grid)
    assert log.has_labels and log.schema_version == FACTS_SCHEMA_VERSION
    assert [r["key"] for r in log.rows] == ["peer.145020.business"]
    assert log.rows[0]["value"] == "보툴리눔 톡신"
    assert log.rows[0]["approval"] == "suggested"


# ── append-only · 인과성 · 멱등 ──────────────────────────────────────────────
def test_same_value_is_idempotent():
    """두 번 눌러도 원장이 붓지 않는다 — 재시도·더블클릭 방어."""
    grid = _grid(build_append([], [_FACT]))
    plan = build_append(grid, [_FACT])
    assert plan["rows"] == [] and not plan["create"]
    assert any("멱등" in s for s in plan["skipped"])


def test_changed_value_appends_without_deleting():
    grid = _grid(build_append([], [_FACT]))
    plan = build_append(grid, [{**_FACT, "value": "톡신·필러"}])
    assert len(plan["rows"]) == 1
    assert plan["rows"][0][FACTS_ORDER.index("seq")] == 2      # 작성자 스코프 단조 증가
    assert plan["start_row"] == FIRST_DATA_ROW + 1             # 기존 행 아래에 이어쓴다
    assert plan["existing_count"] == 1                          # 옛 행은 그대로 남는다


def test_fold_takes_latest_by_seq_not_by_row_order():
    """읽기 시점 fold — 행 순서가 아니라 seq 로 결정한다(작성 순서가 뒤섞여도 결정론)."""
    g = _grid(build_append([], [_FACT]))
    g = g + [list(build_append(g, [{**_FACT, "value": "최신"}])["rows"][0])]
    # 옛 관측을 뒤에 덧붙여도(순서 교란) fold 는 seq 가 큰 쪽을 고른다
    g = g + [["1", _FACT["key"], "옛값", "", "", "", "", "", "", WRITER]]
    assert parse_facts(g).fold()[_FACT["key"]]["value"] == "최신"


def test_seq_is_writer_scoped():
    g = _grid(build_append([], [_FACT]))
    g = g + [["7", "other.key", "남의 값", "", "", "", "", "", "", "claude"]]
    log = parse_facts(g)
    assert log.next_seq(WRITER) == 2          # 남의 7 에 영향받지 않는다
    assert log.next_seq("claude") == 8


# ── 열이름 기반 · 방어 ───────────────────────────────────────────────────────
def test_parsed_by_label_not_position():
    """열을 중간에 끼워도 필드가 밀리지 않는다(P2-D 와 같은 규율)."""
    grid = [["facts_schema", 1], ["── 사실 원장(append-only) ──"],
            ["순번", "비고", "키", "값", "작성자"],
            [1, "메모", "peer.x.business", "제품", WRITER]]
    log = parse_facts(grid)
    r = log.rows[0]
    assert r["key"] == "peer.x.business" and r["value"] == "제품"
    assert r["x_비고"] == "메모"                # 모르는 열도 보존


def test_unknown_content_is_never_overwritten():
    """내용이 있는데 원장 열이름이 없다 = 남의 시트. 덮지 않고 차단한다."""
    plan = build_append([["회사", "매출"], ["A", 100]], [_FACT])
    assert plan["blocked"] and plan["rows"] == []
    assert "기록하지 않았습니다" in plan["reason"]


def test_higher_schema_warns_but_still_reads():
    grid = _grid(build_append([], [_FACT]))
    grid[0] = ["facts_schema", FACTS_SCHEMA_VERSION + 1]
    log = parse_facts(grid)
    assert log.rows and any("스키마 v" in w for w in log.warnings)


def test_blank_keys_are_ignored():
    plan = build_append([], [{"key": "  ", "value": "x"}, _FACT])
    assert len(plan["rows"]) == 1


# ── API ──────────────────────────────────────────────────────────────────────
def test_api_facts_append_plan():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip fastapi 미설치")
        return
    from api.main import app
    client = TestClient(app)

    r = client.post("/api/facts/append-plan", json={"existing": [], "facts": [_FACT]})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["sheet"] == FACTS_SHEET and plan["create"] and len(plan["rows"]) == 1

    # 같은 값 재기록 → 멱등
    again = client.post("/api/facts/append-plan",
                        json={"existing": _grid(plan), "facts": [_FACT]}).json()
    assert again["rows"] == [] and again["skipped"]

    assert client.post("/api/facts/append-plan",
                       json={"existing": [], "facts": []}).status_code == 422


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    ok = skipped = 0
    for fn in fns:
        if fn.__code__.co_argcount:
            print(f"  skip {fn.__name__} (픽스처 필요)"); skipped += 1; continue
        try:
            fn(); ok += 1; print(f"  ok  {fn.__name__}")
        except Exception:
            print(f"  FAIL {fn.__name__}"); traceback.print_exc()
    print(f"\n{ok}/{len(fns) - skipped} passed ({skipped} skipped)")
