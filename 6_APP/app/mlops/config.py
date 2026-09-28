"""
MLOps configuration.

Everything environment-dependent lives here, overridable through an environment
variable prefixed `MEWS_`. Changing the data source therefore needs no code
change at all:

    MEWS_CLIMATE_SOURCE=nasa_power
    MEWS_CLIMATE_SOURCE=csv MEWS_CSV_SOURCE_PATH=/data/iot_dumps
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings


class MLOpsSettings(BaseSettings):
    # ── Data source ─────────────────────────────────────────────────────────
    #: registered source name: open_meteo | nasa_power | csv
    climate_source: str = "open_meteo"

    #: directory or file used when climate_source == "csv"
    csv_source_path: Path = Path("./data/incoming")

    #: how much history each run collects (>= 3 for the climate lags)
    lookback_months: int = 6

    # ── Scheduling ──────────────────────────────────────────────────────────
    #: enables the autonomous trigger at application startup
    scheduler_enabled: bool = False

    #: cron for the main run — by default the 2nd of each month at 03:00, which
    #: gives the ERA5 reanalysis time to publish the month just ended
    schedule_cron: str = "0 3 2 * *"

    #: districts processed automatically; empty = every district in the bundle
    scheduled_districts: str = ""

    # ── Quality and drift ───────────────────────────────────────────────────
    #: maximum share of missing values tolerated per variable
    max_null_rate: float = 0.05

    #: PSI above which drift is considered major
    psi_major_threshold: float = 0.25

    #: error-degradation factor that raises a concept-drift alert
    perf_drift_tolerance: float = 1.5

    #: number of months in the recent window for the performance comparison
    perf_drift_window: int = 6

    # ── Retraining ──────────────────────────────────────────────────────────
    #: propose a retrain as soon as major drift is detected
    retrain_on_major_drift: bool = True

    #: minimum months of ground truth required before any retrain
    retrain_min_new_months: int = 12

    # ── Model registry ──────────────────────────────────────────────────────
    registry_dir: Path = Path(__file__).resolve().parent.parent.parent / "model_registry"

    class Config:
        env_file = ".env"
        env_prefix = "MEWS_"


mlops_settings = MLOpsSettings()


def source_kwargs() -> dict:
    """Constructor arguments specific to the configured source."""
    if mlops_settings.climate_source == "csv":
        return {"path": mlops_settings.csv_source_path}
    return {}
