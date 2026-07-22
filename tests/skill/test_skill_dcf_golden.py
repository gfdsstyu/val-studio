"""스킬 dcf.py 골든 격리 검증 — vendored 엔진이 레포 backend 없이 8413.38 재현.

서브프로세스로 스킬 스크립트를 실행(레포 backend 미의존 증명). 임시 cwd 에서 돌려
스킬 디렉터리만으로 동작함을 확인.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".claude" / "skills" / "excel-valuation-workbook" / "scripts"
VIOL = ROOT / "fixtures" / "viol" / "inputs.json"
EXPECT = ROOT / "fixtures" / "viol" / "expected.json"


def _run(script: str, *args: str, stdin: str | None = None, cwd: str | None = None) -> dict:
    r = subprocess.run(
        [sys.executable, str(SKILL / script), *args],
        input=stdin, capture_output=True, text=True, encoding="utf-8",
        cwd=cwd or tempfile.gettempdir(),
    )
    assert r.returncode == 0, f"{script} 실패:\n{r.stderr}"
    return json.loads(r.stdout)


def test_dcf_golden_per_share():
    inputs = VIOL.read_text(encoding="utf-8")
    out = _run("dcf.py", stdin=inputs)
    expected = json.loads(EXPECT.read_text(encoding="utf-8"))["per_share"]
    # 스킬 출력은 round(2), 골든은 8413.380552 → 2자리 비교
    assert abs(out["per_share"] - round(expected, 2)) < 1e-6, \
        f"{out['per_share']} != {round(expected, 2)}"
    assert out["gate_ok"] is True


def test_dcf_isolated_no_backend_leak():
    """스킬을 임시 디렉터리로 통째 복사해 실행 — 레포 backend 전혀 없이 동작해야."""
    import shutil
    skill_root = ROOT / ".claude" / "skills" / "excel-valuation-workbook"
    with tempfile.TemporaryDirectory() as td:
        dst = Path(td) / "skill"
        shutil.copytree(skill_root, dst, ignore=shutil.ignore_patterns("__pycache__", "dist"))
        r = subprocess.run(
            [sys.executable, str(dst / "scripts" / "dcf.py")],
            input=VIOL.read_text(encoding="utf-8"),
            capture_output=True, text=True, encoding="utf-8", cwd=td,
        )
        assert r.returncode == 0, f"격리 실행 실패:\n{r.stderr}"
        out = json.loads(r.stdout)
        assert out["per_share"] == 8413.38


if __name__ == "__main__":
    test_dcf_golden_per_share()
    print("PASS test_dcf_golden_per_share")
    test_dcf_isolated_no_backend_leak()
    print("PASS test_dcf_isolated_no_backend_leak")
    print("\n2 tests passed.")
