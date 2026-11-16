"""Read-only outcome metrics over state/history.json (Phase 0 measurement).

Usage: python -m auto_dev_crew.metrics [--by engine|kind|key|triage_path] [--export PATH]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from auto_dev_crew import runner

STATES = ("MERGED", "CLOSED", "FAILED", "EVAL_FAILED", "NO_ACTION", "ERROR", "PUSHED", "DRY_RUN")
# Terminal outcomes that count toward merge_rate; PUSHED/DRY_RUN are still in flight or dry runs.
MERGE_RATE_DENOMINATOR = ("MERGED", "CLOSED", "FAILED", "EVAL_FAILED", "NO_ACTION", "ERROR")
GROUP_FIELDS = ("engine", "kind", "key", "triage_path")
BENCHMARK_STATES = ("MERGED", "CLOSED")


def _group_name(entry: dict, by: str) -> str:
    value = entry.get(by)
    return "unknown" if value is None or value == "" else str(value)


def summarize(history: list[dict], by: str = "engine") -> dict[str, dict]:
    """Group history entries by field `by`. Each group has `total`, a count per state seen,
    and `merge_rate` = MERGED / terminal outcomes (0.0 when there are none)."""
    groups: dict[str, dict] = {}
    for entry in history:
        group = groups.setdefault(_group_name(entry, by), {"total": 0})
        group["total"] += 1
        state = entry.get("state") or "unknown"
        group[state] = group.get(state, 0) + 1
    for group in groups.values():
        denom = sum(group.get(s, 0) for s in MERGE_RATE_DENOMINATOR)
        group["merge_rate"] = round(group.get("MERGED", 0) / denom, 3) if denom else 0.0
    return groups


def export_benchmark(history: list[dict], path: Path) -> int:
    """Write one JSONL row per issue whose state is MERGED or CLOSED. Returns the row count."""
    rows = [
        {"repo": e.get("repo"), "key": e.get("key"), "title": e.get("title"),
         "state": e.get("state"), "pr": e.get("pr")}
        for e in history
        if e.get("state") in BENCHMARK_STATES and e.get("kind") == "issue"
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m auto_dev_crew.metrics", description=__doc__.splitlines()[0])
    parser.add_argument("--by", choices=GROUP_FIELDS, default="engine", help="field to group by (default: engine)")
    parser.add_argument("--export", type=Path, metavar="PATH", help="write MERGED/CLOSED issues to a JSONL file")
    args = parser.parse_args(argv)

    history = runner.load_history()
    for name, group in sorted(summarize(history, by=args.by).items()):
        print(f"{name} {group['total']} {group['merge_rate']}")
    if args.export:
        count = export_benchmark(history, args.export)
        print(f"exported {count} rows -> {args.export}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
