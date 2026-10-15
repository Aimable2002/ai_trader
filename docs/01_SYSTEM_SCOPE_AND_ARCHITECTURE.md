# 01 — System Scope and Architecture

## Objective
One system, one core pipeline, one input mode: **live context packs from the cBot**. The system operates wherever the cBot is attached and makes no distinction between live and demo accounts.

## In scope
- XAUUSD (instrument stays configurable).
- Exactly 3 timeframes per request, set by the operator in the cBot (default M5/M15/H1); the smallest is the entry timeframe and the inference trigger.
- cBot (Python) → backend context packs: real candles and platform-fixed indicators (SMA, EMA, ATR, RSI) computed on the cBot; backend → cBot signal delivery (display only).
- Hosted model inference through OpenRouter behind a replaceable adapter.
- Structured setup + confirmation-entry generation, pending-signal keep/invalidate decisions, validation, persistence.
- Confirmation tracking and outcome evaluation (to the next opposite signal).
- Reflection on mistakes, model-judged memory validation, condition-matched retrieval.
- Optional shadow mode on the same live candles.
- Configuration, logging, error handling, API-cost safeguards, repeatable tests.

## Explicitly out of scope
- Historical replay, backtesting, or any loading of historical data into the product.
- Subscriptions, billing, public signup, multi-tenant features, marketing pages.
- Automated trade execution or any order placement.
- SL/TP suggestions or price (high/low) prediction.
- Model training, fine-tuning, weight updates.
- Engineered technical rules for setup or confirmation: the model supplies them.
- The model requesting extra data from the cBot (it gets the full context upfront).
- User-selectable indicators or candle types; recomputing indicators in the backend; Heiken Ashi (later version).
- Multi-user support, per-user caps and identity (version 2).
- Unrestricted model tool access; general AI experimentation platform; complex dashboards.

## Core flow
1. cBot closes a bar on the smallest timeframe and sends the context pack.
2. Backend validates the pack structure (including the model and timeframe allowlists), deduplicates by idempotency key, and replies 202 immediately; steps 3-11 run in the background.
3. Context builder prepares the prompt from the pack plus the current active signal state.
4. Memory retriever selects validated lessons matching instrument + timeframe set + context version + model.
5. Model adapter calls OpenRouter.
6. Output validator checks the response against the schema.
7. Signal repository persists the immutable prediction and provenance; pending-signal decisions update confirmation records.
8. cBot reads the latest signal and displays it.
9. Confirmation tracker and outcome evaluator update separate records as later packs arrive.
10. Reflection runs on resolved mistakes; validation judges candidate lessons.
11. Validated lessons feed future inference under matching conditions.

## Component boundaries (adapt to the repository)
`market_data` (ingest + validation), `context`, `model_provider` (OpenRouter adapter), `signals`, `delivery`, `evaluation`, `reflection`, `memory`, `config`, `observability`.

## Important rule
A prediction is not an outcome. Store the original prediction unchanged; store confirmation, evaluation, reflection, and memory records separately, linked by stable IDs.
