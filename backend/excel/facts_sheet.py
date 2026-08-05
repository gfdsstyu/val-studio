"""`_VS_FACTS` — 워크북 공유 원장(val-studio 소유, **append-only**).

애드인끼리는 직접 통신할 수 없고 공유 매체는 워크북뿐이다. 기존 `_VS_STATE`(스킬 소유)·
`Claude Log`(Claude 소유)는 **Claude→웹 단방향**이라, 웹만 아는 것(DART/스크리너에서
가져온 사실, 판정 provenance)이 워크북에 남지 않았다. 이 시트가 그 반대 방향 채널이다.

설계 근거: docs/plan/workbook_shared_memory.md
  · **소유자별 단방향**: 이 시트는 val-studio 만 쓴다(Claude·웹은 읽기). 양방향 시트는
    잠금이 필요한데 iframe 격리에서 잠금이 불가능하다 → 채널을 나눠 각자 단방향 유지.
  · **표가 아니라 로그**: 가변 표는 갱신유실·인과성 부재·멱등성 부재를 모두 안고 간다.
    append-only + 읽기 시점 fold(키별 최대 seq)는 조정 없이 결정론적으로 수렴하며
    (연산 기반 CRDT 의 최소형 = 키별 LWW 레지스터), ISQM 이 요구하는 이력이 곧 자료구조다.
  · **작성자별 seq**: 벽시계로는 두 작성자 사이의 happens-before 를 복원할 수 없다.
    단일 작성자 안에서 단조 증가하는 순번이면 충분하다(합의 알고리즘 불요).
  · **헤더 이름으로 파싱**: 열 위치 결합은 열 하나만 끼어도 조용한 오독이 된다(P2-D).

⚠️ 워크북은 공유·전달 산출물이다 — API 키·토큰은 물론이고 **원문을 통째로 옮기지
않는다**. 값은 짧은 사실만 담고 긴 원문은 `위치`(접수번호·좌표)로 가리킨다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

FACTS_SHEET = "_VS_FACTS"
FACTS_SCHEMA_VERSION = 1
_SCHEMA_KEY = "facts_schema"
_LEDGER_HEADER = "사실 원장"

#: 열이름(사람이 읽는 라벨) → 필드명. 파싱은 이 사전으로 하며 열 순서에 의존하지 않는다.
FACTS_LABELS: dict[str, str] = {
    "순번": "seq", "키": "key", "값": "value", "방법": "method",
    "원천": "source_id", "위치": "locator", "조회일": "as_of",
    "신뢰도": "confidence", "승인상태": "approval", "작성자": "writer",
}
#: 새로 만들 때의 기본 열 배치(읽기는 라벨 기반이므로 순서는 표시 편의일 뿐).
FACTS_ORDER = ["seq", "key", "value", "method", "source_id", "locator",
               "as_of", "confidence", "approval", "writer"]
_LABEL_OF = {v: k for k, v in FACTS_LABELS.items()}

#: 이 도구가 쓰는 작성자 식별자(작성자별 seq 의 스코프).
WRITER = "val-studio"


@dataclass
class FactsLog:
    """읽어들인 원장. `rows` 는 append 순서 그대로(정렬하지 않는다)."""

    schema_version: int | None = None
    rows: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    has_labels: bool = False          # 열이름 행을 찾았는가(= 우리가 아는 원장인가)

    def fold(self) -> dict[str, dict]:
        """읽기 시점 fold — 키별 최대 seq 채택(LWW). 조정 없이 결정론적."""
        out: dict[str, dict] = {}
        for r in self.rows:
            k = str(r.get("key") or "")
            if not k:
                continue
            cur = out.get(k)
            if cur is None or _as_int(r.get("seq"), -1) >= _as_int(cur.get("seq"), -1):
                out[k] = r
        return out

    def next_seq(self, writer: str = WRITER) -> int:
        """작성자 스코프 다음 순번. 단일 작성자라 경합이 없다."""
        mine = [_as_int(r.get("seq"), 0) for r in self.rows
                if str(r.get("writer") or "") == writer]
        return (max(mine) + 1) if mine else 1


def _as_int(v, default: int) -> int:
    try:
        return int(float(str(v)))
    except (TypeError, ValueError):
        return default


def header_rows() -> list[list[object]]:
    """새 원장의 머리 4행(키·값 블록 → 구분선 → 열이름). `_VS_STATE` 배치를 미러한다."""
    labels = [_LABEL_OF[f] for f in FACTS_ORDER]
    return [
        [_SCHEMA_KEY, FACTS_SCHEMA_VERSION],
        ["owner", WRITER],
        [f"── {_LEDGER_HEADER}(append-only) ──"],
        labels,
    ]


#: 데이터 첫 행(1-based). header_rows() 길이 + 1.
FIRST_DATA_ROW = len(header_rows()) + 1


def parse_facts(rows: list[list[object]]) -> FactsLog:
    """시트 격자(1행부터의 2차원 값) → FactsLog.

    열이름 행을 찾아 **라벨로** 열을 매핑한다. 라벨을 못 찾으면 파싱하지 않는다 —
    위치로 추측해 읽으면 값이 엉뚱한 필드로 들어가고, 그건 침묵하는 오염이다.
    """
    log = FactsLog()
    label_idx: dict[str, int] | None = None
    extras: dict[str, int] = {}
    for row in rows:
        cells = [("" if c is None else str(c).strip()) for c in row]
        if not any(cells):
            continue
        if label_idx is None:
            if cells[0] == _SCHEMA_KEY and len(cells) > 1:
                log.schema_version = _as_int(cells[1], 0) or None
                continue
            # 열이름 행인가 — 아는 라벨이 2개 이상이면 그렇게 본다.
            hit = {FACTS_LABELS[c]: i for i, c in enumerate(cells) if c in FACTS_LABELS}
            if len(hit) >= 2:
                label_idx = hit
                log.has_labels = True
                extras = {c: i for i, c in enumerate(cells) if c and c not in FACTS_LABELS}
            continue
        rec: dict[str, object] = {}
        for f, i in label_idx.items():
            rec[f] = cells[i] if i < len(cells) else ""
        for label, i in extras.items():          # 모르는 열도 보존(전방 호환)
            if i < len(cells) and cells[i]:
                rec[f"x_{label}"] = cells[i]
        if str(rec.get("key") or ""):
            log.rows.append(rec)

    if label_idx is None and any(any(str(c or "").strip() for c in r) for r in rows):
        log.warnings.append(
            f"{FACTS_SHEET}: 열이름 행을 찾지 못해 읽지 않았다 — 원장이 손상됐거나 다른 시트")
    if log.schema_version and log.schema_version > FACTS_SCHEMA_VERSION:
        log.warnings.append(
            f"{FACTS_SHEET} 스키마 v{log.schema_version} — 이 빌드는 "
            f"v{FACTS_SCHEMA_VERSION} 까지 안다(모르는 항목은 무시하고 계속 읽음)")
    return log


def build_append(
    existing: list[list[object]], facts: list[dict], *, writer: str = WRITER,
) -> dict:
    """기존 격자 + 새 사실 → append 계획(헤더 필요 여부·시작 행·행 배열).

    **멱등**: 같은 키에 대해 fold 결과의 값이 동일하면 새 행을 만들지 않는다.
    프리필을 두 번 눌러도 원장이 붓지 않는다(값이 바뀌었을 때만 새 관측을 남긴다).
    """
    log = parse_facts(existing)
    folded = log.fold()
    has_content = any(any(str(c or "").strip() for c in r) for r in existing)
    # ⚠️ 내용이 있는데 열이름을 못 찾았다 = 우리가 모르는 시트다. **덮어쓰지 않는다** —
    # 공유 원장에서 정체 모를 내용을 헤더로 갈아엎으면 남의 기록이 소리 없이 사라진다.
    if has_content and not log.has_labels:
        return {
            "sheet": FACTS_SHEET, "create": False, "header_rows": [], "start_row": 0,
            "rows": [], "skipped": [], "warnings": list(log.warnings),
            "blocked": True,
            "reason": (f"'{FACTS_SHEET}' 에 내용이 있는데 원장 열이름을 찾지 못했습니다 — "
                       "다른 용도의 시트일 수 있어 기록하지 않았습니다(수동 확인 필요)."),
            "schema_version": FACTS_SCHEMA_VERSION, "existing_count": 0,
        }
    create = not has_content

    seq = log.next_seq(writer)
    new_rows: list[list[object]] = []
    skipped: list[str] = []
    for f in facts:
        key = str(f.get("key") or "").strip()
        if not key:
            continue
        value = "" if f.get("value") is None else str(f.get("value"))
        prev = folded.get(key)
        if prev is not None and str(prev.get("value") or "") == value:
            skipped.append(f"{key}: 값 동일 — 새 행을 만들지 않음(멱등)")
            continue
        rec = {"seq": seq, "key": key, "value": value,
               "method": f.get("method", ""), "source_id": f.get("source_id", ""),
               "locator": f.get("locator", ""), "as_of": f.get("as_of", ""),
               "confidence": f.get("confidence", ""),
               "approval": f.get("approval", "suggested"), "writer": writer}
        new_rows.append([rec[c] for c in FACTS_ORDER])
        seq += 1

    start = FIRST_DATA_ROW if create else _next_row(existing)
    return {
        "sheet": FACTS_SHEET,
        "create": create,
        "header_rows": header_rows() if create else [],
        "start_row": start,
        "rows": new_rows,
        "skipped": skipped,
        "warnings": list(log.warnings),
        "blocked": False,
        "reason": "",
        "schema_version": FACTS_SCHEMA_VERSION,
        "existing_count": len(log.rows),
    }


def _next_row(existing: list[list[object]]) -> int:
    """마지막으로 내용이 있는 행 다음(1-based)."""
    last = 0
    for i, row in enumerate(existing, start=1):
        if any(str(c or "").strip() for c in row):
            last = i
    return max(last + 1, FIRST_DATA_ROW)
