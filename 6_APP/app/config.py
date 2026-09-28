"""
Application configuration.

Centralises all settings (paths, database URL, model bundle location) so they
can be overridden by environment variables in production without touching code.
"""

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Application ──────────────────────────────────────────────────────────
    app_name: str = "Malaria Early Warning System"
    app_version: str = "1.0.0"
    api_prefix: str = "/api/v1"

    # ── Model bundle (produced by malaria_deployment.ipynb) ─────────────────
    # Directory containing:
    #   regressor_nolag.joblib, regressor_lag.joblib,
    #   classifier_nolag.joblib, classifier_lag.joblib,
    #   district_static.csv, artifacts.json
    bundle_dir: Path = Path(__file__).resolve().parent.parent / "deployment_bundle"

    # ── Database ─────────────────────────────────────────────────────────────
    # PostgreSQL + PostGIS in production; SQLite fallback for local dev/testing.
    database_url: str = "sqlite:///./malaria.db"
    # Example production value:
    #   postgresql+psycopg://user:pass@host:5432/malaria

    # ── Inference ────────────────────────────────────────────────────────────
    # When True, the LAG model runs recursively (feeding its own predictions
    # back as case lags). When real case counts are supplied they always
    # override the synthetic lag regardless of this flag.
    enable_recursive_chain: bool = True

    class Config:
        env_file = ".env"
        env_prefix = "MEWS_"  # e.g. MEWS_DATABASE_URL=...


settings = Settings()
