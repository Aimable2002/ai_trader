import json

import httpx
import pytest

from app.config import OpenRouterConfig
from app.provider import OpenRouterProvider, ProviderError

CONFIG = OpenRouterConfig(base_url="https://or.test/api/v1", timeout_seconds=5, retries=2, backoff_seconds=1.5)
OK_BODY = {"choices": [{"message": {"content": '{"a": 1}'}}], "usage": {"prompt_tokens": 11, "completion_tokens": 7, "cost": 0.002}}


def build(handler, sleeps=None):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenRouterProvider("secret", CONFIG, client, sleep=(sleeps.append if sleeps is not None else lambda s: None))


def test_success_sends_expected_request_and_parses_usage():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=OK_BODY)

    result = build(handler).complete("vendor/model", [{"role": "user", "content": "hi"}])
    assert seen["url"] == "https://or.test/api/v1/chat/completions"
    assert seen["auth"] == "Bearer secret"
    assert seen["body"] == {"model": "vendor/model", "messages": [{"role": "user", "content": "hi"}]}
    assert (result.text, result.tokens_in, result.tokens_out, result.cost) == ('{"a": 1}', 11, 7, 0.002)


def test_schema_adds_response_format():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=OK_BODY)

    build(handler).complete("m", [], schema={"type": "object"})
    assert seen["body"]["response_format"]["json_schema"]["schema"] == {"type": "object"}


def test_server_error_is_retried_with_backoff():
    responses = [httpx.Response(500), httpx.Response(429), httpx.Response(200, json=OK_BODY)]
    sleeps = []
    result = build(lambda request: responses.pop(0), sleeps).complete("m", [])
    assert result.text == '{"a": 1}'
    assert sleeps == [1.5, 3.0]


def test_gives_up_after_retries():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503)

    with pytest.raises(ProviderError):
        build(handler).complete("m", [])
    assert len(calls) == 3


def test_client_error_is_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(400, text="bad model")

    with pytest.raises(ProviderError) as error:
        build(handler).complete("m", [])
    assert len(calls) == 1 and "bad model" in str(error.value)


def test_transport_error_is_retried():
    attempts = []

    def handler(request):
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.ConnectError("down")
        return httpx.Response(200, json=OK_BODY)

    assert build(handler).complete("m", []).text == '{"a": 1}'


@pytest.mark.parametrize("body", [{"choices": []}, {"nope": 1}, {"choices": [{"message": {"content": "  "}}]}, {"choices": [{"message": {"content": None}}]}])
def test_unusable_responses_raise(body):
    with pytest.raises(ProviderError):
        build(lambda request: httpx.Response(200, json=body)).complete("m", [])


def test_non_json_body_raises():
    with pytest.raises(ProviderError):
        build(lambda request: httpx.Response(200, text="<html>")).complete("m", [])
