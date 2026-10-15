import pytest

from app.llm import BudgetExceeded, OutputError, StructuredLLM, extract_json
from app.models import ModelOutput
from app.provider import ProviderError
from helpers import buy_output, none_output


def test_extract_json_variants():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure, here it is: {"a": 1} hope it helps') == {"a": 1}
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_valid_output_is_parsed_and_call_logged(llm, provider, repo):
    provider.push(buy_output())
    output = llm.ask("inference", "Sonnet55", [], ModelOutput)
    assert output.setup_direction == "BUY"
    assert repo.calls_today() == 1
    assert provider.calls[0]["model_id"] == "anthropic/claude-sonnet-5.5"
    assert provider.calls[0]["schema"] is None


def test_structured_output_models_receive_a_schema(llm, provider):
    provider.push(none_output())
    llm.ask("inference", "DeepseekV41Flash", [], ModelOutput)
    assert provider.calls[0]["schema"]["title"] == "ModelOutput"


def test_invalid_output_is_retried_once(llm, provider, repo):
    provider.push("not json")
    provider.push(none_output())
    assert llm.ask("inference", "Sonnet55", [], ModelOutput).setup_direction == "NONE"
    assert len(provider.calls) == 2 and repo.calls_today() == 2


def test_output_failing_validation_is_retried_then_rejected(llm, provider):
    bad = {"setup_direction": "BUY", "rationale": "missing levels"}
    provider.push(bad)
    provider.push(bad)
    with pytest.raises(OutputError):
        llm.ask("inference", "Sonnet55", [], ModelOutput)


def test_provider_failure_is_logged_and_reraised(llm, provider, repo):
    provider.push(ProviderError("boom"))
    with pytest.raises(ProviderError):
        llm.ask("inference", "Sonnet55", [], ModelOutput)
    row = repo._one("select ok from model_calls")
    assert row["ok"] is False


def test_daily_cap_blocks_calls(provider, repo, settings):
    settings.limits.daily_model_call_cap = 1
    llm = StructuredLLM(provider, repo, settings)
    provider.push(none_output())
    llm.ask("inference", "Sonnet55", [], ModelOutput)
    with pytest.raises(BudgetExceeded):
        llm.ask("inference", "Sonnet55", [], ModelOutput)
    assert len(provider.calls) == 1


def test_kill_switch_blocks_calls(provider, repo, settings):
    settings.limits.kill_switch = True
    with pytest.raises(BudgetExceeded):
        StructuredLLM(provider, repo, settings).ask("inference", "Sonnet55", [], ModelOutput)
    assert provider.calls == []


def test_unknown_model_is_refused(llm):
    with pytest.raises(OutputError):
        llm.ask("inference", "Mystery", [], ModelOutput)
