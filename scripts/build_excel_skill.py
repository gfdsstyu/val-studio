#!/usr/bin/env python
"""excel-valuation-workbook 스킬 패키지 빌드 (자기완결 vendoring + zip).

Claude for Excel 은 레포가 없는 환경 → 스킬이 자기완결이어야 한다. 이 빌드가
결정론 엔진(calc_core·ingest.validators·excel·rag)과 지식(온톨로지·reference md)을
스킬 안으로 복사하고, backend 원본과의 SHA256 동기 매니페스트를 남긴다(drift 방지).

산출:
  .claude/skills/excel-valuation-workbook/scripts/vendor/{calc_core,ingest,excel,rag,reference}
  .claude/skills/excel-valuation-workbook/scripts/vendor/_sync_manifest.json
  .claude/skills/excel-valuation-workbook/dist/excel-valuation-workbook.zip

vendor/ 는 **derived artifact**(gitignore) — 커밋되지 않으므로 drift 는 레포가 아니라
로컬 작업본 문제다. 신선도가 필요한 순간은 둘뿐: ① 스킬 테스트 실행(스크립트가
`_bootstrap` 으로 vendor 를 sys.path 최상단에 올려 **vendored 사본을 검증**한다 —
낡으면 테스트가 옛 backend 를 통과시킨다) ② zip 패키징. 그래서 git 훅이 아니라
**빌드 의존성**으로 다룬다: `tests/skill/conftest.py` 가 stale 이면 자동 재빌드한다.

사용:
  python scripts/build_excel_skill.py            # 전체 빌드(+zip)
  python scripts/build_excel_skill.py --no-zip   # vendoring 만(테스트 경로)
  python scripts/build_excel_skill.py --check    # 변경 없이 drift 만 보고(exit 1)
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
REF_SRC = ROOT / "docs" / "reference"
SKILL = ROOT / ".claude" / "skills" / "excel-valuation-workbook"
VENDOR = SKILL / "scripts" / "vendor"
DIST = SKILL / "dist"

# ── vendoring 대상 (backend 상대경로) — 해시 동기 검사 대상 ──────────────────
# 패키지는 전체 복사, 일부는 지정 파일만(커넥터 등 무거운/네트워크 모듈 배제).
VENDOR_PKGS_FULL = ["calc_core", "excel", "report"]       # 디렉터리 통째
VENDOR_PKG_FILES = {
    # 커넥터(네트워크) 배제. peer_selection=유사회사 4-step 퍼널(stdlib, peer.py 소비).
    # footnote_costs=성격별 원가 주석 추출(stdlib, footnote_costs.py 소비) + 그 백본
    # parsers/base(BaseParser). dart_employee 등 네트워크 커넥터는 계속 배제.
    "ingest": ["__init__.py", "provenance.py", "validators.py", "peer_selection.py",
               "footnote_costs.py", "parsers/__init__.py", "parsers/base.py"],
    "rag": ["__init__.py", "searcher.py", "embedder.py"],
}


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def vendor_plan() -> list[tuple[Path, str]]:
    """vendoring 대상 전량 → [(원본 절대경로, vendor 상대경로)].

    **빌드와 drift 검사의 공용 SSOT.** 둘이 각자 목록을 만들면 갈라져서, 검사가
    통과하는데 빌드 산출이 다른 상황이 생긴다. 지식(reference)도 포함 —
    md 가 스킬의 단계별 지식 주입 정본이라 코드만큼 drift 가 위험하다.
    """
    plan: list[tuple[Path, str]] = []
    for name in VENDOR_PKGS_FULL:
        src = BACKEND / name
        for f in sorted(src.rglob("*.py")):
            if "__pycache__" in f.parts:
                continue
            plan.append((f, (Path(name) / f.relative_to(src)).as_posix()))
    for name, files in VENDOR_PKG_FILES.items():
        for fn in files:
            plan.append((BACKEND / name / fn, f"{name}/{fn}"))
    # 지식(reference)은 **선택적** — 공개 배포본은 저작권상 지식 코퍼스를 포함하지 않는다.
    # 없으면 조용히 건너뛴다(엔진·도구는 지식 없이도 동작). 있으면 vendoring 대상.
    for md in sorted(REF_SRC.glob("*.md")):
        plan.append((md, f"reference/{md.name}"))
    for j in ("graph.json", "rag_index.json"):
        src = REF_SRC / "ontology" / j
        if src.exists():
            plan.append((src, f"reference/ontology/{j}"))
    return plan


def expected_manifest() -> dict:
    """현재 원본 기준으로 vendoring 되어야 할 매니페스트(복사하지 않고 계산)."""
    return {rel: {"origin": src.relative_to(ROOT).as_posix(), "sha256": _sha256(src)}
            for src, rel in vendor_plan()}


def current_manifest() -> dict:
    """마지막 빌드가 남긴 매니페스트(없으면 빈 dict)."""
    path = VENDOR / "_sync_manifest.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def drift() -> dict[str, list[str]]:
    """재빌드가 필요한 이유 → {added|removed|changed|missing: [origin…]}.

    해시 변경만 보면 **파일 추가·삭제를 놓친다**(새 모듈을 vendoring 하지 않아도
    조용히 통과 → 스킬이 import 실패). 파일 집합과 해시를 모두 대조한다.
    missing = 매니페스트엔 있는데 vendor 에 실물이 없는 경우(수동 삭제·빌드 중단).
    """
    exp, cur = expected_manifest(), current_manifest()
    out = {
        "added": sorted(exp[r]["origin"] for r in exp.keys() - cur.keys()),
        "removed": sorted(cur[r]["origin"] for r in cur.keys() - exp.keys()),
        "changed": sorted(exp[r]["origin"] for r in exp.keys() & cur.keys()
                          if exp[r]["sha256"] != cur[r]["sha256"]),
        "missing": sorted(cur[r]["origin"] for r in cur.keys() & exp.keys()
                          if not (VENDOR / r).exists()),
    }
    return {k: v for k, v in out.items() if v}


def is_stale() -> bool:
    return bool(drift())


def _copy_all(manifest: dict) -> int:
    """vendor_plan() 대로 복사 + 매니페스트 기록. 대상 트리는 먼저 비운다."""
    for name in [*VENDOR_PKGS_FULL, *VENDOR_PKG_FILES, "reference"]:
        d = VENDOR / name
        if d.exists():
            shutil.rmtree(d)
    n_ref = 0
    for src, rel in vendor_plan():
        dst = VENDOR / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        manifest[rel] = {"origin": src.relative_to(ROOT).as_posix(), "sha256": _sha256(dst)}
        if rel.startswith("reference/") and rel.endswith(".md"):
            n_ref += 1
    return n_ref


def _rebuild_ontology() -> None:
    """빌드 전 온톨로지 재컴파일(drift 방지). 실패해도 기존 산출로 진행."""
    build_py = REF_SRC / "ontology" / "build.py"
    if not build_py.exists():
        print("  [skip] ontology/build.py 없음")
        return
    try:
        subprocess.run([sys.executable, str(build_py)], cwd=ROOT, check=True,
                       capture_output=True, text=True)
        print("  [ok] ontology 재컴파일")
    except (subprocess.CalledProcessError, OSError) as e:
        print(f"  [warn] ontology 재컴파일 실패(기존 산출 사용): {e}")


def _zip_skill() -> Path:
    DIST.mkdir(parents=True, exist_ok=True)
    out = DIST / "excel-valuation-workbook.zip"
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(SKILL.rglob("*")):
            if f.is_dir() or f == out or "__pycache__" in f.parts:
                continue
            if f.relative_to(SKILL).parts[0] == "dist":
                continue
            zf.write(f, f.relative_to(SKILL).as_posix())
    return out


def build(*, zip_package: bool = True, rebuild_ontology: bool = True,
          verbose: bool = True) -> dict:
    """vendoring 실행 → 매니페스트. 테스트 경로는 zip·온톨로지를 건너뛴다(빠른 재빌드).

    온톨로지 재컴파일은 subprocess 라 테스트에서 생략한다 — 생략해도 drift 오탐은
    없다(매니페스트가 `docs/reference/ontology/*.json` **원본**을 해시하므로).
    """
    def say(msg: str) -> None:
        if verbose:
            print(msg)

    VENDOR.mkdir(parents=True, exist_ok=True)
    if rebuild_ontology:
        say("1) 온톨로지 재컴파일")
        _rebuild_ontology()

    say("2) 엔진·지식 vendoring")
    manifest: dict = {}
    n_ref = _copy_all(manifest)
    say(f"  [ok] {', '.join([*VENDOR_PKGS_FULL, *VENDOR_PKG_FILES])} + reference/ ({n_ref} md)")

    (VENDOR / "_sync_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    say(f"  [ok] _sync_manifest.json ({len(manifest)} 파일 해시)")

    if zip_package:
        say("3) 패키징")
        zpath = _zip_skill()
        say(f"  [ok] {zpath.relative_to(ROOT)} ({zpath.stat().st_size // 1024} KB)")
    return manifest


def _print_drift(d: dict[str, list[str]]) -> None:
    labels = {"added": "vendoring 누락(신규)", "removed": "원본 사라짐",
              "changed": "원본 변경", "missing": "vendor 실물 부재"}
    for kind, origins in d.items():
        print(f"  [{labels[kind]}] {len(origins)}건")
        for o in origins:
            print(f"    - {o}")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    check_only = "--check" in sys.argv
    print(f"[build] excel-valuation-workbook @ {SKILL.relative_to(ROOT)}")

    if check_only:
        d = drift()
        if not d:
            print("  [ok] vendor 동기 — 재빌드 불요")
            return
        print("  [stale] 재빌드 필요:")
        _print_drift(d)
        sys.exit(1)

    build(zip_package="--no-zip" not in sys.argv)
    print("[build] 완료")


if __name__ == "__main__":
    main()
