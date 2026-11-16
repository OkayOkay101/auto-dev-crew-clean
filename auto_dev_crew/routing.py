"""Data-driven engine routing: promote engines with a proven merge rate on a triage path.

Pure function over the engine list and history; it never mutates its inputs and never drops an engine.
"""
from __future__ import annotations


def order_engines(engines: list[dict], history: list[dict], path: str, min_samples: int = 5,
                  demote_below: float = 0.2) -> list[dict]:
    """Return a new engine list reordered for triage ``path``.

    Three tiers, each in config order unless noted:
      1. proven engines with merge rate >= ``demote_below``, sorted by rate descending (ties keep config order)
      2. unproven engines (fewer than ``min_samples`` finished outcomes on ``path``, or no name)
      3. proven engines with merge rate < ``demote_below``, sorted by rate descending (ties keep config order)
    """
    # Imported here: metrics imports runner, and runner imports this module.
    from auto_dev_crew import metrics

    on_path = [entry for entry in history if entry.get("triage_path") == path]
    stats = metrics.summarize(on_path, by="engine")

    strong: list[tuple[float, int, dict]] = []
    unproven: list[dict] = []
    weak: list[tuple[float, int, dict]] = []
    for index, engine in enumerate(engines):
        name = engine.get("name")
        group = stats.get(str(name)) if name else None
        samples = sum(group.get(state, 0) for state in metrics.MERGE_RATE_DENOMINATOR) if group else 0
        if not group or samples < min_samples:
            unproven.append(engine)
            continue
        rate = group["merge_rate"]
        (strong if rate >= demote_below else weak).append((-rate, index, engine))

    strong.sort(key=lambda item: (item[0], item[1]))
    weak.sort(key=lambda item: (item[0], item[1]))
    return ([engine for _, _, engine in strong] + unproven
            + [engine for _, _, engine in weak])
