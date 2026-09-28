"""
Pydantic schemas — the API contract.

These define exactly what the API accepts and returns. The risk classification
is BINARY (Low / High), matching the trained model whose target is
`high = incidence_rate > 75th percentile per region`.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────────────
class RiskLevel(str, Enum):
    """Binary malaria risk, matching the trained classifier."""
    LOW = "Low"
    HIGH = "High"


class ModelUsed(str, Enum):
    """Which model in the two-stage chain produced a given month's prediction."""
    NOLAG = "NO-LAG"   # bootstrap: climate only, no case history
    LAG = "LAG"        # recursive: uses (real or synthetic) case lags


class ImpactDirection(str, Enum):
    INCREASE = "Increase"
    DECREASE = "Decrease"


# ── Incoming sensor data ─────────────────────────────────────────────────────
class SensorReading(BaseModel):
    """One month of environmental measurements for one district."""
    district: str = Field(..., examples=["Mbalmayo"])
    year: int = Field(..., ge=2018, le=2100, examples=[2026])
    month: int = Field(..., ge=1, le=12, examples=[4])

    temperature_c: float = Field(..., examples=[24.1])
    humidity_pct: float = Field(..., ge=0, le=100, examples=[71.2])
    pressure_hpa: float = Field(..., examples=[915.4])
    precipitation_mm: float = Field(..., ge=0, examples=[142.0])

    # Optional ground-truth cases (when a health report is available).
    # If provided, this overrides the synthetic lag in the recursive chain.
    real_cases: Optional[float] = Field(
        default=None, ge=0,
        description="Reported confirmed cases for this month, if known."
    )


class SensorBatch(BaseModel):
    """A time-ordered sequence of monthly readings for one district."""
    readings: List[SensorReading] = Field(..., min_length=1)


# ── SHAP explanation ─────────────────────────────────────────────────────────
class ShapContribution(BaseModel):
    feature: str = Field(..., examples=["Humidity_pct"])
    value: float = Field(..., examples=[71.17])
    shap_value: float = Field(..., examples=[0.34])
    impact: ImpactDirection = Field(..., examples=["Increase"])


class ShapExplanation(BaseModel):
    base_value: float = Field(..., description="Model expected value (baseline).")
    contributions: List[ShapContribution]
    text_summary: str = Field(
        ...,
        description="Plain-language summary of the main drivers.",
        examples=[
            "High humidity (+0.34) and optimal temperature (+0.28) increased "
            "the predicted risk, while low rainfall (-0.07) slightly reduced it."
        ],
    )


# ── Prediction output ────────────────────────────────────────────────────────
class MonthlyPrediction(BaseModel):
    # Row id of THIS month, so the dashboard can request its SHAP explanation
    # via /prediction/{id}/shap. Every month in a chain has its own id.
    prediction_id: int
    month_index: int = Field(..., description="1-based position in the chain.")
    year: int
    month: int

    predicted_cases: int = Field(..., description="Expected confirmed cases.")
    predicted_incidence: float = Field(..., description="Cases per 1 000 pop.")
    risk_level: RiskLevel
    risk_probability: float = Field(..., ge=0, le=1)

    model_used: ModelUsed
    threshold: float = Field(..., description="Region 75th-pct incidence threshold.")


class PredictionResponse(BaseModel):
    prediction_id: int
    district: str
    region: str
    population: int
    created_at: datetime
    months: List[MonthlyPrediction]


# ── Stored-record read models ────────────────────────────────────────────────
class PredictionSummary(BaseModel):
    prediction_id: int
    district: str
    region: str
    created_at: datetime
    n_months: int
    max_risk: RiskLevel


class HealthStatus(BaseModel):
    status: str = "ok"
    app_version: str
    models_loaded: bool
    n_districts: int
    recursive_chain_enabled: bool
