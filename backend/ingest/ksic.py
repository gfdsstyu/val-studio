"""KSIC(한국표준산업분류) 로컬 조회 — peer 선정 Step1a 의 "쓱 찾기" 지원.

데이터: backend/data/ksic10.json — KSIC 10차(2017) 전 2,000코드(중분류 2자리 ~
세세분류 5자리), 출처 FinanceData/KSIC(_meta 에 provenance). DART induty_code 와
동일 체계라 시드 유사회사의 코드 역산([[peer_selection]] codes_from_seed_peers)과
바로 맞물린다.

용법(Step1a 실무 플로우):
  ① 키워드로 후보 코드 탐색: search("의료용 기기") → [('2719', '기타 의료용...'), ...]
  ② 시드 회사의 세세분류(5자리)에서 모집단 코드로 일반화: parents("27192") →
     세분류(2719)·소분류(271)·중분류(27) — 실무는 보통 세분류(4자리) 2~3개 union.
  ③ 코드 계층 확인: children("2719") → 하위 세세분류 전부.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parents[1] / "data" / "ksic10.json"


@lru_cache(maxsize=1)
def _load() -> dict[str, str]:
    return json.loads(_DATA.read_text(encoding="utf-8"))["codes"]


def name(code: str) -> str | None:
    """코드 → 분류명. 없으면 None."""
    return _load().get(code)


def search(keyword: str, *, limit: int = 20) -> list[tuple[str, str]]:
    """분류명 부분일치 탐색(공백 구분 다중 키워드 AND). 코드 오름차순."""
    terms = [t for t in keyword.split() if t]
    hits = [(c, n) for c, n in _load().items()
            if all(t in n for t in terms)]
    return sorted(hits)[:limit]


def parents(code: str) -> list[tuple[str, str]]:
    """코드의 상위 계층(짧은 접두 코드들). 27192 → [(27,..),(271,..),(2719,..)]."""
    codes = _load()
    return [(code[:k], codes[code[:k]])
            for k in range(2, len(code)) if code[:k] in codes]


def children(prefix: str) -> list[tuple[str, str]]:
    """접두 코드의 하위 전부(자기 제외). 모집단 범위 확인용."""
    return sorted((c, n) for c, n in _load().items()
                  if c.startswith(prefix) and c != prefix)


def population_codes(seed_codes: set[str], *, level: int = 4) -> set[str]:
    """시드(보통 5자리 세세분류) → 모집단용 상위 레벨 코드 union.

    실무 기본 = 세분류(4자리): 세세분류 그대로는 너무 좁고, 중분류(2자리)는 너무
    넓다. 시드가 level 보다 짧으면 그대로 둔다."""
    return {c[:level] if len(c) > level else c for c in seed_codes}


def main() -> None:
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    if len(sys.argv) < 2:
        raise SystemExit('사용: python ksic.py "키워드"  |  python ksic.py 2719')
    q = " ".join(sys.argv[1:])
    if q.replace(" ", "").isdigit():                    # 코드 조회 + 계층
        code = q.strip()
        print(f"{code}: {name(code) or '(없음)'}")
        for c, n in parents(code):
            print(f"  ↑ {c}: {n}")
        for c, n in children(code)[:15]:
            print(f"  ↓ {c}: {n}")
    else:
        for c, n in search(q):
            print(f"{c}: {n}")


if __name__ == "__main__":
    main()
