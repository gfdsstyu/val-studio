#!/usr/bin/env python
"""타사·벤더명 마스킹 + 유출 가드 (공개 푸시 전 필수 게이트).

이 레포는 지식 코퍼스에 Big4 교육자료·경쟁 서비스 분석이 섞여 있다. 공개 푸시 시
**법인·벤더 실명이 나가면 안 된다**. 반면 공개 인용 가능한 표준 출처(Damodaran·Kroll·
Bloomberg·한공회·DART·ECOS·KRX)와 상장 사례회사(공개 재무 기반)는 **유지**한다 —
지우면 방법론 근거가 사라져 감사방어·재현성이 무너지기 때문.

마스킹 방침:
  - 경쟁 서비스        : **흔적 완전 제거**(문서명·본문·링크 전부, 이니셜조차 남기지 않음)
  - Big4/교육 벤더      : 이니셜 법인명(D사·S사·K사·M사)
  - 공개 표준 출처      : 유지(forbidden 목록에 없음)

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
_FORBIDDEN_RE = re.compile("|".join(re.escape(t) for t in FORBIDDEN), re.IGNORECASE)


def tracked_text_files() -> list[Path]:
    """git 추적 텍스트 파일만 — 공개되는 것이 곧 위험 범위."""
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                         capture_output=True, check=True).stdout
    files = []
    for rel in out.decode("utf-8").split("\0"):
        if not rel:
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
        if _FORBIDDEN_RE.search(rel):
            hits.append((rel, 0, "[파일명]"))
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if _FORBIDDEN_RE.search(line):
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
