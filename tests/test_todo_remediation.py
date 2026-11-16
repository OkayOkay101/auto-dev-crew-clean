from auto_dev_crew.runner import Job, _todo_prompt_suffix
from auto_dev_crew.todo_scan import (
    TodoItem, _issue_body, _marker, parse_todo_issue, todo_remediation_prompt, todo_still_present,
)


def _item() -> TodoItem:
    return TodoItem("src/a.py", 3, "add retry", "x = 1\n# [AI-TODO] add retry\ny = 2",
                    _marker("src/a.py", "add retry"))


def test_parse_roundtrip():
    assert parse_todo_issue(_issue_body(_item())) == ("src/a.py", "add retry")


def test_parse_plain_issue_none():
    assert parse_todo_issue("fix the bug") is None


def test_prompt_mentions_path_and_text():
    prompt = todo_remediation_prompt("src/a.py", "add retry")
    assert prompt.startswith("## AI-TODO REMEDIATION")
    assert "src/a.py" in prompt and "add retry" in prompt and "[AI-TODO]" in prompt


def test_still_present_true_false(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n# [AI-TODO] add retry\ny = 2\n", encoding="utf-8")
    assert todo_still_present(tmp_path, "a.py", "add retry") is True
    f.write_text("x = 1\ny = 2\n", encoding="utf-8")
    assert todo_still_present(tmp_path, "a.py", "add retry") is False
    assert todo_still_present(tmp_path, "missing.py", "add retry") is False
    (tmp_path.parent / "x.py").write_text("# [AI-TODO] add retry\n", encoding="utf-8")
    assert todo_still_present(tmp_path, "../x.py", "add retry") is False


def test_prompt_suffix_only_for_todo_issue_jobs():
    body = _issue_body(_item())
    suffix = _todo_prompt_suffix(Job("issue", "7", "t", body))
    assert "## AI-TODO REMEDIATION" in suffix and "src/a.py" in suffix
    assert _todo_prompt_suffix(Job("issue", "8", "t", "fix the bug")) == ""
    assert _todo_prompt_suffix(Job("persona", "p", "t", body)) == ""
