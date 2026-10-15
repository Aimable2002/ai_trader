import time
from dataclasses import dataclass
from typing import Callable

import httpx

from .config import OpenRouterConfig


class ProviderError(Exception):
    pass


@dataclass(frozen=True)
class ProviderResult:
    text: str
    tokens_in: int | None
    tokens_out: int | None
    cost: float | None


class OpenRouterProvider:
    def __init__(
        self,
        api_key: str,
        config: OpenRouterConfig,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._api_key = api_key
        self._config = config
        self._client = client or httpx.Client()
        self._sleep = sleep

    def complete(self, model_id: str, messages: list[dict], schema: dict | None = None) -> ProviderResult:
        payload: dict = {"model": model_id, "messages": messages}
        if schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "output", "strict": False, "schema": schema},
            }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        url = f"{self._config.base_url}/chat/completions"
        failure = "no attempt made"
        for attempt in range(self._config.retries + 1):
            try:
                response = self._client.post(url, json=payload, headers=headers, timeout=self._config.timeout_seconds)
            except httpx.TransportError as exc:
                failure = f"transport error: {exc}"
            else:
                if response.status_code == 429 or response.status_code >= 500:
                    failure = f"provider returned {response.status_code}"
                elif response.status_code >= 400:
                    raise ProviderError(f"provider returned {response.status_code}: {response.text[:300]}")
                else:
                    return self._parse(response)
            if attempt < self._config.retries:
                self._sleep(self._config.backoff_seconds * (attempt + 1))
        raise ProviderError(f"giving up after {self._config.retries + 1} attempts: {failure}")

    @staticmethod
    def _parse(response: httpx.Response) -> ProviderResult:
        try:
            data = response.json()
            text = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"unexpected provider response: {exc}") from exc
        if not isinstance(text, str) or not text.strip():
            raise ProviderError("provider returned empty content")
        usage = data.get("usage") or {}
        return ProviderResult(text, usage.get("prompt_tokens"), usage.get("completion_tokens"), usage.get("cost"))
