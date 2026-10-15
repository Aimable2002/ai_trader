import shutil

import pytest
import yaml
from pydantic import ValidationError

from app.config import Settings, load_secrets, load_settings


def clone_config(tmp_path, root):
    shutil.copytree(root / "config", tmp_path / "config")
    return tmp_path / "config" / "settings.yaml"


def test_default_settings_load(settings):
    assert settings.default_timeframes == ["M5", "M15", "H1"]
    assert settings.model(settings.models.default) is not None
    assert settings.context_versions["v1"].indicators == {"sma": 200, "ema": 50, "atr": 14, "rsi": 14}


def test_unknown_model_lookup_returns_none(settings):
    assert settings.model("Nope") is None


@pytest.mark.parametrize(
    "edit",
    [
        lambda d: d["models"].update(default="Missing"),
        lambda d: d.update(default_timeframes=["M5", "M15"]),
        lambda d: d.update(default_timeframes=["M5", "M5", "H1"]),
        lambda d: d.update(default_timeframes=["M5", "M15", "W1"]),
        lambda d: d["models"]["allowed"].append(dict(d["models"]["allowed"][0])),
    ],
)
def test_inconsistent_config_is_rejected(tmp_path, edit):
    from pathlib import Path

    path = clone_config(tmp_path, Path(__file__).resolve().parents[1])
    data = yaml.safe_load(path.read_text())
    edit(data)
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValidationError):
        load_settings(path)


def test_missing_prompt_is_rejected(tmp_path):
    from pathlib import Path

    path = clone_config(tmp_path, Path(__file__).resolve().parents[1])
    (path.parent / "prompts" / "validation.txt").unlink()
    with pytest.raises(ValidationError):
        load_settings(path)


def test_secrets_require_all_variables():
    with pytest.raises(RuntimeError) as error:
        load_secrets({"DATABASE_URL": "x"})
    assert "OPENROUTER_API_KEY" in str(error.value) and "INGEST_API_KEY" in str(error.value)


def test_secrets_load():
    secrets = load_secrets({"OPENROUTER_API_KEY": "a", "DATABASE_URL": "b", "INGEST_API_KEY": "c"})
    assert (secrets.openrouter_api_key, secrets.database_url, secrets.ingest_api_key) == ("a", "b", "c")
