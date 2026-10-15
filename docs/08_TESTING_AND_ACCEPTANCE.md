# 08 — Testing and Acceptance

Automated tests use a **fake model** and **synthetic context-pack fixtures**. These are test fixtures, not a backtest feature. Real API calls are opt-in and limited to small samples. Indicator value correctness is checked manually against the cTrader chart, since only the cBot computes them.

## Unit tests
Context-pack validation (exactly 3 timeframes, aligned series, finite values, known context version); model-output schema validation (including `NONE`, `pending_reviews`, and rejection of SL/TP or data-request fields as non-contract); OpenRouter response parsing and malformed output; idempotency keys; confirmation tracking; outcome resolution on synthetic paths (confirm, reject via invalidation, resolve at opposite signal, `NONE` does not end a trade, same-direction signal does not end a trade); reflection schema; lesson ID verification and count computation; scope filtering by timeframe set and context version; stale-data detection; model and timeframe allowlist rejection; configuration loading.

## Integration tests
Fake provider → validation → persistence → delivery; ingest → signal → later packs → confirmation → outcome; model invalidates a pending signal → REJECTED; resolved mistake → reflection candidate → validation verdict → retrieval in a later prediction; retrieval excludes lessons from a different timeframe set or context version; shadow mode persists both configurations; cBot displays stored signals where tooling allows.

## Critical leakage tests
- Prediction context at T excludes any later candle and any forming bar.
- Memory at T excludes lessons validated after T and lessons from another scope.
- Reflection cannot use unresolved outcomes.
- Validation evidence includes post-creation cases; originating cases are not counted as independent; shared-exit cases are flagged.
- The model's cited counts are never trusted; counts come from stored records.
- Original predictions remain immutable after confirmation and outcome.

## Operational tests
API timeout/rate limit; malformed model output; duplicate ingest; stale or missing data; database/delivery failure; reflection failure does not block delivery; daily call/cost cap halts calls and fails visibly.

## V1 acceptance checklist
- [ ] cBot with exactly 3 configured timeframes sends the context pack; backend triggers on the smallest timeframe close.
- [ ] Pack contains real candles and SMA/EMA/ATR/RSI from closed bars only, tagged with a context version.
- [ ] Model (via OpenRouter) returns schema-valid setup + confirmation entry + pending reviews; no SL/TP, price prediction, or data requests.
- [ ] Signals are timestamped, persisted, immutable.
- [ ] cBot displays signals and statuses correctly; no trade execution exists.
- [ ] Confirmation, model invalidation, and outcomes (to the next opposite signal) are evaluated from real later candles.
- [ ] Reflection uses hosted calls and changes no weights.
- [ ] Lessons carry evidence, verified counts, model confidence, verdict, scope (timeframe set + context version).
- [ ] Retrieval only returns validated, condition-matched lessons.
- [ ] Shadow comparison is possible.
- [ ] Look-ahead tests pass.
- [ ] API usage, cost, errors, latency, and run configuration are logged.
- [ ] No replay/backtest, billing, subscriptions, or customer accounts exist in V1.

Working software does not prove predictive edge. Report signal quality and reflection results honestly.
