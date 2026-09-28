"""
Stage 2 — Data validation.

The quality gate between collection and the model. Bad data caught here costs a
log line; the same data passed to the model produces a false health alert.
Validation is therefore **blocking**: the pipeline stops when a critical rule
fails.

The bounds come from the distribution of the training climate
(`cameroon_districts_climate.csv`, 136 290 daily records) widened by a margin —
they are not arbitrary round numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np
import pandas as pd


class Severity(str, Enum):
    CRITICAL = "critical"   # halts the pipeline
    WARNING = "warning"     # recorded, but lets the run continue


@dataclass
class Check:
    name: str
    severity: Severity
    passed: bool
    detail: str = ""
    n_offending: int = 0

    def __post_init__(self) -> None:
        # pandas/numpy comparisons return np.bool_ / np.int64, which neither
        # FastAPI nor json can serialise. Normalise here rather than at every
        # call site.
        self.passed = bool(self.passed)
        self.n_offending = int(self.n_offending)


@dataclass
class ValidationReport:
    checks: list[Check] = field(default_factory=list)
    n_rows: int = 0
    n_districts: int = 0

    @property
    def passed(self) -> bool:
        """True when no critical rule failed."""
        return not any(c.severity is Severity.CRITICAL and not c.passed
                       for c in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]

    def summary(self) -> str:
        ok = sum(c.passed for c in self.checks)
        state = "OK" if self.passed else "FAILED"
        return (f"[{state}] {ok}/{len(self.checks)} checks passed · "
                f"{self.n_rows} rows · {self.n_districts} districts")

    def to_dict(self) -> dict:
        return {
            "passed": bool(self.passed),
            "n_rows": int(self.n_rows),
            "n_districts": int(self.n_districts),
            "checks": [{"name": c.name, "severity": c.severity.value,
                        "passed": bool(c.passed), "detail": str(c.detail),
                        "n_offending": int(c.n_offending)} for c in self.checks],
        }


# Physically admissible ranges, per variable.
# (min, max, severity) — derived from the range observed during training.
BOUNDS = {
    "Temperature_C":    (5.0, 50.0, Severity.CRITICAL),
    "Humidity_pct":     (0.0, 100.0, Severity.CRITICAL),
    "Pressure_hPa":     (700.0, 1100.0, Severity.CRITICAL),
    "Precipitation_mm": (0.0, 500.0, Severity.WARNING),   # plausible daily extreme
}

# Maximum share of missing values tolerated per variable.
MAX_NULL_RATE = 0.05


def validate_climate(df: pd.DataFrame,
                     expected_districts: set[str] | None = None,
                     max_null_rate: float = MAX_NULL_RATE) -> ValidationReport:
    """Check a batch of daily climate readings."""
    rep = ValidationReport(n_rows=len(df))
    add = rep.checks.append

    # ── Structure ───────────────────────────────────────────────────────────
    required = ["Location", "Date", "Temperature_C", "Humidity_pct",
                "Pressure_hPa", "Precipitation_mm"]
    missing = [c for c in required if c not in df.columns]
    add(Check("schema", Severity.CRITICAL, not missing,
              f"missing columns: {missing}" if missing else "schema conforms"))
    if missing:
        return rep          # no point going further

    add(Check("non_empty", Severity.CRITICAL, len(df) > 0,
              f"{len(df)} rows received"))
    if df.empty:
        return rep

    rep.n_districts = int(df["Location"].nunique())

    # ── Missing values ──────────────────────────────────────────────────────
    for col in ("Temperature_C", "Humidity_pct", "Pressure_hPa", "Precipitation_mm"):
        rate = float(df[col].isna().mean())
        add(Check(f"nulls::{col}", Severity.CRITICAL, rate <= max_null_rate,
                  f"{rate:.1%} missing (threshold {max_null_rate:.0%})",
                  int(df[col].isna().sum())))

    # ── Physical bounds ─────────────────────────────────────────────────────
    for col, (lo, hi, sev) in BOUNDS.items():
        s = pd.to_numeric(df[col], errors="coerce")
        bad = int(((s < lo) | (s > hi)).sum())
        add(Check(f"bounds::{col}", sev, bad == 0,
                  f"{bad} value(s) outside [{lo}, {hi}]", bad))

    # ── Temporal consistency ────────────────────────────────────────────────
    dates = pd.to_datetime(df["Date"], errors="coerce")
    add(Check("valid_dates", Severity.CRITICAL, dates.notna().all(),
              f"{int(dates.isna().sum())} unparseable date(s)",
              int(dates.isna().sum())))

    future = int((dates > pd.Timestamp.today().normalize()).sum())
    add(Check("no_future_dates", Severity.WARNING, future == 0,
              f"{future} reading(s) dated after today", future))

    dups = int(df.duplicated(subset=["Location", "Date"]).sum())
    add(Check("no_duplicates", Severity.CRITICAL, dups == 0,
              f"{dups} duplicate (district, date) pair(s)", dups))

    # Gaps in the series: a warning, because the climate lags depend on them.
    gaps = []
    for loc, g in df.groupby("Location"):
        d = pd.to_datetime(g["Date"]).sort_values()
        if len(d) < 2:
            continue
        expected = pd.date_range(d.min(), d.max(), freq="D")
        missing_days = len(expected) - len(set(d))
        if missing_days:
            gaps.append((loc, missing_days))
    add(Check("continuous_series", Severity.WARNING, not gaps,
              (f"{len(gaps)} district(s) with missing days; "
               f"worst: {max(gaps, key=lambda x: x[1])}" if gaps
               else "no interruption"),
              sum(n for _, n in gaps)))

    # ── Expected coverage ───────────────────────────────────────────────────
    if expected_districts:
        got = set(df["Location"].unique())
        absent = expected_districts - got
        add(Check("coverage", Severity.WARNING, not absent,
                  (f"{len(absent)} district(s) with no data: "
                   f"{sorted(absent)[:5]}" if absent else "full coverage"),
                  len(absent)))

    # ── Zero variance (stuck sensor) ────────────────────────────────────────
    frozen = []
    for loc, g in df.groupby("Location"):
        if len(g) >= 7 and float(pd.to_numeric(g["Temperature_C"],
                                               errors="coerce").std(ddof=0) or 0) == 0.0:
            frozen.append(loc)
    add(Check("stuck_sensor", Severity.WARNING, not frozen,
              (f"constant temperature for {len(frozen)} district(s) — "
               f"stuck sensor?" if frozen else "variance normal"),
              len(frozen)))

    return rep
