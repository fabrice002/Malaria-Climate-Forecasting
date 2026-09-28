"""
Inference service — loads the model bundle and runs the two-stage chain.

This is the heart of the operational system. It wraps the four trained models
(produced by malaria_deployment.ipynb) and implements the deployment logic:

    Month 1 (no case history)  -> NO-LAG model bootstraps the chain
    Month 2..N                 -> LAG model runs recursively, feeding the
                                  previous month's PREDICTED cases back as
                                  cases_lag1. Real cases, when supplied,
                                  override the synthetic lag.

Both regressors predict log_cases; incidence and the Low/High class are derived
from predicted cases / population vs the district's 75th-percentile threshold.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import joblib

from app.config import settings


class ModelBundle:
    """Loads and holds the four models + artifacts; runs the chain."""

    def __init__(self, bundle_dir: Path = settings.bundle_dir):
        self.bundle_dir = Path(bundle_dir)
        self._loaded = False
        self.regressor_nolag = None
        self.regressor_lag = None
        self.classifier_nolag = None
        self.classifier_lag = None
        self.feat_nolag: List[str] = []
        self.feat_lag: List[str] = []
        self.feat_medians: Dict[str, float] = {}
        self.district_static: Optional[pd.DataFrame] = None

    # ── Loading ──────────────────────────────────────────────────────────────
    def load(self) -> None:
        d = self.bundle_dir
        self.regressor_nolag = joblib.load(d / "regressor_nolag.joblib")
        self.regressor_lag = joblib.load(d / "regressor_lag.joblib")
        self.classifier_nolag = joblib.load(d / "classifier_nolag.joblib")
        self.classifier_lag = joblib.load(d / "classifier_lag.joblib")

        with open(d / "artifacts.json") as f:
            art = json.load(f)
        self.feat_nolag = art["feature_list_nolag"]
        self.feat_lag = art["feature_list_lag"]
        self.feat_medians = {k: float(v) for k, v in art["feature_medians"].items()}

        self.district_static = pd.read_csv(d / "district_static.csv")
        self._loaded = True

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def n_districts(self) -> int:
        return 0 if self.district_static is None else len(self.district_static)

    # ── District lookup ──────────────────────────────────────────────────────
    def get_static(self, district: str) -> dict:
        if self.district_static is None:
            raise RuntimeError("Bundle not loaded.")
        row = self.district_static[self.district_static["district"] == district]
        if row.empty:
            raise KeyError(f"Unknown district: {district}")
        return row.iloc[0].to_dict()

    # ── Feature construction for one month ───────────────────────────────────
    @staticmethod
    def _seasonal(month: int) -> dict:
        return {
            "month": month,
            "sin_month": float(np.sin(2 * np.pi * month / 12)),
            "cos_month": float(np.cos(2 * np.pi * month / 12)),
        }

    def _build_row(self, reading: dict, static: dict,
                   clim_hist: List[dict]) -> dict:
        """Assemble the non-case features for one month.

        clim_hist holds the previous months' climate dicts (for climate lags).
        """
        row = {}
        row.update(self._seasonal(reading["month"]))
        for k in ("SHP_lat", "SHP_lon", "SHP_Area", "cluster"):
            row[k] = static[k]
        row["Temperature_C"] = reading["temperature_c"]
        row["Humidity_pct"] = reading["humidity_pct"]
        row["Pressure_hPa"] = reading["pressure_hpa"]
        row["Precipitation_mm"] = reading["precipitation_mm"]

        # Climate lags (observed previous months, or median fallback)
        def lagval(var, k):
            if len(clim_hist) >= k:
                return clim_hist[-k][var]
            return self.feat_medians.get(f"{var}_lag{k}", self.feat_medians.get(var, 0.0))

        row["Temperature_C_lag1"] = lagval("Temperature_C", 1)
        row["Temperature_C_lag2"] = lagval("Temperature_C", 2)
        row["Precipitation_mm_lag1"] = lagval("Precipitation_mm", 1)
        row["Precipitation_mm_lag2"] = lagval("Precipitation_mm", 2)
        row["Humidity_pct_lag1"] = lagval("Humidity_pct", 1)
        row["Humidity_pct_lag2"] = lagval("Humidity_pct", 2)
        return row

    # ── The recursive chain ──────────────────────────────────────────────────
    def predict_chain(self, district: str, readings: List[dict]) -> List[dict]:
        """Run the full two-stage chain for one district.

        readings: time-ordered list of dicts with keys
            month, year, temperature_c, humidity_pct, pressure_hpa,
            precipitation_mm, and optional real_cases.
        Returns a list of per-month prediction dicts.
        """
        static = self.get_static(district)
        pop = static["p_totale"]
        thr = static["threshold_75"]

        results: List[dict] = []
        case_hist: List[float] = []   # real where available, else predicted
        clim_hist: List[dict] = []    # for climate lags

        for i, reading in enumerate(readings):
            base = self._build_row(reading, static, clim_hist)

            use_lag = (
                settings.enable_recursive_chain
                and i > 0
                and len(case_hist) >= 1
            )

            if not use_lag:
                # Bootstrap with NO-LAG model
                X = pd.DataFrame([base]).reindex(columns=self.feat_nolag)
                X = X.fillna(pd.Series(self.feat_medians))
                log_cases = float(self.regressor_nolag.predict(X)[0])
                proba = float(self.classifier_nolag.predict_proba(X)[0, 1])
                model_used = "NO-LAG"
            else:
                # Recursive LAG model — synthetic case lags
                base["cases_lag1"] = case_hist[-1]
                base["cases_lag2"] = case_hist[-2] if len(case_hist) >= 2 \
                    else self.feat_medians["cases_lag2"]
                base["cases_lag3"] = case_hist[-3] if len(case_hist) >= 3 \
                    else self.feat_medians["cases_lag3"]
                base["rolling_mean_3m"] = float(np.mean(case_hist[-3:]))
                X = pd.DataFrame([base]).reindex(columns=self.feat_lag)
                X = X.fillna(pd.Series(self.feat_medians))
                log_cases = float(self.regressor_lag.predict(X)[0])
                proba = float(self.classifier_lag.predict_proba(X)[0, 1])
                model_used = "LAG"

            pred_cases = float(np.expm1(log_cases))
            incidence = pred_cases / pop * 1000
            risk = "High" if incidence > thr else "Low"

            results.append({
                "month_index": i + 1,
                "year": reading["year"],
                "month": reading["month"],
                "predicted_cases": int(round(pred_cases)),
                "predicted_incidence": round(incidence, 2),
                "risk_level": risk,
                "risk_probability": round(proba, 4),
                "model_used": model_used,
                "threshold": round(thr, 2),
                "_feature_row": base,          # kept for SHAP / storage
                "_feature_set": "lag" if use_lag else "nolag",
            })

            # Next month's lag: real case overrides synthetic prediction
            real = reading.get("real_cases")
            case_hist.append(real if real is not None else pred_cases)
            clim_hist.append({
                "Temperature_C": reading["temperature_c"],
                "Humidity_pct": reading["humidity_pct"],
                "Pressure_hPa": reading["pressure_hpa"],
                "Precipitation_mm": reading["precipitation_mm"],
            })

        return results


# Singleton, loaded once at startup.
bundle = ModelBundle()
