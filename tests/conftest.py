"""pytest 부트스트랩 — backend 를 import 경로에 추가(설치 없이 calc_core 해석)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
