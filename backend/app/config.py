import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, model_validator

REQUIRED_PROMPTS = ("inference", "reflection", "evidence_selection", "validation")


class ModelOption(BaseModel):
    key: str
    openrouter_id: str
    label: str
    structured_output: bool = False


class ContextSpec(BaseModel):
    candles_per_timeframe: int
    indicators: dict[str, int]


class ModelsConfig(BaseModel):
    default: str
    allowed: list[ModelOption]


class InferenceConfig(BaseModel):
    prompt_config_version: str
    evaluator_version: str
    max_attempts: int
    max_entry_distance_pct: float
    store_context_pack: bool


class LimitsConfig(BaseModel):
    daily_model_call_cap: int
    kill_switch: bool


class MemoryConfig(BaseModel):
    lessons_per_call: int
    contrast_cases: int
    validation_cadence_new_cases: int
    evidence_cases_cap: int


class OpenRouterConfig(BaseModel):
    base_url: str
    timeout_seconds: float
    retries: int
    backoff_seconds: float


class Settings(BaseModel):
    instrument: str
    timeframes: dict[str, int]
    default_timeframes: list[str]
    context_versions: dict[str, ContextSpec]
    models: ModelsConfig
    inference: InferenceConfig
    limits: LimitsConfig
    memory: MemoryConfig
    shadow_mode: bool
    stale_after_intervals: int
    openrouter: OpenRouterConfig
    prompts: dict[str, str] = {}

    @model_validator(mode="after")
    def _consistent(self):
        keys = [m.key for m in self.models.allowed]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate model keys")
        if self.models.default not in keys:
            raise ValueError("default model is not in the allowed list")
        defaults = self.default_timeframes
        if len(defaults) != 3 or len(set(defaults)) != 3:
            raise ValueError("default_timeframes must hold exactly 3 distinct timeframes")
        if not set(defaults) <= set(self.timeframes):
            raise ValueError("default_timeframes contains an unknown timeframe")
        missing = [name for name in REQUIRED_PROMPTS if name not in self.prompts]
        if missing:
            raise ValueError(f"missing prompts: {missing}")
        return self

    def model(self, key: str) -> ModelOption | None:
        return next((m for m in self.models.allowed if m.key == key), None)


@dataclass(frozen=True)
class Secrets:
    openrouter_api_key: str
    database_url: str
    ingest_api_key: str


def load_settings(path: str | Path) -> Settings:
    path = Path(path)
    data = yaml.safe_load(path.read_text())
    data["prompts"] = {p.stem: p.read_text() for p in (path.parent / "prompts").glob("*.txt")}
    return Settings.model_validate(data)


def load_secrets(env=None) -> Secrets:
    env = os.environ if env is None else env
    names = {
        "openrouter_api_key": "OPENROUTER_API_KEY",
        "database_url": "DATABASE_URL",
        "ingest_api_key": "INGEST_API_KEY",
    }
    missing = [var for var in names.values() if not env.get(var)]
    if missing:
        raise RuntimeError(f"missing environment variables: {', '.join(missing)}")
    return Secrets(**{field: env[var] for field, var in names.items()})
