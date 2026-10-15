# 05 — Outcome Evaluation

## Purpose
Measure whether setups and confirmation entries carry useful information, using real subsequent price action. Direction accuracy alone and profitability alone are not acceptance criteria.

## Versioned evaluator configuration
Define and version: the confirmation check (price reaches the model's entry level; candle granularity used), how a signal ends, handling of overlapping signals, the definition of a mistake, and any spread/cost assumption if net figures are reported.

## Lifecycle
Signals are tracked within one scope: instrument, timeframe set, context version and model.
1. `BUY`/`SELL` signal → `PENDING`.
2. Price reaches `confirmation_entry_price` on a later candle → `CONFIRMED` (`confirmed_at` recorded).
3. The model invalidates it through `pending_reviews` → `REJECTED`. A rejected setup is **not** counted as wrong: no entry ever happened. It stays a distinct record and feeds the confirmation-rate metric.
4. A pending setup has no other end. A newer signal does not expire it. Report the age of long-pending setups so they don't silently skew confirmation rate.

## Outcome (CONFIRMED signals only)
- Entry price = the signal's confirmation entry.
- The trade ends when the **next opposite-direction BUY/SELL signal arrives** (its `prediction_time`). `NONE` does not end it.
- Exit reference price = close of the smallest-timeframe candle that triggered the opposite signal.
- Result = signed price move in the signal's direction (points), plus maximum favorable and adverse excursion during the window and its duration.
- Unresolved (still open) records are distinct from failures.
- There is no SL/TP in the system, so there is no stop/target ambiguity. The operator's own stop is outside the system.

## Overlapping signals
A same-direction signal that arrives while one is CONFIRMED is still delivered and has its own lifecycle (its own pending/confirmed state and outcome). It does not end the existing trade. Several confirmed signals can therefore share the same exit. They are not independent samples: report per-signal results, and also flag the groups that share an exit so statistics are not overstated.

## Metrics (always with sample counts)
Total signals; BUY/SELL vs NONE coverage; confirmation rate (confirmed vs rejected, pending reported separately with ages); resolved confirmed count; share with positive signed move; mean/median signed move; MFE/MAE; duration; breakdowns by timeframe set, context version, session, or condition only when sample size supports them; uncertainty intervals where feasible. Results are computed from observed price data, not account P&L; disclose any spread/cost assumption.

## Shadow mode (optional, off by default)
On each trigger, run two configurations on the same candles and persist both with their `mode`: memory off vs memory on, or two context versions. Display only the configured primary. Both are tracked through confirmation and outcome by the same evaluator. It doubles API calls, so it is a deliberate switch. Compare on the same live period with counts, API cost, and uncertainty. If there is no reliable difference, say so.

## Honesty rules
- Never claim an edge without enough resolved live outcomes; report small samples as inconclusive.
- Do not write lessons from outcomes and then count those same outcomes as independent validation (see 06).
