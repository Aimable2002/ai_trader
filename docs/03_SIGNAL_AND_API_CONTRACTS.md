# 03 — Signal and API Contracts

Typed models and schema validation are used throughout (pydantic in the backend). Fields specify semantics.

## Candle
`open_time`, `close_time` (UTC, timezone-aware), `open`, `high`, `low`, `close`. Only **completed** candles are accepted; the forming candle is never sent. Non-finite numbers never parse.

## Context pack (cBot → `POST /ingest`)
- `instrument`, `trigger_candle_time` (close time of the latest completed candle on the smallest timeframe), `cbot_version`, `sent_at`.
- `context_version`: names the platform-fixed indicator set, its periods and the candle count. v1 = SMA 200, EMA 50, ATR 14, RSI 14 and 150 candles per timeframe. Unknown versions are rejected.
- `model`: the model key chosen in the cBot dropdown (e.g. `Sonnet55`). Keys outside the backend allowlist are rejected; the key maps to an OpenRouter model id in the config.
- `timeframes`: **exactly 3** distinct timeframes from the backend allowlist, each with `candles` (real, closed, ordered) and `indicators` (`sma`, `ema`, `atr`, `rsi`) aligned one value per candle.

The backend validates structure only and never recomputes indicators: 3 distinct allowed timeframes, candle count for the context version, indicator names and series lengths, finite values, candle width equals the timeframe, strict ordering without duplicates or overlap, OHLC sanity, every candle closed at the trigger time, and the last smallest-timeframe candle closing exactly at the trigger time.
Roles by size: largest = bias and key levels, middle = setup, smallest = confirmation entry and trigger.

Response: `202 {"run_id", "duplicate"}` immediately. Validation failures return 422 with the reason. The model runs in the background.

## Model input additions (added by the backend)
The active signals (PENDING and CONFIRMED) for the same scope, and the retrieved validated lessons.

## Model output
- `setup_direction`: `BUY`, `SELL`, or `NONE`
- `setup_zone_low`, `setup_zone_high`: the support/resistance zone the setup is based on; null when `NONE`
- `confirmation_entry_price`: the real-entry level; null when `NONE`
- `pending_reviews`: for each PENDING signal, `signal_id` and `action` = `KEEP` or `INVALIDATE`
- `rationale`, `confidence` (optional, 0 to 1, never treated as a calibrated probability)

Not part of the contract: stop loss, take profit, predicted high/low, data requests. Levels must be positive and finite with `low <= high`. A configurable maximum distance from the last close (`max_entry_distance_pct`) guards against malformed output; it is not a trading rule. A response that fails validation is retried up to `max_attempts` times, then the run fails visibly.

## Stored signal (immutable)
Model output plus `run_id`, `instrument`, `timeframe_set`, `context_version`, `model_key`, `openrouter_id`, `mode` (`primary` or `shadow_memory_off`), `prediction_time`, `lesson_ids`, `prompt_config_version`, `source_candle_times` and, if enabled, the exact context pack. A database trigger rejects any update to a signal.

## Confirmation (separate table)
`PENDING` → `CONFIRMED` when a later smallest-timeframe candle's range reaches the entry price, or → `REJECTED` when the model invalidates it through `pending_reviews`. A pending setup ends no other way. `NONE` signals have no lifecycle.

## Outcome (separate table)
Created when the next opposite BUY/SELL signal arrives: entry (the confirmation entry), exit price (close of the triggering candle), signed move, MFE, MAE, duration, `is_mistake` (signed move below zero), evaluator version. Outcomes are keyed by signal, so a trade resolves once.

## Delivery (backend → cBot)
`GET /signals/latest?timeframes=M5,M15,H1&model=Sonnet55&context_version=v1` returns the active signals, the latest signal (with `NONE` status when it has no lifecycle), `last_ingest_at`, `stale` and `server_time`. It is read-only and never triggers a model call. `GET /runs/{id}` shows a run's status and error. `GET /health` is open. Every other endpoint requires the `X-API-Key` header.

## Idempotency
Key = model + prompt config version + mode + instrument + timeframe set + context version + trigger candle time. A resend of the same pack never creates a second prediction. `lesson_ids` on the signal record which memory was used.
