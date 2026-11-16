import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIDEBAR = (ROOT / "auto_dev_crew" / "static" / "index_sidebar.html").read_text(encoding="utf-8")


def _render_block() -> str:
    m = re.search(r'\$\("#repos"\)\.innerHTML = (.*?)applyRepoFilter\(\);', SIDEBAR, re.S)
    assert m, "#repos render block not found"
    return m.group(1)


def _function_body(name: str) -> str:
    m = re.search(rf"function {name}\([^)]*\) \{{(.*?)\n\}}", SIDEBAR, re.S)
    assert m, f"function {name} not found"
    return m.group(1)


def _select(kind: str) -> str:
    m = re.search(rf'<select [^>]*data-work-filter="{kind}"[^>]*>', _render_block())
    assert m, f"select for {kind} missing in repo card template"
    return m.group(0)


class TestRepoWorkDropdown(unittest.TestCase):
    def test_each_repo_card_has_issue_and_pr_filter_selects(self):
        block = _render_block()
        self.assertIn('data-work-filter="issue"', block)
        self.assertIn('data-work-filter="pr"', block)
        self.assertIn('onchange="setAgentWorkFilter(this)"', _select("issue"))
        self.assertIn('onchange="setAgentWorkFilter(this)"', _select("pr"))

    def test_filter_selects_have_accessible_labels(self):
        for kind in ("issue", "pr"):
            self.assertIn("aria-label=", _select(kind))

    def test_issue_filter_options_match_issue_states(self):
        body = _function_body("workFilterOptions")
        self.assertIn('kind === "issue" ? ISSUE_FILTER_KEYS : PR_FILTER_KEYS', body)
        keys = re.search(r"const ISSUE_FILTER_KEYS = \[(.*?)\];", SIDEBAR).group(1)
        self.assertEqual(re.findall(r'"([^"]+)"', keys), ["queued", "working", "failed", "closed", "ignored"])

    def test_pr_filter_options_match_pr_states(self):
        keys = re.search(r"const PR_FILTER_KEYS = \[(.*?)\];", SIDEBAR).group(1)
        self.assertEqual(re.findall(r'"([^"]+)"', keys), ["OPEN", "MERGED", "CLOSED"])

    def test_tables_and_rows_expose_kind_and_status(self):
        block = _render_block()
        self.assertIn('data-work-table="issue"', block)
        self.assertIn('data-work-table="pr"', block)
        self.assertIn('<tr data-status="${esc(i.status)}">', block)
        self.assertIn('<tr data-status="${esc(p.state)}">', block)

    def test_selection_is_remembered_across_rerenders(self):
        self.assertRegex(SIDEBAR, r"const AGENT_WORK_FILTER = new Map\(\)")
        set_body = _function_body("setAgentWorkFilter")
        self.assertIn("AGENT_WORK_FILTER.set(", set_body)
        self.assertIn("applyAllWorkFilters()", set_body)
        opts = _function_body("workFilterOptions")
        self.assertIn("AGENT_WORK_FILTER.get(", opts)

    def test_filter_hides_non_matching_rows_and_shows_empty_message(self):
        body = _function_body("applyAgentWorkFilter")
        self.assertIn("tr.hidden = !hit", body)
        self.assertIn('cur === "all"', body)
        self.assertIn("data-filter-empty", body)

    def test_filters_reapplied_after_every_render(self):
        m = re.search(r"\$\(\"#repos\"\)\.innerHTML = .*?applyRepoFilter\(\);\s*applyAllWorkFilters\(\);", SIDEBAR, re.S)
        self.assertIsNotNone(m, "applyAllWorkFilters() must run right after #repos render")

    def test_new_attributes_escape_repo_name(self):
        block = _render_block()
        self.assertNotRegex(block, r"\$\{r\.name\}")
        self.assertIn('data-repo="${esc(r.name)}"', block)
        self.assertIn('data-work-table="issue" data-repo="${esc(r.name)}"', block)


if __name__ == "__main__":
    unittest.main()
