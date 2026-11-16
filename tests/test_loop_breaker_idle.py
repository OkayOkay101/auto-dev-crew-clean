"""F-4: idle-output watchdog for run_opencode_stream."""
import sys
import time

from auto_dev_crew.loop_breaker import run_opencode_stream


def _run(script: str, tmp_path, **kw):
    return run_opencode_stream(
        base_cmd=[sys.executable, "-c", script],
        prompt="hi",
        cwd=tmp_path,
        env=None,
        **kw,
    )


def test_idle_watchdog_kills_silent_process(tmp_path):
    script = "import time\nprint('start', flush=True)\ntime.sleep(30)"
    t0 = time.time()
    res = _run(script, tmp_path, timeout=60, idle_timeout=1.0)
    assert res["status"] == "ERROR"
    assert "no output for 1s" in res["response"]
    assert "timed out" in res["response"]
    assert time.time() - t0 < 15


def test_idle_watchdog_disabled_when_zero(tmp_path):
    script = (
        "import time\nprint('start', flush=True)\ntime.sleep(2)\n"
        "print('{\"type\":\"text\",\"part\":{\"text\":\"ok\"}}', flush=True)"
    )
    res = _run(script, tmp_path, timeout=30, idle_timeout=0)
    assert "no output for" not in res["response"]


def test_idle_resets_on_each_line(tmp_path):
    script = (
        "import time\nfor i in range(6):\n    print('tick', i, flush=True)\n"
        "    time.sleep(0.5)"
    )
    res = _run(script, tmp_path, timeout=30, idle_timeout=1.5)
    assert "no output for" not in res["response"]
