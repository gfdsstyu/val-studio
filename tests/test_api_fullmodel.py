"""/api/xlsx/import 풀모델 라우팅 스모크 — 애드인 getFileAsync 경로의 서버측 계약.

풀모델 좌표에 비올 입력을 심은 합성 워크북을 base64 로 올려:
  ① layout=valstudio-full-v1 판별 ② 입력 복원 ③ H49 주장값 tie-out 동봉을 검증.
"""
from __future__ import annotations

import base64
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests" / "xlsx"))

try:
    from fastapi.testclient import TestClient
except ImportError:
    if "pytest" in sys.modules:
        import pytest
        pytest.skip("fastapi 미설치 — py -3.12 로 실행", allow_module_level=True)
    print("fastapi 미설치 — skip (py -3.12 로 실행)")
    sys.exit(0)

from backend.api.main import app                      # noqa: E402
from calc_core import DcfSpineInput, run              # noqa: E402
from test_fullmodel_import import GOLDEN_PER_SHARE, _build_fullmodel_xlsx  # noqa: E402

C = TestClient(app)
VIOL = ROOT / "fixtures" / "viol" / "inputs.json"


def _viol() -> DcfSpineInput:
    d = json.loads(VIOL.read_text(encoding="utf-8"))
    fields = set(DcfSpineInput.__dataclass_fields__)
    return DcfSpineInput(**{k: v for k, v in d.items() if k in fields})


def test_xlsx_import_fullmodel_route():
    inp = _viol()
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "full.xlsx"
        _build_fullmodel_xlsx(inp, str(p))
        b64 = base64.b64encode(p.read_bytes()).decode()
    r = C.post("/api/xlsx/import", json={"xlsx_b64": b64})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["layout"] == "valstudio-full-v1"
    assert abs(out["input"]["wacc"] - inp.wacc) < 1e-12
    assert abs(out["input"]["net_debt"] - inp.net_debt) < 1e-6      # -H46 부호 복원
    assert abs(out["result"]["per_share"] - GOLDEN_PER_SHARE) < 1e-3


def test_xlsx_import_fullmodel_tieout():
    """H49 에 주장값을 심으면 tie_out_workbook 동봉 — 일치/불일치 양방향."""
    inp = _viol()
    per = run(inp).per_share
    for claimed, expect in ((per, True), (per * 1.10, False)):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "full.xlsx"
            _build_fullmodel_xlsx(inp, str(p), claimed_per_share=claimed)
            b64 = base64.b64encode(p.read_bytes()).decode()
        out = C.post("/api/xlsx/import", json={"xlsx_b64": b64}).json()
        assert out["tie_out_workbook"] is expect, (claimed, out)


if __name__ == "__main__":
    test_xlsx_import_fullmodel_route()
    test_xlsx_import_fullmodel_tieout()
    print("OK")
