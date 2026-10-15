import os

import httpx

from .config import load_secrets, load_settings
from .lifecycle import Lifecycle
from .llm import StructuredLLM
from .main import create_app
from .memory import MemoryService
from .provider import OpenRouterProvider
from .repository import Repository
from .signals import SignalService

settings = load_settings(os.environ.get("CONFIG_PATH", "config/settings.yaml"))
secrets = load_secrets()
repository = Repository(secrets.database_url)
repository.migrate(os.environ.get("MIGRATIONS_DIR", "backend/migrations"))
provider = OpenRouterProvider(secrets.openrouter_api_key, settings.openrouter, httpx.Client())
llm = StructuredLLM(provider, repository, settings)
service = SignalService(repository, llm, Lifecycle(repository, settings), MemoryService(repository, llm, settings), settings)
app = create_app(settings, repository, service, secrets.ingest_api_key)
