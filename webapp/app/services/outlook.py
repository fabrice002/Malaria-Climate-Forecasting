"""
Forward-looking climate — what the month ahead is expected to bring.

An early-warning system that can only score months already past is not an
early-warning system. To forecast the current and next month the model needs
climate for days that have not happened, which the reanalysis archive by
definition does not hold. Three tiers cover it:

    observed   ERA5 archive          days already recorded
    forecast   16-day NWP forecast   the next fortnight
    seasonal   ensemble, ~9 months   beyond that

Every daily row is tagged with which tier produced it, and that tag survives the
monthly aggregation, so a caller can always tell a month that was measured from
one that was projected. Nothing here is a `ClimateSource` and nothing is
registered: the MLOps pipeline must never train, score for the record, or
monitor drift against predicted weather. This is a serving-side concern only.
"""

from __future__ import annotations

import time
from datetime import date, timedelta

import pandas as pd
import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
SEASONAL_URL = "https://seasonal-api.open-meteo.com/v1/seasonal"

DAILY_VARS = [
    "temperature_2m_mean",
    "relative_humidity_2m_mean",
    "surface_pressure_mean",
    "precipitation_sum",
]

# The deterministic forecast runs out at 16 days; the seasonal ensemble carries
# on from there. Asking the seasonal model for the next fortnight as well would
# throw away the sharper product for no reason.
FORECAST_DAYS = 16
# The seasonal endpoint rejects anything past 217 days.
SEASONAL_DAYS = 217

COLUMNS = ["Location", "Date", "Temperature_C", "Humidity_pct",
           "Pressure_hPa", "Precipitation_mm", "provenance"]


def _get(url: str, params: dict, timeout_s: int = 90,
         max_retries: int = 3) -> dict:
    """GET with the same quota-aware back-off the archive source uses."""
    last: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.get(url, params=params, timeout=timeout_s)
            r.raise_for_status()
            return r.json()
        except Exception as exc:                            # noqa: BLE001
            last = exc
            if attempt < max_retries:
                time.sleep((30 * attempt) if "429" in str(exc) else 2 ** attempt)
    raise RuntimeError(f"Open-Meteo outlook: failed after {max_retries} "
                       f"attempts — {last}")


def _frame(district: str, daily: dict, provenance: str) -> pd.DataFrame:
    """Daily payload -> the shared schema, tagged with its tier."""
    out = pd.DataFrame({
        "Location": district,
        "Date": pd.to_datetime(daily["time"]),
        "Temperature_C": daily.get("temperature_2m_mean"),
        "Humidity_pct": daily.get("relative_humidity_2m_mean"),
        "Pressure_hPa": daily.get("surface_pressure_mean"),
        "Precipitation_mm": daily.get("precipitation_sum"),
    })
    out["provenance"] = provenance
    # The last day of a run is often still null; carrying it into a monthly mean
    # would silently shorten the month.
    return out.dropna(subset=["Temperature_C", "Humidity_pct",
                              "Pressure_hPa", "Precipitation_mm"])


def fetch_forecast(district: str, lat: float, lon: float) -> pd.DataFrame:
    """The next 16 days, from the deterministic forecast."""
    j = _get(FORECAST_URL, {
        "latitude": f"{lat:.5f}", "longitude": f"{lon:.5f}",
        "daily": ",".join(DAILY_VARS),
        "forecast_days": FORECAST_DAYS,
        "timezone": "Africa/Douala",
    })
    return _frame(district, j["daily"], "forecast")


def fetch_seasonal(district: str, lat: float, lon: float,
                   days: int = SEASONAL_DAYS) -> pd.DataFrame:
    """The seasonal ensemble, averaged across its members.

    The API returns a control series plus ~50 perturbed members. The ensemble
    mean is the usable signal: any single member is one plausible weather
    trajectory, and at a month's range the spread between them is wide.
    """
    j = _get(SEASONAL_URL, {
        "latitude": f"{lat:.5f}", "longitude": f"{lon:.5f}",
        "daily": ",".join(DAILY_VARS),
        "forecast_days": days,
        "timezone": "Africa/Douala",
    })
    daily = j["daily"]
    mean = {"time": daily["time"]}
    for var in DAILY_VARS:
        members = [k for k in daily
                   if k == var or k.startswith(f"{var}_member")]
        if not members:
            mean[var] = [None] * len(daily["time"])
            continue
        mean[var] = (pd.DataFrame({k: daily[k] for k in members})
                     .mean(axis=1, skipna=True).tolist())
    return _frame(district, mean, "seasonal")


def fetch_outlook(district: str, lat: float, lon: float,
                  through: date) -> pd.DataFrame:
    """Daily climate from tomorrow through `through`, best tier first.

    Tiers are stitched by date, not concatenated: where the 16-day forecast and
    the seasonal ensemble both cover a day, the forecast wins.
    """
    frames, errors = [], []

    # The sharper product first. A failure here is survivable because the
    # seasonal ensemble also covers the near term, so it is recorded rather
    # than raised.
    try:
        frames.append(fetch_forecast(district, lat, lon))
    except Exception as exc:                                # noqa: BLE001
        errors.append(f"forecast: {exc}")

    covered = max((f.Date.max().date() for f in frames if not f.empty),
                  default=None)
    if covered is None or covered < through:
        try:
            frames.append(fetch_seasonal(district, lat, lon))
        except Exception as exc:                            # noqa: BLE001
            errors.append(f"seasonal: {exc}")

    frames = [f for f in frames if not f.empty]
    if not frames:
        # Swallowing this would hand back an empty outlook that looks like
        # "no future months requested" rather than "both providers failed".
        raise RuntimeError("no forward climate available — "
                           + "; ".join(errors or ["both tiers returned nothing"]))

    out = pd.concat(frames, ignore_index=True)
    # Forecast before seasonal for any day both cover.
    rank = {"forecast": 0, "seasonal": 1}
    out["_r"] = out.provenance.map(rank).fillna(9)
    out = (out.sort_values(["Date", "_r"])
              .drop_duplicates("Date", keep="first")
              .drop(columns="_r"))
    return out[out.Date.dt.date <= through].reset_index(drop=True)
