from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.ingest import IngestError, validate_pack
from app.models import IngestRequest
from helpers import make_request


def test_valid_pack_returns_timeframes_smallest_first(settings):
    assert validate_pack(make_request(timeframes=("H1", "M5", "M15")), settings) == ["M5", "M15", "H1"]


def pack(req, code):
    return next(p for p in req.timeframes if p.timeframe == code)


def drop_timeframe(req):
    req.timeframes.pop()


def duplicate_timeframe(req):
    req.timeframes[1].timeframe = "M5"


def disallowed_timeframe(req):
    req.timeframes[1].timeframe = "M2"


def missing_candle(req):
    pack(req, "M15").candles.pop()


def missing_indicator(req):
    del pack(req, "H1").indicators["rsi"]


def extra_indicator(req):
    pack(req, "H1").indicators["macd"] = [1.0] * 150


def short_series(req):
    pack(req, "M5").indicators["sma"].pop()


def swapped_candles(req):
    candles = pack(req, "M5").candles
    candles[10], candles[11] = candles[11], candles[10]


def duplicated_candle(req):
    candles = pack(req, "M15").candles
    candles[20] = candles[19].model_copy()


def high_below_close(req):
    candles = pack(req, "M5").candles
    candles[5] = candles[5].model_copy(update={"high": candles[5].close - 1})


def non_positive_low(req):
    candles = pack(req, "M5").candles
    candles[5] = candles[5].model_copy(update={"low": 0})


def wrong_width(req):
    candles = pack(req, "H1").candles
    candles[3] = candles[3].model_copy(update={"close_time": candles[3].close_time + timedelta(minutes=1)})


def forming_higher_candle(req):
    for index, candle in enumerate(pack(req, "H1").candles):
        pack(req, "H1").candles[index] = candle.model_copy(
            update={"open_time": candle.open_time + timedelta(hours=1), "close_time": candle.close_time + timedelta(hours=1)}
        )


def trigger_mismatch(req):
    req.trigger_candle_time += timedelta(minutes=5)
    req.sent_at += timedelta(minutes=5)


def trigger_after_sent(req):
    req.sent_at = req.trigger_candle_time - timedelta(seconds=1)


def unknown_context(req):
    req.context_version = "v9"


def unknown_model(req):
    req.model = "Mystery"


def wrong_instrument(req):
    req.instrument = "EURUSD"


@pytest.mark.parametrize(
    "mutation",
    [
        drop_timeframe, duplicate_timeframe, disallowed_timeframe, missing_candle, missing_indicator, extra_indicator,
        short_series, swapped_candles, duplicated_candle, high_below_close, non_positive_low, wrong_width,
        forming_higher_candle, trigger_mismatch, trigger_after_sent, unknown_context, unknown_model, wrong_instrument,
    ],
)
def test_invalid_packs_are_rejected(settings, mutation):
    req = make_request()
    mutation(req)
    with pytest.raises(IngestError):
        validate_pack(req, settings)


def test_non_finite_values_never_parse():
    data = make_request().model_dump(mode="json")
    data["timeframes"][0]["indicators"]["sma"][3] = float("nan")
    with pytest.raises(ValidationError):
        IngestRequest.model_validate(data)


def test_naive_datetimes_never_parse():
    data = make_request().model_dump(mode="json")
    data["trigger_candle_time"] = "2026-01-05T12:00:00"
    with pytest.raises(ValidationError):
        IngestRequest.model_validate(data)
