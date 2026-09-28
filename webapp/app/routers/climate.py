"""
Climate router — fetch real observed climate for any district.

Endpoint (under the configured prefix, default /api/v1):
  GET /climate   monthly climate for one district, ready to feed /predict

This is what lets the dashboard forecast **any** of the 197 districts with that
district's own weather, instead of scoring every one of them against a single
hard-coded climate seed — and to do it for **the month ahead**, not only for
months already past.

Days that have happened come from the reanalysis archive; days that have not come
from `app.services.outlook` (16-day forecast, then the seasonal ensemble). Every
month returned carries a `provenance` saying which, because a projected month and
a measured one do not deserve equal confidence.

It deliberately reuses the MLOps source layer (`app.mlops.sources`) rather than
calling a weather API directly: switching provider stays a matter of setting
`MEWS_CLIMATE_SOURCE`, and the daily-to-monthly aggregation is the same single
implementation the training pipeline uses (`app.mlops.stages.features`), so the
readings handed to the model cannot drift from the training convention.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.mlops.config import mlops_settings
from app.mlops.sources.base import get_source
from app.mlops.stages import features as feat
from app.models.orm import District
from app.services.outlook import fetch_outlook

router = APIRouter()

# Two months of the window are consumed by the climate lags the model needs
# (lag1 and lag2), so they can never themselves be forecast.
LAG_MONTHS = 2

# How far past the current month the outlook may be asked to reach. The seasonal
# endpoint will answer for 217 days, but ensemble skill at that range is poor
# enough that offering it would imply a confidence the forecast does not have.
MAX_OUTLOOK_MONTHS = 3


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _shift_months(d: date, n: int) -> date:
    """Move `n` months from a month start, without a calendar dependency."""
    total = (d.year * 12 + d.month - 1) + n
    return date(total // 12, total % 12 + 1, 1)


@router.get("/climate", tags=["climate"])
def district_climate(
    district: str = Query(..., description="District name, exactly as listed."),
    months: int = Query(3, ge=1, le=12,
                        description="How many months to mark for forecast."),
    end: date | None = Query(None,
                             description="Last month to return. Defaults to the "
                                         "most recent month the source can serve."),
    db: Session = Depends(get_db),
):
    """Monthly climate for one district, shaped for `POST /predict`.

    Returns `months` forecastable months plus the two earlier months the chain
    needs to build its climate lags, flagged `forecast: false`.

    `end` defaults to **next month**, so the default answer covers the month in
    progress and the one ahead. Days already recorded come from the reanalysis
    archive; days still to come are stitched from the 16-day forecast and then
    the seasonal ensemble. Each month therefore carries a `provenance` of
    `observed`, `partly observed` or `projected`, and a `complete` flag — a month
    missing days under-reports rainfall, which is a sum rather than a mean.
    """
    d = db.query(District).filter(District.name == district).first()
    if d is None:
        raise HTTPException(404, f"Unknown district: {district}")

    today = date.today()
    this_month = _month_start(today)

    # The default reaches one month past the one in progress. An early-warning
    # system is asked "what is happening, and what is coming"; defaulting to the
    # current month answers only the first half, and defaulting to the last
    # finished month answers neither.
    last = _month_start(end) if end else _shift_months(this_month, 1)
    first = _shift_months(last, -(months + LAG_MONTHS - 1))
    ceiling = _shift_months(this_month, MAX_OUTLOOK_MONTHS)

    if last > ceiling:
        raise HTTPException(
            422,
            f"{last:%Y-%m} is beyond the forecast horizon. Climate is projected "
            f"at most {MAX_OUTLOOK_MONTHS} months past the current one, so the "
            f"furthest month available is {ceiling:%Y-%m}.",
        )

    # The window must cover whole months at both ends for the aggregate to mean
    # anything: start on the 1st, stop on the last day of `last`.
    start_day = first
    end_day = _shift_months(last, 1) - timedelta(days=1)

    # `shp_lat` / `shp_lon` are transposed in the source file; the weather API
    # needs real coordinates, so they are swapped back here (see routers/districts).
    lat, lon = d.shp_lon, d.shp_lat
    source_name = mlops_settings.climate_source
    parts = []

    # ── Days that have happened ──────────────────────────────────────────────
    if start_day <= today:
        try:
            source = get_source(source_name)
            observed = source.fetch(district=d.name, lat=lat, lon=lon,
                                    start=start_day, end=min(end_day, today))
        except Exception as exc:                               # noqa: BLE001
            raise HTTPException(
                502,
                f"Climate source '{source_name}' failed for {district}: {exc}",
            ) from exc
        if observed is not None and not observed.empty:
            observed = observed.copy()
            observed["provenance"] = "observed"
            parts.append(observed)

    # ── Days that have not ───────────────────────────────────────────────────
    if end_day > today:
        try:
            parts.append(fetch_outlook(d.name, lat, lon, through=end_day))
        except Exception as exc:                               # noqa: BLE001
            raise HTTPException(
                502,
                f"Forward climate unavailable for {district}: {exc}",
            ) from exc

    if not parts:
        raise HTTPException(
            404,
            f"No climate available for {district} between {start_day} and {end_day}.",
        )

    daily = pd.concat(parts, ignore_index=True)
    daily["Date"] = pd.to_datetime(daily["Date"])
    # The archive and the forecast overlap on today; a measurement outranks a
    # projection for the same day.
    order = {"observed": 0, "forecast": 1, "seasonal": 2}
    daily["_r"] = daily.provenance.map(order).fillna(9)
    daily = (daily.sort_values(["Date", "_r"])
                  .drop_duplicates("Date", keep="first")
                  .drop(columns="_r"))

    # Same aggregation as training: means for state variables, sum for rainfall.
    monthly = feat.daily_to_monthly(daily).sort_values(["year", "month"])
    if monthly.empty:
        raise HTTPException(404, f"No complete month for {district} in the window.")

    # Carry provenance through the aggregation: a month stitched from measured
    # and projected days is neither, and must not be presented as either.
    prov = (daily.assign(year=daily.Date.dt.year, month=daily.Date.dt.month)
                 .groupby(["year", "month"])["provenance"]
                 .agg(lambda v: "observed" if set(v) == {"observed"}
                      else "projected" if "observed" not in set(v)
                      else "partly observed")
                 .to_dict())

    readings = []
    for row in monthly.itertuples():
        y, mth = int(row.year), int(row.month)
        m_start = date(y, mth, 1)
        n_days = int(row.n_days)
        in_month = calendar.monthrange(y, mth)[1]
        readings.append({
            "year": y,
            "month": mth,
            "temperature_c": round(float(row.Temperature_C), 2),
            "humidity_pct": round(float(row.Humidity_pct), 2),
            "pressure_hpa": round(float(row.Pressure_hPa), 2),
            "precipitation_mm": round(float(row.Precipitation_mm), 2),
            "n_days": n_days,
            "days_in_month": in_month,
            # Rainfall is a sum, so a month missing days under-reports it badly.
            # Flagging the shortfall is more honest than scaling it up.
            "complete": n_days == in_month,
            "provenance": prov.get((y, mth), "unknown"),
            # The first LAG_MONTHS months exist only to supply lags.
            "forecast": m_start >= _shift_months(first, LAG_MONTHS),
        })

    n_forecast = sum(1 for r in readings if r["forecast"])
    if n_forecast == 0:
        raise HTTPException(
            404,
            f"Only {len(readings)} month(s) available for {district}; at least "
            f"{LAG_MONTHS + 1} are needed (two supply the climate lags).",
        )

    scored = [r for r in readings if r["forecast"]]
    return {
        "district": d.name,
        "region": d.region,
        "lat": lat,
        "lon": lon,
        "source": source_name,
        "window": {"start": str(start_day), "end": str(end_day)},
        "n_forecast_months": n_forecast,
        # A caller that shows only one badge should show the weakest one.
        "provenance": ("observed" if all(r["provenance"] == "observed" for r in scored)
                       else "projected" if all(r["provenance"] == "projected" for r in scored)
                       else "partly observed"),
        "incomplete_months": [f"{r['year']}-{r['month']:02d}"
                              for r in scored if not r["complete"]],
        "readings": readings,
    }
