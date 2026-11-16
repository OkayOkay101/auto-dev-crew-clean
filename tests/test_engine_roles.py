"""Engine-level `roles` narrows which key roles an engine uses (judge-only DeepSeek, coder Luna)."""
from auto_dev_crew import runner

ENV = {"POLLINATIONS_API_KEY_1": "sk-test-value"}
KEY_ROLES = ["coder", "judge", "scan"]


def _eng(name, roles=None):
    eng = {"name": name, "command": "opencode", "model": "m", "api_keys": ["${POLLINATIONS_API_KEY_1}"]}
    if roles is not None:
        eng["roles"] = roles
    return eng


def _use_key_roles(monkeypatch):
    monkeypatch.setattr(runner, "get_key_effective_roles", lambda name: list(KEY_ROLES))


def test_engine_without_roles_keeps_key_roles(monkeypatch):
    _use_key_roles(monkeypatch)
    eng = _eng("opencode-plain")
    for role in ("coder", "judge", "scan"):
        assert len(runner.get_engine_key_entries(eng, env_vars=ENV, role=role, allow_fallback=False)) == 1


def test_judge_only_engine_is_not_a_coder(monkeypatch):
    _use_key_roles(monkeypatch)
    eng = _eng("opencode-pollinations-deepseek", roles=["judge"])
    assert len(runner.get_engine_key_entries(eng, env_vars=ENV, role="judge", allow_fallback=False)) == 1
    assert runner.get_engine_key_entries(eng, env_vars=ENV, role="coder", allow_fallback=False) == []
    assert runner.get_engine_key_entries(eng, env_vars=ENV, role="scan", allow_fallback=False) == []


def test_coder_scan_engine_is_not_a_judge(monkeypatch):
    _use_key_roles(monkeypatch)
    eng = _eng("opencode-pollinations", roles=["coder", "scan"])
    assert len(runner.get_engine_key_entries(eng, env_vars=ENV, role="coder", allow_fallback=False)) == 1
    assert len(runner.get_engine_key_entries(eng, env_vars=ENV, role="scan", allow_fallback=False)) == 1
    assert runner.get_engine_key_entries(eng, env_vars=ENV, role="judge", allow_fallback=False) == []


def test_judge_only_engine_cannot_fall_back_to_coder(monkeypatch):
    # a judge-only engine has no coder role, so the coder fallback must not pick it up
    _use_key_roles(monkeypatch)
    eng = _eng("opencode-pollinations-deepseek", roles=["judge"])
    assert runner.get_engine_key_entries(eng, env_vars=ENV, role="scan", allow_fallback=True) == []
