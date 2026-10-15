import json
import os
import shutil
import sys
import tempfile
import threading
import time
from datetime import timedelta
from pathlib import Path

import httpx
import pgserver
import uvicorn
import yaml
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "tests")]
from helpers import T0, buy_output, make_request, none_output  # noqa: E402

SCRIPTED = [buy_output(entry=4001.0), none_output()]


def fake_openrouter(port: int) -> uvicorn.Server:
    app = FastAPI()
    seen = []

    @app.post("/api/v1/chat/completions")
    def completions(body: dict):
        seen.append(body)
        reply = SCRIPTED[min(len(seen) - 1, len(SCRIPTED) - 1)]
        return {"choices": [{"message": {"content": json.dumps(reply)}}], "usage": {"prompt_tokens": 1000, "completion_tokens": 80, "cost": 0.01}}

    server = uvicorn.Server(uvicorn.Config(app, port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    return server


def wait_for(url: str) -> None:
    for _ in range(100):
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.1)
    raise RuntimeError(f"{url} did not start")


def main() -> None:
    database = pgserver.get_server(tempfile.mkdtemp())
    config_dir = Path(tempfile.mkdtemp()) / "config"
    shutil.copytree(ROOT / "config", config_dir)
    settings = yaml.safe_load((config_dir / "settings.yaml").read_text())
    settings["openrouter"]["base_url"] = "http://127.0.0.1:8791/api/v1"
    (config_dir / "settings.yaml").write_text(yaml.safe_dump(settings))
    os.environ.update(
        OPENROUTER_API_KEY="test-key", DATABASE_URL=database.get_uri(), INGEST_API_KEY="k",
        CONFIG_PATH=str(config_dir / "settings.yaml"), MIGRATIONS_DIR=str(ROOT / "backend" / "migrations"),
    )
    fake_openrouter(8791)
    from app.asgi import app

    backend = uvicorn.Server(uvicorn.Config(app, port=8790, log_level="warning"))
    threading.Thread(target=backend.run, daemon=True).start()
    wait_for("http://127.0.0.1:8790/health")
    headers = {"X-API-Key": "k", "Content-Type": "application/json"}
    query = {"timeframes": "M5,M15,H1", "model": "Sonnet55", "context_version": "v1"}
    first = httpx.post("http://127.0.0.1:8790/ingest", content=make_request(T0).model_dump_json(), headers=headers)
    second = httpx.post("http://127.0.0.1:8790/ingest", content=make_request(T0 + timedelta(minutes=5), last_candle=(4000.5, 4002.0, 3999.0, 4001.5)).model_dump_json(), headers=headers)
    time.sleep(1)
    signals = httpx.get("http://127.0.0.1:8790/signals/latest", params=query, headers=headers).json()
    print("ingest:", first.status_code, first.json(), "|", second.status_code, second.json())
    print("active:", [(s["direction"], s["lifecycle_status"], s["entry_price"]) for s in signals["signals"]], "stale:", signals["stale"])
    backend.should_exit = True
    database.cleanup()


if __name__ == "__main__":
    main()
