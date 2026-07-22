"""vendor 동기 계약 — vendored 사본이 backend·docs 원본과 일치하는가.

`conftest.fresh_vendor` 가 세션 시작 시 stale 이면 재빌드하므로, 이 테스트는
"낡았다"고 죽는 대신 **재생성이 실제로 동기를 달성했는지**와 매니페스트 불변식을
검증한다(빌드 자체가 깨지면 여기서 잡힌다).

drift 판정은 해시뿐 아니라 **파일 집합**도 본다 — 신규 backend 모듈을 vendoring 에
넣지 않으면 해시 비교만으로는 조용히 통과하고, 스킬이 런타임에 import 실패한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from build_excel_skill import (  # noqa: E402
    VENDOR, current_manifest, drift, expected_manifest, vendor_plan,
)

MANIFEST = VENDOR / "_sync_manifest.json"


def test_manifest_exists():
    assert MANIFEST.exists(), "빌드 안 됨 — python scripts/build_excel_skill.py 실행"


def test_vendor_is_in_sync():
    """재빌드 후에도 drift 가 남으면 빌드 로직 결함(계획 ↔ 복사 불일치)."""
    d = drift()
    assert not d, ("vendor 동기 실패 — 재빌드로도 해소되지 않음:\n  "
                   + "\n  ".join(f"{k}: {v}" for k, v in d.items()))


def test_vendored_files_present():
    manifest = current_manifest()
    assert manifest, "매니페스트 비어 있음"
    missing = [rel for rel in manifest if not (VENDOR / rel).exists()]
    assert not missing, f"vendored 실물 부재: {missing}"


def test_plan_covers_engine_and_knowledge():
    """vendoring 범위 회귀 — 엔진뿐 아니라 지식(md·온톨로지)도 동기 대상이다.

    references 는 스킬 단계별 지식 주입의 정본이라, 코드만 추적하면 낡은 지식이
    조용히 스킬 컨텍스트로 들어간다(감사 2026-07-19 §5 문서부채와 같은 종류의 사고).
    """
    rels = {rel for _, rel in vendor_plan()}
    assert any(r.startswith("calc_core/") for r in rels)
    assert any(r.startswith("excel/") for r in rels)
    assert "reference/ontology/graph.json" in rels
    assert sum(r.startswith("reference/") and r.endswith(".md") for r in rels) >= 20


def test_manifest_origins_exist():
    for rel, meta in expected_manifest().items():
        assert (ROOT / meta["origin"]).exists(), f"원본 사라짐: {meta['origin']} → {rel}"


def test_drift_detects_added_file(tmp_path, monkeypatch):
    """신규 원본이 vendoring 계획에 들어오면 drift 로 잡히는가(해시-only 사각 방어)."""
    import build_excel_skill as B

    real_plan = B.vendor_plan()
    extra = ROOT / "backend" / "calc_core" / "__init__.py"      # 실존 파일 재사용
    monkeypatch.setattr(B, "vendor_plan",
                        lambda: [*real_plan, (extra, "calc_core/_probe_added.py")])
    d = B.drift()
    assert d.get("added"), "계획에 새 파일이 생겼는데 drift 가 감지하지 못함"


if __name__ == "__main__":
    test_manifest_exists()
    test_vendor_is_in_sync()
    test_vendored_files_present()
    test_plan_covers_engine_and_knowledge()
    test_manifest_origins_exist()
    print("5 tests passed (pytest 로 실행 시 6번째 monkeypatch 테스트 포함).")
