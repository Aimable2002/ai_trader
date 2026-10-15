import pytest
from pydantic import ValidationError

from app.models import ModelOutput, ReflectionOutput, ValidationVerdict
from helpers import buy_output


def test_buy_requires_all_levels():
    for field in ("setup_zone_low", "setup_zone_high", "confirmation_entry_price"):
        data = buy_output()
        data[field] = None
        with pytest.raises(ValidationError):
            ModelOutput.model_validate(data)


def test_zone_must_be_ordered_and_positive():
    with pytest.raises(ValidationError):
        ModelOutput.model_validate(buy_output(low=4005, high=4000))
    with pytest.raises(ValidationError):
        ModelOutput.model_validate(buy_output(entry=-1))


def test_none_discards_levels():
    output = ModelOutput.model_validate({"setup_direction": "NONE", "setup_zone_low": 1, "confirmation_entry_price": 2})
    assert output.setup_zone_low is None and output.confirmation_entry_price is None


def test_stop_loss_and_take_profit_are_not_part_of_the_contract():
    output = ModelOutput.model_validate({**buy_output(), "stop_loss": 3900, "take_profit": 4100})
    assert not hasattr(output, "stop_loss") and not hasattr(output, "take_profit")


def test_confidence_must_be_a_unit_number():
    with pytest.raises(ValidationError):
        ModelOutput.model_validate({**buy_output(), "confidence": 1.5})


def test_reflection_needs_a_lesson_unless_abstaining():
    assert ReflectionOutput.model_validate({"abstain": True}).abstain
    with pytest.raises(ValidationError):
        ReflectionOutput.model_validate({"abstain": False, "candidate_lesson": "  "})


def test_verdict_values_are_closed():
    with pytest.raises(ValidationError):
        ValidationVerdict.model_validate({"verdict": "MAYBE", "model_confidence": 0.5})
