# 02 — Implementation Plan

Implement in small, testable increments. Do not generate the whole application in one pass.

## Stage 0 — Inspect repositories
- Identify language/framework, dependencies, tests, persistence, and the existing cBot project and confirm on your cTrader version that a Python cBot supports HTTP calls, the built-in indicators, dropdown parameters, `on_bar_closed` bar indexing, and `GetBars` for three timeframes.
- Propose the smallest plan; do not silently replace the stack.
**Exit:** plan names files/modules to change and concrete blockers.

## Stage 0b — cBot smoke test
- Run `cbot/smoke_test.py` in cTrader against the backend: it checks outbound HTTP, headers, and a JSON POST (expected reply: 422 validation error from `/ingest`).
**Exit:** the transport is confirmed before anything else depends on it.

## Stage 1 — Pipeline skeleton with fake model
- Define context-pack, signal, and ingest contracts (exactly 3 timeframes).
- Deterministic fake model provider; synthetic context-pack fixtures used only in tests.
- Ingest → context → inference → validation → persistence → delivery interfaces; run IDs; structured logs.
**Exit:** a test produces and retrieves a valid signal without a paid API call.

## Stage 2 — Live ingest integrity
- Strict validation: exactly 3 distinct timeframes, completed candles only, ordering, OHLC sanity, series lengths, finite indicator values, known context version.
- Idempotency by trigger candle and configuration; resend-safe.
**Exit:** tests prove no incomplete candle reaches the model context and duplicate ingests create one prediction.

## Stage 3 — OpenRouter model adapter
- One adapter; the model comes from the request (cBot dropdown) and is checked against the backend allowlist; prompt config version configurable.
- Validate structured output; handle timeout, rate limit, malformed response, provider errors.
- Record model/config versions, latency, token usage and cost when returned.
- Secrets in environment variables or the existing secret manager.
**Exit:** a real model produces a validated setup + confirmation entry on a small controlled sample of live candles.

## Stage 4 — cBot context pack and display
- cBot (Python) computes the fixed indicator set, sends the pack on smallest-timeframe bar close, fetches and displays signals, shows stale/error state. No trade execution.
**Exit:** a backend signal appears correctly in cTrader.

## Stage 5 — Confirmation and outcome evaluation
- Version the evaluator. Track PENDING → CONFIRMED / REJECTED (model-invalidated); resolve outcomes at the next opposite signal.
- Evaluation records stay separate from predictions.
**Exit:** synthetic price-path tests produce expected states and outcomes.

## Stage 6 — Reflection and memory
- Reflect on resolved mistakes; system verifies cited cases; model judges confidence and verdict.
- Retrieve validated lessons matching current conditions; record lesson IDs per prediction.
**Exit:** candidate → validated/rejected/retired flow works with fake and real models; memory retrieval is switchable.

## Stage 7 — Operation and safeguards
- Stale-data checks, retry limits, daily call/cost caps, kill switch, optional shadow mode.
**Exit:** stable live observation with an auditable signal history.

## Stage 8 — V1 research acceptance
- Report counts, confirmation rate, outcome statistics, and shadow comparisons honestly, including negative results.
**Exit:** pipeline runs live, outcomes are auditable, improvement claims are supported or rejected by the observed data.
