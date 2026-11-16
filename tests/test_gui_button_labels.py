"""Bug 3: the sandbox "🚀 เปิด Pull Request" button only queues an ai-task issue, it does not open a PR.
Bug 4: the "สร้าง PR เพิ่ม CI" button must check the bootstrap plan first and hide/disable when it says skipped.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PAGES = ("index_sidebar.html", "index.html")


def _read(name):
    return (ROOT / "auto_dev_crew" / "static" / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", PAGES)
def test_pr_button_does_not_claim_to_open_a_pull_request_now(name):
    html = _read(name)
    assert "🚀 เปิด Pull Request" not in html
    assert "กด “เปิด Pull Request”" not in html
    assert "ส่งเข้าคิวให้เอเจนต์" in html


@pytest.mark.parametrize("name", PAGES)
def test_bootstrap_ci_button_is_hidden_when_plan_says_skipped(name):
    html = _read(name)
    # The page asks the plan for each repo and records the "skipped" ones ...
    assert "/api/repos/bootstrap-ci-plan" in html
    assert '"skipped"' in html
    assert "ciHasWorkflow.add(" in html
    # ... and the repo list leaves the button out for those repos.
    assert "ciHasWorkflow.has(r.name)" in html
    # The plan must run before any confirm() that could lead to opening a PR.
    checker = html[html.index("function checkCiPlans"):html.index("async function refresh")]
    assert "/api/repos/bootstrap-ci-plan" in checker
