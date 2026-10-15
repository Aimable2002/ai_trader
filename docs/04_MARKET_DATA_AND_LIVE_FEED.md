# 04 — Market Data and Live Feed

## Goal
The cBot is the market-data source. The system runs on live candles from wherever the cBot is attached; it does not distinguish live from demo accounts. There is no replay mode, no backtest, and no historical data loading in the product.

## Trigger
A model call is considered only when a candle closes on the **smallest** configured timeframe. The higher timeframes supply context.

## Point-in-time integrity
At prediction time T:
- Only candles **completed** by T are used, for all 3 timeframes. The still-forming bar of any timeframe is never sent, so the model never sees an unfinished candle.
- Indicator values are read by the cBot at the last **closed** bar index, from closed bars only.
- Only non-repainting indicators are used (SMA, EMA, ATR, RSI).
- Memory includes only lessons validated before T whose scope matches.
- Confirmation tracking and outcome data never enter the prediction context for the signal they concern.
- The current active signal state (PENDING/CONFIRMED) is part of the context; it is information available at T.

## Context completeness
- Candle counts per timeframe come from the context version (v1: 150 bars each). SMA 200 needs at least candles + period - 1 = 349 loaded bars per timeframe.
- The cBot must have enough loaded history that every sent bar has valid indicator values. If it doesn't, it does not send the pack and shows an error.
- The model cannot ask for more data. If context proves insufficient, change the context version.

## Cross-timeframe consistency checks
- The latest smallest-timeframe candle's close time equals the trigger time.
- The latest completed candle of each higher timeframe closes at or before T.
- Gaps: distinguish expected closures (e.g. weekend) from unexpected gaps; report unexpected gaps, never fabricate data.
- UTC timestamps; source precision preserved.

## Live behavior
- Ingest replies 202 immediately and the model runs in the background; the cBot polls for the signal because cBot HTTP calls are synchronous.
- Deduplicate: a cBot restart or resend of the same pack must not create a second prediction.
- Detect stale feeds (no ingest within a configured multiple of the smallest timeframe) and expose stale state to the cBot.
- Keep data acquisition and indicator computation (cBot) separate from inference logic (backend).

## Paid API safeguards
- Full context is sent on every call (about 280 triggers a day on an M5 trigger), so token size matters: send compact numeric series and only the last N values.
- Daily call cap and cost cap, with a kill switch.
- Bounded retries; token and cost logging when returned by OpenRouter.
- Caching keyed by immutable input + configuration.
- Fail visibly when the cap is hit; never silently continue.

## Required tests (synthetic context-pack fixtures + fake model only)
1. A prediction at T cannot see any candle that closes after T, nor a forming bar.
2. Reflection cannot use outcomes unresolved at reflection time.
3. Duplicate or re-sent packs do not create duplicate predictions.
4. A fixed fake-model run is deterministic.
5. Missing data is reported, never silently fabricated.
6. Requests with fewer or more than 3 timeframes, repeated timeframes, mismatched series lengths, non-finite indicator values, an unknown context version, or a model outside the allowlist are rejected.
