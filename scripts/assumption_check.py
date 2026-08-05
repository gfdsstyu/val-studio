# -*- coding: utf-8 -*-
"""
가정 원장 자기정합성 검산 (narrative→number 다리 검증).

가정의 formula(산문 논리)를 inputs에 실행 → output_reported(리포트 표)와 비교.
잔차가 tolerance 내면 "산문 논리가 리포트 숫자를 재현" = narrative↔number 정합 입증.
잔차가 크면 방법론 차이/오류를 가리킴(checks.py CHECK행과 동일 정신).

사용: python scripts/assumption_check.py <ledger.yaml>
필요: PyYAML (없으면 최소 파서 폴백은 미지원 — pip install pyyaml)
"""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")   # 콘솔 cp949 회피
except Exception:
    pass

try:
    import yaml
except ImportError:
    print("PyYAML 필요: pip install pyyaml"); sys.exit(1)


def evaluate(formula, inputs, params, period):
    """formula 내 변수(input 키/param 키)를 period 값으로 치환해 평가.
    input/param 값이 연도별 dict면 해당 period 값을 자동 선택(연도별 비율 지원)."""
    env = {}
    for k, v in inputs.items():
        env[k] = v[period] if isinstance(v, dict) and period in v else v
    for k, v in (params or {}).items():
        env[k] = v[period] if isinstance(v, dict) and period in v else v
    # 안전: 이름/숫자/연산자만 허용
    return eval(formula, {"__builtins__": {}}, env)  # noqa: S307 (신뢰된 원장만)


def in_band(pred, reported):
    """reported가 [lo,hi] 대역이면 대역 내 여부, 단일값이면 근접 여부."""
    if isinstance(reported, list) and len(reported) == 2:
        lo, hi = min(reported), max(reported)
        return lo <= pred <= hi, f"[{lo:,}~{hi:,}]"
    return None, f"{reported:,}"


def main(path):
    doc = yaml.safe_load(open(path, encoding="utf-8"))
    inputs = doc.get("inputs", {})
    print(f"# {doc['company']} ({doc['slug']}) — 가정 원장 검산\n")
    total = passed = 0
    for a in doc.get("assumptions", []):
        f = a.get("formula")
        rep = a.get("output_reported")
        if not f or not rep:
            print(f"  ⋯ {a['id']}: formula/output 없음 — 검산 skip ({a.get('driver_type')})")
            continue
        for period, reported in rep.items():
            total += 1
            try:
                pred = evaluate(f, inputs, a.get("params"), period)
            except Exception as e:
                print(f"  ✗ {a['id']} {period}: 평가 실패 {e}"); continue
            band_ok, rep_s = in_band(pred, reported)
            if band_ok is True:
                passed += 1
                print(f"  ✓ {a['id']} {period}: 예측 {pred:,.0f} ∈ {rep_s} 백만원 — 정합")
            elif band_ok is False:
                print(f"  ✗ {a['id']} {period}: 예측 {pred:,.0f} ∉ {rep_s} — 이탈(방법론 차이/오류)")
            else:
                mid = reported
                resid = abs(pred - mid) / mid * 100
                tol = a.get("tolerance_pct", 5)
                ok = resid <= tol
                passed += ok
                mark = "✓" if ok else "✗"
                print(f"  {mark} {a['id']} {period}: 예측 {pred:,.0f} vs 보고 {mid:,} "
                      f"(잔차 {resid:.1f}% / 허용 {tol}%)")
    print(f"\n검산 {passed}/{total} 정합")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python scripts/assumption_check.py <ledger.yaml>"); sys.exit(1)
    main(sys.argv[1])
