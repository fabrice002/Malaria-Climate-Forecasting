"""
MLOps traceability tables.

These complement the existing application schema (`app/models/orm.py`) without
modifying it. Three needs:

* `pipeline_runs`  — what ran, when, for how long, with what outcome;
* `data_quality`   — each run's validation report;
* `drift_reports`  — drift measurements over time.

Without these tables the pipeline would be automated but blind: no way to say
why an alert fired three months ago, nor whether that day's data was sound.
"""

from datetime import datetime

from sqlalchemy import (Boolean, Column, DateTime, Float, ForeignKey, Integer,
                        String, Text)
from sqlalchemy.orm import relationship

from app.db.base import Base

from app.utils import utc_now


class PipelineRun(Base):
    """One pipeline execution, successful or not."""

    __tablename__ = "pipeline_runs"

    id = Column(Integer, primary_key=True)
    trigger = Column(String, index=True)        # scheduler | api | manual | backfill
    source = Column(String)                     # open_meteo | nasa_power | csv

    started_at = Column(DateTime(timezone=True), default=utc_now, index=True)
    finished_at = Column(DateTime(timezone=True))
    duration_s = Column(Float)

    status = Column(String, index=True)         # success | failed | skipped | validation_failed
    n_districts = Column(Integer, default=0)
    n_predictions = Column(Integer, default=0)
    error = Column(Text)

    # Per-stage durations, as JSON — records execution times without
    # multiplying columns.
    stages_json = Column(Text)

    quality = relationship("DataQualityReport", back_populates="run")
    drift = relationship("DriftReport", back_populates="run")


class DataQualityReport(Base):
    """Validation report attached to a run."""

    __tablename__ = "data_quality"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("pipeline_runs.id"), index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    passed = Column(Boolean, index=True)
    n_rows = Column(Integer)
    n_districts = Column(Integer)
    n_checks = Column(Integer)
    n_failed = Column(Integer)
    checks_json = Column(Text)                  # full detail

    run = relationship("PipelineRun", back_populates="quality")


class DriftReport(Base):
    """A drift measurement — data or performance."""

    __tablename__ = "drift_reports"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("pipeline_runs.id"), index=True, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, index=True)

    kind = Column(String, index=True)           # data | performance
    feature = Column(String, index=True)        # feature name, or "__global__"

    psi = Column(Float)
    ks_stat = Column(Float)
    ks_pvalue = Column(Float)
    mean_ref = Column(Float)
    mean_new = Column(Float)
    severity = Column(String, index=True)       # stable | minor | major | degraded

    detail_json = Column(Text)

    run = relationship("PipelineRun", back_populates="drift")


class ModelVersion(Base):
    """Model registry — which artifact produced which prediction."""

    __tablename__ = "model_versions"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, index=True)

    name = Column(String, index=True)           # regressor_nolag, classifier_lag, …
    version = Column(String, index=True)        # timestamp or semantic tag
    stage = Column(String, default="production", index=True)  # production | staging | archived

    algorithm = Column(String)                  # XGBRegressor, …
    target = Column(String)                     # log_cases | log_incidence | high
    n_features = Column(Integer)
    feature_list_json = Column(Text)

    #: metrics recorded at training time (KFold, TimeSeriesSplit, ...)
    metrics_json = Column(Text)

    #: file digest, to detect an artifact swapped out silently
    artifact_path = Column(String)
    artifact_sha256 = Column(String)

    notes = Column(Text)
