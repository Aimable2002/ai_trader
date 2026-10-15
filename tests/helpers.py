import math
from datetime import datetime, timedelta, timezone

from app.models import Candle, IngestRequest, TimeframePack

T0 = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
MINUTES = {"M5": 5, "M15": 15, "H1": 60, "H4": 240}
INDICATORS = ("sma", "ema", "atr", "rsi")


def floor_to(moment: datetime, minutes: int) -> datetime:
    total = int(moment.timestamp()) // 60 // minutes * minutes
    return datetime.fromtimestamp(total * 60, timezone.utc)


def make_candles(end: datetime, minutes: int, count: int = 150) -> list[Candle]:
    candles = []
    for index in range(count):
        close_time = end - timedelta(minutes=minutes * (count - 1 - index))
        base = 4000 + 5 * math.sin(index / 7)
        candles.append(
            Candle(
                open_time=close_time - timedelta(minutes=minutes),
                close_time=close_time,
                open=base,
                high=base + 1,
                low=base - 1,
                close=base + 0.3,
            )
        )
    return candles


def make_request(
    trigger: datetime = T0,
    model: str = "Sonnet55",
    timeframes: tuple = ("M5", "M15", "H1"),
    context_version: str = "v1",
    last_candle: tuple | None = None,
    count: int = 150,
) -> IngestRequest:
    packs = []
    smallest = min(timeframes, key=MINUTES.get)
    for code in timeframes:
        minutes = MINUTES[code]
        candles = make_candles(floor_to(trigger, minutes), minutes, count)
        if code == smallest and last_candle is not None:
            o, h, l, c = last_candle
            candles[-1] = candles[-1].model_copy(update={"open": o, "high": h, "low": l, "close": c})
        indicators = {name: [4000.0 + index * 0.01 for index in range(count)] for name in INDICATORS}
        packs.append(TimeframePack(timeframe=code, candles=candles, indicators=indicators))
    return IngestRequest(
        instrument="XAUUSD",
        trigger_candle_time=trigger,
        cbot_version="1.0.0",
        sent_at=trigger + timedelta(seconds=5),
        context_version=context_version,
        model=model,
        timeframes=packs,
    )


def buy_output(entry: float = 4001.0, low: float = 3995.0, high: float = 4000.0, reviews: list | None = None) -> dict:
    return {
        "setup_direction": "BUY",
        "setup_zone_low": low,
        "setup_zone_high": high,
        "confirmation_entry_price": entry,
        "pending_reviews": reviews or [],
        "rationale": "support retest",
        "confidence": 0.7,
    }


def sell_output(entry: float = 3990.0, low: float = 4000.0, high: float = 4005.0, reviews: list | None = None) -> dict:
    return {
        "setup_direction": "SELL",
        "setup_zone_low": low,
        "setup_zone_high": high,
        "confirmation_entry_price": entry,
        "pending_reviews": reviews or [],
        "rationale": "resistance rejection",
        "confidence": 0.6,
    }


def none_output(reviews: list | None = None) -> dict:
    return {"setup_direction": "NONE", "pending_reviews": reviews or [], "rationale": "no setup"}


from app.models import Candle as _Candle
from app.repository import Scope

SCOPE = Scope("XAUUSD", "M5,M15,H1", "v1", "Sonnet55")


def seed_signal(repo, scope=SCOPE, direction="BUY", entry=4001.0, at=T0, mode="primary", pending=True):
    key = f"{scope}-{direction}-{entry}-{at.isoformat()}-{mode}-{id(object())}"
    run_id, _ = repo.create_run(key, scope, mode, at)
    return repo.insert_signal(
        {
            "run_id": run_id,
            "instrument": scope.instrument,
            "timeframe_set": scope.timeframe_set,
            "context_version": scope.context_version,
            "model_key": scope.model_key,
            "openrouter_id": "vendor/model",
            "mode": mode,
            "prediction_time": at,
            "direction": direction,
            "zone_low": entry - 5,
            "zone_high": entry - 1,
            "entry_price": entry,
            "rationale": "seeded",
            "confidence": 0.5,
            "pending_reviews": [],
            "lesson_ids": [],
            "prompt_config_version": "p1",
            "source_candle_times": {},
            "context_pack": None,
        },
        pending=pending,
    )


def seed_candles(repo, scope, specs):
    candles = [
        _Candle(open_time=start, close_time=start + timedelta(minutes=5), open=(h + l) / 2, high=h, low=l, close=(h + l) / 2)
        for start, h, l in specs
    ]
    repo.upsert_candles(scope.instrument, scope.smallest_timeframe, candles)


def seed_outcome(repo, signal_id, exit_signal_id, signed_move, resolved_at, entry=4000.0):
    return repo.insert_outcome(
        {
            "signal_id": signal_id,
            "exit_signal_id": exit_signal_id,
            "entry_price": entry,
            "exit_price": entry + signed_move,
            "confirmed_at": resolved_at - timedelta(minutes=30),
            "exit_time": resolved_at,
            "resolved_at": resolved_at,
            "signed_move": signed_move,
            "mfe": max(signed_move, 0.0),
            "mae": max(-signed_move, 0.0),
            "duration_seconds": 1800.0,
            "is_mistake": signed_move < 0,
            "evaluator_version": "e1",
        }
    )


def seed_lesson(repo, scope=SCOPE, status="CANDIDATE", confidence=0.5, created_at=T0, validated_at=None, text="avoid chasing", origin=None, cited=()):
    origin = origin or seed_signal(repo, scope, direction="NONE", at=created_at, pending=False)
    lesson_id = repo.insert_lesson(
        {
            "instrument": scope.instrument,
            "timeframe_set": scope.timeframe_set,
            "context_version": scope.context_version,
            "model_key": scope.model_key,
            "status": status,
            "origin_signal_id": origin,
            "observed_fact": "fact",
            "hypothesis": "hypothesis",
            "candidate_lesson": text,
            "conditions": "after a spike",
            "cited_signal_ids": list(cited),
            "model_confidence": confidence,
            "created_at": created_at,
        }
    )
    if validated_at is not None:
        repo.apply_verdict(lesson_id, status, validated_at, validated_at)
    return lesson_id
