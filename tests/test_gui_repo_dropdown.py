import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIDEBAR = (ROOT / "auto_dev_crew" / "static" / "index_sidebar.html").read_text(encoding="utf-8")


def _function_body(name: str) -> str:
    m = re.search(rf"function {name}\(\) \{{(.*?)\n\}}", SIDEBAR, re.S)
    assert m, f"function {name} not found"
    return m.group(1)


class TestRepoDropdown(unittest.TestCase):
    def test_repo_list_is_inside_dropdown(self):
        m = re.search(r'<details class="repo-dd" id="repoDropdown"[^>]*>(.*?)</details>', SIDEBAR, re.S)
        self.assertIsNotNone(m, "repoDropdown <details> missing")
        inner = m.group(1)
        self.assertIn("<summary>", inner)
        self.assertIn('id="repos"', inner)
        self.assertIn('id="repoFilter"', inner)
        self.assertIn('id="repoLimit"', inner)
        self.assertIn('id="repoFilterCount"', inner)

    def test_search_input_is_type_search_and_reapplies_on_input(self):
        tag = re.search(r'<input [^>]*id="repoFilter"[^>]*>', SIDEBAR).group(0)
        self.assertIn('type="search"', tag)
        self.assertIn('oninput="applyRepoFilter()"', tag)

    def test_limit_options_present_and_reapply_on_change(self):
        sel = re.search(r'<select id="repoLimit"[^>]*>(.*?)</select>', SIDEBAR, re.S)
        self.assertIsNotNone(sel, "repoLimit select missing")
        self.assertIn('onchange="applyRepoFilter()"', sel.group(0))
        values = re.findall(r'<option value="([^"]+)"', sel.group(1))
        self.assertEqual(values, ["5", "10", "20", "all"])
        self.assertEqual(len(re.findall(r"<option [^>]*selected", sel.group(1))), 1)

    def test_repo_cards_marked_so_filter_ignores_empty_state(self):
        self.assertIn('<div class="card" data-repo-card', SIDEBAR)
        body = _function_body("applyRepoFilter")
        self.assertIn('#repos > .card[data-repo-card]', body)

    def test_filter_logic_is_case_insensitive_and_limited(self):
        body = _function_body("applyRepoFilter")
        self.assertIn(".toLowerCase()", body)
        self.assertIn('limitValue === "all" ? Infinity', body)
        self.assertIn("matched < limit", body)
        self.assertIn("card.hidden = !show", body)

    def test_count_message_shows_matched_and_total(self):
        body = _function_body("applyRepoFilter")
        self.assertIn("ตรงกับการค้นหา ${matched} จาก ${total}", body)
        self.assertIn("แสดง ${shown} จาก ${total}", body)

    def test_filter_is_called_after_every_render(self):
        render_body = re.search(r"\$\(\"#repos\"\)\.innerHTML = .*?applyRepoFilter\(\);", SIDEBAR, re.S)
        self.assertIsNotNone(render_body, "applyRepoFilter() must run after #repos is rendered")

    def test_repo_names_are_escaped_in_card_template(self):
        m = re.search(r'\$\("#repos"\)\.innerHTML = s\.repos\.length \? s\.repos\.map\(r => `(.*?)`\)\.join', SIDEBAR, re.S)
        self.assertIsNotNone(m)
        self.assertIn("esc(r.name)", m.group(1))
        self.assertNotRegex(m.group(1), r"\$\{r\.name\}")


if __name__ == "__main__":
    unittest.main()
