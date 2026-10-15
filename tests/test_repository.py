import psycopg
import pytest

from app.repository import Scope
from helpers import SCOPE, T0, seed_outcome, seed_signal
from datetime import timedelta


def test_create_run_is_idempotent(repo):
    first = repo.create_run("key", SCOPE, "primary", T0)
    second = repo.create_run("key", SCOPE, "primary", T0)
    assert first[1] is True and second == (first[0], False)


def test_migrate_can_run_twice(repo):
    from helpers import T0 as _  # noqa: F401
    from pathlib import Path

    repo.migrate(Path(__file__).resolve().parents[1] / "backend" / "migrations")
    assert repo._one("select count(*) as n from schema_migrations")["n"] == 1


def test_signals_are_immutable(repo):
    signal = seed_signal(repo)
    with pytest.raises(psycopg.Error):
        repo._run("update signals set rationale = 'changed' where id = %s", (signal,))


def test_calls_today_counts_logged_calls(repo):
    assert repo.calls_today() == 0
    repo.log_call("inference", "Sonnet55", "m", 1, 1, 0.0, True)
    repo.log_call("inference", "Sonnet55", "m", 1, 1, 0.0, False)
    assert repo.calls_today() == 2


def test_active_and_latest_signals(repo):
    pending = seed_signal(repo, direction="BUY", entry=4001.0, at=T0)
    none = seed_signal(repo, direction="NONE", entry=4000.0, at=T0 + timedelta(minutes=5), pending=False)
    assert [s["id"] for s in repo.active_signals(SCOPE, "primary")] == [pending]
    latest = repo.latest_signal(SCOPE, "primary")
    assert latest["id"] == none and latest["lifecycle_status"] == "NONE"
    assert repo.active_signals(SCOPE, "shadow_memory_off") == []


def test_resolved_cases_filters(repo):
    exit_signal = seed_signal(repo, direction="SELL")
    ids = {}
    for name, direction, move, minutes in (("win", "BUY", 5.0, 10), ("loss", "BUY", -3.0, 20), ("sell_win", "SELL", 2.0, 30)):
        ids[name] = seed_signal(repo, direction=direction)
        seed_outcome(repo, ids[name], exit_signal, move, T0 + timedelta(minutes=minutes))
    cases = lambda **kw: [c["id"] for c in repo.resolved_cases(SCOPE, "primary", **kw)]
    assert cases() == [ids["sell_win"], ids["loss"], ids["win"]]
    assert cases(direction="BUY", correct=True) == [ids["win"]]
    assert cases(correct=False) == [ids["loss"]]
    assert cases(since=T0 + timedelta(minutes=15)) == [ids["sell_win"], ids["loss"]]
    assert cases(limit=1) == [ids["sell_win"]]


def test_verify_cases_respects_scope(repo):
    other = Scope("XAUUSD", "M15,H1,H4", "v1", "Sonnet55")
    exit_signal = seed_signal(repo, direction="SELL")
    mine = seed_signal(repo)
    foreign = seed_signal(repo, scope=other)
    seed_outcome(repo, mine, exit_signal, 1.0, T0)
    seed_outcome(repo, foreign, seed_signal(repo, scope=other, direction="SELL"), 1.0, T0)
    assert [c["id"] for c in repo.verify_cases(SCOPE, "primary", [mine, foreign, 9999])] == [mine]
    assert repo.verify_cases(SCOPE, "primary", []) == []
