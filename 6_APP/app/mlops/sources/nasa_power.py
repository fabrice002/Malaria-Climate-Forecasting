"""
NASA POWER source — the cross-check source.

It exists for two reasons:

1. **To prove the abstraction works.** Switching the whole pipeline to NASA POWER
   takes one environment variable: `MEWS_CLIMATE_SOURCE=nasa_power`. No other
   line of code changes.
2. **As a quality control.** `te/climate_fetch.py` already compared Open-Meteo
   against NASA POWER; keeping both lets that check run automatically (see
   `app.mlops.monitoring.drift.cross_check_sources`).

Mind the units: POWER returns pressure in kPa (converted to hPa here) and codes
missing values as -999.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import requests

from app.mlops.sources.base import ClimateSource, register_source

API_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
PARAMS = "T2M,PRECTOTCORR,RH2M,PS"


@register_source("nasa_power")
class NasaPowerSource(ClimateSource):
    """Daily climate from NASA POWER."""

    supports_batch = False       # the API handles one point per request

    def __init__(self, timeout_s: int = 180) -> None:
        self.timeout_s = timeout_s

    def fetch(self, district: str, lat: float, lon: float,
              start: date, end: date) -> pd.DataFrame:
        r = requests.get(API_URL, params={
            "parameters": PARAMS,
            "community": "AG",
            "latitude": lat,
            "longitude": lon,
            "start": str(start).replace("-", ""),
            "end": str(end).replace("-", ""),
            "format": "JSON",
        }, timeout=self.timeout_s)
        r.raise_for_status()

        p = r.json()["properties"]["parameter"]
        dates = list(p["T2M"].keys())
        df = pd.DataFrame({
            "Location": district,
            "Date": pd.to_datetime(dates, format="%Y%m%d"),
            "Temperature_C": [p["T2M"][d] for d in dates],
            "Humidity_pct": [p["RH2M"][d] for d in dates],
            "Pressure_hPa": [p["PS"][d] * 10 for d in dates],   # kPa -> hPa
            "Precipitation_mm": [p["PRECTOTCORR"][d] for d in dates],
        })
        # POWER encodes missing data with negative sentinels.
        return df.replace({-999: pd.NA, -999.0: pd.NA, -9990: pd.NA})
