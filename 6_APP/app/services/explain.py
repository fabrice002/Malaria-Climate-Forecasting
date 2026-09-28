"""
SHAP explanation service.

Computes per-feature SHAP contributions for a single prediction using a
TreeExplainer (fast and exact for the XGBoost models). Returns the contributions
ranked by absolute impact, plus a plain-language text summary for the dashboard.

The explainers are built lazily and cached, since constructing a TreeExplainer
is cheap but need not be repeated per request.
"""

from functools import lru_cache
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import shap
import xgboost as xgb

from app.services.inference import bundle


# Human-readable names for the text summary.
PRETTY = {
    "Humidity_pct": "humidity",
    "Temperature_C": "temperature",
    "Precipitation_mm": "rainfall",
    "Pressure_hPa": "pressure",
    "sin_month": "season", "cos_month": "season",
    "SHP_lat": "latitude", "SHP_lon": "longitude",
    "SHP_Area": "district area", "cluster": "ecological zone",
    "cases_lag1": "last month's cases",
    "rolling_mean_3m": "recent case trend",
}


def _model_for(model_kind: str, feature_set: str):
    """Pick the model matching the requested task and feature set."""
    if model_kind == "regressor":
        return bundle.regressor_lag if feature_set == "lag" else bundle.regressor_nolag
    return bundle.classifier_lag if feature_set == "lag" else bundle.classifier_nolag


@lru_cache(maxsize=4)
def _explainer(model_kind: str, feature_set: str):
    """Cached TreeExplainer, or None when this shap/xgboost pair is incompatible.

    shap <= 0.47 combined with xgboost >= 3.0 raises
    `ValueError: could not convert string to float: '[5E-1]'` because xgboost now
    serialises `base_score` as a one-element array while shap calls float() on it
    directly. We detect that once, cache the miss, and use the fallback below.
    """
    try:
        return shap.TreeExplainer(_model_for(model_kind, feature_set))
    except ValueError as err:
        if "could not convert string to float" not in str(err):
            raise
        return None


def _contributions(model_kind: str, feature_set: str,
                   X: pd.DataFrame) -> Tuple[np.ndarray, float]:
    """SHAP values and base value for a single-row feature frame.

    Falls back to xgboost's own `pred_contribs=True`, which runs the same
    TreeSHAP algorithm inside xgboost. Values are identical to float precision,
    so the explanation is exact either way.

    @returns (shap_values_for_row, base_value)
    """
    explainer = _explainer(model_kind, feature_set)
    if explainer is not None:
        sv = np.asarray(explainer.shap_values(X))
        row = sv[0] if sv.ndim == 2 else sv
        return row, float(np.ravel(explainer.expected_value)[0])

    model = _model_for(model_kind, feature_set)
    booster = model.get_booster()
    contrib = booster.predict(
        xgb.DMatrix(X, feature_names=list(X.columns)), pred_contribs=True
    )
    # Last column is the base value; the rest align with the feature columns.
    return contrib[0, :-1], float(contrib[0, -1])


def explain(feature_row: Dict[str, float], feature_set: str,
            model_kind: str = "classifier", top_k: int = 8) -> dict:
    """Compute SHAP contributions for one feature vector.

    feature_row : the exact dict used for the prediction
    feature_set : "lag" or "nolag"
    model_kind  : "classifier" or "regressor"
    """
    feats = bundle.feat_lag if feature_set == "lag" else bundle.feat_nolag
    X = pd.DataFrame([feature_row]).reindex(columns=feats)
    X = X.fillna(pd.Series(bundle.feat_medians))

    shap_row, base_value = _contributions(model_kind, feature_set, X)

    contribs = []
    for feat, val, sh in zip(feats, X.iloc[0].values, shap_row):
        contribs.append({
            "feature": feat,
            "value": round(float(val), 4),
            "shap_value": round(float(sh), 4),
            "impact": "Increase" if sh >= 0 else "Decrease",
        })
    contribs.sort(key=lambda c: abs(c["shap_value"]), reverse=True)
    top = contribs[:top_k]

    return {
        "base_value": round(base_value, 4),
        "contributions": top,
        "text_summary": _summarise(top),
    }


def _summarise(top: List[dict]) -> str:
    """Build a one-sentence natural-language explanation from top contributors."""
    ups = [c for c in top if c["impact"] == "Increase"][:2]
    downs = [c for c in top if c["impact"] == "Decrease"][:1]

    def phrase(c):
        name = PRETTY.get(c["feature"], c["feature"])
        sign = "+" if c["shap_value"] >= 0 else ""
        return f"{name} ({sign}{c['shap_value']:.2f})"

    parts = []
    if ups:
        parts.append(" and ".join(phrase(c) for c in ups) + " increased the predicted risk")
    if downs:
        parts.append(phrase(downs[0]) + " slightly reduced it")
    return ", while ".join(parts) + "." if parts else "No dominant single driver."
