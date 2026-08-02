"""pytest 부트스트랩 — backend 를 import 경로에 추가(설치 없이 calc_core 해석).

추가로 **vendor 오염 격리**를 한다. 배경:

tests/skill/ 의 테스트들은 스킬 스크립트의 `_bootstrap` 을 타고, 그것이
`.claude/skills/*/scripts/vendor/` 를 sys.path **최상단**에 올린다. vendor 는
backend 의 사본(빌드 산출물)이라 `ingest`·`calc_core` 같은 같은 이름의 패키지를
갖고 있다.

문제는 수집 순서다. pytest 는 디렉터리·파일을 알파벳순으로 수집하므로
`golden` → `skill` → `test_*.py` 순이 되고, `skill` 이 sys.path 를 오염시킨 뒤
나머지 전부가 vendor 사본을 import 하게 된다. vendor 는 부분 사본이라
`ImportError: cannot import name 'ksic' from 'ingest'` 류로 31개 모듈이 수집
단계에서 죽었다(2026-07-29 발견). 개별 파일 실행은 멀쩡해서 오래 안 보였다.

그래서 스킬 테스트가 아닌 모듈을 임포트하기 **직전마다** vendor 를 걷어낸다.
스킬 테스트 자신은 vendor 가 검증 대상이므로 건드리지 않는다(이미 임포트를
끝낸 모듈들은 객체 참조를 들고 있어 sys.modules 정리의 영향을 받지 않는다).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_BACKEND = str(_ROOT / "backend")

sys.path.insert(0, _BACKEND)

_SKILL_TESTS = f"tests{os.sep}skill"


def _is_vendor(path: str) -> bool:
    """`.claude/skills/<이름>/scripts/vendor` 트리에 속하는 경로인가."""
    norm = path.replace("\\", "/")
    return "/skills/" in norm and "/vendor" in norm


def _purge_vendor() -> None:
    """sys.path 에서 vendor 를 제거하고, 거기서 로드된 모듈을 sys.modules 에서 뺀다.

    모듈까지 비우지 않으면 이미 캐시된 vendor 패키지가 계속 재사용되어
    경로만 고쳐도 소용이 없다. backend 는 최상단으로 되돌린다.
    """
    if not any(_is_vendor(p) for p in sys.path):
        return
    sys.path[:] = [p for p in sys.path if not _is_vendor(p)]
    for name, mod in list(sys.modules.items()):
        if _is_vendor(getattr(mod, "__file__", "") or ""):
            del sys.modules[name]
    if _BACKEND in sys.path:
        sys.path.remove(_BACKEND)
    sys.path.insert(0, _BACKEND)


def pytest_collectstart(collector) -> None:
    """모듈 임포트 직전 훅 — 스킬 테스트가 아니면 vendor 오염을 걷어낸다."""
    path = str(getattr(collector, "path", "") or "")
    if _SKILL_TESTS in path:          # 스킬 테스트는 vendor 가 검증 대상
        return
    _purge_vendor()
