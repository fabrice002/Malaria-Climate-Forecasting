"""
Fetch daily climate for every district in the national validation set, 2023-2025.

Why this is needed
------------------
`cameroon_districts_climate.csv` stops at 2022-02. The `dataset/` DHIS2 export
supplies malaria ground truth for 2024 and 2025, so scoring the models on it
requires climate covering those years (plus 2023, which supplies the climate lags
that feed January 2024).

Source: Open-Meteo Historical (ERA5) — the same source as the training climate,
so the reanalysis product is consistent. No API key required.

Output
------
`climate_districts_2023_2025.csv`, in exactly the schema of the training file:

    Location, Date, Temperature_C, Humidity_%, Pressure_hPa, Precipitation_mm

so it can be dropped straight into the existing pipeline.

Usage
-----
    python fetch_climate_2023_2025.py                 # all matched districts
    python fetch_climate_2023_2025.py --limit 10      # prototype on 10 first
    python fetch_climate_2023_2025.py --resume        # skip districts already saved
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd
import requests

# ── Configuration ────────────────────────────────────────────────────────────
HERE = Path(__file__).parent
ROOT = HERE.parent                          # the curated package
DATASET_DIR = ROOT.parent / "dataset"       # the raw DHIS2 exports
STATIC_CSV = ROOT / "models" / "protocol" / "district_static.csv"
OUT_CSV = HERE / "climate_districts_2023_2025.csv"

START, END = "2023-01-01", "2025-12-31"
API = "https://archive-api.open-meteo.com/v1/archive"
# Open-Meteo weights each request by the volume of data it returns, so a batch of
# 10 locations × 3 years × 4 variables counts as many "calls" against the free
# quota. Batches of 5 with a longer pause stay comfortably inside it; larger or
# faster settings return HTTP 429.
BATCH = 5                                   # locations per request (API accepts lists)
SLEEP_S = 6.0                               # be polite to a free service
MAX_RETRIES = 4

DAILY_VARS = [
    "temperature_2m_mean",
    "relative_humidity_2m_mean",
    "surface_pressure_mean",
    "precipitation_sum",
]

# Cameroon bounding box, used to catch transposed coordinates
LAT_RANGE, LON_RANGE = (1.5, 13.5), (8.0, 16.5)


# ── District list ────────────────────────────────────────────────────────────
def districts_to_fetch() -> pd.DataFrame:
    """Districts present in BOTH the DHIS2 export and the model's static table.

    Coordinates come from district_static.csv, where `SHP_lat` and `SHP_lon` are
    TRANSPOSED — the column named `SHP_lat` holds the longitude. Verified against
    five known towns: swapping matches to ~0.06 deg, taking them as named is off
    by 7-18 deg. The models consume both as anonymous features so training is
    unaffected, but anything geographic (including this fetch) must swap them.
    """
    static = pd.read_csv(STATIC_CSV)

    names = set()
    for f in sorted(DATASET_DIR.glob("*.xls")):
        d = pd.read_excel(f, engine="xlrd", sheet_name="Sheet 1", header=1)
        d = d.dropna(how="all")
        names |= {
            str(n).replace("District ", "").replace("DS ", "").strip()
            for n in d["organisationunitname"].dropna().unique()
        }

    matched = static[static["district"].isin(names)].copy()
    matched["lat"] = matched["SHP_lon"]      # <- transposed on purpose
    matched["lon"] = matched["SHP_lat"]

    bad = matched[
        ~matched["lat"].between(*LAT_RANGE) | ~matched["lon"].between(*LON_RANGE)
    ]
    if len(bad):
        print(f"  WARNING: {len(bad)} districts fall outside Cameroon after the "
              f"swap — check the coordinate convention:")
        for _, r in bad.head(5).iterrows():
            print(f"    {r['district']:<24} lat={r['lat']:.3f} lon={r['lon']:.3f}")

    print(f"  {len(names)} districts in the DHIS2 export")
    print(f"  {len(static)} districts known to the models")
    print(f"  {len(matched)} matched -> will be fetched")
    return matched[["district", "region", "lat", "lon"]].reset_index(drop=True)


# ── Fetch ────────────────────────────────────────────────────────────────────
def _block_to_frame(name: str, daily: dict) -> pd.DataFrame:
    """One location's `daily` block, in the training file's schema."""
    return pd.DataFrame({
        "Location": name,
        "Date": daily["time"],
        "Temperature_C": daily["temperature_2m_mean"],
        "Humidity_%": daily["relative_humidity_2m_mean"],
        "Pressure_hPa": daily["surface_pressure_mean"],
        "Precipitation_mm": daily["precipitation_sum"],
    })


def fetch_batch(rows: pd.DataFrame) -> list[pd.DataFrame]:
    """Fetch several districts in one request.

    Open-Meteo accepts comma-separated coordinate lists and then returns a JSON
    *array*, one block per location, in the order requested. Batching cuts the
    wall time roughly in half versus one request per district.
    """
    params = {
        "latitude": ",".join(f"{v:.5f}" for v in rows["lat"]),
        "longitude": ",".join(f"{v:.5f}" for v in rows["lon"]),
        "start_date": START,
        "end_date": END,
        "daily": ",".join(DAILY_VARS),
        "timezone": "Africa/Douala",
    }

    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(API, params=params, timeout=180)
            r.raise_for_status()
            payload = r.json()
            # A single-location request returns an object, not a list.
            blocks = payload if isinstance(payload, list) else [payload]
            if len(blocks) != len(rows):
                raise RuntimeError(
                    f"expected {len(rows)} blocks, got {len(blocks)}")
            return [_block_to_frame(name, b["daily"])
                    for name, b in zip(rows["district"], blocks)]
        except Exception as exc:                       # noqa: BLE001
            last_err = exc
            if attempt < MAX_RETRIES:
                # HTTP 429 means the quota window is exhausted; that needs a much
                # longer pause than a transient network error.
                rate_limited = "429" in str(exc)
                time.sleep((30 * attempt) if rate_limited else (2 ** attempt))
    raise RuntimeError(f"batch failed after {MAX_RETRIES} attempts — {last_err}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None,
                    help="fetch only the first N districts (prototyping)")
    ap.add_argument("--resume", action="store_true",
                    help="skip districts already present in the output file")
    args = ap.parse_args()

    print("Building the district list…")
    targets = districts_to_fetch()
    if args.limit:
        targets = targets.head(args.limit)
        print(f"  --limit {args.limit}: fetching {len(targets)} districts only")

    done, frames = set(), []
    if args.resume and OUT_CSV.exists():
        prev = pd.read_csv(OUT_CSV)
        frames.append(prev)
        done = set(prev["Location"].unique())
        print(f"  --resume: {len(done)} districts already saved, skipping them")

    todo = targets[~targets["district"].isin(done)].reset_index(drop=True)
    n_batches = (len(todo) + BATCH - 1) // BATCH
    print(f"\nFetching {len(todo)} districts in {n_batches} batches of {BATCH}, "
          f"{START} → {END}\n")

    failed = []
    t0 = time.time()
    for b in range(n_batches):
        chunk = todo.iloc[b * BATCH:(b + 1) * BATCH]
        try:
            frames.extend(fetch_batch(chunk))
            status = "ok"
        except Exception as exc:                       # noqa: BLE001
            # Fall back to one-at-a-time so a single bad coordinate cannot
            # take down the whole batch.
            status = "retry-single"
            for row in chunk.itertuples():
                try:
                    frames.extend(fetch_batch(
                        pd.DataFrame([{"district": row.district,
                                       "lat": row.lat, "lon": row.lon}])))
                except Exception as e2:                # noqa: BLE001
                    failed.append((row.district, str(e2)[:70]))
        el = time.time() - t0
        eta = el / (b + 1) * (n_batches - b - 1)
        print(f"  batch {b+1:>2}/{n_batches}  {len(chunk):>2} districts  {status:<12} "
              f"elapsed {el/60:.1f}m  eta {eta/60:.1f}m")
        time.sleep(SLEEP_S)

    if not frames:
        print("Nothing fetched.")
        return 1

    out = pd.concat(frames, ignore_index=True)
    out["Date"] = pd.to_datetime(out["Date"])
    out = out.sort_values(["Location", "Date"]).reset_index(drop=True)
    out.to_csv(OUT_CSV, index=False)

    print(f"\nWrote {OUT_CSV.name}")
    print(f"  {len(out):,} daily rows · {out.Location.nunique()} districts · "
          f"{out.Date.min():%Y-%m-%d} → {out.Date.max():%Y-%m-%d}")
    print(f"  missing values per column:\n{out.isna().sum().to_string()}")
    if failed:
        print(f"\n  {len(failed)} district(s) FAILED — re-run with --resume:")
        for n, e in failed[:10]:
            print(f"    {n}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
