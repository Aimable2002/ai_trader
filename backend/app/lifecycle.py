from datetime import datetime

from .config import Settings
from .models import PendingReview
from .repository import Repository, Scope

OPPOSITE = {"BUY": "SELL", "SELL": "BUY"}


def evaluate_outcome(direction: str, entry: float, confirmed_at: datetime, exit_time: datetime, exit_price: float, candles: list[dict]) -> dict:
    buy = direction == "BUY"
    signed_move = (exit_price - entry) if buy else (entry - exit_price)
    path = [c for c in candles if c["open_time"] >= confirmed_at and c["close_time"] <= exit_time]
    favorable = [(c["high"] - entry) if buy else (entry - c["low"]) for c in path]
    adverse = [(entry - c["low"]) if buy else (c["high"] - entry) for c in path]
    return {
        "signed_move": signed_move,
        "mfe": max([0.0, *favorable]),
        "mae": max([0.0, *adverse]),
        "duration_seconds": (exit_time - confirmed_at).total_seconds(),
        "is_mistake": signed_move < 0,
    }


class Lifecycle:
    def __init__(self, repo: Repository, settings: Settings):
        self._repo = repo
        self._settings = settings

    def confirm_pending(self, scope: Scope, mode: str, trigger_time: datetime) -> list[int]:
        confirmed = []
        for signal in self._repo.active_signals(scope, mode):
            if signal["lifecycle_status"] != "PENDING":
                continue
            candles = self._repo.candles_between(scope.instrument, scope.smallest_timeframe, signal["prediction_time"], trigger_time)
            touch = next((c for c in candles if c["low"] <= signal["entry_price"] <= c["high"]), None)
            if touch and self._repo.set_confirmed(signal["id"], touch["close_time"]):
                confirmed.append(signal["id"])
        return confirmed

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
            result = evaluate_outcome(signal["direction"], signal["entry_price"], signal["confirmed_at"], exit_time, exit_price, candles)
            resolved.append(
                self._repo.insert_outcome(
                    {
                        "signal_id": signal["id"],
                        "exit_signal_id": new_signal_id,
                        "entry_price": signal["entry_price"],
                        "exit_price": exit_price,
                        "confirmed_at": signal["confirmed_at"],
                        "exit_time": exit_time,
                        "resolved_at": exit_time,
                        "evaluator_version": self._settings.inference.evaluator_version,
                        **result,
                    }
                )
            )
        return resolved
