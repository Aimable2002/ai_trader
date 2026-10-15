from datetime import timedelta

from .config import ContextSpec, Settings
from .models import IngestRequest, TimeframePack


class IngestError(ValueError):
    pass


def ordered_timeframes(codes: list[str], settings: Settings) -> list[str]:
    return sorted(codes, key=lambda code: settings.timeframes[code])


def validate_pack(req: IngestRequest, settings: Settings) -> list[str]:
    if req.instrument != settings.instrument:
        raise IngestError(f"unsupported instrument {req.instrument}")
    spec = settings.context_versions.get(req.context_version)
    if spec is None:
        raise IngestError(f"unknown context version {req.context_version}")
    if settings.model(req.model) is None:
        raise IngestError(f"model {req.model} is not allowed")
    codes = [pack.timeframe for pack in req.timeframes]
    if len(codes) != 3 or len(set(codes)) != 3:
        raise IngestError("exactly 3 distinct timeframes are required")
    unknown = [code for code in codes if code not in settings.timeframes]
    if unknown:
        raise IngestError(f"timeframes not allowed: {unknown}")
    if req.trigger_candle_time > req.sent_at:
        raise IngestError("trigger candle time is after sent_at")
    ordered = ordered_timeframes(codes, settings)
    packs = {pack.timeframe: pack for pack in req.timeframes}
    for code in ordered:
        _validate_timeframe(packs[code], settings.timeframes[code], spec, req)
    if packs[ordered[0]].candles[-1].close_time != req.trigger_candle_time:
        raise IngestError("last candle of the smallest timeframe must close at the trigger time")
    return ordered


def _validate_timeframe(pack: TimeframePack, minutes: int, spec: ContextSpec, req: IngestRequest) -> None:
    name = pack.timeframe
    if len(pack.candles) != spec.candles_per_timeframe:
        raise IngestError(f"{name}: expected {spec.candles_per_timeframe} candles, got {len(pack.candles)}")
    if set(pack.indicators) != set(spec.indicators):
        raise IngestError(f"{name}: indicators must be exactly {sorted(spec.indicators)}")
    for key, series in pack.indicators.items():
        if len(series) != len(pack.candles):
            raise IngestError(f"{name}: indicator {key} length does not match candle count")
    width = timedelta(minutes=minutes)
    previous = None
    for candle in pack.candles:
        if candle.close_time - candle.open_time != width:
            raise IngestError(f"{name}: candle at {candle.open_time.isoformat()} does not span {minutes} minutes")
        if candle.low <= 0 or candle.high < max(candle.open, candle.close, candle.low) or candle.low > min(candle.open, candle.close):
            raise IngestError(f"{name}: invalid OHLC at {candle.open_time.isoformat()}")
        if previous is not None and candle.open_time < previous.close_time:
            raise IngestError(f"{name}: candles must be strictly ordered without overlap or duplicates")
        previous = candle
    last = pack.candles[-1]
    if last.close_time > req.trigger_candle_time or last.close_time > req.sent_at:
        raise IngestError(f"{name}: contains a candle that was not closed at the trigger time")
