from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

SIGNAL_COLUMNS = (
    "s.id, s.run_id, s.instrument, s.timeframe_set, s.context_version, s.model_key, s.mode, s.prediction_time, "
    "s.direction, s.zone_low, s.zone_high, s.entry_price, s.rationale, s.confidence, s.lesson_ids"
)

SIGNAL_INSERT_FIELDS = (
    "run_id", "instrument", "timeframe_set", "context_version", "model_key", "openrouter_id", "mode",
    "prediction_time", "direction", "zone_low", "zone_high", "entry_price", "rationale", "confidence",
    "pending_reviews", "lesson_ids", "prompt_config_version", "source_candle_times", "context_pack",
)
JSON_FIELDS = {"pending_reviews", "source_candle_times", "context_pack"}

LESSON_INSERT_FIELDS = (
    "instrument", "timeframe_set", "context_version", "model_key", "status", "origin_signal_id", "observed_fact",
    "hypothesis", "candidate_lesson", "conditions", "cited_signal_ids", "model_confidence", "created_at",
)

OUTCOME_INSERT_FIELDS = (
    "signal_id", "exit_signal_id", "entry_price", "exit_price", "confirmed_at", "exit_time", "signed_move",
    "mfe", "mae", "duration_seconds", "is_mistake", "evaluator_version", "resolved_at",
)

SCOPE_FILTER = "s.instrument = %s and s.timeframe_set = %s and s.context_version = %s and s.model_key = %s and s.mode = %s"

CASE_COLUMNS = (
    "o.signal_id as id, s.direction, o.entry_price, o.exit_price, o.signed_move, o.mfe, o.mae, "
    "o.exit_signal_id, o.confirmed_at, o.resolved_at, s.rationale"
)


@dataclass(frozen=True)
class Scope:
    instrument: str
    timeframe_set: str
    context_version: str
    model_key: str

    @property
    def smallest_timeframe(self) -> str:
        return self.timeframe_set.split(",")[0]

    def params(self, mode: str) -> tuple:
        return (self.instrument, self.timeframe_set, self.context_version, self.model_key, mode)


class Repository:
    def __init__(self, database_url: str, max_size: int = 5):
        self._pool = ConnectionPool(
            database_url,
            min_size=1,
            max_size=max_size,
            kwargs={"row_factory": dict_row, "autocommit": True, "prepare_threshold": None},
            open=True,
        )

    def close(self) -> None:
        self._pool.close()

    def migrate(self, directory: str | Path) -> None:
        with self._pool.connection() as conn:
            conn.execute("create table if not exists schema_migrations (name text primary key)")
            done = {row["name"] for row in conn.execute("select name from schema_migrations").fetchall()}
            for path in sorted(Path(directory).glob("*.sql")):
                if path.name not in done:
                    conn.execute(path.read_text())
                    conn.execute("insert into schema_migrations (name) values (%s)", (path.name,))

    def _all(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._pool.connection() as conn:
            return conn.execute(sql, params).fetchall()

    def _one(self, sql: str, params: tuple = ()) -> dict | None:
        with self._pool.connection() as conn:
            return conn.execute(sql, params).fetchone()

    def _run(self, sql: str, params: tuple = ()) -> int:
        with self._pool.connection() as conn:
            return conn.execute(sql, params).rowcount

    def create_run(self, key: str, scope: Scope, mode: str, trigger_time: datetime) -> tuple[int, bool]:
        row = self._one(
            "insert into inference_runs (idempotency_key, instrument, timeframe_set, context_version, model_key, mode, trigger_time) "
            "values (%s, %s, %s, %s, %s, %s, %s) on conflict (idempotency_key) do nothing returning id",
            (key, scope.instrument, scope.timeframe_set, scope.context_version, scope.model_key, mode, trigger_time),
        )
        if row:
            return row["id"], True
        existing = self._one("select id from inference_runs where idempotency_key = %s", (key,))
        return existing["id"], False

    def get_run(self, run_id: int) -> dict | None:
        return self._one("select * from inference_runs where id = %s", (run_id,))

    def finish_run(self, run_id: int, status: str, signal_id: int | None = None, error: str | None = None) -> None:
        self._run(
            "update inference_runs set status = %s, signal_id = %s, error = %s, finished_at = now() where id = %s",
            (status, signal_id, error, run_id),
        )

    def last_ingest_at(self, scope: Scope) -> datetime | None:
        row = self._one(
            "select max(created_at) as at from inference_runs where instrument = %s and timeframe_set = %s "
            "and context_version = %s and model_key = %s and mode = 'primary'",
            (scope.instrument, scope.timeframe_set, scope.context_version, scope.model_key),
        )
        return row["at"] if row else None

    def upsert_candles(self, instrument: str, timeframe: str, candles) -> None:
        rows = [(instrument, timeframe, c.open_time, c.close_time, c.open, c.high, c.low, c.close) for c in candles]
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    "insert into candles (instrument, timeframe, open_time, close_time, open, high, low, close) "
                    "values (%s, %s, %s, %s, %s, %s, %s, %s) on conflict do nothing",
                    rows,
                )

    def candles_between(self, instrument: str, timeframe: str, start: datetime, end: datetime) -> list[dict]:
        return self._all(
            "select * from candles where instrument = %s and timeframe = %s and open_time >= %s and close_time <= %s "
            "order by open_time",
            (instrument, timeframe, start, end),
        )

    def insert_signal(self, row: dict, pending: bool) -> int:
        values = tuple(Jsonb(row[f]) if f in JSON_FIELDS and row[f] is not None else row[f] for f in SIGNAL_INSERT_FIELDS)
        marks = ", ".join(["%s"] * len(SIGNAL_INSERT_FIELDS))
        with self._pool.connection() as conn:
            with conn.transaction():
                signal_id = conn.execute(
                    f"insert into signals ({', '.join(SIGNAL_INSERT_FIELDS)}) values ({marks}) returning id", values
                ).fetchone()["id"]
                if pending:
                    conn.execute("insert into confirmations (signal_id, status) values (%s, 'PENDING')", (signal_id,))
        return signal_id

    def get_signal(self, signal_id: int) -> dict | None:
        return self._one(f"select {SIGNAL_COLUMNS} from signals s where s.id = %s", (signal_id,))

    def active_signals(self, scope: Scope, mode: str) -> list[dict]:
        return self._all(
            f"select {SIGNAL_COLUMNS}, c.status as lifecycle_status, c.confirmed_at from signals s "
            "join confirmations c on c.signal_id = s.id left join outcomes o on o.signal_id = s.id "
            f"where {SCOPE_FILTER} and c.status in ('PENDING', 'CONFIRMED') and o.id is null "
            "order by s.prediction_time, s.id",
            scope.params(mode),
        )

    def latest_signal(self, scope: Scope, mode: str) -> dict | None:
        return self._one(
            f"select {SIGNAL_COLUMNS}, coalesce(c.status, 'NONE') as lifecycle_status from signals s "
            f"left join confirmations c on c.signal_id = s.id where {SCOPE_FILTER} "
            "order by s.prediction_time desc, s.id desc limit 1",
            scope.params(mode),
        )

    def set_confirmed(self, signal_id: int, at: datetime) -> int:
        return self._run(
            "update confirmations set status = 'CONFIRMED', confirmed_at = %s where signal_id = %s and status = 'PENDING'",
            (at, signal_id),
        )

    def set_rejected(self, signal_id: int, at: datetime, reason: str) -> int:
        return self._run(
            "update confirmations set status = 'REJECTED', ended_at = %s, ended_reason = %s "
            "where signal_id = %s and status = 'PENDING'",
            (at, reason, signal_id),
        )

    def confirmed_unresolved(self, scope: Scope, mode: str, direction: str) -> list[dict]:
        return self._all(
            f"select {SIGNAL_COLUMNS}, c.confirmed_at from signals s join confirmations c on c.signal_id = s.id "
            f"left join outcomes o on o.signal_id = s.id where {SCOPE_FILTER} and c.status = 'CONFIRMED' "
            "and o.id is null and s.direction = %s order by s.prediction_time",
            scope.params(mode) + (direction,),
        )

    def insert_outcome(self, row: dict) -> int:
        marks = ", ".join(["%s"] * len(OUTCOME_INSERT_FIELDS))
        return self._one(
            f"insert into outcomes ({', '.join(OUTCOME_INSERT_FIELDS)}) values ({marks}) returning id",
            tuple(row[f] for f in OUTCOME_INSERT_FIELDS),
        )["id"]

    def unreflected_mistakes(self, scope: Scope, mode: str) -> list[dict]:
        return self._all(
            "select o.id as outcome_id, o.signal_id, o.entry_price, o.exit_price, o.signed_move, o.mfe, o.mae, "
            "o.exit_signal_id, o.confirmed_at, o.resolved_at, s.direction, s.zone_low, s.zone_high, s.rationale, "
            "s.prediction_time from outcomes o join signals s on s.id = o.signal_id "
            f"where {SCOPE_FILTER} and o.is_mistake and o.reflected_at is null order by o.resolved_at, o.id",
            scope.params(mode),
        )

    def mark_reflected(self, outcome_id: int, at: datetime) -> None:
        self._run("update outcomes set reflected_at = %s where id = %s", (at, outcome_id))

    def resolved_cases(
        self,
        scope: Scope,
        mode: str,
        direction: str | None = None,
        correct: bool | None = None,
        since: datetime | None = None,
        limit: int = 30,
    ) -> list[dict]:
        sql = f"select {CASE_COLUMNS} from outcomes o join signals s on s.id = o.signal_id where {SCOPE_FILTER}"
        params = scope.params(mode)
        if direction:
            sql += " and s.direction = %s"
            params += (direction,)
        if correct is True:
            sql += " and o.signed_move > 0"
        if correct is False:
            sql += " and o.signed_move < 0"
        if since is not None:
            sql += " and o.resolved_at > %s"
            params += (since,)
        return self._all(sql + " order by o.resolved_at desc, o.id desc limit %s", params + (limit,))

    def verify_cases(self, scope: Scope, mode: str, signal_ids: list[int]) -> list[dict]:
        if not signal_ids:
            return []
        return self._all(
            f"select {CASE_COLUMNS} from outcomes o join signals s on s.id = o.signal_id "
            f"where {SCOPE_FILTER} and o.signal_id = any(%s) order by o.signal_id",
            scope.params(mode) + (list(set(signal_ids)),),
        )

    def insert_lesson(self, row: dict) -> int:
        marks = ", ".join(["%s"] * len(LESSON_INSERT_FIELDS))
        return self._one(
            f"insert into lessons ({', '.join(LESSON_INSERT_FIELDS)}) values ({marks}) returning id",
            tuple(row[f] for f in LESSON_INSERT_FIELDS),
        )["id"]

    def get_lesson(self, lesson_id: int) -> dict | None:
        return self._one("select * from lessons where id = %s", (lesson_id,))

    def judgeable_lessons(self, scope: Scope) -> list[dict]:
        return self._all(
            "select * from lessons where instrument = %s and timeframe_set = %s and context_version = %s "
            "and model_key = %s and status in ('CANDIDATE', 'VALIDATED') order by id",
            (scope.instrument, scope.timeframe_set, scope.context_version, scope.model_key),
        )

    def validated_lessons(self, scope: Scope, before: datetime, limit: int) -> list[dict]:
        return self._all(
            "select * from lessons where instrument = %s and timeframe_set = %s and context_version = %s "
            "and model_key = %s and status = 'VALIDATED' and validated_at <= %s "
            "order by model_confidence desc, validated_at desc, id desc limit %s",
            (scope.instrument, scope.timeframe_set, scope.context_version, scope.model_key, before, limit),
        )

    def apply_verdict(self, lesson_id: int, status: str, validated_at: datetime | None, judged_at: datetime) -> None:
        self._run(
            "update lessons set status = %s, validated_at = coalesce(%s, validated_at), last_judged_at = %s where id = %s",
            (status, validated_at, judged_at, lesson_id),
        )

    def insert_verdict(self, row: dict) -> int:
        return self._one(
            "insert into lesson_verdicts (lesson_id, verdict, model_confidence, reasoning, verified_right, verified_wrong, "
            "evidence_signal_ids, judged_at) values (%s, %s, %s, %s, %s, %s, %s, %s) returning id",
            (
                row["lesson_id"], row["verdict"], row["model_confidence"], row["reasoning"],
                row["verified_right"], row["verified_wrong"], row["evidence_signal_ids"], row["judged_at"],
            ),
        )["id"]

    def verdicts_for(self, lesson_id: int) -> list[dict]:
        return self._all("select * from lesson_verdicts where lesson_id = %s order by id", (lesson_id,))

    def log_call(self, purpose, model_key, openrouter_id, tokens_in, tokens_out, cost, ok) -> None:
        self._run(
            "insert into model_calls (purpose, model_key, openrouter_id, tokens_in, tokens_out, cost, ok) "
            "values (%s, %s, %s, %s, %s, %s, %s)",
            (purpose, model_key, openrouter_id, tokens_in, tokens_out, cost, ok),
        )

    def calls_today(self) -> int:
        row = self._one(
            "select count(*) as n from model_calls where (created_at at time zone 'utc')::date = (now() at time zone 'utc')::date"
        )
        return row["n"]
