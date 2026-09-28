"""
Orchestrator — chains the stages and records every execution.

    Collection -> Validation -> Features -> Prediction -> Storage

Three principles:

1. **Every stage is timed and logged.** A run leaves a complete trace in the
   database, including when it fails: that is what makes the pipeline observable
   rather than merely automatic.
2. **Validation is blocking.** A critical failure stops the run before the model.
   Better not to predict than to predict on doubtful data.
3. **Idempotence.** Replaying a run over the same window replaces the
   corresponding predictions instead of duplicating them.
"""

from __future__ import annotations

import json
import time
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum

import numpy as np
import pandas as pd

from app.mlops.sources.base import get_source
from app.mlops.stages import features as feat
from app.mlops.stages.validation import validate_climate
from app.utils import utc_now


class RunStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"          # nothing new to process
    VALIDATION_FAILED = "validation_failed"


@dataclass
class StageResult:
    name: str
    ok: bool
    duration_s: float
    detail: dict = field(default_factory=dict)
    error: str | None = None

    def __post_init__(self) -> None:
        # As in `validation.Check`: neutralise numpy scalars before they reach
        # JSON serialisation.
        self.ok = bool(self.ok)
        self.duration_s = float(self.duration_s)


@dataclass
class PipelineRun:
    """Complete trace of one execution."""

    trigger: str                      # scheduler | api | manual | backfill
    started_at: datetime = field(default_factory=utc_now)
    finished_at: datetime | None = None
    status: RunStatus = RunStatus.SUCCESS
    stages: list[StageResult] = field(default_factory=list)
    districts: list[str] = field(default_factory=list)
    n_predictions: int = 0
    source: str = ""
    error: str | None = None

    @property
    def duration_s(self) -> float:
        end = self.finished_at or utc_now()
        return (end - self.started_at).total_seconds()

    def stage(self, name: str) -> StageResult | None:
        return next((s for s in self.stages if s.name == name), None)

    def to_dict(self) -> dict:
        return {
            "trigger": self.trigger,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_s": round(self.duration_s, 2),
            "status": self.status.value,
            "source": self.source,
            "n_districts": len(self.districts),
            "n_predictions": self.n_predictions,
            "error": self.error,
            "stages": [{"name": s.name, "ok": s.ok,
                        "duration_s": round(s.duration_s, 2),
                        "detail": s.detail, "error": s.error} for s in self.stages],
        }


class Pipeline:
    """The end-to-end autonomous pipeline.

    Deliberately decoupled from the database: `run()` returns the results and the
    trace, and the caller (`app.mlops.service`) persists them. That keeps the
    pipeline testable without a database.
    """

    def __init__(self, bundle, static: pd.DataFrame,
                 source_name: str = "open_meteo",
                 source_kwargs: dict | None = None) -> None:
        self.bundle = bundle
        self.static = static
        self.source_name = source_name
        self.source_kwargs = source_kwargs or {}

    # ── Execution ───────────────────────────────────────────────────────────
    def run(self, districts: list[str] | None = None,
            start: date | None = None, end: date | None = None,
            trigger: str = "manual",
            lookback_months: int = 6) -> tuple[PipelineRun, pd.DataFrame]:
        """Run the full pipeline.

        `lookback_months` sets how much history is collected: at least 3 are
        needed for the first usable month's climate lags to exist.
        """
        run = PipelineRun(trigger=trigger, source=self.source_name)

        end = end or date.today()
        start = start or (end - timedelta(days=31 * max(lookback_months, 3)))

        targets = self._targets(districts)
        run.districts = targets["district"].tolist()

        predictions = pd.DataFrame()
        try:
            daily = self._stage_ingest(run, targets, start, end)
            if daily is None:
                return run, predictions

            if not self._stage_validate(run, daily, set(targets["district"])):
                return run, predictions

            frame = self._stage_features(run, daily)
            if frame is None or frame.empty:
                return run, predictions

            predictions = self._stage_predict(run, frame)
            run.n_predictions = len(predictions)

        except Exception as exc:                           # noqa: BLE001
            run.status = RunStatus.FAILED
            run.error = f"{type(exc).__name__}: {exc}"
            run.stages.append(StageResult(
                "unexpected", False, 0.0, error=traceback.format_exc()[-1500:]))

        run.finished_at = utc_now()
        return run, predictions

    # ── Stages ──────────────────────────────────────────────────────────────
    def _targets(self, districts: list[str] | None) -> pd.DataFrame:
        """Districts to process, with real geographic coordinates.

        ⚠️ `SHP_lat`/`SHP_lon` are transposed in the static file. They are put
        back the right way round **here only**, because a weather API expects
        real coordinates. The features keep the training convention
        (see `stages/features.py`).
        """
        s = self.static
        if districts:
            s = s[s["district"].isin(districts)]
        return pd.DataFrame({
            "district": s["district"].values,
            "lat": s["SHP_lon"].values,      # deliberate swap
            "lon": s["SHP_lat"].values,
        })

    def _stage_ingest(self, run: PipelineRun, targets: pd.DataFrame,
                      start: date, end: date) -> pd.DataFrame | None:
        t0 = time.time()
        try:
            source = get_source(self.source_name, **self.source_kwargs)
            result = source.fetch_many(targets, start, end)
            run.stages.append(StageResult(
                "ingestion", result.ok, time.time() - t0,
                detail={"source": result.source_name, "rows": result.n_rows,
                        "districts": result.n_districts,
                        "failures": len(result.failures),
                        "window": f"{start} -> {end}"}))
            if not result.ok:
                run.status = RunStatus.SKIPPED
                run.error = "no data collected"
                return None
            return result.frame
        except Exception as exc:                           # noqa: BLE001
            run.stages.append(StageResult("ingestion", False, time.time() - t0,
                                          error=str(exc)[:500]))
            run.status = RunStatus.FAILED
            run.error = f"ingestion: {exc}"
            return None

    def _stage_validate(self, run: PipelineRun, daily: pd.DataFrame,
                        expected: set[str]) -> bool:
        t0 = time.time()
        report = validate_climate(daily, expected_districts=expected)
        run.stages.append(StageResult(
            "validation", report.passed, time.time() - t0,
            detail=report.to_dict()))
        if not report.passed:
            run.status = RunStatus.VALIDATION_FAILED
            run.error = "; ".join(
                f"{c.name}: {c.detail}" for c in report.failures
                if c.severity.value == "critical")[:500]
            return False
        return True

    def _stage_features(self, run: PipelineRun,
                        daily: pd.DataFrame) -> pd.DataFrame | None:
        t0 = time.time()
        try:
            frame = feat.build_feature_frame(daily, self.static)
            scorable = feat.scorable_rows(frame)
            run.stages.append(StageResult(
                "features", not scorable.empty, time.time() - t0,
                detail={"months_built": len(frame),
                        "months_scorable": len(scorable),
                        "districts": int(scorable["district"].nunique())
                        if not scorable.empty else 0}))
            return scorable
        except Exception as exc:                           # noqa: BLE001
            run.stages.append(StageResult("features", False, time.time() - t0,
                                          error=str(exc)[:500]))
            run.status = RunStatus.FAILED
            run.error = f"features: {exc}"
            return None

    def _stage_predict(self, run: PipelineRun, frame: pd.DataFrame) -> pd.DataFrame:
        """Score with the NO-LAG model.

        NO-LAG rather than LAG: the automated pipeline runs without any reported
        case history. As soon as a district reports real cases, the API switches
        to the recursive chain (`services/inference.predict_chain`).
        """
        t0 = time.time()
        X = frame[feat.FEAT_NOLAG]

        log_cases = self.bundle.regressor_nolag.predict(X)
        proba = self.bundle.classifier_nolag.predict_proba(X)[:, 1]

        out = frame[["district", "region", "year", "month", "date",
                     "p_totale", "threshold_75"]].copy()
        out["predicted_cases"] = np.expm1(log_cases).round().astype(int)
        out["predicted_incidence"] = (out["predicted_cases"]
                                      / out["p_totale"] * 1000).round(2)
        out["risk_probability"] = proba.round(4)
        out["risk_level"] = np.where(
            out["predicted_incidence"] > out["threshold_75"], "High", "Low")
        out["model_used"] = "NO-LAG"
        out["feature_json"] = [json.dumps(r) for r in
                               X.round(6).to_dict("records")]

        run.stages.append(StageResult(
            "prediction", True, time.time() - t0,
            detail={"predictions": len(out),
                    "high": int((out["risk_level"] == "High").sum()),
                    "mean_incidence": float(out["predicted_incidence"].mean())}))
        return out
