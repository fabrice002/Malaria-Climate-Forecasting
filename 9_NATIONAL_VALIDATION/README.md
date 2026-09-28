# 9_NATIONAL_VALIDATION

External validation across **195 districts in all 10 regions**, using the
`dataset/` DHIS2 export as ground truth for 2024–2025.

Until now the project's only external test was a single district (Foumban). This
extends it nationally — which directly attacks the thesis's biggest open question,
whether the model transfers spatially.

```
9_NATIONAL_VALIDATION/
├── fetch_climate_2023_2025.py        run this FIRST (~30 min, no API key)
├── national_spatial_validation.ipynb ★ the evaluation
├── climate_districts_2023_2025.csv   produced by the fetch
├── figures/                          produced by the notebook
└── national_validation_results.json  produced by the notebook
```

## Results

**194 districts × 2 years = 388 district-years**, all 10 regions.

| Statistic | Value | Random baseline |
|---|---|---|
| **Spearman ρ (pooled)** | **+0.859** | 0.00 |
| Kendall τ (pooled) | +0.669 | 0.00 |
| **Top-25 % targeting recall** | **0.679** | 0.25 |
| Within-region ρ (median) | +0.708 | 0.00 |
| Between-region ρ | +0.915 | 0.00 |
| *Ground-truth year-to-year stability* | *+0.971* | — |

**The model ranks districts well on genuinely unseen data.** It places 68 % of the
truly worst-quartile districts in its own worst quartile, against 25 % by chance.
Within-region ranking — the harder task, since it strips out the national burden
gradient — still reaches ρ = 0.708, ranging from Littoral (+0.940) down to
Adamaoua (+0.265).

**This substantially softens the Leave-One-Region-Out pessimism.** Internal LORO
reported mean F1 0.372 and mean R² −0.461 and was read as "the model does not
transfer spatially". On real out-of-sample data the spatial *ordering* transfers
well. The two are compatible: LORO measured absolute per-month classification,
this measures relative annual ranking, and the latter is what targeting decisions
actually need.

**But it does not beat the trivial baseline.** The ground truth is 97 % stable
year to year (ρ = 0.971), so "rank districts by last year's reported cases" scores
higher than the model's 0.859. The model's value is not that it beats historical
data — it is that it needs **no case reporting at all**, which is the situation in
districts that do not report.

**The between/within gap (+0.207) confirms geography dominance.** The model knows
which *region* is worse (ρ = 0.915) better than which district inside it
(ρ = 0.708) — the expected signature of `SHP_lat`/`SHP_lon`/`SHP_Area`/`cluster`
carrying most of the feature importance.

The median predicted/actual ratio is **1.80×**, consistent with the simple-versus-
total case definition gap explained below, and exactly why the evaluation is
rank-based.

## Run it

```bash
cd 9_NATIONAL_VALIDATION
python fetch_climate_2023_2025.py     # ~40 min: 195 districts × 3 years, ERA5
jupyter lab national_spatial_validation.ipynb    # Cell → Run All, ~30 s
```

The fetch is resumable (`--resume`) and can be prototyped (`--limit 10`).
Open-Meteo rate-limits by data volume, so it may take two or three `--resume`
passes to complete; 194 of 195 districts were retrieved this way.

---

## What the `dataset/` folder actually contains

10 regional DHIS2 exports (`NDR_<Region>_data_14072026.xls`), one sheet each:

| Property | Value |
|---|---|
| Rows | 824 = 206 districts × 4 years |
| Columns | 47 indicators (ANC, IPT, bed nets, suspected/confirmed cases, treatments, deaths) |
| Granularity | **Annual** — one row per district-year |
| Years with data | **2024 and 2025 only** (2023 and 2026 rows exist but are empty) |
| Usable observations | **412** district-years |
| Districts matching the models | **195 of 206** after stripping the `District ` prefix |

Header is on **row 1**, not row 0. Read with
`pd.read_excel(f, engine='xlrd', sheet_name='Sheet 1', header=1)`.

## Three obstacles, and how each is handled

### 1 · The indicator is half the size of what the models predict

`04.1.4.Cas de paludisme simple confirmes` is **simple cases only**:

| Source | Indicator | Foumban 2024 |
|---|---|---|
| `dataset/` `04.1.4` | simple confirmed | 10 164 |
| PNLP xls row 11 | simple confirmed | 9 880 |
| PNLP xls row 10 | **grave** confirmed | 11 777 |
| PNLP xls row 7 | **FOSA + Communauté** (total) | 21 657 |
| — | row 10 + row 11 | 21 657 ✔ |

`04.1.4` matches the simple-only row to within 3 %, so it is roughly **half** the
total-confirmed definition the models were trained and evaluated on. The export's
severe-case columns (`09.4.3`, `09.4.6`, `09.4.7`) are **empty**, so the total
cannot be reconstructed.

**Handled by evaluating ranks, not levels.** Spearman ρ, Kendall τ and
top-quartile targeting recall are all invariant to a constant scale factor, so the
~2× definitional gap cancels out entirely. Comparing absolute values instead would
manufacture a spurious 2× over-prediction that says nothing about the model.

### 2 · There was no climate data for 2024–2025

`cameroon_districts_climate.csv` stops at 2022-02; only Foumban and Yaoundé had
anything later. `fetch_climate_2023_2025.py` closes the gap from **Open-Meteo
Historical (ERA5)** — the same source as the training climate, so the reanalysis
product is consistent. 2023 is fetched but never scored: it exists only to supply
the climate lags that feed January 2024.

**Validated against the existing Foumban file** over the 1 096 overlapping days:

| Variable | Correlation | MAE |
|---|---|---|
| Temperature | 0.995 | 0.57 °C |
| Humidity | 0.998 | 1.06 % |
| Pressure | 0.999 | 2.21 hPa |
| Precipitation | 0.900 | 1.61 mm |

Small offsets are expected — the two fetches resolve to slightly different ERA5
grid points. This also confirms the coordinate handling is right (see below).

### 3 · Annual granularity rules out the interesting experiments

With one observation per district-year there is no way to validate seasonality,
month-level accuracy, or any of the lag / recursive / sliding-window strategies
from `8_FOUMBAN_EXPERIMENTS/` — those all need monthly case history. The notebook
therefore sums 12 monthly predictions into an annual total and compares that.

Note this **flatters the model**: monthly errors of opposite sign partly cancel in
an annual sum.

## ⚠️ The transposed coordinates

`district_static.csv` has `SHP_lat` and `SHP_lon` **swapped** — the column named
`SHP_lat` holds the longitude. Verified against five known towns: swapping gives a
~0.06° match, taking them as named is off by 7–18°.

Two consequences, in opposite directions:

- **The fetch script swaps them back**, because Open-Meteo needs real coordinates.
- **The notebook passes them through unchanged**, because that is the convention
  the models were trained with. Swapping them before inference would silently
  corrupt every prediction.

## What this test can and cannot establish

**Can** — whether spatial *ordering* transfers to unseen districts and later years;
whether transfer is uniform across regions; which districts are systematically
mis-ranked; whether the internal LORO pessimism (mean F1 0.372, R² −0.461) holds
up against real out-of-sample data.

**Cannot** — absolute calibration (definitions differ ~2×); seasonality or monthly
accuracy (annual data); anything about lag-based or recursive forecasting.

## To make this a full like-for-like external test

Re-export from DHIS2 including the **severe** case indicators, so
`simple + grave` reconstructs the total-confirmed definition the models predict.
That would unlock absolute MAE/MAPE/R² alongside the rank statistics. Monthly
rather than annual periodicity would additionally unlock every experiment in
`8_FOUMBAN_EXPERIMENTS/` across all 195 districts.
