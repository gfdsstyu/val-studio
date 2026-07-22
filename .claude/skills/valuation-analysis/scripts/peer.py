#!/usr/bin/env python
"""유사회사 선정 (Skill 도구, 3b-pre) — 4-step 퍼널 실행 + 감사 방어 리포트.

사용: python peer.py <candidates.json> [--judgments=step2.json] [--codes=C2719,C2720]
      [--seeds] [--threshold=0.7] [--min-years=2]

candidates.json: [{"ticker","name","industry_code","revenue_share_related",
                   "listed_years","suspended"}, ...]  (결측 필드 생략 가능)
step2.json:      [{"ticker","similar":true/false,"reason":"근거",
                   "uncertain":true(애매→유저 결정 큐, 자동탈락 금지)}, ...] ← LLM 산출
--seeds:         candidates 를 rough 시드로 취급, KSIC 역산 코드만 출력(Step1a)
                 (실무: 코드 확정 자체가 시드 유사회사 역산 — 코드 2~3개 union)
출력: 퍼널·최종 peer·회사별 탈락 사유 markdown (유저 승인용).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _find_backend() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "backend" / "ingest").is_dir():
            return parent / "backend"
    raise SystemExit("backend/ 를 찾을 수 없음.")


sys.path.insert(0, str(_find_backend()))

from ingest.peer_selection import (  # noqa: E402
    PeerCandidate, Step2Judgment, codes_from_seed_peers, select_peers,
)


def _load_candidates(path: str) -> list[PeerCandidate]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    return [PeerCandidate(
        ticker=str(r["ticker"]), name=r["name"],
        industry_code=r.get("industry_code"),
        revenue_share_related=r.get("revenue_share_related"),
        listed_years=r.get("listed_years"),
        suspended=bool(r.get("suspended", False)),
    ) for r in rows]


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = dict(a[2:].split("=", 1) if "=" in a else (a[2:], "1")
                for a in sys.argv[1:] if a.startswith("--"))
    if not args:
        raise SystemExit(__doc__)
    cands = _load_candidates(args[0])

    if "seeds" in opts:                     # Step1a: 시드 → KSIC 역산만
        codes = codes_from_seed_peers(cands)
        print(json.dumps({"target_industry_codes": sorted(codes)},
                         ensure_ascii=False, indent=2))
        return

    judgments = None
    if "judgments" in opts:
        judgments = [Step2Judgment(str(j["ticker"]), bool(j.get("similar", False)),
                                   j["reason"], uncertain=bool(j.get("uncertain", False)))
                     for j in json.loads(Path(opts["judgments"]).read_text(encoding="utf-8"))]
    codes = set(opts["codes"].split(",")) if "codes" in opts else None

    result = select_peers(
        cands,
        target_industry_codes=codes,
        judgments=judgments,
        revenue_share_threshold=float(opts.get("threshold", 0.70)),
        min_listed_years=float(opts.get("min-years", 2.0)),
    )
    print(result.to_markdown())


if __name__ == "__main__":
    main()
