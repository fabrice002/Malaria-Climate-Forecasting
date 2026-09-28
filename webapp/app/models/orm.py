"""
SQLAlchemy ORM models — the database schema.

Six tables matching the thesis design:
  districts          — fixed geography, population, regional threshold
  raw_sensor_data    — incoming environmental measurements as received
  engineered_features— the exact feature vector fed to the models
  predictions        — one row per district per forecast month
  shap_explanations  — per-feature SHAP contributions for each prediction
  users              — API/dashboard users

In production this targets PostgreSQL with the PostGIS extension; the geometry
column on `districts` is described in the migration notes. For the runnable
skeleton we use plain lat/lon floats so it also works on SQLite.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
)
from sqlalchemy.orm import relationship

from app.db.base import Base

from app.utils import utc_now


class District(Base):
    __tablename__ = "districts"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, index=True, nullable=False)
    region = Column(String, index=True, nullable=False)

    shp_lat = Column(Float, nullable=False)
    shp_lon = Column(Float, nullable=False)
    shp_area = Column(Float, nullable=False)
    cluster = Column(Integer, nullable=False)
    population = Column(Integer, nullable=False)

    # Per-region 75th-percentile incidence threshold used to derive Low/High.
    threshold_75 = Column(Float, nullable=False)

    # In PostGIS this becomes: geom = Column(Geometry("POINT", srid=4326))

    readings = relationship("RawSensorData", back_populates="district")
    predictions = relationship("Prediction", back_populates="district")


class RawSensorData(Base):
    __tablename__ = "raw_sensor_data"

    id = Column(Integer, primary_key=True)
    district_id = Column(Integer, ForeignKey("districts.id"), index=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)

    temperature_c = Column(Float)
    humidity_pct = Column(Float)
    pressure_hpa = Column(Float)
    precipitation_mm = Column(Float)
    real_cases = Column(Float, nullable=True)  # ground truth if available

    source = Column(String, default="iot")  # iot | weather_api | historical
    received_at = Column(DateTime(timezone=True), default=utc_now)

    district = relationship("District", back_populates="readings")


class EngineeredFeatures(Base):
    __tablename__ = "engineered_features"

    id = Column(Integer, primary_key=True)
    prediction_id = Column(Integer, ForeignKey("predictions.id"), index=True)
    # The full feature vector is stored as JSON text for traceability /
    # reproducibility (so any prediction can be re-explained later).
    feature_json = Column(Text, nullable=False)
    feature_set = Column(String)  # "nolag" or "lag"


class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True)
    district_id = Column(Integer, ForeignKey("districts.id"), index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, index=True)

    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    month_index = Column(Integer)  # position in the recursive chain

    predicted_cases = Column(Integer)
    predicted_incidence = Column(Float)
    risk_level = Column(String)            # "Low" | "High"
    risk_probability = Column(Float)
    model_used = Column(String)            # "NO-LAG" | "LAG"
    threshold = Column(Float)

    district = relationship("District", back_populates="predictions")
    shap = relationship("ShapExplanationRow", back_populates="prediction")


class ShapExplanationRow(Base):
    __tablename__ = "shap_explanations"

    id = Column(Integer, primary_key=True)
    prediction_id = Column(Integer, ForeignKey("predictions.id"), index=True)
    model_kind = Column(String)  # "regressor" | "classifier"

    base_value = Column(Float)
    feature = Column(String)
    value = Column(Float)
    shap_value = Column(Float)
    impact = Column(String)  # "Increase" | "Decrease"
    rank = Column(Integer)

    prediction = relationship("Prediction", back_populates="shap")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="viewer")  # viewer | analyst | admin
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
