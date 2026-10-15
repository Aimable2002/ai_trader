from datetime import timedelta

import pytest

from app.lifecycle import evaluate_outcome
from app.models import PendingReview
from helpers import SCOPE, T0, seed_candles, seed_signal

M5 = timedelta(minutes=5)


def status(repo, signal_id):
    return repo._one("select status from confirmations where signal_id = %s", (signal_id,))["status"]


def test_evaluate_buy_outcome():
    candles = [
        {"open_time": T0, "close_time": T0 + M5, "high": 4010.0, "low": 3996.0},
        {"open_time": T0 + M5, "close_time": T0 + 2 * M5, "high": 4004.0, "low": 3990.0},
    ]
    result = evaluate_outcome("BUY", 4000.0, T0, T0 + 2 * M5, 3995.0, candles)
    assert result == {"signed_move": -5.0, "mfe": 10.0, "mae": 10.0, "duration_seconds": 600.0, "is_mistake": True}


def test_evaluate_sell_outcome_wins_when_price_falls():
    candles = [{"open_time": T0, "close_time": T0 + M5, "high": 4002.0, "low": 3980.0}]
    result = evaluate_outcome("SELL", 4000.0, T0, T0 + M5, 3985.0, candles)
    assert result["signed_move"] == 15.0 and result["mfe"] == 20.0 and result["mae"] == 2.0 and not result["is_mistake"]


def test_evaluate_ignores_candles_outside_the_window():
    candles = [
        {"open_time": T0 - M5, "close_time": T0, "high": 5000.0, "low": 1.0},
        {"open_time": T0 + 10 * M5, "close_time": T0 + 11 * M5, "high": 5000.0, "low": 1.0},
    ]
    result = evaluate_outcome("BUY", 4000.0, T0, T0 + 5 * M5, 4001.0, candles)
    assert result["mfe"] == 0.0 and result["mae"] == 0.0


def test_pending_signal_is_confirmed_when_price_touches_entry(repo, lifecycle):
    signal = seed_signal(repo, entry=4001.0)
    seed_candles(repo, SCOPE, [(T0 - M5, 4002.0, 4000.0), (T0, 4000.5, 3999.0), (T0 + M5, 4003.0, 4000.0)])
    assert lifecycle.confirm_pending(SCOPE, "primary", T0 + 2 * M5) == [signal]
    row = repo._one("select * from confirmations where signal_id = %s", (signal,))
    assert row["status"] == "CONFIRMED" and row["confirmed_at"] == T0 + 2 * M5


def test_candles_before_the_signal_never_confirm(repo, lifecycle):
    signal = seed_signal(repo, entry=4001.0)
    seed_candles(repo, SCOPE, [(T0 - M5, 4005.0, 3999.0)])
    assert lifecycle.confirm_pending(SCOPE, "primary", T0 + M5) == []
    assert status(repo, signal) == "PENDING"


def test_candles_after_the_trigger_never_confirm(repo, lifecycle):
    signal = seed_signal(repo, entry=4001.0)
    seed_candles(repo, SCOPE, [(T0 + 3 * M5, 4005.0, 3999.0)])
    assert lifecycle.confirm_pending(SCOPE, "primary", T0 + M5) == []
    assert status(repo, signal) == "PENDING"


def test_untouched_entry_stays_pending(repo, lifecycle):
    signal = seed_signal(repo, entry=4001.0)
    seed_candles(repo, SCOPE, [(T0, 3999.0, 3990.0)])
    assert lifecycle.confirm_pending(SCOPE, "primary", T0 + M5) == []
    assert status(repo, signal) == "PENDING"


def test_model_invalidation_rejects_only_pending_signals(repo, lifecycle):
    pending = seed_signal(repo, entry=4001.0)
    kept = seed_signal(repo, entry=4002.0)
    confirmed = seed_signal(repo, entry=4003.0)
    repo.set_confirmed(confirmed, T0)
    reviews = [PendingReview(signal_id=pending, action="INVALIDATE"), PendingReview(signal_id=kept, action="KEEP"),
               PendingReview(signal_id=confirmed, action="INVALIDATE"), PendingReview(signal_id=99999, action="INVALIDATE")]
    assert lifecycle.apply_reviews(SCOPE, "primary", reviews, T0) == [pending]
    assert (status(repo, pending), status(repo, kept), status(repo, confirmed)) == ("REJECTED", "PENDING", "CONFIRMED")


def test_opposite_signal_resolves_confirmed_trade(repo, lifecycle):
    buy = seed_signal(repo, direction="BUY", entry=4000.0)
    repo.set_confirmed(buy, T0 + M5)
    seed_candles(repo, SCOPE, [(T0 + M5, 4004.0, 3999.0), (T0 + 2 * M5, 4001.0, 3990.0)])
    sell = seed_signal(repo, direction="SELL", entry=3990.0, at=T0 + 3 * M5)
    resolved = lifecycle.resolve_opposites(SCOPE, "primary", "SELL", sell, T0 + 3 * M5, 3995.0)
    assert len(resolved) == 1
    row = repo._one("select * from outcomes")
    assert (row["signal_id"], row["exit_signal_id"], row["signed_move"], row["is_mistake"]) == (buy, sell, -5.0, True)
    assert row["mfe"] == 4.0 and row["mae"] == 10.0 and row["duration_seconds"] == 600.0


def test_same_direction_and_pending_signals_are_not_resolved(repo, lifecycle):
    confirmed_buy = seed_signal(repo, direction="BUY", entry=4000.0)
    repo.set_confirmed(confirmed_buy, T0)
    seed_signal(repo, direction="SELL", entry=3990.0)
    new_buy = seed_signal(repo, direction="BUY", entry=4002.0, at=T0 + M5)
    assert lifecycle.resolve_opposites(SCOPE, "primary", "BUY", new_buy, T0 + M5, 4001.0) == []
    pending_sell = seed_signal(repo, direction="SELL", entry=3999.0)
    assert lifecycle.resolve_opposites(SCOPE, "primary", "BUY", new_buy, T0 + M5, 4001.0) == []
    assert status(repo, pending_sell) == "PENDING"


def test_overlapping_confirmed_trades_share_one_exit(repo, lifecycle):
    first = seed_signal(repo, direction="BUY", entry=4000.0)
    second = seed_signal(repo, direction="BUY", entry=4002.0, at=T0 + M5)
    repo.set_confirmed(first, T0 + M5)
    repo.set_confirmed(second, T0 + 2 * M5)
    sell = seed_signal(repo, direction="SELL", entry=3990.0, at=T0 + 4 * M5)
    assert len(lifecycle.resolve_opposites(SCOPE, "primary", "SELL", sell, T0 + 4 * M5, 3998.0)) == 2
    exits = {r["exit_signal_id"] for r in repo._all("select exit_signal_id from outcomes")}
    assert exits == {sell}
    assert lifecycle.resolve_opposites(SCOPE, "primary", "SELL", sell, T0 + 4 * M5, 3998.0) == []


def test_other_scopes_and_modes_are_untouched(repo, lifecycle):
    from app.repository import Scope

    other = Scope("XAUUSD", "M15,H1,H4", "v1", "Sonnet55")
    foreign = seed_signal(repo, scope=other, direction="BUY", entry=4000.0)
    shadow = seed_signal(repo, direction="BUY", entry=4000.0, mode="shadow_memory_off")
    repo.set_confirmed(foreign, T0)
    repo.set_confirmed(shadow, T0)
    sell = seed_signal(repo, direction="SELL", entry=3990.0, at=T0 + M5)
    assert lifecycle.resolve_opposites(SCOPE, "primary", "SELL", sell, T0 + M5, 3995.0) == []
