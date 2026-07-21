#!/usr/bin/env python
"""타사·벤더명 마스킹 + 유출 가드 (공개 푸시 전 필수 게이트).

지식 코퍼스에는 공개하면 안 되는 출처(교육 벤더·회계법인 자료, 경쟁 서비스 분석)가
섞여 있다. 반면 공개 인용 가능한 표준 출처(Damodaran·Kroll·Bloomberg·한공회·DART·
ECOS·KRX)와 상장 사례회사(공개 재무 기반)는 **유지**한다 — 지우면 방법론 근거가
사라져 감사방어·재현성이 무너지기 때문.

치환은 **2단**이다(rules 가 순서대로 연쇄 적용):
  1차 실명 → 임시 이니셜,  2차 이니셜 → **중립 서술어**.
2차가 필요한 이유: 이니셜(X사)만 남기면 "익명화했다" 는 사실 자체가 드러나 무엇이
가려졌는지 찾아보게 만든다. 최종 산출물에는 익명화 흔적조차 남기지 않는다.

두 가지 모드:
  --check  : 위반 스캔만(수정 없음). 위반 있으면 exit 1 → **푸시 전 가드/CI**
  --apply  : 본문 치환 + 파일명 변경(git mv). 멱등(재실행 안전).

실행:
  python scripts/mask_names.py --check
  python scripts/mask_names.py --apply
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 처리 대상 확장자(텍스트만). 바이너리·산출물은 제외.
TEXT_EXT = {".md", ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".txt",
            ".toml", ".yml", ".yaml", ".html", ".css", ".cfg", ".ini"}

# ── 규칙표는 **비공개 설정 파일**에서 로드 ─────────────────────────────────
# 실명 매핑 자체가 민감정보다 — 규칙을 이 스크립트에 하드코딩하면, 스크립트를 공개하는
# 순간 마스킹하려던 이름이 그대로 공개된다(가드가 자기 자신을 잡는 역설). 그래서
# 도구(이 파일)는 공개하고 매핑(mask_rules.json)은 .gitignore 로 로컬에만 둔다.
RULES_PATH = Path(__file__).resolve().parent / "mask_rules.json"


def load_rules() -> tuple[dict[str, str], list[tuple[str, str]], list[str]]:
    """(renames, rules, forbidden) 로드. 없으면 **fail-closed** — 조용한 통과 금지.

    규칙이 없는데 '위반 0' 을 반환하면 거짓 안전판이 된다. 가드는 막지 못할 때
    통과가 아니라 실패해야 한다.
    """
    if not RULES_PATH.exists():
        raise SystemExit(
            f"[mask] 규칙 파일 없음: {RULES_PATH.name}\n"
            "  이 파일은 실명 매핑을 담아 비공개(.gitignore)로 관리된다.\n"
            "  공개 클론에는 포함되지 않으며, 마스킹 가드는 원본 레포에서만 동작한다.")
    d = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    return (d.get("renames", {}),
            [(a, b) for a, b in d.get("rules", [])],
            d.get("forbidden", []))


RENAMES, RULES, FORBIDDEN = load_rules()

# 금지어는 두 부류 — 매칭 규칙이 다르다.
#  ① 실명 토큰: 대소문자 무시(Deloitte/deloitte/DELOITTE 전부 잡아야).
#  ② 이니셜(X사): **대문자 + 앞에 영문자 없음**. IGNORECASE 로 잡으면 'lookback사유'
#     의 'k사' 같은 정상 한국어가 오탐된다(실제로 걸렸다).
_INITIAL_TOKENS = [t for t in FORBIDDEN if re.fullmatch(r"[A-Z]사", t)]
_NAME_TOKENS = [t for t in FORBIDDEN if t not in _INITIAL_TOKENS]

_NAME_RE = re.compile("|".join(re.escape(t) for t in _NAME_TOKENS), re.IGNORECASE) \
    if _NAME_TOKENS else None
_INITIAL_RE = re.compile(r"(?<![A-Za-z])(?:" + "|".join(re.escape(t) for t in _INITIAL_TOKENS) + ")") \
    if _INITIAL_TOKENS else None


def _find_forbidden(s: str):
    """문자열에서 금지어 매치 이터레이트(두 규칙 합산)."""
    if _NAME_RE:
        yield from _NAME_RE.finditer(s)
    if _INITIAL_RE:
        yield from _INITIAL_RE.finditer(s)


def _has_forbidden(s: str) -> bool:
    return any(True for _ in _find_forbidden(s))


# 자기 자신은 변환 대상에서 제외 — 규칙 문자열이 담긴 파일을 스스로 치환하면
# 문서·규칙이 깨진다(실제로 독스트링이 한 번 망가졌다). 자기수정 변환기는 금물.
_SELF = {"scripts/mask_names.py", "scripts/mask_rules.json"}


def tracked_text_files() -> list[Path]:
    """git 추적 텍스트 파일만 — 공개되는 것이 곧 위험 범위. 자기 자신은 제외."""
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                         capture_output=True, check=True).stdout
    files = []
    for rel in out.decode("utf-8").split("\0"):
        if not rel or rel in _SELF:
            continue
        p = ROOT / rel
        if p.suffix.lower() in TEXT_EXT and p.is_file():
            files.append(p)
    return files


def mask_text(s: str) -> str:
    for old, new in RULES:
        s = s.replace(old, new)
    return s


def scan() -> list[tuple[str, int, str]]:
    """위반 목록 → [(repo상대경로, 행번호, 행내용)]. 파일명 위반도 포함."""
    hits: list[tuple[str, int, str]] = []
    for p in tracked_text_files():
        rel = p.relative_to(ROOT).as_posix()
        if _has_forbidden(rel):
            hits.append((rel, 0, "[파일명]"))
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if _has_forbidden(line):
                hits.append((rel, i, line.strip()[:110]))
    return hits


def apply() -> tuple[int, int]:
    """본문 치환 + 파일명 변경. → (수정 파일 수, 이름변경 수)."""
    renamed = 0
    for old, new in RENAMES.items():
        src, dst = ROOT / old, ROOT / new
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "mv", old, new], cwd=ROOT, check=True)
            renamed += 1

    changed = 0
    for p in tracked_text_files():
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        masked = mask_text(text)
        if masked != text:
            p.write_text(masked, encoding="utf-8", newline="")
            changed += 1
    return changed, renamed


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    if "--apply" in sys.argv:
        changed, renamed = apply()
        print(f"[mask] 본문 수정 {changed}파일 · 이름변경 {renamed}건")
        hits = scan()
        if hits:
            print(f"  [!] 잔여 위반 {len(hits)}건 — RULES 보강 필요:")
            for rel, ln, txt in hits[:20]:
                print(f"    {rel}:{ln} {txt}")
            sys.exit(1)
        print("  [ok] 잔여 위반 0 — 공개 안전")
        return

    hits = scan()
    if not hits:
        print("[mask] 위반 0 — 공개 푸시 안전")
        return
    print(f"[mask] 위반 {len(hits)}건 (공개 전 --apply 필요):")
    for rel, ln, txt in hits[:40]:
        print(f"  {rel}:{ln} {txt}")
    if len(hits) > 40:
        print(f"  … 외 {len(hits) - 40}건")
    sys.exit(1)


if __name__ == "__main__":
    main()
