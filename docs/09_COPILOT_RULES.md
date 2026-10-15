# 09 — Instructions for GitHub Copilot

## Product constraints
- V1 of a research-first AI Forex indicator for a single operator; not a SaaS platform.
- The system works on live candles from the cBot, wherever it runs; do not add live/demo-account logic. **No replay, backtest, or historical data loading.**
- A cBot supplies the context pack and displays signals. Signals are for a human trader; no autonomous trading, no order placement.
- The cBot is Python. Exactly 3 timeframes and the model are predefined dropdowns in the cBot (default M5/M15/H1); the smallest timeframe is the entry timeframe and trigger. The backend keeps an allowlist and rejects anything else.
- Indicators (SMA, EMA, ATR, RSI) and candle counts are fixed by a platform `context_version` and computed on the cBot. Heiken Ashi is postponed. Do not recompute them in the backend and do not make them user-selectable.
- The model (via OpenRouter, provider-neutral adapter) supplies the setup, confirmation entry, and keep/invalidate decisions for pending signals. Do not engineer indicator rules for these. Do not add SL/TP, price-prediction, or data-request capabilities.
- Do not train/fine-tune models or change weights.
- Memory: lessons are model-judged but system-verified; scope = instrument + timeframe set + context version + model; no engineered promotion thresholds.
- No billing, subscriptions, public signup, customer management, or unrelated infrastructure.

## Engineering rules
1. Inspect the repository (and the existing cBot project) before changes.
2. Follow existing language, framework, formatting, and testing conventions.
3. Make the smallest change that satisfies the current task.
4. Explain files affected before broad refactors.
5. Add tests for meaningful components; use fake models and synthetic fixtures.
6. Validate every model response and every context pack against a typed schema.
7. Keep provider-specific code behind the adapter.
8. Keep secrets out of source control and out of the cBot.
9. Use stable IDs, UTC timestamps, config versions, structured logs.
10. Preserve original predictions; store confirmation, outcomes, reflections separately.
11. Enforce call/cost caps and log usage.
12. Fail visibly and safely on invalid data, provider errors, or stale signals.
13. Do not invent confirmation, entry/exit, or unsupported data rules.
14. Do not claim a model edge without enough resolved live outcomes.
15. Prevent look-ahead in predictions, reflection, and memory retrieval; never send a forming candle.
16. Never trust model-claimed evidence counts; compute them from stored records.
17. Code stays clean: no unnecessary comments, no pseudo-code; comments only where they matter.
18. No hardcoded values: tunables live in `config/settings.yaml`, secrets in the environment, and the cBot's constants in one block.
19. Ingest replies immediately; model calls never block the cBot.

## Work process for each task
State the intended small change; inspect related files; implement only that; run available tests/lint/type checks; report files changed, checks run, results, and unresolved assumptions. Do not proceed to unrelated stages without direction.

## First Copilot task
Inspect the repository and the existing cBot project and report:
1. project structure and stack;
2. existing cTrader/cBot, model API, market-data, and persistence code, and which cTrader indicators are available ;
3. the smallest implementation plan for Stage 1 in `02_IMPLEMENTATION_PLAN.md`;
4. concrete blockers or decisions needed before coding.

Do not write the whole application in one pass.
