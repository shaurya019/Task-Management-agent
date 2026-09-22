"""Central settings.  Loads .env into os.environ FIRST so that libraries which read
the environment directly (OpenAI, Langfuse) see the values too."""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from pydantic_settings import BaseSettings, SettingsConfigDict  # noqa: E402


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── service ──
    db_backend: str = "mongo"            # "sqlite" | "mongo"
    sqlite_path: str = "./tasks.db"
    mongo_uri: str = "mongodb://localhost:27017/?replicaSet=rs0"
    mongo_db: str = "task_agent"
    mongo_use_transactions: bool = True
    max_tasks_per_user: int = 200

    # ── agent ──
    api_base_url: str = "http://127.0.0.1:8000"
    agent_token: str = "token-alice"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    agent_run_store: str = "none"          # "none" | "mongo"  (persist agent runs to MongoDB)


def get_settings() -> Settings:
    return Settings()
