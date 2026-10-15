import json
import math
from datetime import datetime, timezone

import clr

clr.AddReference("cAlgo.API")
from cAlgo.API import *
from robot_wrapper import *
from System import TimeSpan, Uri

CBOT_VERSION = "1.0.0"
CONTEXT_VERSION = "v1"
CANDLES_PER_TIMEFRAME = 150
SMA_PERIOD = 200
EMA_PERIOD = 50
ATR_PERIOD = 14
RSI_PERIOD = 14
POLL_SECONDS = 15
HISTORY_MARGIN = 5
TIMEFRAME_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}
EPOCH_TICKS = 621355968000000000
PANEL_NAME = "aifs_panel"


class InsufficientHistory(Exception):
    pass


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ticks_to_epoch(ticks):
    return (ticks - EPOCH_TICKS) // 10000000


def last_closed_index(open_epochs, minutes, trigger_epoch):
    for index in range(len(open_epochs) - 1, -1, -1):
        if open_epochs[index] + minutes * 60 <= trigger_epoch:
            return index
    return -1


def timeframe_payload(code, open_epochs, opens, highs, lows, closes, indicators):
    for name, series in indicators.items():
        if any(math.isnan(value) for value in series):
            raise InsufficientHistory(f"{code}: indicator {name} has no value yet; load more chart history")
    width = TIMEFRAME_MINUTES[code] * 60
    candles = [
        {"open_time": iso(t), "close_time": iso(t + width), "open": o, "high": h, "low": l, "close": c}
        for t, o, h, l, c in zip(open_epochs, opens, highs, lows, closes)
    ]
    return {"timeframe": code, "candles": candles, "indicators": {name: list(series) for name, series in indicators.items()}}


def build_request(instrument, model, trigger_epoch, sent_epoch, timeframes):
    return {
        "instrument": instrument,
        "trigger_candle_time": iso(trigger_epoch),
        "cbot_version": CBOT_VERSION,
        "sent_at": iso(sent_epoch),
        "context_version": CONTEXT_VERSION,
        "model": model,
        "timeframes": timeframes,
    }


def panel_lines(data):
    lines = ["AI Forex Signal"]
    if data["stale"]:
        lines.append("STALE: no recent data from the backend")
    if not data["signals"]:
        latest = data["latest"]
        lines.append("No active signal" if latest is None else f"Latest: {latest['direction']} ({latest['lifecycle_status']})")
    for signal in data["signals"]:
        lines.append(
            f"#{signal['id']} {signal['direction']} {signal['lifecycle_status']} "
            f"zone {signal['zone_low']}-{signal['zone_high']} entry {signal['entry_price']}"
        )
    return lines


def drawing_plan(data):
    plan = []
    for signal in data["signals"]:
        side = signal["direction"].lower()
        plan.append((f"aifs_entry_{signal['id']}", signal["entry_price"], side))
        plan.append((f"aifs_zone_low_{signal['id']}", signal["zone_low"], "zone"))
        plan.append((f"aifs_zone_high_{signal['id']}", signal["zone_high"], "zone"))
    return plan


def timeframe_code(timeframe):
    known = (
        ("M1", TimeFrame.Minute), ("M5", TimeFrame.Minute5), ("M15", TimeFrame.Minute15), ("M30", TimeFrame.Minute30),
        ("H1", TimeFrame.Hour), ("H4", TimeFrame.Hour4), ("D1", TimeFrame.Daily),
    )
    for code, constant in known:
        if timeframe == constant:
            return code
    raise ValueError("unsupported timeframe")


class AiForexSignal():
    def on_start(self):
        chosen = [api.TimeframeOne, api.TimeframeTwo, api.TimeframeThree]
        codes = [timeframe_code(tf) for tf in chosen]
        if len(set(codes)) != 3:
            api.Print("Select three different timeframes")
            api.Stop()
            return
        by_size = sorted(zip(codes, chosen), key=lambda pair: TIMEFRAME_MINUTES[pair[0]])
        self.codes = [code for code, _ in by_size]
        if api.TimeFrame != by_size[0][1]:
            api.Print("Attach the cBot to a chart of the smallest selected timeframe")
            api.Stop()
            return
        self.feeds = {}
        for code, timeframe in by_size:
            bars = api.MarketData.GetBars(timeframe)
            closes = bars.ClosePrices
            self.feeds[code] = {
                "bars": bars,
                "sma": api.Indicators.MovingAverage(closes, SMA_PERIOD, MovingAverageType.Simple),
                "ema": api.Indicators.MovingAverage(closes, EMA_PERIOD, MovingAverageType.Exponential),
                "atr": api.Indicators.AverageTrueRange(bars, ATR_PERIOD, MovingAverageType.Simple),
                "rsi": api.Indicators.RelativeStrengthIndex(closes, RSI_PERIOD),
            }
        self.drawn = []
        api.Timer.Start(TimeSpan.FromSeconds(POLL_SECONDS))

    def on_bar_closed(self):
        trigger = ticks_to_epoch(api.Bars.OpenTimes.LastValue.Ticks)
        try:
            timeframes = [self.collect(code, trigger) for code in self.codes]
        except InsufficientHistory as exc:
            api.Print(str(exc))
            return
        sent = ticks_to_epoch(api.Server.Time.Ticks)
        body = json.dumps(build_request(api.SymbolName, api.Model.ToString(), trigger, sent, timeframes))
        response = self.send(HttpMethod.Post, "/ingest", body)
        if not response.IsSuccessful:
            api.Print(f"ingest rejected: {response.StatusCode} {response.Body}")

    def on_timer(self):
        query = f"timeframes={','.join(self.codes)}&model={api.Model.ToString()}&context_version={CONTEXT_VERSION}"
        response = self.send(HttpMethod.Get, f"/signals/latest?{query}")
        if response.IsSuccessful:
            self.render(json.loads(response.Body))

    def on_stop(self):
        api.Timer.Stop()

    def collect(self, code, trigger):
        feed = self.feeds[code]
        bars = feed["bars"]
        count = bars.Count
        offset = max(0, count - (CANDLES_PER_TIMEFRAME + HISTORY_MARGIN))
        window = [ticks_to_epoch(bars.OpenTimes[i].Ticks) for i in range(offset, count)]
        relative = last_closed_index(window, TIMEFRAME_MINUTES[code], trigger)
        last = offset + relative
        first = last - CANDLES_PER_TIMEFRAME + 1
        if relative < 0 or first < 0:
            raise InsufficientHistory(f"{code}: not enough closed bars loaded")
        rows = range(first, last + 1)
        return timeframe_payload(
            code,
            [ticks_to_epoch(bars.OpenTimes[i].Ticks) for i in rows],
            [bars.OpenPrices[i] for i in rows],
            [bars.HighPrices[i] for i in rows],
            [bars.LowPrices[i] for i in rows],
            [bars.ClosePrices[i] for i in rows],
            {name: [feed[name].Result[i] for i in rows] for name in ("sma", "ema", "atr", "rsi")},
        )

    def send(self, method, path, body=None):
        request = HttpRequest(Uri(api.BackendUrl.rstrip("/") + path))
        request.Method = method
        request.Headers.Add("X-API-Key", api.ApiKey)
        if body is not None:
            request.Body = body
            request.Headers.Add("Content-Type", "application/json")
        return api.Http.Send(request)

    def render(self, data):
        for name in self.drawn:
            api.Chart.RemoveObject(name)
        colors = {"buy": Color.Green, "sell": Color.Red, "zone": Color.Gray}
        self.drawn = []
        for name, price, kind in drawing_plan(data):
            api.Chart.DrawHorizontalLine(name, price, colors[kind])
            self.drawn.append(name)
        api.Chart.DrawStaticText(PANEL_NAME, "\n".join(panel_lines(data)), VerticalAlignment.Top, HorizontalAlignment.Left, Color.White)
