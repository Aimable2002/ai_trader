from datetime import timedelta

from app.context import build_inference_messages, format_timeframe
from helpers import T0, make_request

KEYS = ["atr", "ema", "rsi", "sma"]


def build(settings, active=None, lessons=None, req=None):
    req = req or make_request()
    return req, build_inference_messages(settings, req, ["M5", "M15", "H1"], active or [], lessons or [])


def test_system_prompt_comes_from_config(settings):
    _, messages = build(settings)
    assert messages[0] == {"role": "system", "content": settings.prompts["inference"]}


def test_timeframes_are_presented_top_down_with_roles(settings):
    _, messages = build(settings)
    user = messages[1]["content"]
    assert user.index("## H1") < user.index("## M15") < user.index("## M5")
    assert "role: bias and key levels" in user and "role: setup" in user and "role: entry" in user


def test_every_candle_row_is_present_and_nothing_after_the_trigger(settings):
    req, messages = build(settings)
    user = messages[1]["content"]
    m5 = next(p for p in req.timeframes if p.timeframe == "M5")
    table = format_timeframe(m5, KEYS)
    assert len(table.splitlines()) == 151
    last_open = (T0 - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M")
    assert last_open in user
    assert (T0 + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M") not in user


def test_header_lists_indicator_columns(settings):
    _, messages = build(settings)
    assert "time,open,high,low,close,atr,ema,rsi,sma" in messages[1]["content"]


def test_empty_active_signals_and_lessons_read_none(settings):
    _, messages = build(settings)
    user = messages[1]["content"]
    assert "Active signals:\nnone" in user and "Validated lessons for these conditions:\nnone" in user


def test_active_signals_and_lessons_are_listed(settings):
    active = [{"id": 7, "direction": "BUY", "lifecycle_status": "PENDING", "zone_low": 3995.0, "zone_high": 4000.0, "entry_price": 4001.0, "prediction_time": T0}]
    lessons = [{"id": 3, "candidate_lesson": "avoid chasing", "conditions": "after a spike"}]
    _, messages = build(settings, active, lessons)
    user = messages[1]["content"]
    assert "id=7 BUY status=PENDING zone=3995-4000 entry=4001" in user
    assert "id=3: avoid chasing (applies when: after a spike)" in user
