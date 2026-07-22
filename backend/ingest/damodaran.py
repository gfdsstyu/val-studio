"""Damodaran 국가위험프리미엄(CRP) — WACC 의 마지막 미연결 입력.

방법론(교육자료·checks): CRP = 국가 부도스프레드 × (주식σ/채권σ). Ke 빌드업의
+CRP 항. β·MRP 가 성숙시장(S&P500) 기준이면 신흥국 대상회사엔 CRP 를 더한다.

⚠️ 값은 **예시 vintage 고정치**(Kroll size premium 표와 동일 원칙) — Damodaran 은 매년
1월 ctryprem 을 갱신하므로 반드시 최신값으로 교체할 것. 실무: stern.nyu.edu 에서
ctryprem.xlsx 다운로드 → parse_ctryprem 또는 /api/upload/sheet 로 갱신.

provenance: 값에 vintage 를 달아 감사 추적. country 는 한글·영문 모두 매칭.
"""
from __future__ import annotations

# Damodaran ctryprem 예시 vintage (반드시 갱신). (CRP, Moody's 등급).
DAMODARAN_VINTAGE = "2024-07 (예시 — 최신 ctryprem 으로 갱신 필요)"

# country(정규화 키) → (crp, rating). 한국 밸류에이션 상용국 + 주요국.
_CRP: dict[str, tuple[float, str]] = {
    "korea": (0.0055, "Aa2"),        "한국": (0.0055, "Aa2"),
    "usa": (0.0, "Aaa"),             "미국": (0.0, "Aaa"),
    "japan": (0.0058, "A1"),         "일본": (0.0058, "A1"),
    "china": (0.0068, "A1"),         "중국": (0.0068, "A1"),
    "germany": (0.0, "Aaa"),         "독일": (0.0, "Aaa"),
    "india": (0.0203, "Baa3"),       "인도": (0.0203, "Baa3"),
    "vietnam": (0.0281, "Ba2"),      "베트남": (0.0281, "Ba2"),
    "indonesia": (0.0169, "Baa2"),   "인도네시아": (0.0169, "Baa2"),
    "brazil": (0.0338, "Ba1"),       "브라질": (0.0338, "Ba1"),
    "taiwan": (0.0047, "Aa3"),       "대만": (0.0047, "Aa3"),
    "uk": (0.0059, "Aa3"),           "영국": (0.0059, "Aa3"),
    "france": (0.0047, "Aa2"),       "프랑스": (0.0047, "Aa2"),
}


def _norm(country: str) -> str:
    return "".join(str(country).split()).lower()


def country_risk_premium(country: str) -> float | None:
    """국가명(한/영) → CRP(소수). 미등록국은 None(유저 확인/업로드 필요)."""
    hit = _CRP.get(_norm(country))
    return hit[0] if hit else None


def country_detail(country: str) -> dict | None:
    hit = _CRP.get(_norm(country))
    if not hit:
        return None
    return {"country": country, "crp": hit[0], "rating": hit[1], "vintage": DAMODARAN_VINTAGE}


def list_countries() -> list[dict]:
    """등록국 목록(중복 키 제거, 한글명 우선). CRP 오름차순."""
    seen: dict[tuple[float, str], str] = {}
    for name, (crp, rating) in _CRP.items():
        # 한글명 우선 표기
        key = (crp, rating)
        if key not in seen or _is_hangul(name):
            seen[key] = name
    rows = [{"country": n, "crp": c, "rating": r} for (c, r), n in seen.items()]
    return sorted(rows, key=lambda x: x["crp"])


def _is_hangul(s: str) -> bool:
    return any("가" <= ch <= "힣" for ch in s)


def parse_ctryprem(rows: list[list], *, country_col: int = 0,
                   crp_col: int = 1) -> dict[str, float]:
    """업로드한 Damodaran ctryprem 표(2D) → {country: crp}. 갱신 경로.

    crp 셀은 '%'·콤마 정규화(validators). 헤더행(비숫자 crp)은 자동 스킵.
    country_col/crp_col 로 열 위치 지정(기본 0·1).
    """
    from ingest.validators import parse_number
    out: dict[str, float] = {}
    for r in rows:
        if len(r) <= max(country_col, crp_col):
            continue
        country = str(r[country_col]).strip()
        raw = str(r[crp_col]).strip()
        if not country:
            continue
        val = parse_number(raw if raw.endswith("%") else raw + "%", field_name="crp")
        if val is None:
            continue                    # 헤더·빈칸
        out[country] = float(val)
    return out
