import json
import math
import sys
import types
from datetime import timedelta
from types import SimpleNamespace

import pytest

SENT = []


class FakeHeaders:
    def __init__(self):
        self.items = {}

    def Add(self, name, value):
        self.items[name] = value


class FakeRequest:
    def __init__(self, uri):
        self.uri = uri
        self.Method = None
        self.Body = None
        self.Headers = FakeHeaders()


def install_stubs():
    api = types.ModuleType("cAlgo.API")
    api.TimeFrame = SimpleNamespace(Minute="m1", Minute5="m5", Minute15="m15", Minute30="m30", Hour="h1", Hour4="h4", Daily="d1")
    api.MovingAverageType = SimpleNamespace(Simple="simple", Exponential="exponential")
    api.HttpMethod = SimpleNamespace(Get="GET", Post="POST")
    api.HttpRequest = FakeRequest
    api.Color = SimpleNamespace(Green="green", Red="red", Gray="gray", White="white")
    api.VerticalAlignment = SimpleNamespace(Top="top")
    api.HorizontalAlignment = SimpleNamespace(Left="left")
    package = types.ModuleType("cAlgo")
    package.API = api
    clr = types.ModuleType("clr")
    clr.AddReference = lambda name: None
    system = types.ModuleType("System")
    system.TimeSpan = SimpleNamespace(FromSeconds=lambda s: s)
    system.Uri = lambda text: text
    for name, module in {"clr": clr, "cAlgo": package, "cAlgo.API": api, "robot_wrapper": types.ModuleType("robot_wrapper"), "System": system}.items():
        sys.modules[name] = module


install_stubs()
import ai_forex_signal as cbot  # noqa: E402
from app.ingest import validate_pack  # noqa: E402
from app.models import IngestRequest  # noqa: E402
from helpers import MINUTES, T0, floor_to  # noqa: E402

NAN = float("nan")


def epoch(moment):
    return int(moment.timestamp())


def ticks(moment):
    return cbot.EPOCH_TICKS + epoch(moment) * 10000000


class Series:
    def __init__(self, values):
        self.values = values

    def __getitem__(self, index):
        return self.values[index]


class FakeTime:
    def __init__(self, moment):
        self.Ticks = ticks(moment)


def make_bars(minutes, trigger, count):
    forming = floor_to(trigger, minutes)
    opens = [forming - timedelta(minutes=minutes * (count - 1 - i)) for i in range(count)]
    base = [4000 + 5 * math.sin(i / 7) for i in range(count)]
    return SimpleNamespace(
        Count=count,
        OpenTimes=Series([FakeTime(t) for t in opens]),
        OpenPrices=Series(base),
        HighPrices=Series([b + 1 for b in base]),
        LowPrices=Series([b - 1 for b in base]),
        ClosePrices=Series([b + 0.3 for b in base]),
    )


def make_feed(minutes, trigger, count=450):
    values = {name: Series([NAN if (name == "sma" and i < 199) else 4000.0 + i * 0.01 for i in range(count)]) for name in ("sma", "ema", "atr", "rsi")}
    feed = {"bars": make_bars(minutes, trigger, count)}
    feed.update({name: SimpleNamespace(Result=series) for name, series in values.items()})
    return feed


def make_robot(trigger, counts=None):
    robot = cbot.AiForexSignal()
    robot.codes = ["M5", "M15", "H1"]
    counts = counts or {}
    robot.feeds = {code: make_feed(MINUTES[code], trigger, counts.get(code, 450)) for code in robot.codes}
    robot.drawn = []
    return robot


def test_epoch_helpers_round_trip():
    assert cbot.ticks_to_epoch(ticks(T0)) == epoch(T0)
    assert cbot.iso(epoch(T0)) == "2026-01-05T12:00:00Z"


def test_last_closed_index_ignores_the_forming_bar():
    opens = [epoch(T0 - timedelta(hours=2)), epoch(T0 - timedelta(hours=1)), epoch(T0)]
    assert cbot.last_closed_index(opens, 60, epoch(T0)) == 1
    assert cbot.last_closed_index(opens, 60, epoch(T0 + timedelta(minutes=5))) == 1
    assert cbot.last_closed_index(opens, 60, epoch(T0 + timedelta(hours=1))) == 2
    assert cbot.last_closed_index(opens[2:], 60, epoch(T0)) == -1


def test_timeframe_payload_shape():
    payload = cbot.timeframe_payload("M5", [epoch(T0)], [1.0], [2.0], [0.5], [1.5], {"sma": [1.0], "ema": [1.0], "atr": [1.0], "rsi": [50.0]})
    assert payload["candles"][0] == {"open_time": "2026-01-05T12:00:00Z", "close_time": "2026-01-05T12:05:00Z", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5}
    assert payload["timeframe"] == "M5" and payload["indicators"]["rsi"] == [50.0]


def test_missing_indicator_values_block_the_send():
    with pytest.raises(cbot.InsufficientHistory):
        cbot.timeframe_payload("M5", [epoch(T0)], [1.0], [2.0], [0.5], [1.5], {"sma": [NAN]})


def test_constants_match_the_backend_context_version(settings):
    spec = settings.context_versions[cbot.CONTEXT_VERSION]
    assert cbot.CANDLES_PER_TIMEFRAME == spec.candles_per_timeframe
    assert {"sma": cbot.SMA_PERIOD, "ema": cbot.EMA_PERIOD, "atr": cbot.ATR_PERIOD, "rsi": cbot.RSI_PERIOD} == spec.indicators
    assert cbot.TIMEFRAME_MINUTES == settings.timeframes


def test_timeframe_code_maps_known_timeframes_only():
    assert cbot.timeframe_code("m5") == "M5" and cbot.timeframe_code("h1") == "H1"
    with pytest.raises(ValueError):
        cbot.timeframe_code("w1")


def test_collect_takes_closed_bars_only():
    robot = make_robot(T0)
    for code in robot.codes:
        payload = robot.collect(code, epoch(T0))
        assert len(payload["candles"]) == 150
        assert cbot.iso(epoch(T0)) >= payload["candles"][-1]["close_time"]
        assert all(len(series) == 150 for series in payload["indicators"].values())
    assert robot.collect("M5", epoch(T0))["candles"][-1]["close_time"] == "2026-01-05T12:00:00Z"


def test_collect_refuses_when_history_is_too_short_for_the_indicators():
    robot = make_robot(T0, counts={"H1": 300})
    with pytest.raises(cbot.InsufficientHistory):
        robot.collect("H1", epoch(T0))
    with pytest.raises(cbot.InsufficientHistory):
        make_robot(T0, counts={"M5": 100}).collect("M5", epoch(T0))


def test_on_bar_closed_sends_a_pack_the_backend_accepts(settings):
    robot = make_robot(T0)
    printed = []
    reply = SimpleNamespace(IsSuccessful=True, StatusCode=202, Body="{}")
    fake_api = SimpleNamespace(
        Bars=SimpleNamespace(OpenTimes=SimpleNamespace(LastValue=FakeTime(T0))),
        Server=SimpleNamespace(Time=FakeTime(T0 + timedelta(seconds=5))),
        SymbolName="XAUUSD",
        Model=SimpleNamespace(ToString=lambda: "Sonnet55"),
        BackendUrl="https://backend.test/",
        ApiKey="secret",
        Http=SimpleNamespace(Send=lambda request: (SENT.append(request), reply)[1]),
        Print=printed.append,
    )
    cbot.api = fake_api
    SENT.clear()
    robot.on_bar_closed()
    request = SENT[0]
    assert request.uri == "https://backend.test/ingest" and request.Method == "POST"
    assert request.Headers.items == {"X-API-Key": "secret", "Content-Type": "application/json"}
    req = IngestRequest.model_validate(json.loads(request.Body))
    assert validate_pack(req, settings) == ["M5", "M15", "H1"]
    assert req.model == "Sonnet55" and req.cbot_version == cbot.CBOT_VERSION and printed == []


def test_on_bar_closed_sends_nothing_without_enough_history():
    robot = make_robot(T0, counts={"H1": 300})
    printed = []
    SENT.clear()
    cbot.api = SimpleNamespace(
        Bars=SimpleNamespace(OpenTimes=SimpleNamespace(LastValue=FakeTime(T0))),
        Http=SimpleNamespace(Send=lambda request: SENT.append(request)),
        Print=printed.append,
    )
    robot.on_bar_closed()
    assert SENT == [] and "H1" in printed[0]


def sample_data(**overrides):
    signal = {"id": 4, "direction": "BUY", "lifecycle_status": "PENDING", "zone_low": 3995.0, "zone_high": 4000.0, "entry_price": 4001.0}
    return {"signals": [signal], "latest": signal, "stale": False, **overrides}


def test_panel_and_drawing_plan():
    assert "#4 BUY PENDING zone 3995.0-4000.0 entry 4001.0" in cbot.panel_lines(sample_data())
    assert cbot.drawing_plan(sample_data()) == [("aifs_entry_4", 4001.0, "buy"), ("aifs_zone_low_4", 3995.0, "zone"), ("aifs_zone_high_4", 4000.0, "zone")]
    assert any("STALE" in line for line in cbot.panel_lines(sample_data(stale=True)))
    assert "No active signal" in cbot.panel_lines(sample_data(signals=[], latest=None))
    assert cbot.drawing_plan(sample_data(signals=[])) == []


def test_render_replaces_previous_drawings():
    removed, drawn, texts = [], [], []
    cbot.api = SimpleNamespace(
        Chart=SimpleNamespace(
            RemoveObject=removed.append,
            DrawHorizontalLine=lambda name, price, color: drawn.append((name, price, color)),
            DrawStaticText=lambda *args: texts.append(args),
        )
    )
    robot = make_robot(T0)
    robot.drawn = ["old_line"]
    robot.render(sample_data())
    assert removed == ["old_line"] and drawn[0] == ("aifs_entry_4", 4001.0, "green")
    assert robot.drawn == ["aifs_entry_4", "aifs_zone_low_4", "aifs_zone_high_4"] and texts[0][0] == cbot.PANEL_NAME


def test_generated_stub_matches_the_backend_model_list(settings, tmp_path):
    sys.path.insert(0, str(tmp_path.parent))
    from importlib import import_module

    generator = import_module("generate_stubs")
    generator.generate(generator.ROOT / "config" / "settings.yaml", tmp_path)
    stub = (tmp_path / "AiForexSignal.cs").read_text()
    for option in settings.models.allowed:
        assert f"        {option.key}" in stub
    assert f"DefaultValue = SignalModel.{settings.models.default}" in stub
    for name in ("BackendUrl", "ApiKey", "Model", "TimeframeOne", "TimeframeTwo", "TimeframeThree"):
        assert f" {name} " in stub
    assert "AccessRights = AccessRights.None" in (tmp_path / "SmokeTest.cs").read_text()
