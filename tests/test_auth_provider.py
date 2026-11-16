"""auth_provider_for: explicit config wins, otherwise the legacy ``opencode-`` prefix is dropped."""
from __future__ import annotations

from auto_dev_crew.runner import auth_provider_for


def test_explicit_auth_provider_overrides_name():
    eng = {"name": "pollinations-luna", "auth_provider": "Pollinations"}
    assert auth_provider_for(eng) == "pollinations"


def test_legacy_name_still_maps_to_provider():
    assert auth_provider_for({"name": "opencode-pollinations-deepseek"}) == "pollinations-deepseek"


def test_renamed_engine_without_field_would_lose_provider():
    # documents why the field exists: a plain rename changes the derived provider id
    assert auth_provider_for({"name": "nvidia-nemotron"}) == "nvidia-nemotron"
