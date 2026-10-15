import secrets
from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query

from .config import Settings
from .ingest import IngestError, ordered_timeframes
from .memory import PRIMARY
from .models import IngestRequest
from .repository import Repository, Scope
from .signals import SignalService


def create_app(settings: Settings, repo: Repository, service: SignalService, api_key: str) -> FastAPI:
    app = FastAPI(title="AI Forex Signal Backend")

    def require_key(x_api_key: str | None = Header(default=None)) -> None:
        if not x_api_key or not secrets.compare_digest(x_api_key, api_key):
            raise HTTPException(status_code=401, detail="invalid api key")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/ingest", status_code=202, dependencies=[Depends(require_key)])
    def ingest(req: IngestRequest, background: BackgroundTasks) -> dict:
        try:
            tickets = service.submit(req)
        except IngestError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        for ticket in tickets:
            if ticket.created:
                background.add_task(service.process, ticket, req)
        return {"run_id": tickets[0].run_id, "duplicate": not tickets[0].created}

    @app.get("/runs/{run_id}", dependencies=[Depends(require_key)])
    def get_run(run_id: int) -> dict:
        run = repo.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return run

    @app.get("/signals/latest", dependencies=[Depends(require_key)])
    def latest(
        timeframes: str = Query(description="comma separated, e.g. M5,M15,H1"),
        model: str = Query(),
        context_version: str = Query(),
        instrument: str | None = None,
    ) -> dict:
        codes = [code.strip() for code in timeframes.split(",")]
        if len(codes) != 3 or len(set(codes)) != 3 or any(code not in settings.timeframes for code in codes):
            raise HTTPException(status_code=422, detail="exactly 3 distinct allowed timeframes are required")
        if settings.model(model) is None or context_version not in settings.context_versions:
            raise HTTPException(status_code=422, detail="unknown model or context version")
        ordered = ordered_timeframes(codes, settings)
        scope = Scope(instrument or settings.instrument, ",".join(ordered), context_version, model)
        last = repo.last_ingest_at(scope)
        now = datetime.now(timezone.utc)
        limit = timedelta(minutes=settings.timeframes[ordered[0]] * settings.stale_after_intervals)
        return {
            "signals": repo.active_signals(scope, PRIMARY),
            "latest": repo.latest_signal(scope, PRIMARY),
            "last_ingest_at": last,
            "stale": last is None or now - last > limit,
            "server_time": now,
        }

    return app
