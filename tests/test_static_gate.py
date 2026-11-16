from auto_dev_crew import static_gate

FAKE_TOKEN = "ghp_" + "A" * 36  # ค่าปลอมสำหรับเทสต์ ไม่ใช่ token จริง


def _diff(*lines: str) -> str:
    return "diff --git a/app.py b/app.py\n+++ b/app.py\n" + "\n".join(lines) + "\n"


def test_secret_on_added_line_is_flagged():
    problems = static_gate.secret_problems(_diff(f'+TOKEN = "{FAKE_TOKEN}"'))
    assert problems and "app.py" in problems[0]


def test_secret_on_removed_line_is_not_flagged():
    # การลบความลับออกต้องผ่านได้ ไม่ใช่ปัญหาของ diff
    assert static_gate.secret_problems(_diff(f'-TOKEN = "{FAKE_TOKEN}"', "+TOKEN = os.environ['X']")) == []


def test_clean_added_lines_pass():
    assert static_gate.secret_problems(_diff("+x = 1", "+print('hello')")) == []


def test_python_syntax_error_is_flagged(tmp_path):
    (tmp_path / "bad.py").write_text("def broken(:\n    pass\n", encoding="utf-8")
    problems = static_gate.syntax_problems(tmp_path, ["bad.py"])
    assert problems and "bad.py" in problems[0]


def test_valid_python_passes(tmp_path):
    (tmp_path / "good.py").write_text("x = 1\n", encoding="utf-8")
    assert static_gate.syntax_problems(tmp_path, ["good.py"]) == []


def test_deleted_file_is_skipped(tmp_path):
    assert static_gate.syntax_problems(tmp_path, ["gone.py"]) == []


def test_combined_gate_reports_secret_and_syntax(tmp_path):
    (tmp_path / "bad.py").write_text("def broken(:\n", encoding="utf-8")
    problems = static_gate.static_gate_problems(tmp_path, _diff(f'+T = "{FAKE_TOKEN}"'), ["bad.py"])
    assert len(problems) == 2
