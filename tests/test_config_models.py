from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def test_nvidia_opencode_models_have_org_prefix():
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    engines = config["engines"]
    for engine in engines:
        if engine.get("enabled") is False:
            continue
        if engine.get("command") != "opencode":
            continue
        model = engine.get("model") or ""
        if not model.startswith("nvidia/"):
            continue
        name = engine.get("name")
        assert model.count("/") >= 2, (
            f"engine {name!r}: model {model!r} must use the opencode catalog id "
            "'<provider>/<nim-org>/<model>' (e.g. nvidia/nvidia/...)"
        )
