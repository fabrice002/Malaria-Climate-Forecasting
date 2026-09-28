"""
Contract for climate data sources.

The key property of this module: **switching provider must touch one file and
no more**. Every source implements `ClimateSource`, returns the same schema, and
registers itself. The rest of the pipeline only ever sees the interface.

Adding a source:

    from app.mlops.sources.base import ClimateSource, register_source

    @register_source("ma_source")
    class MaSource(ClimateSource):
        def fetch(self, district, lat, lon, start, end) -> pd.DataFrame:
            ...

Then in configuration:  MEWS_CLIMATE_SOURCE=my_source
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Dict, Type

import pandas as pd

# Schema shared by every source — identical to the training file
# `cameroon_districts_climate.csv`, so nothing downstream has to adapt.
CLIMATE_SCHEMA = ["Location", "Date", "Temperature_C", "Humidity_pct",
                  "Pressure_hPa", "Precipitation_mm"]


@dataclass
class FetchResult:
    """Result of one collection, with its provenance."""

    frame: pd.DataFrame
    source_name: str
    n_rows: int = 0
    n_districts: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)
    duration_s: float = 0.0

    def __post_init__(self) -> None:
        self.n_rows = len(self.frame)
        if "Location" in self.frame.columns:
            self.n_districts = int(self.frame["Location"].nunique())

    @property
    def ok(self) -> bool:
        return self.n_rows > 0


class ClimateSource(abc.ABC):
    """Interface every climate source must implement."""

    #: short name, used in configuration and recorded with every prediction
    name: str = "abstract"

    #: True when the source can handle several points in one request
    supports_batch: bool = False

    @abc.abstractmethod
    def fetch(self, district: str, lat: float, lon: float,
              start: date, end: date) -> pd.DataFrame:
        """Return one district's daily readings, in the shared schema."""

    def fetch_many(self, districts: pd.DataFrame,
                   start: date, end: date) -> FetchResult:
        """Collect several districts.

        Default implementation: loop over `fetch`. Sources that support batching
        override this method (see `open_meteo`).

        `districts` must carry the columns district / lat / lon.
        """
        import time

        t0 = time.time()
        frames, failures = [], []
        for row in districts.itertuples():
            try:
                frames.append(self.fetch(row.district, row.lat, row.lon, start, end))
            except Exception as exc:                       # noqa: BLE001
                failures.append((row.district, str(exc)[:120]))
        out = (pd.concat(frames, ignore_index=True) if frames
               else pd.DataFrame(columns=CLIMATE_SCHEMA))
        return FetchResult(frame=self._normalise(out), source_name=self.name,
                           failures=failures, duration_s=time.time() - t0)

    # ── Shared helpers ──────────────────────────────────────────────────────
    @staticmethod
    def _normalise(df: pd.DataFrame) -> pd.DataFrame:
        """Enforce the shared schema, the dtypes and the row order."""
        if df.empty:
            return pd.DataFrame(columns=CLIMATE_SCHEMA)
        out = df.copy()
        # Tolerate the naming variants found across the project
        out = out.rename(columns={"Humidity_%": "Humidity_pct",
                                  "district": "Location", "date": "Date"})
        missing = [c for c in CLIMATE_SCHEMA if c not in out.columns]
        if missing:
            raise ValueError(f"missing columns after collection: {missing}")
        out = out[CLIMATE_SCHEMA]
        out["Date"] = pd.to_datetime(out["Date"])
        for c in ("Temperature_C", "Humidity_pct", "Pressure_hPa", "Precipitation_mm"):
            out[c] = pd.to_numeric(out[c], errors="coerce")
        return out.sort_values(["Location", "Date"]).reset_index(drop=True)


# ── Source registry ─────────────────────────────────────────────────────────
_REGISTRY: Dict[str, Type[ClimateSource]] = {}


def register_source(name: str) -> Callable[[Type[ClimateSource]], Type[ClimateSource]]:
    """Decorator registering a source."""

    def deco(cls: Type[ClimateSource]) -> Type[ClimateSource]:
        cls.name = name
        _REGISTRY[name] = cls
        return cls

    return deco


def get_source(name: str, **kwargs) -> ClimateSource:
    """Instantiate a source by name."""
    # Late import: populates the registry without a circular dependency.
    from app.mlops.sources import csv_source, nasa_power, open_meteo  # noqa: F401

    if name not in _REGISTRY:
        raise KeyError(
            f"unknown source: {name!r}. Available: {sorted(_REGISTRY)}")
    return _REGISTRY[name](**kwargs)


def available_sources() -> list[str]:
    from app.mlops.sources import csv_source, nasa_power, open_meteo  # noqa: F401

    return sorted(_REGISTRY)
