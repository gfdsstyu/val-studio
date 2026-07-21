#!/usr/bin/env python
"""타사·벤더명 마스킹 + 유출 가드 (공개 푸시 전 필수 게이트).

이 레포는 지식 코퍼스에 Big4 교육자료·경쟁 서비스 분석이 섞여 있다. 공개 푸시 시
**법인·벤더 실명이 나가면 안 된다**. 반면 공개 인용 가능한 표준 출처(Damodaran·Kroll·
Bloomberg·한공회·DART·ECOS·KRX)와 상장 사례회사(공개 재무 기반)는 **유지**한다 —
지우면 방법론 근거가 사라져 감사방어·재현성이 무너지기 때문.

마스킹 방침:
  - 경쟁 서비스(xDCF)  : **흔적 완전 제거**(문서명·본문·링크 전부)
  - Big4/교육 벤더      : 이니셜 법인명(D사·S사·K사·M사)
  - 공개 표준 출처      : 유지(FORBIDDEN 에 없음)

두 가지 모드:
  --check  : 위반 스캔만(수정 없음). 위반 있으면 exit 1 → **푸시 전 가드/CI**
  --apply  : 본문 치환 + 파일명 변경(git mv). 멱등(재실행 안전).

실행:
  python scripts/mask_names.py --check
  python scripts/mask_names.py --apply
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 처리 대상 확장자(텍스트만). 바이너리·산출물은 제외.
TEXT_EXT = {".md", ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".txt",
            ".toml", ".yml", ".yaml", ".html", ".css", ".cfg", ".ini"}

# ── 파일명 변경 (repo 상대) ─────────────────────────────────────────────────
RENAMES: dict[str, str] = {
    "docs/reference/xDCF_계정분류_모델아키텍처.md": "docs/reference/계정분류_모델아키텍처.md",
    "docs/reference/deloitte_감사인검토_WACC방법론.md": "docs/reference/D사_감사인검토_WACC방법론.md",
    "docs/reference/msvalue_DCF_교육_정본.md": "docs/reference/M사_DCF_교육_정본.md",
    "docs/reference/msvalue_리포트예시_클래시스.md": "docs/reference/M사_리포트예시_클래시스.md",
    "docs/plan/skill_sheet_detail_msvalue.md": "docs/plan/skill_sheet_detail_M사.md",
    "docs/benchmarks/samil_pwc_easy_view.md": "docs/benchmarks/S사_easy_view.md",
}

# ── 본문 치환 (순서 = 우선순위, 긴/특수 패턴 먼저) ──────────────────────────
# ⚠️ 순서 의존: 'xDCF_계정분류' 는 'xDCF' 보다, '삼일 Fulcrum' 은 '삼일' 보다 먼저.
RULES: list[tuple[str, str]] = [
    # 경쟁 서비스 — 흔적 제거(이니셜조차 남기지 않음)
    ("xdcf.co", "타사"),
    ("xDCF_계정분류_모델아키텍처", "계정분류_모델아키텍처"),
    ("xDCF_계정분류", "계정분류"),
    ("xDCF_", "계정분류_"),
    ("xDCF", "타사"),
    ("xdcf", "타사"),
    # 교육 벤더 → M사
    ("msvalue_", "M사_"),
    ("MSVALUE", "M사"),
    ("msvalue", "M사"),
    ("엠에스밸류", "M사"),
    # Deloitte/안진 → D사
    ("deloitte_감사인검토", "D사_감사인검토"),
    ("deloitte_fas", "dfas"),
    ("Deloitte VKG=Valuation Knowledge Gateway", "D사"),
    ("Deloitte VKG", "D사"),
    ("Deloitte", "D사"),
    ("deloitte", "D사"),
    ("딜로이트", "D사"),
    ("안진", "D사"),
    # 삼일/PwC → S사
    ("삼일 Fulcrum Valuation Update", "S사 밸류에이션 자료"),
    ("삼일_Fulcrum", "S사_자료"),
    ("삼일 Fulcrum", "S사 자료"),
    ("Fulcrum", "자료"),
    ("samil_pwc_easy_view", "S사_easy_view"),
    ("삼일PwC", "S사"),
    ("PwC Easy View for Tax preview", "S사 Easy View"),
    ("PwC Easy View", "S사 Easy View"),
    ("PwC", "S사"),
    ("삼일", "S사"),
    # KPMG/삼정 → K사
    ("kpmg-korea-anti-aging", "K사-anti-aging"),
    ("KPMG", "K사"),
    ("kpmg", "K사"),
    ("삼정", "K사"),
]

# ── 유출 가드 — 남아 있으면 안 되는 토큰(대소문자 무시) ────────────────────
FORBIDDEN = ["xdcf", "deloitte", "딜로이트", "안진", "삼일", "pwc",
             "kpmg", "삼정", "msvalue", "엠에스밸류", "fulcrum"]
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
