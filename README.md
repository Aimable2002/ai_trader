# AI Forex Signal System (V1)

A hosted LLM reads three timeframes of XAUUSD (candles plus SMA, EMA, ATR, RSI) the way a discretionary trader does, and returns a setup with a confirmation entry. A Python cBot in cTrader sends the data and displays the signals. The system learns from its own mistakes through model-judged, system-verified lessons. No trades are placed and no model is trained.

## Layout
- `backend/app`: FastAPI service (ingest, inference, lifecycle, reflection and memory, repository over Postgres/Supabase).
- `backend/migrations`: SQL schema.
- `config/settings.yaml`: every tunable value. `config/prompts/`: the four prompts.
- `cbot/`: Python cBot, generated C# parameter stub, smoke test.
- `tests/`: 138 tests (real Postgres 16 via `pgserver`, scripted fake model, stand-in for the cTrader API).
- `scripts/local_e2e.py`: runs the real backend process against local Postgres and a local stand-in for OpenRouter.
- `docs/`: the specification (v4).

## Run the tests
```
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest
python scripts/local_e2e.py
```

## Deploy the backend
Set the environment variables from `.env.example` (`OPENROUTER_API_KEY`, `DATABASE_URL` = your Supabase Postgres connection string, `INGEST_API_KEY`). Use Supabase's direct or session-pooler connection string. Then build the `Dockerfile` on any host that gives you a public HTTPS URL. Migrations run on startup.

## Set up the cBot
1. In cTrader Algo, create a new Python cBot and compare the generated `.cs` file with `cbot/AiForexSignal.cs` (regenerate it with `python cbot/generate_stubs.py` after editing the model list).
2. Run `cbot/smoke_test.py` first. Its log should show `GET /health -> 200` and `POST /ingest -> 422`.
3. Install `ai_forex_signal.py`, attach it to a chart of the smallest timeframe you will use, choose the three timeframes and the model, and enter the backend URL and API key.

## Configuration
Everything tunable is in `config/settings.yaml`: model allowlist (OpenRouter ids), timeframes, context versions, lessons per call, validation cadence, daily call cap, kill switch, shadow mode. The cBot keeps its own constants in one block at the top of `ai_forex_signal.py`; a test checks they match the backend.

## What is verified and what is not
Verified by tests: contract and pack validation, point-in-time rules, idempotency, confirmation, outcomes, reflection, verified-count validation, memory scoping, budget and kill switch, shadow mode, the OpenRouter HTTP client (mocked transport and a local stand-in), SQL against real Postgres, immutability, and the cBot's pure logic including its wire format against the backend validator.

Not verified, because it cannot run outside your environment:
- The cBot inside cTrader: the `.cs` stub shape, `Headers.Add` for `Content-Type`, `Timer`, `Chart` drawing calls and `Http.Send` details. Run the smoke test first.
- Real OpenRouter calls. Structured output is enabled only for DeepSeek V4.1 Flash; the others rely on the prompt, JSON extraction and one retry.
- Supabase itself (tested on local Postgres 16).

Known limits:
- Background runs live in the web process. If it restarts mid-run, that run stays `QUEUED`; the next trigger proceeds normally.
- The default cap of 400 model calls a day covers a single M5 trigger (about 280 inference calls) plus learning calls. Raise it before turning shadow mode on, which doubles the calls.
- Lesson validation is slow by nature: it needs resolved live trades, and overlapping same-direction trades are flagged as not independent.
