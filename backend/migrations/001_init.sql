create table if not exists inference_runs (
  id bigserial primary key,
  idempotency_key text not null unique,
  instrument text not null,
  timeframe_set text not null,
  context_version text not null,
  model_key text not null,
  mode text not null,
  trigger_time timestamptz not null,
  status text not null default 'QUEUED' check (status in ('QUEUED', 'DONE', 'FAILED')),
  signal_id bigint,
  error text,
  created_at timestamptz not null default now(),
  finished_at timestamptz
);

create table if not exists candles (
  instrument text not null,
  timeframe text not null,
  open_time timestamptz not null,
  close_time timestamptz not null,
  open double precision not null,
  high double precision not null,
  low double precision not null,
  close double precision not null,
  primary key (instrument, timeframe, open_time)
);

create table if not exists signals (
  id bigserial primary key,
  run_id bigint not null references inference_runs (id),
  instrument text not null,
  timeframe_set text not null,
  context_version text not null,
  model_key text not null,
  openrouter_id text not null,
  mode text not null,
  prediction_time timestamptz not null,
  direction text not null check (direction in ('BUY', 'SELL', 'NONE')),
  zone_low double precision,
  zone_high double precision,
  entry_price double precision,
  rationale text not null default '',
  confidence double precision,
  pending_reviews jsonb not null default '[]',
  lesson_ids bigint[] not null default '{}',
  prompt_config_version text not null,
  source_candle_times jsonb not null,
  context_pack jsonb,
  created_at timestamptz not null default now()
);
create index if not exists signals_scope on signals (instrument, timeframe_set, context_version, model_key, mode, prediction_time desc);

create or replace function forbid_signal_update() returns trigger as $$
begin
  raise exception 'signals are immutable';
end;
$$ language plpgsql;

drop trigger if exists signals_immutable on signals;
create trigger signals_immutable before update on signals for each row execute function forbid_signal_update();

create table if not exists confirmations (
  signal_id bigint primary key references signals (id),
  status text not null check (status in ('PENDING', 'CONFIRMED', 'REJECTED')),
  confirmed_at timestamptz,
  ended_at timestamptz,
  ended_reason text
);

create table if not exists outcomes (
  id bigserial primary key,
  signal_id bigint not null unique references signals (id),
  exit_signal_id bigint not null references signals (id),
  entry_price double precision not null,
  exit_price double precision not null,
  confirmed_at timestamptz not null,
  exit_time timestamptz not null,
  signed_move double precision not null,
  mfe double precision not null,
  mae double precision not null,
  duration_seconds double precision not null,
  is_mistake boolean not null,
  evaluator_version text not null,
  resolved_at timestamptz not null,
  reflected_at timestamptz
);

create table if not exists lessons (
  id bigserial primary key,
  instrument text not null,
  timeframe_set text not null,
  context_version text not null,
  model_key text not null,
  status text not null check (status in ('CANDIDATE', 'VALIDATED', 'REJECTED', 'RETIRED')),
  origin_signal_id bigint not null references signals (id),
  observed_fact text not null,
  hypothesis text not null,
  candidate_lesson text not null,
  conditions text not null,
  cited_signal_ids bigint[] not null default '{}',
  model_confidence double precision not null,
  created_at timestamptz not null,
  validated_at timestamptz,
  last_judged_at timestamptz
);
create index if not exists lessons_scope on lessons (instrument, timeframe_set, context_version, model_key, status);

create table if not exists lesson_verdicts (
  id bigserial primary key,
  lesson_id bigint not null references lessons (id),
  verdict text not null,
  model_confidence double precision not null,
  reasoning text not null,
  verified_right integer not null,
  verified_wrong integer not null,
  evidence_signal_ids bigint[] not null default '{}',
  judged_at timestamptz not null
);

create table if not exists model_calls (
  id bigserial primary key,
  purpose text not null,
  model_key text not null,
  openrouter_id text not null,
  tokens_in integer,
  tokens_out integer,
  cost double precision,
  ok boolean not null,
  created_at timestamptz not null default now()
);
create index if not exists model_calls_day on model_calls (created_at);
