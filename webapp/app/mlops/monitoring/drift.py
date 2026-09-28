"""
Monitoring — data drift and performance drift.

Two distinct questions, often conflated:

* **Data drift** — has the distribution of the *inputs* changed? Detectable
  immediately, without waiting for ground truth.
* **Concept drift** — has the *relationship* input to output changed? Only
  visible once real cases are reported, months later.

The project supplies a textbook case of the second: Foumban was evaluated with a
+28 % bias, yet the indicator definition itself differs by a factor of ~1.3
between the training and test periods. Performance drift can therefore come from
a change of definition rather than epidemiology — hence `cross_check_sources`
below.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats as sps

# PSI thresholds in common industry use.
PSI_MINOR = 0.10        # below this: distribution is stable
PSI_MAJOR = 0.25        # above this: significant drift, action needed


@dataclass
class DriftMetric:
    feature: str
    psi: float
    ks_stat: float
    ks_pvalue: float
    mean_ref: float
    mean_new: float
    severity: str = field(init=False)

    def __post_init__(self) -> None:
        self.severity = ("major" if self.psi >= PSI_MAJOR
                         else "minor" if self.psi >= PSI_MINOR
                         else "stable")

    @property
    def shift_pct(self) -> float:
        return ((self.mean_new / self.mean_ref - 1) * 100
                if self.mean_ref not in (0, np.nan) else np.nan)


@dataclass
class DriftReport:
    metrics: list[DriftMetric] = field(default_factory=list)
    n_ref: int = 0
    n_new: int = 0

    @property
    def drifted(self) -> list[DriftMetric]:
        return [m for m in self.metrics if m.severity != "stable"]

    @property
    def has_major_drift(self) -> bool:
        return any(m.severity == "major" for m in self.metrics)

    @property
    def max_psi(self) -> float:
        return max((m.psi for m in self.metrics), default=0.0)

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([{
            "feature": m.feature, "PSI": m.psi, "severity": m.severity,
            "KS": m.ks_stat, "p(KS)": m.ks_pvalue,
            "mean_ref": m.mean_ref, "mean_new": m.mean_new,
            "shift_%": m.shift_pct,
        } for m in self.metrics]).sort_values("PSI", ascending=False)

    def to_dict(self) -> dict:
        return {"n_ref": self.n_ref, "n_new": self.n_new,
                "max_psi": self.max_psi,
                "has_major_drift": self.has_major_drift,
                "drifted": [m.feature for m in self.drifted],
                "metrics": self.to_frame().to_dict("records")}


def population_stability_index(ref: np.ndarray, new: np.ndarray,
                               bins: int = 10) -> float:
    """PSI between a reference distribution and a new one.

    Binned on the reference quantiles rather than on regular intervals, to stay
    robust to strongly skewed distributions — rainfall has a coefficient of
    variation of 101 % in this project.
    """
    ref = np.asarray(ref, dtype=float)
    new = np.asarray(new, dtype=float)
    ref = ref[np.isfinite(ref)]
    new = new[np.isfinite(new)]
    if len(ref) < bins or len(new) == 0:
        return 0.0

    edges = np.unique(np.quantile(ref, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf

    r, _ = np.histogram(ref, bins=edges)
    n, _ = np.histogram(new, bins=edges)

    # Smoothing: avoids a division by zero on an empty bin.
    eps = 1e-6
    r_pct = np.clip(r / max(r.sum(), 1), eps, None)
    n_pct = np.clip(n / max(n.sum(), 1), eps, None)

    return float(np.sum((n_pct - r_pct) * np.log(n_pct / r_pct)))


def detect_data_drift(reference: pd.DataFrame, new: pd.DataFrame,
                      features: list[str]) -> DriftReport:
    """Compare two batches of data, feature by feature."""
    rep = DriftReport(n_ref=len(reference), n_new=len(new))

    for f in features:
        if f not in reference.columns or f not in new.columns:
            continue
        a = pd.to_numeric(reference[f], errors="coerce").dropna().values
        b = pd.to_numeric(new[f], errors="coerce").dropna().values
        if len(a) < 10 or len(b) < 3:
            continue

        ks, p = sps.ks_2samp(a, b)
        rep.metrics.append(DriftMetric(
            feature=f,
            psi=population_stability_index(a, b),
            ks_stat=float(ks), ks_pvalue=float(p),
            mean_ref=float(np.mean(a)), mean_new=float(np.mean(b)),
        ))

    return rep


def detect_performance_drift(history: pd.DataFrame,
                             metric: str = "abs_error",
                             window: int = 6,
                             tolerance: float = 1.5) -> dict:
    """Look for a degradation of performance over time.

    Compares the error of the recent window against the earlier period.
    `tolerance` is the degradation factor above which an alert is raised
    (1.5 = +50 % error).

    `history` must carry a date column and the `metric` column.
    """
    if len(history) < window * 2:
        return {"status": "insufficient",
                "detail": f"{len(history)} points, {window * 2} required"}

    h = history.sort_values(history.columns[0])
    recent = h[metric].tail(window)
    baseline = h[metric].iloc[:-window]

    r_mean, b_mean = float(recent.mean()), float(baseline.mean())
    ratio = r_mean / b_mean if b_mean else np.nan

    # Non-parametric test: no normality assumption on the errors.
    try:
        stat, p = sps.mannwhitneyu(recent, baseline, alternative="greater")
    except ValueError:
        stat, p = np.nan, np.nan

    degraded = bool(np.isfinite(ratio) and ratio > tolerance)
    return {
        "status": "degraded" if degraded else "stable",
        "baseline_mean": b_mean,
        "recent_mean": r_mean,
        "ratio": ratio,
        "p_value": float(p) if np.isfinite(p) else None,
        "window": window,
        "detail": (f"recent error {r_mean:.1f} vs baseline {b_mean:.1f} "
                   f"({ratio:.2f}x, threshold {tolerance}x)"),
    }


def cross_check_sources(a: pd.DataFrame, b: pd.DataFrame,
                        label_a: str = "source_a",
                        label_b: str = "source_b") -> pd.DataFrame:
    """Compare two climate sources over their common period.

    Brings the cross-check of `te/climate_fetch.py` (Open-Meteo vs NASA POWER)
    into the pipeline. Useful to tell a genuine climate shift apart from a mere
    change of provider.
    """
    m = a.merge(b, on=["Location", "Date"], suffixes=(f"_{label_a}", f"_{label_b}"))
    rows = []
    for v in ("Temperature_C", "Humidity_pct", "Pressure_hPa", "Precipitation_mm"):
        ca, cb = f"{v}_{label_a}", f"{v}_{label_b}"
        if ca not in m.columns or cb not in m.columns:
            continue
        x = pd.to_numeric(m[ca], errors="coerce")
        y = pd.to_numeric(m[cb], errors="coerce")
        ok = x.notna() & y.notna()
        if ok.sum() < 10:
            continue
        rows.append({
            "variable": v, "n": int(ok.sum()),
            "correlation": float(x[ok].corr(y[ok])),
            "MAE": float((x[ok] - y[ok]).abs().mean()),
            f"mean_{label_a}": float(x[ok].mean()),
            f"mean_{label_b}": float(y[ok].mean()),
        })
    return pd.DataFrame(rows)
