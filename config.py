"""
Application settings — loaded once from .env at import time.

All modules import the singleton `settings` object:
    from config import settings
"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).parent.resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- API keys ---
    openrouter_api_key: str = ""
    openrouter_model: str = "meta-llama/llama-3.1-8b-instruct:free"

    # --- Storage ---
    duckdb_path: str = str(ROOT_DIR / "data" / "truescout.duckdb")
    parquet_bronze_dir: str = str(ROOT_DIR / "data" / "bronze")
    parquet_silver_dir: str = str(ROOT_DIR / "data" / "silver")
    parquet_gold_dir: str = str(ROOT_DIR / "data" / "gold")

    # --- Ingestion endpoints ---
    # www.sofascore.com is the same-origin host as our Referer/Origin headers;
    # api.sofascore.com is cross-origin and Cloudflare fakes 404s for it.
    sofascore_base_url: str = "https://www.sofascore.com/api/v1"
    sofascore_fallback_url: str = "https://api.sofascore.app/api/v1"
    espn_soccer_base_url: str = "https://site.api.espn.com/apis/site/v2/sports/soccer"
    espn_core_base_url: str = "https://sports.core.api.espn.com/v2/sports/soccer"

    # --- Modeling ---
    mc_iterations: int = 10_000
    # Players below this threshold → "data_sparse" → Traditional Scout LLM voice
    confidence_score_threshold: float = 0.4
    # Narrative routing: >= this value → Data Analyst voice; below → Traditional Scout
    narrative_confidence_threshold: float = 0.7

    # --- Server ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    debug: bool = False

    # --- CORS (JSON array in .env: '["http://localhost:3000"]') ---
    allowed_origins: list[str] = [
        "http://localhost:3000",  # Next.js dev server
        "http://localhost:3001",  # staging preview
    ]


settings = Settings()
