import json
from typing import TypeVar

from pydantic import BaseModel

from .config import Settings
from .provider import OpenRouterProvider, ProviderError

T = TypeVar("T", bound=BaseModel)


class BudgetExceeded(Exception):
    pass


class OutputError(Exception):
    pass


def extract_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        cleaned = cleaned.rsplit("```", 1)[0]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(cleaned[start : end + 1])


class StructuredLLM:
    def __init__(self, provider: OpenRouterProvider, repo, settings: Settings):
        self._provider = provider
        self._repo = repo
        self._settings = settings

    def ask(self, purpose: str, model_key: str, messages: list[dict], output_cls: type[T]) -> T:
        option = self._settings.model(model_key)
        if option is None:
            raise OutputError(f"model {model_key} is not allowed")
        schema = output_cls.model_json_schema() if option.structured_output else None
        last_error: Exception | None = None
        for _ in range(self._settings.inference.max_attempts):
            self._guard()
            try:
                result = self._provider.complete(option.openrouter_id, messages, schema)
            except ProviderError:
                self._repo.log_call(purpose, model_key, option.openrouter_id, None, None, None, False)
                raise
            self._repo.log_call(purpose, model_key, option.openrouter_id, result.tokens_in, result.tokens_out, result.cost, True)
            try:
                return output_cls.model_validate(extract_json(result.text))
            except ValueError as exc:
                last_error = exc
        raise OutputError(f"{purpose}: model output rejected after {self._settings.inference.max_attempts} attempts: {last_error}")

    def _guard(self) -> None:
        limits = self._settings.limits
        if limits.kill_switch:
            raise BudgetExceeded("kill switch is active")
        if self._repo.calls_today() >= limits.daily_model_call_cap:
            raise BudgetExceeded("daily model call cap reached")
