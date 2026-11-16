"""Data-driven engine routing: order_engines and its wiring into runner.execute."""
from __future__ import annotations

import copy

from auto_dev_crew import routing, runner
from auto_dev_crew.runner import Job
from tests.test_runner_lifecycle import make_cfg, make_rcfg


def eng(name: str) -> dict:
    return {"name": name, "command": name}


def h(engine: str, state: str, path: str = "fast") -> dict:
    return {"engine": engine, "state": state, "triage_path": path, "kind": "issue", "key": "1"}


def names(engines: list[dict]) -> list[str]:
    return [e["name"] for e in engines]


def test_engines_with_enough_samples_sorted_by_merge_rate_first():
    engines = [eng("a"), eng("b"), eng("c")]
    history = (
        [h("a", "MERGED")] * 2 + [h("a", "FAILED")] * 3      # a: 2/5 = 0.4
        + [h("b", "MERGED")] * 5                               # b: 5/5 = 1.0
        + [h("c", "MERGED")] * 4 + [h("c", "NO_ACTION")]       # c: 4/5 = 0.8
    )

    out = routing.order_engines(engines, history, "fast", min_samples=5)

    assert names(out) == ["b", "c", "a"]


def test_few_samples_fall_back_to_config_order():
    engines = [eng("a"), eng("b"), eng("c")]
    history = [h("c", "MERGED")] * 4 + [h("b", "MERGED")] * 4  # below min_samples=5

    out = routing.order_engines(engines, history, "fast", min_samples=5)

    assert names(out) == ["a", "b", "c"]


def test_proven_engine_moves_first_and_unproven_keep_config_order():
    engines = [eng("a"), eng("b"), eng("c"), eng("d")]
    history = [h("c", "FAILED")] * 5 + [h("d", "MERGED")] * 5 + [h("b", "MERGED")] * 2

    out = routing.order_engines(engines, history, "fast", min_samples=5)

    # d (rate 1.0) leads; c (rate 0.0 < demote_below) drops below the unproven a and b.
    assert names(out) == ["d", "a", "b", "c"]


def test_ties_keep_config_order():
    engines = [eng("x"), eng("y"), eng("z")]
    history = [h("z", "MERGED")] * 5 + [h("x", "MERGED")] * 5 + [h("y", "MERGED")] * 5

    out = routing.order_engines(engines, history, "fast", min_samples=5)

    assert names(out) == ["x", "y", "z"]


def test_only_history_on_same_triage_path_counts():
    engines = [eng("a"), eng("b")]
    history = [h("b", "MERGED", path="heavy")] * 5 + [h("a", "MERGED", path="fast")] * 5

    out = routing.order_engines(engines, history, "fast", min_samples=5)

    assert names(out) == ["a", "b"]


def test_non_terminal_states_do_not_count_as_samples():
    engines = [eng("a"), eng("b")]
    history = [h("b", "PUSHED")] * 9 + [h("b", "MERGED")] * 4  # only 4 finished outcomes

    out = routing.order_engines(engines, history, "fast", min_samples=5)

    assert names(out) == ["a", "b"]


def test_proven_but_low_merge_rate_is_demoted_below_unproven():
    engines = [eng("bad"), eng("new"), eng("good"), eng("worse")]
    history = ([h("bad", "FAILED")] * 4 + [h("bad", "MERGED")]      # 0.2 -> kept as proven
               + [h("worse", "FAILED")] * 5)                         # 0.0 -> demoted
    history += [h("good", "MERGED")] * 5

    out = routing.order_engines(engines, history, "fast", min_samples=5)

    assert names(out) == ["good", "bad", "new", "worse"]


def test_demote_below_threshold_is_configurable():
    engines = [eng("a"), eng("c")]
    history = [h("a", "MERGED")] * 2 + [h("a", "FAILED")] * 3   # 0.4, proven

    default = routing.order_engines(engines, history, "fast", min_samples=5)
    strict = routing.order_engines(engines, history, "fast", min_samples=5, demote_below=0.5)

    assert names(default) == ["a", "c"]
    assert names(strict) == ["c", "a"]


def test_demote_below_default_is_point_two():
    engines = [eng("a"), eng("b")]
    history = [h("a", "MERGED")] + [h("a", "FAILED")] * 4       # 0.2 exactly -> not demoted
    history += [h("b", "FAILED")] * 5                           # 0.0 -> demoted

    out = routing.order_engines(engines, history, "fast", min_samples=5)

    assert names(out) == ["a", "b"]


def test_demoted_engines_are_kept_sorted_by_rate_among_themselves():
    engines = [eng("x"), eng("y"), eng("z")]
    history = [h("x", "MERGED")] + [h("x", "FAILED")] * 9       # 0.1
    history += [h("y", "FAILED")] * 5                            # 0.0
    history += [h("z", "MERGED")] * 1 + [h("z", "FAILED")] * 4   # 0.2 (kept)

    out = routing.order_engines(engines, history, "fast", min_samples=5)

    assert names(out) == ["z", "x", "y"]


def test_engines_without_name_keep_config_order_and_are_not_dropped():
    anon = {"command": "anon"}
    engines = [anon, eng("b")]
    history = [h("b", "MERGED")] * 5

    out = routing.order_engines(engines, history, "fast", min_samples=5)

    assert out[0] == {"name": "b", "command": "b"}
    assert out[1] is anon
    assert len(out) == 2


def test_input_engines_and_history_are_not_mutated():
    engines = [eng("a"), eng("b")]
    history = [h("b", "MERGED")] * 5
    engines_before, history_before = copy.deepcopy(engines), copy.deepcopy(history)

    routing.order_engines(engines, history, "fast", min_samples=5)

    assert engines == engines_before
    assert history == history_before


def test_execute_routes_engines_when_enabled_without_mutating_caller_cfg(fake_pipeline):
    cfg = make_cfg(engines=[eng("a"), eng("b")], routing={"enabled": True, "min_samples": 3})
    original_engines = list(cfg["engines"])
    history = [h("b", "MERGED", path="heavy")] * 3
    runner.execute(Job("issue", "5", "Add thing", "please add thing"), cfg, make_rcfg(), history,
                   dry_run=True)
    sent_cfg = fake_pipeline.call_agent.call_args.args[0]

    assert names(sent_cfg["engines"]) == ["b", "a"]
    assert cfg["engines"] == original_engines


def test_execute_skips_routing_when_disabled(fake_pipeline):
    cfg = make_cfg(engines=[eng("a"), eng("b")], routing={"enabled": False, "min_samples": 3})
    history = [h("b", "MERGED", path="heavy")] * 3
    runner.execute(Job("issue", "5", "Add thing", "please add thing"), cfg, make_rcfg(), history,
                   dry_run=True)
    sent_cfg = fake_pipeline.call_agent.call_args.args[0]

    assert names(sent_cfg["engines"]) == ["a", "b"]
