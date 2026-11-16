"""The Playwright E2E script must refuse to run without an explicit test repo."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_gui_e2e_requires_explicit_repo():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gui_e2e.py")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 2
    assert "--repo" in proc.stderr
