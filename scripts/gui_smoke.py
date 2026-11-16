"""Smoke-check the Auto Dev Crew GUI with Playwright (headless Chromium).

Usage:
    python scripts/gui_smoke.py [--url http://127.0.0.1:8765] [--shot state/gui_smoke.png]

What it checks (read-only; it never clicks scan/issue/run buttons):
  1. /api/status returns JSON
  2. the main page loads with no uncaught JS error and no console.error
  3. a screenshot is saved for a human or AI to inspect

The checks live in auto_dev_crew/gui_check.py, which the runner loop also uses.

Exit code 0 = all checks passed, 1 = a check failed (details printed).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auto_dev_crew.gui_check import check_api, check_page  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--shot", default=str(ROOT / "state" / "gui_smoke.png"))
    args = ap.parse_args()

    problems = check_api(args.url) + check_page(args.url, Path(args.shot))
    if problems:
        print("FAIL")
        for line in problems:
            print(" -", line)
        return 1
    print(f"PASS  api ok, page loaded with no JS errors, screenshot: {args.shot}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
