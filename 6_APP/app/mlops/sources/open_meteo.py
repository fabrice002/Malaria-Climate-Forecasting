"""
Open-Meteo source (ERA5 reanalysis) — the source in use today.

Same source as the training climate, so the reanalysis product stays consistent
between training and inference. No API key required.

Takes over and hardens the logic of
`9_NATIONAL_VALIDATION/fetch_climate_2023_2025.py`, which was a standalone
script: batching, per-district fallback, and a back-off specific to the quota
(HTTP 429) learned in practice — the API weights each request by the volume of
data it returns, so large batches trip the rate limit.
"""

from __future__ import annotations

import time
from datetime import date

import pandas as pd
import requests

from app.mlops.sources.base import ClimateSource, FetchResult, register_source

API_URL = "https://archive-api.open-meteo.com/v1/archive"

DAILY_VARS = [
    "temperature_2m_mean",
    "relative_humidity_2m_mean",
    "surface_pressure_mean",
    "precipitation_sum",
]


@register_source("open_meteo")
class OpenMeteoSource(ClimateSource):
    """Daily climate from Open-Meteo's ERA5 reanalysis."""

    supports_batch = True

    def __init__(self, batch_size: int = 5, sleep_s: float = 6.0,
                 max_retries: int = 4, timeout_s: int = 180) -> None:
        self.batch_size = batch_size
        self.sleep_s = sleep_s
        self.max_retries = max_retries
        self.timeout_s = timeout_s

    # ── One location ────────────────────────────────────────────────────────
    def fetch(self, district: str, lat: float, lon: float,
              start: date, end: date) -> pd.DataFrame:
        frames = self._request(
            pd.DataFrame([{"district": district, "lat": lat, "lon": lon}]), start, end)
        return frames[0]

    # ── Several locations, batched ──────────────────────────────────────────
    def fetch_many(self, districts: pd.DataFrame,
                   start: date, end: date) -> FetchResult:
        t0 = time.time()
        frames: list[pd.DataFrame] = []
        failures: list[tuple[str, str]] = []

        n_batches = (len(districts) + self.batch_size - 1) // self.batch_size
        for b in range(n_batches):
            chunk = districts.iloc[b * self.batch_size:(b + 1) * self.batch_size]
            try:
                frames.extend(self._request(chunk, start, end))
            except Exception:                              # noqa: BLE001
                # Fall back one at a time so a single malformed point cannot
                # take down the whole batch.
                for row in chunk.itertuples():
                    try:
                        frames.extend(self._request(
                            pd.DataFrame([{"district": row.district,
                                           "lat": row.lat, "lon": row.lon}]),
                            start, end))
                    except Exception as exc2:              # noqa: BLE001
                        failures.append((row.district, str(exc2)[:120]))
            time.sleep(self.sleep_s)

        out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        return FetchResult(frame=self._normalise(out), source_name=self.name,
                           failures=failures, duration_s=time.time() - t0)

    # ── HTTP call ───────────────────────────────────────────────────────────
    def _request(self, rows: pd.DataFrame, start: date, end: date) -> list[pd.DataFrame]:
        params = {
            "latitude": ",".join(f"{v:.5f}" for v in rows["lat"]),
            "longitude": ",".join(f"{v:.5f}" for v in rows["lon"]),
            "start_date": str(start),
            "end_date": str(end),
            "daily": ",".join(DAILY_VARS),
            "timezone": "Africa/Douala",
        }

        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                r = requests.get(API_URL, params=params, timeout=self.timeout_s)
                r.raise_for_status()
                payload = r.json()
                # A single location returns an object; several return an array.
                blocks = payload if isinstance(payload, list) else [payload]
                if len(blocks) != len(rows):
                    raise RuntimeError(
                        f"expected {len(rows)} blocks, got {len(blocks)}")
                return [self._block_to_frame(name, b["daily"])
                        for name, b in zip(rows["district"], blocks)]
            except Exception as exc:                       # noqa: BLE001
                last_err = exc
                if attempt < self.max_retries:
                    # 429 means the quota window is exhausted; that needs a much
                    # longer pause than a transient network error.
                    rate_limited = "429" in str(exc)
                    time.sleep((30 * attempt) if rate_limited else 2 ** attempt)
        raise RuntimeError(
            f"Open-Meteo: failed after {self.max_retries} attempts — {last_err}")

    @staticmethod
    def _block_to_frame(name: str, daily: dict) -> pd.DataFrame:
        return pd.DataFrame({
            "Location": name,
            "Date": daily["time"],
            "Temperature_C": daily["temperature_2m_mean"],
            "Humidity_pct": daily["relative_humidity_2m_mean"],
            "Pressure_hPa": daily["surface_pressure_mean"],
            "Precipitation_mm": daily["precipitation_sum"],
        })
