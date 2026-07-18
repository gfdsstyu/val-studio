#!/usr/bin/env python
"""excel-valuation-workbook 스킬 패키지 빌드 (자기완결 vendoring + zip).

Claude for Excel 은 레포가 없는 환경 → 스킬이 자기완결이어야 한다. 이 빌드가
결정론 엔진(calc_core·ingest.validators·excel·rag)과 지식(온톨로지·reference md)을
스킬 안으로 복사하고, backend 원본과의 SHA256 동기 매니페스트를 남긴다(drift 방지).

산출:
  .claude/skills/excel-valuation-workbook/scripts/vendor/{calc_core,ingest,excel,rag,reference}
  .claude/skills/excel-valuation-workbook/scripts/vendor/_sync_manifest.json
  .claude/skills/excel-valuation-workbook/dist/excel-valuation-workbook.zip

사용: python scripts/build_excel_skill.py
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
VENDOR_PKGS_FULL = ["calc_core", "excel"]                 # 디렉터리 통째
VENDOR_PKG_FILES = {
    # 커넥터(네트워크) 배제. peer_selection=유사회사 4-step 퍼널(stdlib, peer.py 소비).
    "ingest": ["__init__.py", "provenance.py", "validators.py", "peer_selection.py"],
    "rag": ["__init__.py", "searcher.py", "embedder.py"],
}


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _copy_pkg_full(name: str, manifest: dict) -> None:
    src = BACKEND / name
    dst = VENDOR / name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for f in sorted(dst.rglob("*.py")):
        rel = f.relative_to(VENDOR).as_posix()
        origin = (src / f.relative_to(dst)).relative_to(ROOT).as_posix()
        manifest[rel] = {"origin": origin, "sha256": _sha256(f)}


def _copy_pkg_files(name: str, files: list[str], manifest: dict) -> None:
    src = BACKEND / name
    dst = VENDOR / name
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for fn in files:
        shutil.copy2(src / fn, dst / fn)
        rel = (dst / fn).relative_to(VENDOR).as_posix()
        origin = (src / fn).relative_to(ROOT).as_posix()
        manifest[rel] = {"origin": origin, "sha256": _sha256(dst / fn)}


def _copy_reference() -> int:
    """docs/reference/*.md + ontology/{graph,rag_index}.json → vendor/reference/.

    BookSearcher(ref_dir=vendor/reference) 가 소비(레퍼런스 md + ontology json).
    """
    dst = VENDOR / "reference"
    if dst.exists():
        shutil.rmtree(dst)
    (dst / "ontology").mkdir(parents=True)
    n = 0
    for md in sorted(REF_SRC.glob("*.md")):
        shutil.copy2(md, dst / md.name)
        n += 1
    for j in ("graph.json", "rag_index.json"):
        shutil.copy2(REF_SRC / "ontology" / j, dst / "ontology" / j)
    return n


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


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    print(f"[build] excel-valuation-workbook @ {SKILL.relative_to(ROOT)}")
    VENDOR.mkdir(parents=True, exist_ok=True)

    print("1) 온톨로지 재컴파일")
    _rebuild_ontology()

    print("2) 엔진 vendoring")
    manifest: dict = {}
    for name in VENDOR_PKGS_FULL:
        _copy_pkg_full(name, manifest)
        print(f"  [ok] {name}/ (전체)")
    for name, files in VENDOR_PKG_FILES.items():
        _copy_pkg_files(name, files, manifest)
        print(f"  [ok] {name}/ ({len(files)}파일)")

    print("3) 지식 vendoring")
    n_md = _copy_reference()
    print(f"  [ok] reference/ ({n_md} md + ontology json)")

    (VENDOR / "_sync_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [ok] _sync_manifest.json ({len(manifest)} 파일 해시)")

    print("4) 패키징")
    zpath = _zip_skill()
    print(f"  [ok] {zpath.relative_to(ROOT)} ({zpath.stat().st_size // 1024} KB)")
    print("[build] 완료")


if __name__ == "__main__":
    main()
