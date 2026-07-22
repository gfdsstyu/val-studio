#!/usr/bin/env python
"""유사회사(peer) 선정 4-step 퍼널 (Skill 도구, W5) — 웹 /api/peer/select 미러.

벤더 `ingest.peer_selection`(정본 엔진) 얇은 래퍼. 웹 PeerSheet 와 **같은 엔진·같은 결과**.
방법론: 할인율서식 §1(Step0~3) + 참고 모델 §E(83→11→9→6). Step2(사업유사성)만 LLM 판정,
나머지(코드·매출비중·베타포인트·거래정지)는 결정론. uncertain 은 자동 탈락 금지 → ⚖️큐.

입력 (stdin, JSON):
  {
    "candidates": [{"ticker","name","industry_code","revenue_share_related",
                    "listed_years","suspended"}, ...],
    "target_industry_codes": ["2710", ...],     # Step1 모집단 코드
    "seed_peers": [{"ticker","industry_code"}],  # (선택) Step1a KSIC 역산(코드 union)
    "judgments": [{"ticker","similar","uncertain","reason"}],  # (선택) Step2 LLM 판정
    "revenue_share_threshold": 0.70,             # Step3 임계
    "min_listed_years": 2.0                       # Step4 베타포인트(2Y weekly→상장 2년)
  }
출력 (stdout, JSON):
  {
    "funnel": {step→생존수}, "selected": [{ticker,name}],
    "needs_review": [{ticker,name,reason}], "dropped": [{ticker,name,dropped_at,reason}],
    "warnings": [str], "size_note": str|null, "markdown": str,
    "codes_used": [코드]   # 역산 사용 시
  }
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401

from ingest.peer_selection import (  # noqa: E402
    PeerCandidate, Step2Judgment, codes_from_seed_peers, select_peers,
)


def _candidate(d: dict) -> PeerCandidate:
    return PeerCandidate(
        ticker=str(d["ticker"]), name=str(d.get("name") or d["ticker"]),
        industry_code=d.get("industry_code"),
        revenue_share_related=d.get("revenue_share_related"),
        listed_years=d.get("listed_years"),
        suspended=bool(d.get("suspended", False)),
    )


def run_peer(payload: dict) -> dict:
    candidates = [_candidate(c) for c in payload.get("candidates", [])]

    # Step1 코드: 직접 지정 우선, 없으면 seed_peers 로 KSIC 역산(Step1a)
    codes = set(payload.get("target_industry_codes") or [])
    if not codes and payload.get("seed_peers"):
        codes = codes_from_seed_peers([_candidate(s) for s in payload["seed_peers"]])

    judgments = None
    if payload.get("judgments") is not None:
        judgments = [
            Step2Judgment(ticker=str(j["ticker"]), similar=bool(j.get("similar", False)),
                          reason=str(j.get("reason", "")), uncertain=bool(j.get("uncertain", False)))
            for j in payload["judgments"]
        ]

    result = select_peers(
        candidates,
        target_ticker=payload.get("target_ticker"),
        target_industry_codes=codes or None,
        judgments=judgments,
        revenue_share_threshold=float(payload.get("revenue_share_threshold", 0.70)),
        min_listed_years=float(payload.get("min_listed_years", 2.0)),
    )

    return {
        "funnel": result.funnel,
        "selected": [{"ticker": c.ticker, "name": c.name} for c in result.selected],
        "needs_review": [{"ticker": t.candidate.ticker, "name": t.candidate.name,
                          "reason": t.review_reason} for t in result.needs_review],
        "dropped": [{"ticker": t.candidate.ticker, "name": t.candidate.name,
                     "dropped_at": t.dropped_at, "reason": t.reason}
                    for t in result.traces if t.dropped_at],
        "warnings": [f"{t.candidate.name}: {w}" for t in result.traces for w in t.warnings],
        "size_note": result.size_note(),
        "markdown": result.to_markdown(),
        "codes_used": sorted(codes),
    }


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    raw = Path(sys.argv[1]).read_text(encoding="utf-8") if len(sys.argv) > 1 else sys.stdin.read()
    try:
        out = run_peer(json.loads(raw))
    except ValueError as e:                    # Step2 판정 누락·무사유 등 게이트 거부
        out = {"error": str(e), "gate": "step2_judgment"}
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
