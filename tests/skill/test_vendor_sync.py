"""vendor 동기 검사 — vendored 엔진이 backend 원본과 바이트 동일한가(drift 감지).

빌드가 남긴 _sync_manifest.json 의 해시를 backend 원본과 대조. 불일치 = backend 가
바뀌었는데 재빌드 안 함 → `python scripts/build_excel_skill.py` 필요.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / ".claude" / "skills" / "excel-valuation-workbook" / "scripts" / "vendor"
MANIFEST = VENDOR / "_sync_manifest.json"


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_manifest_exists():
    assert MANIFEST.exists(), "빌드 안 됨 — python scripts/build_excel_skill.py 실행"


def test_vendor_matches_backend():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest, "매니페스트 비어 있음"
    stale = []
    for rel, meta in manifest.items():
        origin = ROOT / meta["origin"]
        assert origin.exists(), f"원본 사라짐: {meta['origin']}"
        if _sha256(origin) != meta["sha256"]:
            stale.append(meta["origin"])
    assert not stale, (
        "backend 원본이 vendored 사본과 다름(재빌드 필요):\n  " + "\n  ".join(stale))


def test_vendored_files_present():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for rel in manifest:
        assert (VENDOR / rel).exists(), f"vendored 파일 부재: {rel}"


if __name__ == "__main__":
    test_manifest_exists()
    print("PASS test_manifest_exists")
    test_vendor_matches_backend()
    print("PASS test_vendor_matches_backend")
    test_vendored_files_present()
    print("PASS test_vendored_files_present")
    print("\n3 tests passed.")
