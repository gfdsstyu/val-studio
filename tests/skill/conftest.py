"""스킬 테스트 부트스트랩 — vendor 를 **빌드 의존성**으로 다룬다.

스킬 스크립트는 `_bootstrap` 으로 `scripts/vendor/` 를 sys.path 최상단에 올린다.
따라서 vendor 가 낡으면 이 디렉터리의 테스트들은 **옛 backend 를 검증하고 통과한다** —
드리프트의 진짜 위험은 동기 테스트가 빨개지는 게 아니라 이 침묵이다.

vendor/ 는 gitignore 되는 derived artifact 라 커밋에 실리지 않는다. 그래서 git 훅이
아니라 make 식 **의존성 재생성**이 맞다: stale 이면 세션 시작 시 한 번 재빌드한다
(1초 남짓, zip·온톨로지 생략). 변경 없이 확인만 하려면 `--check` 를 쓴다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from build_excel_skill import build, drift  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def fresh_vendor() -> dict:
    """세션 1회: vendor 가 stale 이면 재빌드. 반환값은 재생성 사유(없으면 빈 dict)."""
    reasons = drift()
    if reasons:
        build(zip_package=False, rebuild_ontology=False, verbose=False)
    return reasons
