"""
File source — IoT sensors, manual exports, history replay.

Three uses:

1. **IoT network.** LoRa/Meshtastic gateways drop their readings into a
   directory; the pipeline consumes them like any other source.
2. **Deterministic replay.** Pointing at a frozen CSV makes a run reproducible,
   which both tests and incident replays need.
3. **Degraded mode.** When the remote API is unavailable, switching to the last
   known file keeps the pipeline running.

The directory is scanned recursively; any CSV carrying the schema columns is
accepted, whatever its name.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from app.mlops.sources.base import (CLIMATE_SCHEMA, ClimateSource, FetchResult,
                                    register_source)


@register_source("csv")
class CsvSource(ClimateSource):
    """Climate read from a local file or directory."""

    supports_batch = True

    def __init__(self, path: str | Path, glob: str = "**/*.csv") -> None:
        self.path = Path(path)
        self.glob = glob
        self._cache: pd.DataFrame | None = None

    # ── Loading ─────────────────────────────────────────────────────────────
    def _load(self) -> pd.DataFrame:
        if self._cache is not None:
            return self._cache

        if self.path.is_file():
            files = [self.path]
        elif self.path.is_dir():
            files = sorted(self.path.glob(self.glob))
        else:
            raise FileNotFoundError(f"CSV source not found: {self.path}")

        frames = []
        for f in files:
            try:
                d = pd.read_csv(f)
            except Exception:                              # noqa: BLE001
                continue                                   # unreadable file: skipped
            d = d.rename(columns={"Humidity_%": "Humidity_pct",
                                  "district": "Location", "date": "Date"})
            if all(c in d.columns for c in CLIMATE_SCHEMA):
                frames.append(d[CLIMATE_SCHEMA])

        if not frames:
            raise ValueError(
                f"no CSV matching the expected schema under {self.path} "
                f"(required columns: {CLIMATE_SCHEMA})")

        self._cache = self._normalise(pd.concat(frames, ignore_index=True))
        return self._cache

    # ── Interface ───────────────────────────────────────────────────────────
    def fetch(self, district: str, lat: float, lon: float,
              start: date, end: date) -> pd.DataFrame:
        d = self._load()
        m = ((d["Location"] == district)
             & (d["Date"] >= pd.Timestamp(start))
             & (d["Date"] <= pd.Timestamp(end)))
        return d[m].copy()

    def fetch_many(self, districts: pd.DataFrame,
                   start: date, end: date) -> FetchResult:
        import time

        t0 = time.time()
        d = self._load()
        wanted = set(districts["district"])
        m = ((d["Location"].isin(wanted))
             & (d["Date"] >= pd.Timestamp(start))
             & (d["Date"] <= pd.Timestamp(end)))
        out = d[m].copy()

        found = set(out["Location"].unique())
        failures = [(name, "absent from the source file")
                    for name in sorted(wanted - found)]
        return FetchResult(frame=out, source_name=self.name,
                           failures=failures, duration_s=time.time() - t0)
