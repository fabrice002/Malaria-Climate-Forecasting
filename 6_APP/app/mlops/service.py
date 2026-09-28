"""
MLOps service — the bridge between the pipeline and the database.

The orchestrator knows nothing about the database; this module handles
persistence, drift detection, and reading the indicators the dashboard needs.
That separation is what lets the pipeline be tested without a database.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy.orm import Session

from app.config import settings
from app.db.base import SessionLocal
from app.mlops.config import mlops_settings, source_kwargs
from app.mlops.monitoring.drift import detect_data_drift, detect_performance_drift
from app.mlops.orchestrator import Pipeline, PipelineRun, RunStatus
from app.mlops.stages import features as feat
from app.models.orm import District, EngineeredFeatures, Prediction
from app.mlops.orm import DataQualityReport
from app.mlops.orm import DriftReport as DriftRow
from app.mlops.orm import PipelineRun as RunRow
from app.services.inference import bundle

from app.utils import utc_now


# ── Full execution ───────────────────────────────────────────────────────────
def run_pipeline(districts: list[str] | None = None,
                 trigger: str = "manual",
                 start=None, end=None,
                 persist: bool = True) -> dict:
    """Run the pipeline and persist everything it produces."""
    if not bundle.is_loaded:
        bundle.load()

    pipe = Pipeline(bundle=bundle, static=bundle.district_static,
                    source_name=mlops_settings.climate_source,
                    source_kwargs=source_kwargs())

    run, preds = pipe.run(districts=districts, start=start, end=end,
                          trigger=trigger,
                          lookback_months=mlops_settings.lookback_months)

    if not persist:
        return {"run": run.to_dict(), "predictions": len(preds)}

    db = SessionLocal()
    try:
        run_row = _persist_run(db, run)
        if not preds.empty:
            _persist_predictions(db, preds)
            _persist_drift(db, run_row.id, preds)
        db.commit()
        return {"run_id": run_row.id, **run.to_dict()}
    finally:
        db.close()


# ── Persistence ──────────────────────────────────────────────────────────────
def _persist_run(db: Session, run: PipelineRun) -> RunRow:
    row = RunRow(
        trigger=run.trigger, source=run.source,
        started_at=run.started_at, finished_at=run.finished_at,
        duration_s=run.duration_s, status=run.status.value,
        n_districts=len(run.districts), n_predictions=run.n_predictions,
        error=run.error,
        stages_json=json.dumps([{"name": s.name, "ok": s.ok,
                                 "duration_s": round(s.duration_s, 3),
                                 "detail": s.detail, "error": s.error}
                                for s in run.stages], default=str),
    )
    db.add(row)
    db.flush()

    val = run.stage("validation")
    if val and val.detail:
        d = val.detail
        checks = d.get("checks", [])
        db.add(DataQualityReport(
            run_id=row.id, passed=bool(d.get("passed")),
            n_rows=d.get("n_rows"), n_districts=d.get("n_districts"),
            n_checks=len(checks),
            n_failed=sum(1 for c in checks if not c.get("passed")),
            checks_json=json.dumps(checks, default=str)))
    return row


def _persist_predictions(db: Session, preds: pd.DataFrame) -> None:
    """Write the predictions, replacing any for the same district-month.

    Replaying a run must not stack duplicates: for a given window, the latest
    execution is authoritative.
    """
    created = utc_now()
    by_name = {d.name: d for d in db.query(District).all()}

    for r in preds.itertuples():
        district = by_name.get(r.district)
        if district is None:
            continue

        db.query(Prediction).filter(
            Prediction.district_id == district.id,
            Prediction.year == int(r.year),
            Prediction.month == int(r.month),
        ).delete(synchronize_session=False)

        p = Prediction(
            district_id=district.id, created_at=created,
            year=int(r.year), month=int(r.month), month_index=1,
            predicted_cases=int(r.predicted_cases),
            predicted_incidence=float(r.predicted_incidence),
            risk_level=r.risk_level,
            risk_probability=float(r.risk_probability),
            model_used=r.model_used, threshold=float(r.threshold_75),
        )
        db.add(p)
        db.flush()
        db.add(EngineeredFeatures(prediction_id=p.id,
                                  feature_json=r.feature_json,
                                  feature_set="nolag"))


def _persist_drift(db: Session, run_id: int, preds: pd.DataFrame) -> None:
    """Compare this run's features against the training distribution.

    Only **dynamic** features are monitored. Geography (`SHP_lat`, `SHP_lon`,
    `SHP_Area`, `cluster`) is constant per district: its PSI would only reflect
    which subset of districts was processed — a run covering two districts would
    raise "major drift" every time, without any data having changed.
    """
    ref = _training_reference()
    if ref is None or preds.empty:
        return

    new = pd.DataFrame([json.loads(s) for s in preds["feature_json"]])
    report = detect_data_drift(ref, new, feat.DYNAMIC_FEATURES)

    for m in report.metrics:
        db.add(DriftRow(run_id=run_id, kind="data", feature=m.feature,
                        psi=m.psi, ks_stat=m.ks_stat, ks_pvalue=m.ks_pvalue,
                        mean_ref=m.mean_ref, mean_new=m.mean_new,
                        severity=m.severity))


_REF_CACHE: pd.DataFrame | None = None


def _training_reference() -> pd.DataFrame | None:
    """Reference distribution for drift comparison.

    The full training CSV is not shipped with the application, so the reference
    is rebuilt from it when present. If it is not, drift monitoring is skipped
    rather than computed against an approximation that would be misleading.
    """
    global _REF_CACHE
    if _REF_CACHE is not None:
        return _REF_CACHE

    candidates = [
        settings.bundle_dir.parent.parent / "1_DATA" / "cameroon_districts_climate.csv",
        settings.bundle_dir.parent / "cameroon_districts_climate.csv",
    ]
    for path in candidates:
        if path.exists():
            try:
                daily = pd.read_csv(path, parse_dates=["Date"])
                daily = daily.rename(columns={"Humidity_%": "Humidity_pct"})
                frame = feat.build_feature_frame(daily, bundle.district_static)
                _REF_CACHE = feat.scorable_rows(frame)[feat.FEAT_NOLAG]
                return _REF_CACHE
            except Exception:                              # noqa: BLE001
                continue
    return None


# ── Read paths for the dashboard ─────────────────────────────────────────────
def recent_runs(limit: int = 20) -> list[dict]:
    db = SessionLocal()
    try:
        rows = (db.query(RunRow).order_by(RunRow.started_at.desc())
                .limit(limit).all())
        return [{
            "id": r.id, "trigger": r.trigger, "source": r.source,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "duration_s": r.duration_s, "status": r.status,
            "n_districts": r.n_districts, "n_predictions": r.n_predictions,
            "error": r.error,
            "stages": json.loads(r.stages_json) if r.stages_json else [],
        } for r in rows]
    finally:
        db.close()


def pipeline_health(days: int = 30) -> dict:
    """Summary indicators for the monitoring page."""
    db = SessionLocal()
    try:
        since = utc_now() - timedelta(days=days)
        runs = db.query(RunRow).filter(RunRow.started_at >= since).all()
        if not runs:
            return {"window_days": days, "n_runs": 0}

        ok = [r for r in runs if r.status == RunStatus.SUCCESS.value]
        durations = [r.duration_s for r in runs if r.duration_s]

        stage_times: dict[str, list[float]] = {}
        for r in runs:
            for s in json.loads(r.stages_json or "[]"):
                stage_times.setdefault(s["name"], []).append(s.get("duration_s", 0))

        drift = (db.query(DriftRow)
                 .filter(DriftRow.created_at >= since,
                         DriftRow.severity == "majeure").all())

        return {
            "window_days": days,
            "n_runs": len(runs),
            "success_rate": round(len(ok) / len(runs), 3),
            "mean_duration_s": round(sum(durations) / len(durations), 2) if durations else None,
            "n_predictions": sum(r.n_predictions or 0 for r in runs),
            "failures": [{"id": r.id, "status": r.status, "error": r.error}
                         for r in runs if r.status != RunStatus.SUCCESS.value][:10],
            "stage_mean_duration_s": {k: round(sum(v) / len(v), 3)
                                      for k, v in stage_times.items()},
            "features_in_major_drift": sorted({d.feature for d in drift}),
            "last_run": max(r.started_at for r in runs).isoformat(),
        }
    finally:
        db.close()


def drift_history(feature: str | None = None, limit: int = 500) -> list[dict]:
    db = SessionLocal()
    try:
        q = db.query(DriftRow).order_by(DriftRow.created_at.desc())
        if feature:
            q = q.filter(DriftRow.feature == feature)
        return [{
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "run_id": d.run_id, "kind": d.kind, "feature": d.feature,
            "psi": d.psi, "severity": d.severity,
            "mean_ref": d.mean_ref, "mean_new": d.mean_new,
        } for d in q.limit(limit).all()]
    finally:
        db.close()


def performance_drift(district: str | None = None) -> dict:
    """Concept drift: compares predictions against real cases where they exist.

    Returns `insufficient` while too few months carry ground truth — the normal
    situation when the system starts up.
    """
    from app.models.orm import RawSensorData

    db = SessionLocal()
    try:
        q = (db.query(Prediction, RawSensorData)
             .join(District, Prediction.district_id == District.id)
             .join(RawSensorData,
                   (RawSensorData.district_id == Prediction.district_id)
                   & (RawSensorData.year == Prediction.year)
                   & (RawSensorData.month == Prediction.month))
             .filter(RawSensorData.real_cases.isnot(None)))
        if district:
            q = q.filter(District.name == district)

        rows = [{"date": datetime(p.year, p.month, 1),
                 "predicted": p.predicted_cases,
                 "actual": s.real_cases,
                 "abs_error": abs(p.predicted_cases - s.real_cases)}
                for p, s in q.all()]

        if len(rows) < 4:
            return {"status": "insufficient",
                    "detail": f"{len(rows)} months with ground truth",
                    "n": len(rows)}

        hist = pd.DataFrame(rows).sort_values("date")
        result = detect_performance_drift(
            hist, metric="abs_error",
            window=mlops_settings.perf_drift_window,
            tolerance=mlops_settings.perf_drift_tolerance)
        result["n"] = len(hist)
        result["mae_global"] = float(hist["abs_error"].mean())
        return result
    finally:
        db.close()
