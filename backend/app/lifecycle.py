from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable

from .config import Settings
from .models import PendingReview
from .repository import Repository, Scope

OPPOSITE = {"BUY": "SELL", "SELL": "BUY"}
TERMINAL = ("REJECTED", "STOPPED", "TARGET", "UNDETERMINED")
UNDETERMINED_REASON = "the order of touches could not be determined from the available candles"
REJECTED_REASON = "price reached the stop or the target before the entry"

FineLookup = Callable[[dict], list[dict] | None]


@dataclass(frozen=True)
class Progress:
    state: str
    confirmed_at: datetime | None = None
    ended_at: datetime | None = None
    source: str = "candles"


def touched(candle: dict, levels: dict) -> set[str]:
    return {name for name, level in levels.items() if level is not None and candle["low"] <= level <= candle["high"]}


def classify(state: str, hit: set[str]) -> str:
    if state == "PENDING":
        if "entry" in hit:
            return "confirm" if len(hit) == 1 else "ambiguous"
        return "reject" if hit else "none"
    if hit == {"stop"}:
        return "stop"
    if hit == {"target"}:
        return "target"
    return "ambiguous" if hit else "none"


def apply_event(event: str, progress: Progress, candle: dict) -> Progress:
    at = candle["close_time"]
    states = {"confirm": "CONFIRMED", "reject": "REJECTED", "stop": "STOPPED", "target": "TARGET"}
    if event == "none":
        return progress
    if event == "confirm":
        return replace(progress, state="CONFIRMED", confirmed_at=at)
    return replace(progress, state=states[event], ended_at=at)


def walk(signal: dict, progress: Progress, candles: list[dict], fine_for: FineLookup | None) -> Progress:
    for candle in candles:
        if progress.state in TERMINAL:
            break
        if progress.state == "PENDING":
            levels = {"entry": signal["entry_price"], "stop": signal["stop_loss"], "target": signal["target"]}
        else:
            levels = {"stop": signal["stop_loss"], "target": signal["target"]}
        event = classify(progress.state, touched(candle, levels))
        if event != "ambiguous":
            progress = apply_event(event, progress, candle)
            continue
        fine = fine_for(candle) if fine_for else None
        if not fine:
            return replace(progress, state="UNDETERMINED", ended_at=candle["close_time"])
        progress = walk(signal, progress, fine, None)
        if progress.state != "UNDETERMINED":
            progress = replace(progress, source="fine_candles")
    return progress


def evaluate_outcome(direction: str, entry: float, confirmed_at: datetime, exit_time: datetime, exit_price: float, candles: list[dict]) -> dict:
    buy = direction == "BUY"
    signed_move = (exit_price - entry) if buy else (entry - exit_price)
    path = [c for c in candles if c["open_time"] >= confirmed_at and c["close_time"] <= exit_time]
    favorable = [(c["high"] - entry) if buy else (entry - c["low"]) for c in path]
    adverse = [(entry - c["low"]) if buy else (c["high"] - entry) for c in path]
    return {
        "signed_move": signed_move,
        "mfe": max([0.0, signed_move, *favorable]),
        "mae": max([0.0, -signed_move, *adverse]),
        "duration_seconds": (exit_time - confirmed_at).total_seconds(),
    }


class Lifecycle:
    def __init__(self, repo: Repository, settings: Settings):
        self._repo = repo
        self._settings = settings

    def advance(self, scope: Scope, mode: str, trigger_time: datetime) -> None:
        fine_for = self._fine_lookup(scope)
        for signal in self._repo.active_signals(scope, mode):
            if signal["lifecycle_status"] == "PENDING":
                start, progress = signal["prediction_time"], Progress("PENDING")
            else:
                start = signal["confirmed_at"]
                progress = Progress("CONFIRMED", confirmed_at=start)
            candles = self._repo.candles_between(scope.instrument, scope.smallest_timeframe, start, trigger_time)
            self._record(scope, signal, walk(signal, progress, candles, fine_for))

    def apply_reviews(self, scope: Scope, mode: str, reviews: list[PendingReview], at: datetime) -> list[int]:
        pending = {s["id"] for s in self._repo.active_signals(scope, mode) if s["lifecycle_status"] == "PENDING"}
        rejected = []
        for review in reviews:
            if review.action == "INVALIDATE" and review.signal_id in pending:
                if self._repo.set_rejected(review.signal_id, at, "invalidated by model"):
                    rejected.append(review.signal_id)
        return rejected

    def resolve_opposites(self, scope: Scope, mode: str, new_direction: str, new_signal_id: int, exit_time: datetime, exit_price: float) -> list[int]:
        resolved = []
        for signal in self._repo.confirmed_unresolved(scope, mode, OPPOSITE[new_direction]):
            candles = self._repo.candles_between(scope.instrument, scope.smallest_timeframe, signal["confirmed_at"], exit_time)
            stats = evaluate_outcome(signal["direction"], signal["entry_price"], signal["confirmed_at"], exit_time, exit_price, candles)
            resolved.append(
                self._store_outcome(signal, exit_price, signal["confirmed_at"], exit_time, stats, new_signal_id, "OPPOSITE_SIGNAL", "NO_VERDICT", "candles")
            )
        return resolved

    def _fine_lookup(self, scope: Scope) -> FineLookup | None:
        resolution = self._settings.resolution
        fine_minutes = self._settings.timeframes[resolution.timeframe]
        coarse_minutes = self._settings.timeframes[scope.smallest_timeframe]
        if fine_minutes >= coarse_minutes:
            return None
        expected = coarse_minutes // fine_minutes

        def lookup(candle: dict) -> list[dict] | None:
            rows = self._repo.candles_between(scope.instrument, resolution.timeframe, candle["open_time"], candle["close_time"])
            return rows if len(rows) == expected else None

        return lookup

    def _record(self, scope: Scope, signal: dict, result: Progress) -> None:
        if result.state == "PENDING" or (result.state == "CONFIRMED" and signal["lifecycle_status"] == "CONFIRMED"):
            return
        if result.confirmed_at and signal["lifecycle_status"] == "PENDING" and result.state != "REJECTED":
            self._repo.set_confirmed(signal["id"], result.confirmed_at)
        if result.state == "REJECTED":
            self._repo.set_rejected(signal["id"], result.ended_at, REJECTED_REASON)
        elif result.state == "UNDETERMINED":
            self._repo.set_undetermined(signal["id"], result.ended_at, UNDETERMINED_REASON)
        elif result.state in ("STOPPED", "TARGET"):
            stopped = result.state == "STOPPED"
            exit_price = signal["stop_loss"] if stopped else signal["target"]
            candles = self._repo.candles_between(scope.instrument, scope.smallest_timeframe, result.confirmed_at, result.ended_at)
            stats = evaluate_outcome(signal["direction"], signal["entry_price"], result.confirmed_at, result.ended_at, exit_price, candles)
            self._store_outcome(
                signal, exit_price, result.confirmed_at, result.ended_at, stats, None,
                "STOP" if stopped else "TARGET", "MISTAKE" if stopped else "WIN", result.source,
            )

    def _store_outcome(self, signal, exit_price, confirmed_at, exit_time, stats, exit_signal_id, exit_reason, result, source) -> int:
        return self._repo.insert_outcome(
            {
                "signal_id": signal["id"],
                "exit_signal_id": exit_signal_id,
                "entry_price": signal["entry_price"],
                "exit_price": exit_price,
                "confirmed_at": confirmed_at,
                "exit_time": exit_time,
                "resolved_at": exit_time,
                "evaluator_version": self._settings.inference.evaluator_version,
                "is_mistake": result == "MISTAKE",
                "exit_reason": exit_reason,
                "result": result,
                "touch_source": source,
                **stats,
            }
        )
