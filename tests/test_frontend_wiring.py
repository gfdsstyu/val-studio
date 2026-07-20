"""프론트 배선 감사 — **죽은 참조**(쓰기만 하고 아무도 안 읽는 project.data 키) 탐지.

이 결함 유형이 반복해서 나왔다:
  · `macro_cpi`        — 쓰는 곳만 있고 주체가 없어 cpi 드라이버가 조용히 0% 계산(2026-07-19 감사)
  · `peer_target_ticker` — 엔진엔 R11 자기제외가 있는데 PeerSheet 가 전송 안 함(2026-07-20)
  · `three_statement_*`  — ModelSheet 가 저장만 하고 Dashboard·Report 가 안 읽음(2026-07-21)

공통 성격은 **"기능이 있는 척"** — 엔진·시트는 동작하는데 산출물이 어디에도 안 흘러
사용자는 반영됐다고 믿는다. 정적 스캔으로 고정한다.

⚠️ 정규식 휴리스틱이라 완벽하지 않다. 오탐이 나면 `ALLOWED_UNREAD` 에 **사유와 함께**
등재한다(조용히 예외 추가 금지).

실행: `py -3.12 -m pytest tests/test_frontend_wiring.py`
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

# 쓰기만 있어도 되는 키 — 반드시 사유를 남긴다.
ALLOWED_UNREAD: dict[str, str] = {
    # (현재 없음. 추가 시 "키": "왜 읽는 곳이 없어도 되는지" 형식으로.)
}

_ONSAVE = re.compile(r"onSave\?\.\(\{(.*?)\}\);", re.S)


def _top_keys(body: str) -> list[str]:
    """객체 리터럴 본문에서 **최상위 깊이의 키**만 뽑는다.

    줄 시작 정규식(`^\s*(\w+):`)으로 하면 한 줄에 여러 키가 있을 때 첫 개만 잡힌다 —
    자기검증 테스트가 실제로 이 결함을 잡아냈다. 중첩 객체의 내부 키를 오탐하지 않도록
    괄호 깊이를 세며 스캔한다.
    """
    keys, depth, buf = [], 0, ""
    for ch in body:
        if ch in "{[(":
            depth += 1
            buf = ""
        elif ch in "}])":
            depth -= 1
            buf = ""
        elif depth == 0:
            if ch == ":":
                k = buf.strip().strip("\"'")
                if re.fullmatch(r"\w+", k):
                    keys.append(k)
                buf = ""
            elif ch == ",":
                buf = ""
            else:
                buf += ch
    return keys


def _sources() -> list[Path]:
    return sorted(list(SRC.rglob("*.jsx")) + list(SRC.rglob("*.js")))


def _collect() -> tuple[dict, dict]:
    """(쓰기 {key: {파일}}, 언급 {key: {파일}}) 수집."""
    writes: dict[str, set] = defaultdict(set)
    mentions: dict[str, set] = defaultdict(set)
    for p in _sources():
        text = p.read_text(encoding="utf-8")
        for m in _ONSAVE.finditer(text):
            body = m.group(1)
            # 중첩 객체의 내부 키를 잡지 않도록 최상위 들여쓰기 라인만
            for k in _top_keys(body):
                writes[k].add(p.name)
        # 언급: 식별자 접근(d.key / data.key)이든 문자열 리터럴이든 모두 "읽음"으로 본다
        # (Dashboard 는 keys:["dcf_result_summary", …] 처럼 문자열로 참조한다)
        for k in set(re.findall(r"\b(\w*_\w+)\b", text)):
            mentions[k].add(p.name)
    return writes, mentions


# **하류 소비를 전제로 만든 산출물** 접미사. 이것만 외부 소비자를 요구한다.
#
# 왜 전체 키가 아닌가: 시트는 자기 입력 상태를 재진입 복원용으로도 저장한다
# (`peer_candidates`·`fa_input`·`revenue_tree` 등 — 쓴 시트가 스스로 읽는 게 정상).
# 전부를 검사하면 그런 정상 패턴이 대량 오탐으로 잡혀 린트가 무시당한다.
# 반면 `_summary`·`_findings`·`_result` 는 **다른 화면 보라고 만든 것**이라,
# 읽는 곳이 없으면 그 자체로 결함이다(= "기능이 있는 척").
ARTIFACT_SUFFIXES = ("_summary", "_findings", "_result")


def test_downstream_artifacts_have_consumers():
    """하류 산출물(`*_summary`·`*_findings`·`*_result`)은 **쓴 파일 밖에서** 읽혀야 한다."""
    if not SRC.is_dir():                       # 프론트 없는 체크아웃(공개 스냅샷 등)
        return
    writes, mentions = _collect()
    assert writes, "onSave 호출을 하나도 못 찾았다 — 스캐너가 깨졌을 가능성"

    dead = []
    for key, writers in sorted(writes.items()):
        if key in ALLOWED_UNREAD or not key.endswith(ARTIFACT_SUFFIXES):
            continue
        readers = mentions.get(key, set()) - writers
        if not readers:
            dead.append((key, sorted(writers)))

    assert not dead, (
        "죽은 참조(쓰기만 하고 아무도 안 읽는 키) — 기능이 '있는 척'하게 된다:\n"
        + "\n".join(f"  · {k}  (쓰기: {', '.join(w)})" for k, w in dead)
        + "\n의도적이면 ALLOWED_UNREAD 에 사유와 함께 등재하라."
    )


def test_scanner_actually_detects_a_dead_key(tmp_path=None):
    """스캐너 자체 검증 — 합성 사례에서 실제로 잡히는지.

    스캐너가 조용히 아무것도 못 잡으면 이 테스트 전체가 무의미해진다.
    """
    fake_writer = 'onSave?.({ live_summary: 1, dead_summary: 2 });'
    fake_reader = 'const x = d.live_summary;'
    writes: dict[str, set] = defaultdict(set)
    mentions: dict[str, set] = defaultdict(set)
    for name, text in (("W.jsx", fake_writer), ("R.jsx", fake_reader)):
        for m in _ONSAVE.finditer(text):
            for k in _top_keys(m.group(1)):
                writes[k].add(name)
        for k in set(re.findall(r"\b(\w*_\w+)\b", text)):
            mentions[k].add(name)
    dead = [k for k, w in writes.items()
            if k.endswith(ARTIFACT_SUFFIXES) and not (mentions.get(k, set()) - w)]
    assert dead == ["dead_summary"], (dead, dict(writes), dict(mentions))
    # 한 줄 객체의 **두 번째 키**도 잡혀야 한다 — 줄 시작 정규식이면 놓친다(실제 결함)
    assert set(writes) == {"live_summary", "dead_summary"}, dict(writes)


def test_three_statement_is_wired_end_to_end():
    """3표 산출물이 Dashboard·Report·컨텍스트 패널까지 실제로 흐르는지 고정."""
    if not SRC.is_dir():
        return
    consumers = {
        "App.jsx": "three_statement_findings",              # 우측 컨텍스트 패널
        "Dashboard.jsx": "three_statement_summary",         # 개요 배너·진행표시
        "ReportSheet.jsx": "three_statement_summary",       # 의견서 3.5절
    }
    for fname, key in consumers.items():
        hits = [p for p in _sources() if p.name == fname]
        assert hits, f"{fname} 없음"
        text = hits[0].read_text(encoding="utf-8")
        assert key in text, f"{fname} 가 {key} 를 소비하지 않는다"


def test_every_api_client_path_exists_in_backend():
    """프론트가 부르는 경로가 백엔드에 실제로 있는지 — 없으면 런타임 404."""
    api_js = SRC / "api.js"
    main_py = ROOT / "backend" / "api" / "main.py"
    if not (api_js.is_file() and main_py.is_file()):
        return
    fe = set(re.findall(r'"(/api/[^"]+)"', api_js.read_text(encoding="utf-8")))
    be_raw = set(re.findall(r'@app\.(?:post|get)\("([^"]+)"',
                            main_py.read_text(encoding="utf-8")))
    # 경로 파라미터({pid} 등)는 프리픽스 비교로 완화
    missing = set()
    for path in fe:
        if path in be_raw:
            continue
        if any(b.split("{")[0].rstrip("/") == path.rstrip("/") for b in be_raw if "{" in b):
            continue
        missing.add(path)
    assert not missing, f"백엔드에 없는 경로를 프론트가 호출: {sorted(missing)}"


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"{len(fns)}/{len(fns)} passed")
