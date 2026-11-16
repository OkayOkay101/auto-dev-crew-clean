"""Phase 0 metrics: per-group outcome summary, benchmark JSONL export, and the CLI."""
from __future__ import annotations

import json

import pytest

from auto_dev_crew import metrics, runner


def e(state: str, **fields) -> dict:
    return {"repo": "example-owner/repo-alpha", "kind": "issue", "key": "1", "title": "t",
            "state": state, **fields}


def test_summarize_groups_by_engine_with_state_counts_and_merge_rate():
    history = [
        e("MERGED", engine="nvidia"),
        e("MERGED", engine="nvidia"),
        e("FAILED", engine="nvidia"),
        e("PUSHED", engine="nvidia"),  # not in the merge_rate denominator
        e("MERGED", engine="mistral"),
        e("EVAL_FAILED", engine="mistral"),
    ]

    out = metrics.summarize(history, by="engine")

    assert out["nvidia"]["total"] == 4
    assert out["nvidia"]["MERGED"] == 2
    assert out["nvidia"]["FAILED"] == 1
    assert out["nvidia"]["PUSHED"] == 1
    assert out["nvidia"]["merge_rate"] == round(2 / 3, 3)
    assert out["mistral"]["total"] == 2
    assert out["mistral"]["merge_rate"] == 0.5


def test_merge_rate_denominator_covers_all_terminal_states_and_zero_case():
    history = [
        e("MERGED", engine="x"), e("CLOSED", engine="x"), e("FAILED", engine="x"),
        e("EVAL_FAILED", engine="x"), e("NO_ACTION", engine="x"), e("ERROR", engine="x"),
        e("DRY_RUN", engine="y"),
    ]

    out = metrics.summarize(history, by="engine")

    assert out["x"]["merge_rate"] == round(1 / 6, 3)
    assert out["y"]["merge_rate"] == 0.0  # no terminal outcomes -> 0.0, not ZeroDivisionError


def test_missing_group_field_goes_to_unknown_bucket():
    history = [e("MERGED"), e("FAILED", engine=None), e("MERGED", engine="nvidia")]

    out = metrics.summarize(history, by="engine")

    assert out["unknown"]["total"] == 2
    assert out["unknown"]["merge_rate"] == 0.5
    assert out["nvidia"]["total"] == 1


def test_summarize_by_kind_uses_same_grouping():
    history = [e("MERGED"), {"repo": "r", "kind": "persona", "key": "x", "state": "FAILED"}]

    out = metrics.summarize(history, by="kind")

    assert set(out) == {"issue", "persona"}
    assert out["persona"]["FAILED"] == 1


def test_export_benchmark_keeps_only_merged_or_closed_issues(tmp_path):
    history = [
        e("MERGED", pr=7, title="a"),
        e("CLOSED", pr=8, title="b"),
        e("FAILED", pr=9),
        {"repo": "r", "kind": "persona", "key": "p", "state": "MERGED", "pr": 3, "title": "persona"},
    ]
    path = tmp_path / "bench.jsonl"

    count = metrics.export_benchmark(history, path)

    assert count == 2
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [r["state"] for r in rows] == ["MERGED", "CLOSED"]
    assert set(rows[0]) == {"repo", "key", "title", "state", "pr"}
    assert rows[0]["pr"] == 7 and rows[1]["title"] == "b"


def test_cli_prints_one_line_per_group(tmp_path, monkeypatch, capsys):
    hist = tmp_path / "history.json"
    hist.write_text(json.dumps([e("MERGED", engine="nvidia"), e("FAILED", engine="nvidia")]), encoding="utf-8")
    monkeypatch.setattr(runner, "HISTORY", hist)

    assert metrics.main(["--by", "engine"]) == 0

    lines = capsys.readouterr().out.strip().splitlines()
    assert lines == ["nvidia 2 0.5"]


def test_cli_export_writes_file(tmp_path, monkeypatch, capsys):
    hist = tmp_path / "history.json"
    hist.write_text(json.dumps([e("MERGED", engine="nvidia", pr=1)]), encoding="utf-8")
    monkeypatch.setattr(runner, "HISTORY", hist)
    out = tmp_path / "bench.jsonl"

    assert metrics.main(["--export", str(out)]) == 0

    assert len(out.read_text(encoding="utf-8").splitlines()) == 1


def test_cli_rejects_unknown_group_field(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "HISTORY", tmp_path / "history.json")
    with pytest.raises(SystemExit):
        metrics.main(["--by", "bogus"])
