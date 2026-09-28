# 1_DATA — input files

The six files everything else is built from. Nothing here is derived; these are
the raw sources.

| File | Size | Coverage | Used by |
|---|---|---|---|
| `PNLP_AS_COMPLETE_WITH_FILL_NA_ok_5.csv` | 5.0 MB | 1 795 health areas × 859 cols, Jan 2019 – Feb 2022 | every modelling notebook |
| `cameroon_districts_climate.csv` | 5.5 MB | 136 290 daily rows, 118 locations, Jan 2019 – Feb 2022 | every modelling notebook |
| `yaounde_climate_2026_apr_jun.csv` | 7 KB | 139 daily rows, 1 Feb – 19 Jun 2026 | Yaoundé EDA + 2026 forecast |
| `cameroon_climate_foumban_2022_2026.csv` | 60 KB | Sep 2022 – 2026, Foumban | external test |
| `Données PNLP 2023_2024_2025 - ok.xls` | 32 KB | 3 sheets × 12 months, Foumban | external test ground truth |
| `meteo_log.csv` | 265 KB | 1 567 readings at 180 s, 20–28 Apr 2026, one Meshtastic node | [`12_SENSOR_VALIDATION/`](../12_SENSOR_VALIDATION/) |

---

## PNLP surveillance data

Health-area rows (`as_name`), each carrying district, region, geography
(`SHP_lat`, `SHP_lon`, `SHP_Area` — **decimal comma**, must be converted), population
(`p_totale`), a precomputed UMAP/PCA `cluster` label, and **wide monthly indicator
columns** named `<Mon>_<Year>_MAPE16_H_<n>` with French month abbreviations
(`Jan Fev Mar Avr Mai Jun Jul Aug Sep Oct Nov Dec`).

**The thesis uses the `MAPE16_H_13` family** — 38 monthly columns of confirmed
malaria cases. Read it with `sep=';'`.

```python
df = pd.read_csv('PNLP_AS_COMPLETE_WITH_FILL_NA_ok_5.csv', sep=';')
mape_cols = [c for c in df.columns if 'MAPE16_H_13' in c]   # 38 columns
```

Other `MAPE16_H_*` families exist (`_10`, `_24`) — earlier notebooks experimented
with them before `malaria_v2_pipeline` settled on `_13`.

## Climate data

Daily reanalysis: `Location`, `Date`, `Temperature_C`, `Humidity_%`,
`Pressure_hPa`, `Precipitation_mm`.

**Provenance:** Open-Meteo Historical (ERA5) as the primary source, cross-checked
against NASA POWER. No API keys required. The fetch scripts live in the original
project (`te/climate_fetch.py`, `fetch_climate_yaounde_recent.py`, `foum.py`).

Aggregate to monthly with **means** for temperature / humidity / pressure and a
**sum** for precipitation — it is a flux, not a state.

## Joining the two

197 districts must be matched onto 118 climate locations. Three passes: exact name
match → a hand-curated 10-entry correction map (`Garoua II→Garoua I`, `Maga→Mada`,
`Batcham→Baham`, …) → `rapidfuzz` `token_sort_ratio` accepted at **≥ 55**.

⚠️ That threshold is permissive, and some accepted pairs (`Manoka→Manjo`,
`Ndom→Ndop`) are name-similarity matches between genuinely different places. A
known, unquantified source of climate-attribution noise — see the
limitations discussed in the thesis, `../docs/memoirthesis.pdf`.

The complete fusion is implemented once, readably, as `build_panel()` in
`3_REGENERATE_FIGURES/generate_all_figures.ipynb`.

## A note on the 2026 file

The original project has two copies of `yaounde_climate_2026_apr_jun.csv` with the
same name but different coverage: a root copy spanning 2019–2026 (2 727 rows) and a
139-row copy holding only the deployment window. **This package ships the 139-row
version**, which is what the published figures were built from. The regeneration
notebook also filters to `Date >= 2026-02-01`, so either would work.

---

## IoT sensor log

`meteo_log.csv` is the first real capture from the deployed mesh network, node
`!a0cb4a5c`. One row per received packet:

* `time_utc` — **UTC**, so add one hour for Cameroon local time;
* `temperature`, `relative_humidity`, `barometric_pressure` — present on
  **half** the rows; the rest are link telemetry carrying only `rssi`, `snr`
  and `hops_away`;
* `gas_resistance`, `iaq`, `lux` — columns exist but the channels never
  reported;
* **there is no precipitation channel at all.**

Two things to know before using it. Only **one day** in the window is completely
sampled, so any daily or monthly mean drawn from it is sampling-biased. And the
readings carry a **+7.3 °C siting offset** against the reanalysis the models
were trained on, which is enough to move a forecast by 38 %. Both are
characterised, and the correction derived, in
[`12_SENSOR_VALIDATION/`](../12_SENSOR_VALIDATION/) — read that before
feeding this file to anything.
