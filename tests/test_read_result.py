from pathlib import Path

from auto_dev_crew.runner import read_result

BS = chr(92)  # a single literal backslash


def _read(tmp_path: Path, text: str) -> dict:
    p = tmp_path / "r.json"
    p.write_text(text, encoding="utf-8")
    return read_result(p)


def test_valid_json_is_read(tmp_path):
    assert _read(tmp_path, '{"status": "NO_ACTION"}') == {"status": "NO_ACTION"}


def test_invalid_escape_from_markdown_is_repaired(tmp_path):
    # agent wrote `.apply\(` inside a JSON string: \( is not a valid JSON escape
    text = '{"summary_th": "Search `.apply' + BS + '(` and `.dt' + BS + '.date` in code", "status": "NO_ACTION"}'
    data = _read(tmp_path, text)
    assert data["status"] == "NO_ACTION"
    assert ".apply" + BS + "(" in data["summary_th"]
    assert ".dt" + BS + ".date" in data["summary_th"]


def test_valid_escapes_are_kept(tmp_path):
    text = ('{"a": "line1' + BS + 'nline2", "b": "quote ' + BS + '" here", '
            '"c": "tab' + BS + 'tend", "d": "' + BS + 'u0e01"}')
    data = _read(tmp_path, text)
    assert data["a"] == "line1\nline2"
    assert data["b"] == 'quote " here'
    assert data["c"] == "tab\tend"
    assert data["d"] == chr(0x0e01)


def test_escaped_backslash_followed_by_paren_is_kept(tmp_path):
    # valid JSON: an escaped backslash (two chars) followed by a plain "("
    data = _read(tmp_path, '{"path": "C:' + BS + BS + '(x)"}')
    assert data["path"] == "C:" + BS + "(x)"


def test_missing_file_returns_empty():
    assert read_result(Path("does-not-exist-xyz.json")) == {}


def test_unrecoverable_text_returns_empty(tmp_path):
    assert _read(tmp_path, "this is not json at all") == {}


def test_fenced_block_with_invalid_escape_is_repaired(tmp_path):
    text = 'done\n```json\n{"summary_th": "a' + BS + '(b", "status": "DONE"}\n```'
    assert _read(tmp_path, text)["status"] == "DONE"


def test_fenced_block_fallback_still_works(tmp_path):
    text = 'เสร็จแล้ว\n```json\n{"status": "NO_ACTION"}\n```'
    assert _read(tmp_path, text) == {"status": "NO_ACTION"}


def test_empty_file_returns_empty(tmp_path):
    assert _read(tmp_path, "") == {}


def test_json_list_returns_empty(tmp_path):
    assert _read(tmp_path, '[1, 2, 3]') == {}


def test_json_string_returns_empty(tmp_path):
    assert _read(tmp_path, '"just a string"') == {}


def test_json_number_returns_empty(tmp_path):
    assert _read(tmp_path, '42') == {}


def test_json_null_returns_empty(tmp_path):
    assert _read(tmp_path, 'null') == {}


def test_fenced_block_with_non_dict_returns_empty(tmp_path):
    # the fenced regex only matches {...}, but a valid object is still required
    text = 'เสร็จ\n```json\n{"status": "DONE"}\n```\nและ [1, 2]'
    assert _read(tmp_path, text)["status"] == "DONE"
