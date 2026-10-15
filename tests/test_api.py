import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.provider import ProviderError
from helpers import SCOPE, T0, buy_output, make_request, none_output, seed_lesson, sell_output

KEY = {"X-API-Key": "k"}
MIN5 = timedelta(minutes=5)
PARAMS = {"timeframes": "M5,M15,H1", "model": "Sonnet55", "context_version": "v1"}


@pytest.fixture
def client(settings, repo, service):
    return TestClient(create_app(settings, repo, service, "k"))


def post(client, req):
    return client.post("/ingest", content=req.model_dump_json(), headers={**KEY, "Content-Type": "application/json"})


def latest(client, **overrides):
    return client.get("/signals/latest", params={**PARAMS, **overrides}, headers=KEY)


def run_status(repo, run_id):
    return repo.get_run(run_id)


def signal_ids(repo):
    return [r["id"] for r in repo._all("select id from signals order by id")]


def open_confirmed_buy(client, provider, entry=4001.0):
    provider.push(buy_output(entry=entry))
    post(client, make_request(T0))
    provider.push(none_output())
    post(client, make_request(T0 + MIN5, last_candle=(4000.5, 4002.0, 3999.0, 4001.5)))


def test_authentication_is_required(client):
    req = make_request()
    assert client.post("/ingest", content=req.model_dump_json()).status_code == 401
    assert client.post("/ingest", content=req.model_dump_json(), headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/signals/latest", params=PARAMS).status_code == 401
    assert client.get("/runs/1").status_code == 401
    assert client.get("/health").json() == {"status": "ok"}


def test_invalid_requests_are_rejected_without_model_calls(client, provider):
    assert post(client, make_request(model="Mystery")).status_code == 422
    assert post(client, make_request(count=100)).status_code == 422
    assert client.post("/ingest", content="{}", headers={**KEY, "Content-Type": "application/json"}).status_code == 422
    assert "exactly 3" in client.post("/ingest", content=json.dumps({**make_request().model_dump(mode="json"), "timeframes": []}), headers={**KEY, "Content-Type": "application/json"}).json()["detail"]
    assert provider.calls == []


def test_ingest_replies_immediately_and_signal_is_delivered(client, provider, repo):
    provider.push(buy_output())
    response = post(client, make_request())
    assert response.status_code == 202 and response.json()["duplicate"] is False
    assert run_status(repo, response.json()["run_id"])["status"] == "DONE"
    body = latest(client).json()
    assert [(s["direction"], s["lifecycle_status"]) for s in body["signals"]] == [("BUY", "PENDING")]
    assert body["latest"]["entry_price"] == 4001.0 and body["stale"] is False


def test_resending_the_same_pack_never_calls_the_model_twice(client, provider, repo):
    provider.push(buy_output())
    first = post(client, make_request())
    second = post(client, make_request())
    assert second.json() == {"run_id": first.json()["run_id"], "duplicate": True}
    assert len(provider.calls) == 1 and len(signal_ids(repo)) == 1


def test_polling_never_triggers_a_model_call(client, provider):
    provider.push(buy_output())
    post(client, make_request())
    for _ in range(3):
        latest(client)
    assert len(provider.calls) == 1


def test_full_cycle_confirmation_then_opposite_signal_resolves_the_trade(client, provider, repo):
    provider.push(buy_output(entry=4001.0))
    post(client, make_request(T0))
    buy_id = signal_ids(repo)[0]
    provider.push(none_output())
    post(client, make_request(T0 + MIN5, last_candle=(4000.5, 4002.0, 3999.0, 4001.5)))
    assert latest(client).json()["signals"][0]["lifecycle_status"] == "CONFIRMED"
    provider.push(sell_output(entry=3990.0))
    provider.push({"abstain": False, "observed_fact": "reversal", "hypothesis": "late", "candidate_lesson": "avoid late buys",
                   "conditions": "after a spike", "cited_signal_ids": [buy_id], "model_confidence": 0.5, "uncertainty": "thin"})
    post(client, make_request(T0 + 2 * MIN5, last_candle=(3992.0, 3993.0, 3985.0, 3988.0)))
    outcome = repo._one("select * from outcomes")
    sell_id = signal_ids(repo)[-1]
    assert (outcome["signal_id"], outcome["exit_signal_id"], outcome["is_mistake"]) == (buy_id, sell_id, True)
    assert outcome["signed_move"] == pytest.approx(3988.0 - 4001.0) and outcome["mae"] == pytest.approx(16.0) and outcome["mfe"] == 0.0
    signals = latest(client).json()["signals"]
    assert [(s["direction"], s["lifecycle_status"]) for s in signals] == [("SELL", "PENDING")]
    lesson = repo._one("select * from lessons")
    assert lesson["status"] == "CANDIDATE" and lesson["origin_signal_id"] == buy_id and lesson["cited_signal_ids"] == [buy_id]


def test_a_failed_reflection_never_fails_the_run(client, provider, repo, settings):
    open_confirmed_buy(client, provider)
    provider.push(sell_output(entry=3990.0))
    response = post(client, make_request(T0 + 2 * MIN5, last_candle=(3992.0, 3993.0, 3985.0, 3988.0)))
    assert run_status(repo, response.json()["run_id"])["status"] == "DONE"
    assert len(repo._all("select * from outcomes")) == 1 and repo._all("select * from lessons") == []


def test_none_signal_does_not_end_a_confirmed_trade(client, provider, repo):
    open_confirmed_buy(client, provider)
    provider.push(none_output())
    post(client, make_request(T0 + 2 * MIN5, last_candle=(3992.0, 3993.0, 3985.0, 3988.0)))
    assert repo._all("select * from outcomes") == []
    assert latest(client).json()["signals"][0]["lifecycle_status"] == "CONFIRMED"
    assert latest(client).json()["latest"]["direction"] == "NONE"


def test_same_direction_signal_is_still_delivered_while_one_is_confirmed(client, provider, repo):
    open_confirmed_buy(client, provider)
    provider.push(buy_output(entry=4003.0, low=3998.0, high=4002.0))
    post(client, make_request(T0 + 2 * MIN5, last_candle=(3990.0, 3991.0, 3989.0, 3990.0)))
    signals = latest(client).json()["signals"]
    assert [(s["direction"], s["lifecycle_status"]) for s in signals] == [("BUY", "CONFIRMED"), ("BUY", "PENDING")]
    assert repo._all("select * from outcomes") == []


def test_model_can_invalidate_a_pending_setup(client, provider, repo):
    provider.push(buy_output(entry=4001.0))
    post(client, make_request(T0))
    buy_id = signal_ids(repo)[0]
    provider.push(none_output(reviews=[{"signal_id": buy_id, "action": "INVALIDATE"}]))
    post(client, make_request(T0 + MIN5, last_candle=(3950.0, 3951.0, 3949.0, 3950.0)))
    assert latest(client).json()["signals"] == []
    assert repo._one("select status from confirmations where signal_id = %s", (buy_id,))["status"] == "REJECTED"
    assert repo._all("select * from outcomes") == []


def test_active_signals_are_shown_to_the_model(client, provider):
    provider.push(buy_output())
    post(client, make_request(T0))
    provider.push(none_output())
    post(client, make_request(T0 + MIN5, last_candle=(3950.0, 3951.0, 3949.0, 3950.0)))
    assert "BUY status=PENDING" in provider.calls[1]["messages"][1]["content"]


def test_validated_lessons_are_used_and_recorded(client, provider, repo):
    lesson = seed_lesson(repo, status="VALIDATED", validated_at=T0 - timedelta(days=1), text="never chase spikes")
    provider.push(buy_output())
    post(client, make_request(T0))
    assert "never chase spikes" in provider.calls[0]["messages"][1]["content"]
    assert repo._one("select lesson_ids from signals order by id desc limit 1")["lesson_ids"] == [lesson]


def test_model_failures_mark_the_run_failed(client, provider, repo):
    provider.push(ProviderError("provider down"))
    response = post(client, make_request())
    run = run_status(repo, response.json()["run_id"])
    assert run["status"] == "FAILED" and "provider down" in run["error"]
    assert signal_ids(repo) == []
    assert client.get(f"/runs/{run['id']}", headers=KEY).json()["status"] == "FAILED"


def test_unparseable_model_output_marks_the_run_failed(client, provider, repo):
    provider.push("nonsense")
    provider.push("still nonsense")
    run = run_status(repo, post(client, make_request()).json()["run_id"])
    assert run["status"] == "FAILED" and "rejected" in run["error"]


def test_entries_far_from_price_are_rejected(client, provider, repo):
    provider.push(buy_output(entry=5000.0, low=4990.0, high=4999.0))
    run = run_status(repo, post(client, make_request()).json()["run_id"])
    assert run["status"] == "FAILED" and "away from the last close" in run["error"] and signal_ids(repo) == []


def test_daily_cap_and_kill_switch_fail_visibly(client, provider, repo, settings):
    settings.limits.daily_model_call_cap = 0
    run = run_status(repo, post(client, make_request(T0)).json()["run_id"])
    assert run["status"] == "FAILED" and "cap" in run["error"]
    settings.limits.daily_model_call_cap = 400
    settings.limits.kill_switch = True
    run = run_status(repo, post(client, make_request(T0 + MIN5)).json()["run_id"])
    assert run["status"] == "FAILED" and "kill switch" in run["error"] and provider.calls == []


def test_unknown_run_is_404(client):
    assert client.get("/runs/9999", headers=KEY).status_code == 404


def test_shadow_mode_runs_memory_off_alongside_and_hides_it(client, provider, repo, settings):
    settings.shadow_mode = True
    seed_lesson(repo, status="VALIDATED", validated_at=T0 - timedelta(days=1), text="never chase spikes")
    provider.push(buy_output())
    provider.push(sell_output())
    post(client, make_request())
    modes = [r["mode"] for r in repo._all("select mode from signals order by id")]
    assert modes[-2:] == ["primary", "shadow_memory_off"]
    assert "never chase spikes" in provider.calls[0]["messages"][1]["content"]
    assert "never chase spikes" not in provider.calls[1]["messages"][1]["content"]
    assert [s["direction"] for s in latest(client).json()["signals"]] == ["BUY"]


def test_staleness(client, provider, settings):
    body = latest(client).json()
    assert body["stale"] is True and body["last_ingest_at"] is None
    provider.push(none_output())
    post(client, make_request())
    assert latest(client).json()["stale"] is False
    settings.stale_after_intervals = 0
    assert latest(client).json()["stale"] is True


def test_latest_validates_its_query(client):
    assert latest(client, timeframes="M5,M15").status_code == 422
    assert latest(client, timeframes="M5,M5,H1").status_code == 422
    assert latest(client, model="Mystery").status_code == 422
    assert latest(client, context_version="v9").status_code == 422
    assert latest(client, timeframes="H1,M5,M15").status_code == 200
