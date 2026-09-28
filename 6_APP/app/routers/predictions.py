"""
API routers — prediction, sensor ingestion, history, and SHAP endpoints.

Endpoints (under the configured prefix, default /api/v1):
  POST /sensor-data           ingest a batch of raw readings
  POST /predict               run the chain and persist predictions
  GET  /predictions           list recent prediction runs
  GET  /prediction/{id}       full detail for one run
  GET  /prediction/{id}/shap  SHAP explanation for one run's months
  GET  /history               per-district prediction history
"""

import json
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.models.orm import (
    District, RawSensorData, EngineeredFeatures, Prediction, ShapExplanationRow
)
from app.schemas.prediction import (
    SensorBatch, PredictionResponse, MonthlyPrediction, PredictionSummary,
    ShapExplanation, RiskLevel, ModelUsed,
)
from app.services.inference import bundle
from app.services import explain as explain_svc

from app.utils import utc_now

router = APIRouter()


# ── Sensor ingestion ─────────────────────────────────────────────────────────
@router.post("/sensor-data", status_code=201)
def ingest_sensor_data(batch: SensorBatch, db: Session = Depends(get_db)):
    """Store raw measurements exactly as received (before any processing)."""
    stored = 0
    for r in batch.readings:
        district = db.query(District).filter(District.name == r.district).first()
        if district is None:
            raise HTTPException(404, f"Unknown district: {r.district}")
        db.add(RawSensorData(
            district_id=district.id, year=r.year, month=r.month,
            temperature_c=r.temperature_c, humidity_pct=r.humidity_pct,
            pressure_hpa=r.pressure_hpa, precipitation_mm=r.precipitation_mm,
            real_cases=r.real_cases, source="iot",
        ))
        stored += 1
    db.commit()
    return {"stored": stored}


# ── Prediction ───────────────────────────────────────────────────────────────
@router.post("/predict", response_model=PredictionResponse)
def predict(batch: SensorBatch, db: Session = Depends(get_db)):
    """Run the two-stage recursive chain for one district and persist results."""
    district_name = batch.readings[0].district
    if any(r.district != district_name for r in batch.readings):
        raise HTTPException(400, "All readings in a /predict call must be the same district.")

    district = db.query(District).filter(District.name == district_name).first()
    if district is None:
        raise HTTPException(404, f"Unknown district: {district_name}")

    readings = [r.model_dump() for r in batch.readings]
    try:
        chain = bundle.predict_chain(district_name, readings)
    except KeyError as e:
        raise HTTPException(404, str(e))

    created = utc_now()
    months: List[MonthlyPrediction] = []
    for res in chain:
        pred = Prediction(
            district_id=district.id, created_at=created,
            year=res["year"], month=res["month"], month_index=res["month_index"],
            predicted_cases=res["predicted_cases"],
            predicted_incidence=res["predicted_incidence"],
            risk_level=res["risk_level"], risk_probability=res["risk_probability"],
            model_used=res["model_used"], threshold=res["threshold"],
        )
        db.add(pred)
        db.flush()  # get pred.id

        db.add(EngineeredFeatures(
            prediction_id=pred.id,
            feature_json=json.dumps(res["_feature_row"]),
            feature_set=res["_feature_set"],
        ))
        months.append(MonthlyPrediction(
            prediction_id=pred.id,
            month_index=res["month_index"], year=res["year"], month=res["month"],
            predicted_cases=res["predicted_cases"],
            predicted_incidence=res["predicted_incidence"],
            risk_level=RiskLevel(res["risk_level"]),
            risk_probability=res["risk_probability"],
            model_used=ModelUsed(res["model_used"]), threshold=res["threshold"],
        ))
    db.commit()

    # The run is identified by its FIRST month, so the id is stable and
    # /prediction/{id} returns the same chain regardless of which month is used.
    months.sort(key=lambda m: m.month_index)

    return PredictionResponse(
        prediction_id=months[0].prediction_id,
        district=district.name, region=district.region,
        population=district.population, created_at=created, months=months,
    )


@router.get("/predictions", response_model=List[PredictionSummary])
def list_predictions(limit: int = 20, db: Session = Depends(get_db)):
    """List recent prediction runs (grouped by district + timestamp)."""
    rows = (db.query(Prediction)
            .order_by(Prediction.created_at.desc())
            .limit(limit * 12).all())
    seen = {}
    for p in rows:
        key = (p.district_id, p.created_at)
        seen.setdefault(key, []).append(p)
    out = []
    for (did, ts), preds in list(seen.items())[:limit]:
        district = db.query(District).get(did)
        max_risk = "High" if any(p.risk_level == "High" for p in preds) else "Low"
        out.append(PredictionSummary(
            prediction_id=preds[0].id, district=district.name, region=district.region,
            created_at=ts, n_months=len(preds), max_risk=RiskLevel(max_risk),
        ))
    return out


@router.get("/predictions/latest", tags=["predictions"])
def latest_per_district(region: str | None = None, db: Session = Depends(get_db)):
    """Most recent prediction for every district that has one.

    This is what the map consumes. Recomputing 197 districts in the browser would
    mean 197 POST /predict calls; instead the MLOps pipeline scores them in the
    background and the dashboard reads the stored result.

    Districts never scored are returned with `has_prediction: false` so the map
    can still place them, greyed out.
    """
    districts = db.query(District)
    if region:
        districts = districts.filter(District.region == region)
    districts = districts.order_by(District.region, District.name).all()

    # One query for the whole set, then pick the newest row per district —
    # cheaper than a correlated subquery per district on SQLite.
    rows = (db.query(Prediction)
            .order_by(Prediction.created_at.desc(),
                      Prediction.year.desc(), Prediction.month.desc())
            .all())
    newest: dict[int, Prediction] = {}
    for p in rows:
        newest.setdefault(p.district_id, p)

    out = []
    for d in districts:
        p = newest.get(d.id)
        out.append({
            "district": d.name,
            "region": d.region,
            # SHP_lat / SHP_lon are transposed in the source file; corrected here
            # so the map receives real WGS84 coordinates.
            "lat": d.shp_lon,
            "lon": d.shp_lat,
            "population": d.population,
            "threshold": d.threshold_75,
            "has_prediction": p is not None,
            "prediction_id": p.id if p else None,
            "year": p.year if p else None,
            "month": p.month if p else None,
            "predicted_cases": p.predicted_cases if p else None,
            "predicted_incidence": p.predicted_incidence if p else None,
            "risk_level": p.risk_level if p else None,
            "risk_probability": p.risk_probability if p else None,
            "model_used": p.model_used if p else None,
        })
    return out


@router.get("/prediction/{prediction_id}", response_model=PredictionResponse)
def get_prediction(prediction_id: int, db: Session = Depends(get_db)):
    """Full detail for the run that the given prediction id belongs to."""
    anchor = db.query(Prediction).get(prediction_id)
    if anchor is None:
        raise HTTPException(404, "Prediction not found.")
    district = db.query(District).get(anchor.district_id)
    preds = (db.query(Prediction)
             .filter(Prediction.district_id == anchor.district_id,
                     Prediction.created_at == anchor.created_at)
             .order_by(Prediction.month_index).all())
    months = [MonthlyPrediction(
        prediction_id=p.id,
        month_index=p.month_index, year=p.year, month=p.month,
        predicted_cases=p.predicted_cases, predicted_incidence=p.predicted_incidence,
        risk_level=RiskLevel(p.risk_level), risk_probability=p.risk_probability,
        model_used=ModelUsed(p.model_used), threshold=p.threshold,
    ) for p in preds]
    return PredictionResponse(
        prediction_id=months[0].prediction_id if months else anchor.id,
        district=district.name, region=district.region,
        population=district.population, created_at=anchor.created_at, months=months,
    )


@router.get("/prediction/{prediction_id}/shap", response_model=ShapExplanation)
def get_shap(prediction_id: int, model_kind: str = "classifier",
             db: Session = Depends(get_db)):
    """SHAP explanation for a single prediction month."""
    pred = db.query(Prediction).get(prediction_id)
    if pred is None:
        raise HTTPException(404, "Prediction not found.")
    feats = db.query(EngineeredFeatures).filter(
        EngineeredFeatures.prediction_id == prediction_id).first()
    if feats is None:
        raise HTTPException(404, "No stored feature vector for this prediction.")

    expl = explain_svc.explain(
        feature_row=json.loads(feats.feature_json),
        feature_set=feats.feature_set,
        model_kind=model_kind,
    )

    # Persist SHAP rows (idempotent-ish: only if none stored yet)
    existing = db.query(ShapExplanationRow).filter(
        ShapExplanationRow.prediction_id == prediction_id,
        ShapExplanationRow.model_kind == model_kind).count()
    if existing == 0:
        for rank, c in enumerate(expl["contributions"], 1):
            db.add(ShapExplanationRow(
                prediction_id=prediction_id, model_kind=model_kind,
                base_value=expl["base_value"], feature=c["feature"],
                value=c["value"], shap_value=c["shap_value"],
                impact=c["impact"], rank=rank,
            ))
        db.commit()

    return ShapExplanation(**expl)


@router.get("/history")
def history(district: str, db: Session = Depends(get_db)):
    """Chronological prediction history for one district (for trend charts)."""
    d = db.query(District).filter(District.name == district).first()
    if d is None:
        raise HTTPException(404, f"Unknown district: {district}")
    preds = (db.query(Prediction)
             .filter(Prediction.district_id == d.id)
             .order_by(Prediction.year, Prediction.month).all())
    return [{
        "year": p.year, "month": p.month,
        "predicted_cases": p.predicted_cases,
        "predicted_incidence": p.predicted_incidence,
        "risk_level": p.risk_level, "model_used": p.model_used,
    } for p in preds]
