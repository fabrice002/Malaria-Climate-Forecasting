"""
FastAPI application entrypoint for the Malaria Early Warning System.

Wires together the routers, loads the model bundle once at startup, creates the
database tables, and seeds the districts table from district_static.csv so the
skeleton is runnable immediately.

Run locally:
    uvicorn app.main:app --reload
Then open http://localhost:8000/docs for the interactive API.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.base import init_db, SessionLocal
from app.models.orm import District
from app.routers import climate, districts, mlops, predictions
from app.schemas.prediction import HealthStatus
from app.services.inference import bundle


def seed_districts():
    """Populate the districts table from the bundle's district_static.csv."""
    if bundle.district_static is None:
        return
    db = SessionLocal()
    try:
        if db.query(District).count() > 0:
            return
        for _, r in bundle.district_static.iterrows():
            db.add(District(
                name=r["district"], region=r["region"],
                shp_lat=float(r["SHP_lat"]), shp_lon=float(r["SHP_lon"]),
                shp_area=float(r["SHP_Area"]), cluster=int(r["cluster"]),
                population=int(r["p_totale"]), threshold_75=float(r["threshold_75"]),
            ))
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    bundle.load()
    # Importing the MLOps ORM registers its tables on the shared Base, so
    # init_db() creates them alongside the application tables.
    from app.mlops import orm as mlops_orm  # noqa: F401
    init_db()
    seed_districts()

    # Autonomous trigger. Disabled by default; enable with
    # MEWS_SCHEDULER_ENABLED=true. Never blocks startup if unavailable.
    from app.mlops.scheduler import start_scheduler, stop_scheduler
    start_scheduler()

    yield

    stop_scheduler()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Operational malaria early-warning API (binary Low/High risk).",
    lifespan=lifespan,
)

# CORS so the React dashboard can call the API in development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],         # tighten to the dashboard origin in production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(districts.router, prefix=settings.api_prefix)
app.include_router(predictions.router, prefix=settings.api_prefix)
app.include_router(climate.router, prefix=settings.api_prefix)
app.include_router(mlops.router, prefix=settings.api_prefix)


@app.get(settings.api_prefix + "/health", response_model=HealthStatus, tags=["system"])
def health():
    return HealthStatus(
        app_version=settings.app_version,
        models_loaded=bundle.is_loaded,
        n_districts=bundle.n_districts,
        recursive_chain_enabled=settings.enable_recursive_chain,
    )
