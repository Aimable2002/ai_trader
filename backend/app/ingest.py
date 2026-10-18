from datetime import datetime, timedelta

from .config import ContextSpec, Settings
from .models import Candle, FineCandles, IngestRequest, TimeframePack


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
    smallest_minutes = settings.timeframes[ordered[0]]
    if smallest_minutes > settings.timeframes[settings.resolution.max_smallest_timeframe]:
        raise IngestError(f"the smallest timeframe may not exceed {settings.resolution.max_smallest_timeframe}")
    packs = {pack.timeframe: pack for pack in req.timeframes}
    for code in ordered:
        _validate_timeframe(packs[code], settings.timeframes[code], spec, req)
    if packs[ordered[0]].candles[-1].close_time != req.trigger_candle_time:
        raise IngestError("last candle of the smallest timeframe must close at the trigger time")
    if req.fine_candles is not None:
        _validate_fine(req.fine_candles, smallest_minutes, req, settings)
    return ordered


def _validate_timeframe(pack: TimeframePack, minutes: int, spec: ContextSpec, req: IngestRequest) -> None:
    if len(pack.candles) != spec.candles_per_timeframe:
        raise IngestError(f"{pack.timeframe}: expected {spec.candles_per_timeframe} candles, got {len(pack.candles)}")
    if set(pack.indicators) != set(spec.indicators):
        raise IngestError(f"{pack.timeframe}: indicators must be exactly {sorted(spec.indicators)}")
    for key, series in pack.indicators.items():
        if len(series) != len(pack.candles):
            raise IngestError(f"{pack.timeframe}: indicator {key} length does not match candle count")
    _check_sequence(pack.timeframe, pack.candles, minutes, req.trigger_candle_time, req.sent_at)


def _validate_fine(fine: FineCandles, smallest_minutes: int, req: IngestRequest, settings: Settings) -> None:
    resolution = settings.resolution
    if fine.timeframe != resolution.timeframe:
        raise IngestError(f"fine candles must use the {resolution.timeframe} timeframe")
    fine_minutes = settings.timeframes[resolution.timeframe]
    if fine_minutes >= smallest_minutes:
        raise IngestError("fine candles must be finer than the smallest timeframe")
    if len(fine.candles) > resolution.window_candles * smallest_minutes // fine_minutes:
        raise IngestError("too many fine candles")
    if fine.candles:
        _check_sequence(fine.timeframe, fine.candles, fine_minutes, req.trigger_candle_time, req.sent_at)


def _check_sequence(name: str, candles: list[Candle], minutes: int, trigger: datetime, sent_at: datetime) -> None:
    width = timedelta(minutes=minutes)
    previous = None
    for candle in candles:
        if candle.close_time - candle.open_time != width:
            raise IngestError(f"{name}: candle at {candle.open_time.isoformat()} does not span {minutes} minutes")
        if candle.low <= 0 or candle.high < max(candle.open, candle.close, candle.low) or candle.low > min(candle.open, candle.close):
            raise IngestError(f"{name}: invalid OHLC at {candle.open_time.isoformat()}")
        if previous is not None and candle.open_time < previous.close_time:
            raise IngestError(f"{name}: candles must be strictly ordered without overlap or duplicates")
        previous = candle
    if candles and (candles[-1].close_time > trigger or candles[-1].close_time > sent_at):
        raise IngestError(f"{name}: contains a candle that was not closed at the trigger time")
