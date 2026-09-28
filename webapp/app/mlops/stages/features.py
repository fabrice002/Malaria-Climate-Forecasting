"""
Stage 3 — Feature engineering.

**One single implementation** of the aggregation and the features, shared by the
automated pipeline and the API. This is the most important property of the
module: in the original project this logic was copied across a dozen notebooks,
and any divergence between training and inference silently produces wrong
predictions (*training/serving skew*).

Conventions carried over unchanged from the training pipeline:

* daily → monthly: **mean** for temperature / humidity / pressure, **sum** for
  precipitation (it is a flux, not a state);
* cyclical month encoding (sin/cos) — December is adjacent to January;
* climate lags 1 and 2 months, computed **per district**;
* geography passed through as-is from `district_static.csv`.

⚠️ `SHP_lat` / `SHP_lon` are **transposed** in the source file (`SHP_lat` holds
the longitude). They are passed through **uncorrected**, because that is the
convention the models were trained with. Fixing them here would break every
prediction; the correction happens only for map display.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# The "NO-LAG" feature set: the only one available without case history.
FEAT_NOLAG = [
    "sin_month", "cos_month",
    "SHP_lat", "SHP_lon", "SHP_Area", "cluster",
    "Temperature_C", "Humidity_pct", "Pressure_hPa", "Precipitation_mm",
    "Temperature_C_lag1", "Temperature_C_lag2",
    "Precipitation_mm_lag1", "Precipitation_mm_lag2",
    "Humidity_pct_lag1", "Humidity_pct_lag2",
]

# Case-history features, added by the recursive chain.
CASE_LAGS = ["cases_lag1", "cases_lag2", "cases_lag3", "rolling_mean_3m"]
FEAT_LAG = FEAT_NOLAG + CASE_LAGS

CLIMATE_VARS = ["Temperature_C", "Humidity_pct", "Pressure_hPa", "Precipitation_mm"]

# Features that are constant for a given district: geography and ecological zone.
# Their distribution depends only on which districts are being scored, never on
# the real world. Monitoring them for drift would raise an alert on every run
# covering few districts — see `monitoring.drift`.
STATIC_FEATURES = ["SHP_lat", "SHP_lon", "SHP_Area", "cluster"]

# Features that genuinely can drift: observed climate and seasonality.
DYNAMIC_FEATURES = [f for f in FEAT_NOLAG if f not in STATIC_FEATURES]


def daily_to_monthly(daily: pd.DataFrame) -> pd.DataFrame:
    """Aggregate daily readings to monthly, per district.

    Means for the state variables, sum for precipitation.
    """
    d = daily.copy()
    d["Date"] = pd.to_datetime(d["Date"])
    d["year"] = d["Date"].dt.year
    d["month"] = d["Date"].dt.month

    monthly = (d.groupby(["Location", "year", "month"])
               .agg(Temperature_C=("Temperature_C", "mean"),
                    Humidity_pct=("Humidity_pct", "mean"),
                    Pressure_hPa=("Pressure_hPa", "mean"),
                    Precipitation_mm=("Precipitation_mm", "sum"),
                    n_days=("Date", "size"))
               .reset_index()
               .rename(columns={"Location": "district"}))

    return monthly.sort_values(["district", "year", "month"]).reset_index(drop=True)


def add_temporal_features(monthly: pd.DataFrame) -> pd.DataFrame:
    """Add the seasonal encoding and the climate lags.

    Lags are computed **within each district**: a global `shift` would mix
    districts and leak one district's value into another's features.
    """
    m = monthly.sort_values(["district", "year", "month"]).copy()

    m["sin_month"] = np.sin(2 * np.pi * m["month"] / 12)
    m["cos_month"] = np.cos(2 * np.pi * m["month"] / 12)

    for lag in (1, 2):
        for v in ("Temperature_C", "Precipitation_mm", "Humidity_pct"):
            m[f"{v}_lag{lag}"] = m.groupby("district")[v].shift(lag)

    return m


def attach_static(monthly: pd.DataFrame, static: pd.DataFrame) -> pd.DataFrame:
    """Join the district's geography (lat/lon/area/cluster/population).

    Inner join by design: a district with no static record cannot be scored, and
    it is better to see it disappear here than to produce a prediction built on
    default values.
    """
    cols = ["district", "region", "SHP_lat", "SHP_lon", "SHP_Area",
            "cluster", "p_totale", "threshold_75"]
    return monthly.merge(static[cols], on="district", how="inner")


def build_feature_frame(daily: pd.DataFrame, static: pd.DataFrame,
                        drop_incomplete_months: bool = True,
                        min_days: int = 25) -> pd.DataFrame:
    """Full chain: raw daily readings → feature matrix ready to score.

    `drop_incomplete_months` discards partially observed months: a precipitation
    sum over 12 days is not comparable to one over 31, and the model was trained
    on complete months.
    """
    monthly = daily_to_monthly(daily)

    if drop_incomplete_months:
        monthly = monthly[monthly["n_days"] >= min_days].copy()

    monthly = add_temporal_features(monthly)
    frame = attach_static(monthly, static)
    frame["date"] = pd.to_datetime(
        dict(year=frame["year"], month=frame["month"], day=1))
    return frame.sort_values(["district", "date"]).reset_index(drop=True)


def scorable_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Rows whose NO-LAG features are all present.

    The first two months of each district are naturally discarded: their climate
    lags do not exist yet.
    """
    return frame[frame[FEAT_NOLAG].notna().all(axis=1)].copy()
