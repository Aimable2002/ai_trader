import json
import tempfile
from pathlib import Path

import psycopg
import pgserver
import pytest

from app.config import load_settings
from app.lifecycle import Lifecycle
from app.llm import StructuredLLM
from app.memory import MemoryService
from app.provider import ProviderResult
from app.repository import Repository
from app.signals import SignalService

ROOT = Path(__file__).resolve().parents[1]


class FakeProvider:
    def __init__(self):
        self.queue = []
        self.calls = []

    def push(self, item):
        self.queue.append(item if isinstance(item, (str, Exception)) else json.dumps(item))

    def complete(self, model_id, messages, schema=None):
        self.calls.append({"model_id": model_id, "messages": messages, "schema": schema})
        if not self.queue:
            raise AssertionError("unexpected model call")
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return ProviderResult(item, 100, 50, 0.001)


@pytest.fixture(scope="session")
def pg_uri():
    server = pgserver.get_server(tempfile.mkdtemp())
    yield server.get_uri()
    server.cleanup()


@pytest.fixture
def settings():
    return load_settings(ROOT / "config" / "settings.yaml")


@pytest.fixture
def repo(pg_uri):
    with psycopg.connect(pg_uri, autocommit=True) as conn:
        conn.execute("drop schema public cascade")
        conn.execute("create schema public")
    repository = Repository(pg_uri)
    repository.migrate(ROOT / "backend" / "migrations")
    yield repository
    repository.close()


@pytest.fixture
def provider():
    return FakeProvider()


@pytest.fixture
def llm(provider, repo, settings):
    return StructuredLLM(provider, repo, settings)


@pytest.fixture
def lifecycle(repo, settings):
    return Lifecycle(repo, settings)


@pytest.fixture
def memory(repo, llm, settings):
    return MemoryService(repo, llm, settings)


@pytest.fixture
def service(repo, llm, lifecycle, memory, settings):
    return SignalService(repo, llm, lifecycle, memory, settings)
