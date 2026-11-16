"""การเขียน config.yaml ต้องคงคอมเมนต์ไว้ (auto_dev_crew/yaml_io.py, ใช้ใน gui.py และ keys.py)."""
import yaml

from auto_dev_crew import gui, yaml_io

SRC = """# top comment
merge_mode: merge-all  # inline note
repos: []
# section note
auto_issue:
  enabled: false
  trigger: after_scan
"""


def test_comments_survive_edit():
    data = yaml_io.load_text(SRC)
    data["auto_issue"]["enabled"] = True
    out = yaml_io.dump_text(data)
    assert "# top comment" in out
    assert "# inline note" in out
    assert "# section note" in out
    assert yaml.safe_load(out)["auto_issue"]["enabled"] is True


def test_none_is_written_as_null():
    out = yaml_io.dump_text({"persona": None})
    assert out.strip() == "persona: null"


def test_gui_auto_issue_post_keeps_comments(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(SRC, encoding="utf-8")
    monkeypatch.setattr(gui, "_CONFIG_OVERRIDE", path)
    gui._api_auto_issue_set({"enabled": True}, {})
    text = path.read_text(encoding="utf-8")
    assert "# top comment" in text and "# section note" in text
    assert yaml.safe_load(text)["auto_issue"]["enabled"] is True
