import hashlib
import logging
from dataclasses import dataclass

from .config import Settings
from .context import build_inference_messages
from .ingest import validate_pack
from .lifecycle import Lifecycle
from .llm import BudgetExceeded, OutputError, StructuredLLM
from .memory import PRIMARY, MemoryService
from .models import IngestRequest, ModelOutput
from .provider import ProviderError
from .repository import Repository, Scope

SHADOW = "shadow_memory_off"
logger = logging.getLogger(__name__)


class OutputRejected(Exception):
    pass


@dataclass(frozen=True)
class Ticket:
    run_id: int
    mode: str
    created: bool
    scope: Scope


def idempotency_key(settings: Settings, scope: Scope, mode: str, req: IngestRequest) -> str:
    parts = (
        scope.model_key, settings.inference.prompt_config_version, mode, scope.instrument,
        scope.timeframe_set, scope.context_version, req.trigger_candle_time.isoformat(),
    )
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def check_entry_distance(output: ModelOutput, last_close: float, max_pct: float) -> None:
    if output.setup_direction == "NONE":
        return
    levels = [output.setup_zone_low, output.setup_zone_high, output.confirmation_entry_price, output.stop_loss_price]
    if output.target_price is not None:
        levels.append(output.target_price)
    if any(abs(level - last_close) / last_close * 100 > max_pct for level in levels):
        raise OutputRejected(f"price levels are more than {max_pct}% away from the last close")


class SignalService:
    def __init__(self, repo: Repository, llm: StructuredLLM, lifecycle: Lifecycle, memory: MemoryService, settings: Settings):
        self._repo = repo
        self._llm = llm
        self._lifecycle = lifecycle
        self._memory = memory
        self._settings = settings

    def submit(self, req: IngestRequest) -> list[Ticket]:
        codes = validate_pack(req, self._settings)
        scope = Scope(req.instrument, ",".join(codes), req.context_version, req.model)
        smallest = next(pack for pack in req.timeframes if pack.timeframe == codes[0])
        self._repo.upsert_candles(req.instrument, codes[0], smallest.candles)
        if req.fine_candles is not None:
            self._repo.upsert_candles(req.instrument, req.fine_candles.timeframe, req.fine_candles.candles)
        modes = [PRIMARY, SHADOW] if self._settings.shadow_mode else [PRIMARY]
        tickets = []
        for mode in modes:
            key = idempotency_key(self._settings, scope, mode, req)
            run_id, created = self._repo.create_run(key, scope, mode, req.trigger_candle_time)
            tickets.append(Ticket(run_id, mode, created, scope))
        return tickets

    def process(self, ticket: Ticket, req: IngestRequest) -> None:
        try:
            signal_id = self._infer(ticket, req)
        except (BudgetExceeded, ProviderError, OutputError, OutputRejected) as exc:
            self._repo.finish_run(ticket.run_id, "FAILED", error=str(exc))
            return
        except Exception as exc:
            logger.exception("run %s failed", ticket.run_id)
            self._repo.finish_run(ticket.run_id, "FAILED", error=f"internal error: {exc}")
            return
        self._repo.finish_run(ticket.run_id, "DONE", signal_id=signal_id)
        if ticket.mode == PRIMARY:
            self._learn(ticket.scope, req)

    def _infer(self, ticket: Ticket, req: IngestRequest) -> int:
        scope, mode, at = ticket.scope, ticket.mode, req.trigger_candle_time
        codes = scope.timeframe_set.split(",")
        smallest = next(pack for pack in req.timeframes if pack.timeframe == codes[0])
        last_close = smallest.candles[-1].close
        self._lifecycle.advance(scope, mode, at)
        active = self._repo.active_signals(scope, mode)
        lessons = self._memory.retrieve(scope, at) if mode == PRIMARY else []
        messages = build_inference_messages(self._settings, req, codes, active, lessons)
        output = self._llm.ask("inference", scope.model_key, messages, ModelOutput)
        check_entry_distance(output, last_close, self._settings.inference.max_entry_distance_pct)
        self._lifecycle.apply_reviews(scope, mode, output.pending_reviews, at)
        signal_id = self._repo.insert_signal(self._signal_row(ticket, req, output, lessons), pending=output.setup_direction != "NONE")
        if output.setup_direction != "NONE":
            self._lifecycle.resolve_opposites(scope, mode, output.setup_direction, signal_id, at, last_close)
        return signal_id

    def _signal_row(self, ticket: Ticket, req: IngestRequest, output: ModelOutput, lessons: list[dict]) -> dict:
        scope = ticket.scope
        return {
            "run_id": ticket.run_id,
            "instrument": scope.instrument,
            "timeframe_set": scope.timeframe_set,
            "context_version": scope.context_version,
            "model_key": scope.model_key,
            "openrouter_id": self._settings.model(scope.model_key).openrouter_id,
            "mode": ticket.mode,
            "prediction_time": req.trigger_candle_time,
            "direction": output.setup_direction,
            "zone_low": output.setup_zone_low,
            "zone_high": output.setup_zone_high,
            "entry_price": output.confirmation_entry_price,
            "stop_loss": output.stop_loss_price,
            "target": output.target_price,
            "rationale": output.rationale,
            "confidence": output.confidence,
            "pending_reviews": [review.model_dump() for review in output.pending_reviews],
            "lesson_ids": [lesson["id"] for lesson in lessons],
            "prompt_config_version": self._settings.inference.prompt_config_version,
            "source_candle_times": {pack.timeframe: pack.candles[-1].close_time.isoformat() for pack in req.timeframes},
            "context_pack": req.model_dump(mode="json") if self._settings.inference.store_context_pack else None,
        }

    def _learn(self, scope: Scope, req: IngestRequest) -> None:
        try:
            self._memory.reflect_mistakes(scope, req.trigger_candle_time)
            self._memory.validate_due(scope, req.trigger_candle_time)
        except Exception:
            logger.exception("reflection or validation failed for %s", scope)
