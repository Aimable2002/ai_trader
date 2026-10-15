import json
from datetime import timedelta

import pytest

from app.memory import count_results, flag_shared_exits, next_status
from app.repository import Scope
from helpers import SCOPE, T0, seed_lesson, seed_outcome, seed_signal

MIN = timedelta(minutes=1)


def case(repo, exit_signal, move, minutes, direction="BUY"):
    signal = seed_signal(repo, direction=direction)
    seed_outcome(repo, signal, exit_signal, move, T0 + minutes * MIN)
    return signal


def reflection(lesson="avoid chasing", cited=(), abstain=False, confidence=0.6):
    return {"abstain": abstain, "observed_fact": "price reversed", "hypothesis": "late entry", "candidate_lesson": lesson,
            "conditions": "after a spike", "cited_signal_ids": list(cited), "model_confidence": confidence, "uncertainty": "thin"}


def last_payload(provider, index=-1):
    return json.loads(provider.calls[index]["messages"][1]["content"])


@pytest.mark.parametrize(
    "current,verdict,relevant,expected",
    [
        ("CANDIDATE", "PROMOTE", 2, "VALIDATED"),
        ("CANDIDATE", "PROMOTE", 0, "CANDIDATE"),
        ("VALIDATED", "PROMOTE", 0, "VALIDATED"),
        ("CANDIDATE", "KEEP_CANDIDATE", 3, "CANDIDATE"),
        ("VALIDATED", "KEEP_CANDIDATE", 3, "VALIDATED"),
        ("CANDIDATE", "REJECT", 3, "REJECTED"),
        ("CANDIDATE", "RETIRE", 3, "REJECTED"),
        ("VALIDATED", "REJECT", 3, "RETIRED"),
        ("VALIDATED", "RETIRE", 3, "RETIRED"),
    ],
)
def test_status_transitions(current, verdict, relevant, expected):
    assert next_status(current, verdict, relevant) == expected


def test_counts_and_shared_exit_flags():
    cases = [{"id": 1, "signed_move": 2.0, "exit_signal_id": 9}, {"id": 2, "signed_move": -1.0, "exit_signal_id": 9},
             {"id": 3, "signed_move": 0.0, "exit_signal_id": 8}]
    assert count_results(cases) == (1, 1)
    flagged = {c["id"]: c["shares_exit_with"] for c in flag_shared_exits(cases)}
    assert flagged == {1: [2], 2: [1], 3: []}


def test_reflection_creates_candidate_with_only_verified_citations(repo, memory, provider):
    exit_signal = seed_signal(repo, direction="SELL")
    mistake = case(repo, exit_signal, -3.0, 10)
    contrast = case(repo, exit_signal, 4.0, 20)
    provider.push(reflection(cited=[mistake, contrast, 9999]))
    created = memory.reflect_mistakes(SCOPE, T0 + 60 * MIN)
    lesson = repo.get_lesson(created[0])
    assert lesson["status"] == "CANDIDATE" and lesson["origin_signal_id"] == mistake
    assert sorted(lesson["cited_signal_ids"]) == sorted([mistake, contrast])
    assert lesson["created_at"] == T0 + 60 * MIN and lesson["model_confidence"] == 0.6
    payload = last_payload(provider)
    assert [c["id"] for c in payload["correct_cases"]] == [contrast]
    assert payload["mistake"]["signal_id"] == mistake


def test_a_mistake_is_reflected_only_once(repo, memory, provider):
    case(repo, seed_signal(repo, direction="SELL"), -3.0, 10)
    provider.push(reflection())
    assert len(memory.reflect_mistakes(SCOPE, T0)) == 1
    assert memory.reflect_mistakes(SCOPE, T0) == [] and len(provider.calls) == 1


def test_abstaining_marks_reflected_without_a_lesson(repo, memory, provider):
    case(repo, seed_signal(repo, direction="SELL"), -3.0, 10)
    provider.push({"abstain": True})
    assert memory.reflect_mistakes(SCOPE, T0) == []
    assert repo.unreflected_mistakes(SCOPE, "primary") == []
    assert repo._one("select count(*) as n from lessons")["n"] == 0


def test_wins_are_never_reflected(repo, memory, provider):
    case(repo, seed_signal(repo, direction="SELL"), 5.0, 10)
    assert memory.reflect_mistakes(SCOPE, T0) == [] and provider.calls == []


def test_failed_reflection_keeps_the_mistake_for_a_retry(repo, memory, provider):
    case(repo, seed_signal(repo, direction="SELL"), -3.0, 10)
    with pytest.raises(AssertionError):
        memory.reflect_mistakes(SCOPE, T0)
    assert len(repo.unreflected_mistakes(SCOPE, "primary")) == 1


def judged_lesson(repo, exit_signal, moves=(2.0, -1.0, 3.0), status="CANDIDATE", validated_at=None):
    lesson = seed_lesson(repo, status=status, created_at=T0, validated_at=validated_at)
    cases = [case(repo, exit_signal, move, 10 * (i + 1)) for i, move in enumerate(moves)]
    return lesson, cases


def test_promotion_uses_system_verified_counts(repo, memory, provider):
    exit_signal = seed_signal(repo, direction="SELL")
    lesson, (c1, c2, c3) = judged_lesson(repo, exit_signal)
    at = T0 + 60 * MIN
    provider.push({"relevant_signal_ids": [c1, c2, 777]})
    provider.push({"verdict": "PROMOTE", "model_confidence": 0.8, "reasoning": "held"})
    assert memory.validate_due(SCOPE, at) == [lesson]
    row = repo.get_lesson(lesson)
    assert row["status"] == "VALIDATED" and row["validated_at"] == at and row["last_judged_at"] == at
    verdict = repo.verdicts_for(lesson)[0]
    assert (verdict["verified_right"], verdict["verified_wrong"]) == (1, 1)
    assert sorted(verdict["evidence_signal_ids"]) == sorted([c1, c2]) and verdict["model_confidence"] == 0.8
    payload = last_payload(provider)
    assert payload["verified_counts"] == {"right": 1, "wrong": 1, "relevant_cases": 2}
    assert all(item["shares_exit_with"] for item in payload["relevant_cases_after_creation"])
    assert [c["id"] for c in payload["originating_cases_not_independent"]] == []


def test_nothing_is_judged_below_the_cadence(repo, memory, provider):
    exit_signal = seed_signal(repo, direction="SELL")
    judged_lesson(repo, exit_signal, moves=(2.0, -1.0))
    assert memory.validate_due(SCOPE, T0 + 60 * MIN) == [] and provider.calls == []


def test_promotion_without_relevant_evidence_is_not_granted(repo, memory, provider):
    lesson, _ = judged_lesson(repo, seed_signal(repo, direction="SELL"))
    provider.push({"relevant_signal_ids": []})
    provider.push({"verdict": "PROMOTE", "model_confidence": 0.9, "reasoning": "feels right"})
    memory.validate_due(SCOPE, T0 + 60 * MIN)
    assert repo.get_lesson(lesson)["status"] == "CANDIDATE"


def test_rejecting_a_candidate(repo, memory, provider):
    lesson, (c1, *_ ) = judged_lesson(repo, seed_signal(repo, direction="SELL"))
    provider.push({"relevant_signal_ids": [c1]})
    provider.push({"verdict": "REJECT", "model_confidence": 0.2, "reasoning": "noise"})
    memory.validate_due(SCOPE, T0 + 60 * MIN)
    assert repo.get_lesson(lesson)["status"] == "REJECTED"


def test_retiring_a_validated_lesson(repo, memory, provider):
    lesson, (c1, *_ ) = judged_lesson(repo, seed_signal(repo, direction="SELL"), status="VALIDATED", validated_at=T0)
    provider.push({"relevant_signal_ids": [c1]})
    provider.push({"verdict": "RETIRE", "model_confidence": 0.3, "reasoning": "stopped working"})
    memory.validate_due(SCOPE, T0 + 60 * MIN)
    row = repo.get_lesson(lesson)
    assert row["status"] == "RETIRED" and row["validated_at"] == T0


def test_only_cases_after_the_last_judgement_count(repo, memory, provider):
    exit_signal = seed_signal(repo, direction="SELL")
    judged_lesson(repo, exit_signal)
    provider.push({"relevant_signal_ids": []})
    provider.push({"verdict": "KEEP_CANDIDATE", "model_confidence": 0.4, "reasoning": "thin"})
    memory.validate_due(SCOPE, T0 + 60 * MIN)
    calls = len(provider.calls)
    assert memory.validate_due(SCOPE, T0 + 120 * MIN) == [] and len(provider.calls) == calls


def test_retrieval_is_scoped_ordered_and_capped(repo, memory, settings):
    at = T0 + 600 * MIN
    early = T0 + MIN
    best = seed_lesson(repo, status="VALIDATED", confidence=0.9, validated_at=early, text="best")
    mid = seed_lesson(repo, status="VALIDATED", confidence=0.6, validated_at=early, text="mid")
    low = seed_lesson(repo, status="VALIDATED", confidence=0.3, validated_at=early, text="low")
    seed_lesson(repo, status="CANDIDATE", confidence=0.99)
    seed_lesson(repo, status="REJECTED", confidence=0.99)
    seed_lesson(repo, status="VALIDATED", confidence=0.99, validated_at=at + MIN)
    for other in (Scope("XAUUSD", "M15,H1,H4", "v1", "Sonnet55"), Scope("XAUUSD", "M5,M15,H1", "v2", "Sonnet55"), Scope("XAUUSD", "M5,M15,H1", "v1", "Opus55")):
        seed_lesson(repo, scope=other, status="VALIDATED", confidence=0.99, validated_at=early)
    assert [l["id"] for l in memory.retrieve(SCOPE, at)] == [best, mid, low]
    settings.memory.lessons_per_call = 2
    assert [l["id"] for l in memory.retrieve(SCOPE, at)] == [best, mid]
