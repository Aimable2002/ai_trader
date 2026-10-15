# AI Forex Indicator V1 — Copilot Development Pack (v4)

## Purpose
Build a research-first AI Forex indicator for XAUUSD. A hosted model reads three timeframes the way a human trader does (top-down), produces a **setup** and a **confirmation entry**, shows them in a cTrader cBot, and improves over time through evidence-backed reflection and persistent memory.

V1 is operated by a single operator (the owner). The system works on live candles supplied by the cBot, wherever that cBot runs. It does not know or care whether the account is live or demo. There is **no backtest, no replay, and no historical data loading** in the product. It is not a SaaS launch: no subscriptions, billing, customer accounts, tenant management, or marketing pages.

**Do not train, fine-tune, or change the weights of any model.** The model is reached through OpenRouter; the system does not care which model is configured. Improvement happens around the model: context, reflection, memory, validated system logic.

## Core pipeline
1. The cBot is configured by the operator with **exactly 3 timeframes** (default M5 / M15 / H1). When a candle closes on the **smallest** timeframe, the cBot sends one full context pack: completed candles and SMA, EMA, ATR and RSI series for all 3 timeframes, computed on the cBot, plus the context version and the model chosen in the cBot.
2. The backend validates the pack, adds the active signal state, retrieves validated lessons matching the current conditions, and builds the prompt. The model cannot request additional data; it receives the full context upfront.
3. The backend calls the configured model through a provider-neutral OpenRouter adapter.
4. The model returns a **setup** (direction + zone from support/resistance reading), a **confirmation entry** (the real entry level), and keep/invalidate decisions for any pending signals. It does NOT predict price and does NOT give SL/TP.
5. The output is schema-validated, persisted unchanged, and displayed by the cBot (display only, no trading).
6. The system tracks whether price reaches the confirmation entry (CONFIRMED). A pending setup ends only when the model invalidates it (REJECTED). A confirmed trade is resolved when the **next opposite signal** arrives. The trader exits on that signal and sets their own SL; the system never suggests one.
7. Mistakes are sent to the model for reflection; it proposes candidate lessons.
8. The model judges its own confidence in each lesson using system-verified evidence counts. Validated lessons are retrieved only under matching conditions (same instrument, timeframe set, context version).
9. Optionally, shadow mode runs two configurations (memory off vs on, or two context versions) on the same live candles to compare them.

## Settled decisions
- Pending setups end only by model invalidation.
- A same-direction signal while one is CONFIRMED is still delivered and has its own lifecycle; it does not end the existing trade.
- The only user setting is the 3 timeframes. Indicators are fixed by the platform as a versioned context version.
- Indicators are computed on the cBot with cTrader indicators. The backend does not recompute them.
- The forming (unfinished) candle is never sent.
- The cBot is written in Python. Timeframes and the model are predefined dropdowns in the cBot; the backend keeps an allowlist and rejects anything else.
- The model is part of the lesson scope: lessons match instrument, timeframe set, context version and model.
- Ingest replies immediately (202); the model runs in the background and the cBot polls for the signal.
- Heiken Ashi and multi-user support are postponed to a later version.
- Every tunable value lives in one config file; secrets live in the environment.

## Configuration
`config/settings.yaml` holds the model allowlist, timeframes, context versions (indicator periods, candle counts), lessons per call, validation cadence, daily call cap, kill switch, shadow mode and prompt versions. Prompts live in `config/prompts/`. The cBot keeps its own constants (context version, periods, candle counts) in one block at the top of its file; changing them means releasing a new cBot version.

## How Copilot should start
Inspect the repository and the existing cBot project first. Reuse existing conventions. Implement incrementally; each stage must be testable. Never claim an edge without enough resolved live outcomes.

## Reading order
1. `01_SYSTEM_SCOPE_AND_ARCHITECTURE.md`
2. `02_IMPLEMENTATION_PLAN.md`
3. `03_SIGNAL_AND_API_CONTRACTS.md`
4. `04_MARKET_DATA_AND_LIVE_FEED.md`
5. `05_OUTCOME_EVALUATION.md`
6. `06_REFLECTION_AND_MEMORY.md`
7. `07_CTRADER_INTEGRATION.md`
8. `08_TESTING_AND_ACCEPTANCE.md`
9. `09_COPILOT_RULES.md`

## V1 definition of done
The live path works end to end with exactly 3 configurable timeframes: context pack in, timestamped setup + confirmation entry out, outcomes resolved from real subsequent price action, reflection and model-judged memory operating, and memory-assisted behavior comparable with memory-off. No profitability guarantee is implied.
