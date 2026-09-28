"""
MLOps routes — driving and monitoring the pipeline.

Endpoints (prefix /api/v1):
  POST /mlops/run              start the pipeline (synchronous or background)
  GET  /mlops/runs             execution history
  GET  /mlops/health           pipeline health indicators
  GET  /mlops/drift            data-drift history
  GET  /mlops/drift/performance  performance drift (concept drift)
  GET  /mlops/sources          available data sources and the active one
  GET  /mlops/scheduler        scheduler state
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from app.mlops import service
from app.mlops.config import mlops_settings
from app.mlops.scheduler import scheduler_status
from app.mlops.sources.base import available_sources

router = APIRouter()


class RunRequest(BaseModel):
    districts: Optional[List[str]] = Field(
        default=None, description="Districts to process; empty = all.")
    start: Optional[date] = Field(
        default=None,
        description="Start of the collected window. Defaults to "
                    "`end` minus MEWS_LOOKBACK_MONTHS.")
    end: Optional[date] = Field(
        default=None, description="End of the window. Defaults to today.")
    background: bool = Field(
        default=False,
        description="Return immediately and run in the background.")


@router.post("/mlops/run", tags=["mlops"])
def trigger_run(req: RunRequest, background_tasks: BackgroundTasks):
    """Trigger the full pipeline.

    Without `start`/`end` the window is the last few months (nominal mode).
    Supplying them **replays a past period** (*backfill*): useful after a data
    correction, or to rebuild history. Replaying replaces the predictions for the
    same district-month instead of duplicating them.

    A nationwide run takes several minutes (the provider rate-limits collection);
    `background=true` is recommended beyond a handful of districts.
    """
    trigger = "backfill" if (req.start or req.end) else "api"

    if req.background:
        background_tasks.add_task(service.run_pipeline,
                                  districts=req.districts, trigger=trigger,
                                  start=req.start, end=req.end)
        return {"status": "accepted",
                "detail": "pipeline started in the background; "
                          "follow progress on GET /mlops/runs"}
    try:
        return service.run_pipeline(districts=req.districts, trigger=trigger,
                                    start=req.start, end=req.end)
    except Exception as exc:                               # noqa: BLE001
        raise HTTPException(500, f"pipeline failed: {exc}") from exc


@router.get("/mlops/runs", tags=["mlops"])
def list_runs(limit: int = Query(20, ge=1, le=200)):
    """Execution history, most recent first."""
    return service.recent_runs(limit=limit)


@router.get("/mlops/health", tags=["mlops"])
def health(days: int = Query(30, ge=1, le=365)):
    """Success rate, per-stage timings, currently major drifts."""
    return service.pipeline_health(days=days)


@router.get("/mlops/drift", tags=["mlops"])
def data_drift(feature: Optional[str] = None,
               limit: int = Query(500, ge=1, le=5000)):
    """Data-drift history (PSI and the Kolmogorov-Smirnov test)."""
    return service.drift_history(feature=feature, limit=limit)


@router.get("/mlops/drift/performance", tags=["mlops"])
def perf_drift(district: Optional[str] = None):
    """Performance drift, computed where ground truth is available."""
    return service.performance_drift(district=district)


@router.get("/mlops/sources", tags=["mlops"])
def sources():
    """Registered data sources and the currently active one.

    Switching source needs no code change: `MEWS_CLIMATE_SOURCE=<name>` on
    restart.
    """
    return {
        "active": mlops_settings.climate_source,
        "available": available_sources(),
        "lookback_months": mlops_settings.lookback_months,
        "csv_source_path": str(mlops_settings.csv_source_path),
    }


@router.get("/mlops/scheduler", tags=["mlops"])
def scheduler():
    """Scheduler state and the next scheduled executions."""
    return scheduler_status()
