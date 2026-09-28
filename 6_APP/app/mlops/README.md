# MLOps platform — malaria early-warning system

Turning the application into an autonomous operational platform:
collection → validation → features → prediction → storage → monitoring, with no
manual intervention.

---

## 1 · What existed before the migration

### Already working

| Component | Where | State |
|---|---|---|
| Inference chain | `app/services/inference.py` | ✅ automatic (NO-LAG → recursive LAG) |
| SHAP explainability | `app/services/explain.py` | ✅ automatic |
| REST API | `app/routers/predictions.py` | ✅ 7 endpoints |
| Data schema | `app/models/orm.py` | ✅ 6 tables |
| Dashboard | `frontend/` | ✅ map + panel + SHAP |
| Model bundle | `deployment_bundle/` | ✅ 4 versioned models |

### What was manual — the real problem

| Step | How it happened |
|---|---|
| **Climate collection** | 4 standalone, unintegrated scripts: `te/climate_fetch.py`, `fetch_climate_yaounde_recent.py`, `foum.py`, `9_NATIONAL_VALIDATION/fetch_climate_2023_2025.py` — run by hand, each with its own logic |
| **Validation** | non-existent; an aberrant value went straight to the model |
| **Aggregation & features** | reimplemented across ~10 notebooks, with divergences (*training/serving skew*) |
| **Triggering** | 100 % human: somebody had to decide to run a prediction |
| **Traceability** | none; impossible to know why an alert had been raised |
| **Drift** | never measured, although the project contains a major undetected case |

### The actual data flow

```
PNLP (.csv / .xls)  ─┐
                     ├─► fusion (fuzzy match 197↔118) ─► features ─► models
Open-Meteo (ERA5) ───┘                                                  │
                                                                        ▼
                                            deployment_bundle/ ──► API ──► dashboard
```

---

## 2 · The target architecture

```
        ┌─────────────────────────────────────────────────────────────┐
        │  SCHEDULER      monthly cron + new-data detection (6 h)      │
        └───────────────────────────┬─────────────────────────────────┘
                                    ▼
   ┌────────────┐   ┌────────────┐   ┌──────────┐   ┌────────────┐   ┌──────────┐
   │ INGESTION  │──►│ VALIDATION │──►│ FEATURES │──►│ PREDICTION │──►│ STORAGE  │
   │ sources/   │   │  blocking  │   │  shared  │   │  registry  │   │ + trace  │
   └─────┬──────┘   └─────┬──────┘   └────┬─────┘   └─────┬──────┘   └────┬─────┘
         │                │               │               │               │
         ▼                ▼               ▼               ▼               ▼
   open_meteo      data_quality      DYNAMIC_       model_versions   pipeline_runs
   nasa_power       (blocking)       FEATURES                        drift_reports
   csv / IoT                                                              │
                                                                          ▼
                                                          MONITORING ──► DASHBOARD
                                                          PSI · KS · timings · failures
```

### Mapping to the requested MLOps building blocks

| Block | Implementation | State |
|---|---|---|
| Data Ingestion | `sources/` + `orchestrator._stage_ingest` | ✅ |
| Data Validation | `stages/validation.py` (16 checks, blocking) | ✅ |
| Feature Engineering | `stages/features.py` — **single implementation** | ✅ |
| Model Serving | `services/inference.py` + `orchestrator._stage_predict` | ✅ |
| Monitoring | `monitoring/drift.py` + `pipeline_runs` / `data_quality` tables | ✅ |
| Drift Detection | PSI + Kolmogorov-Smirnov (data), Mann-Whitney (performance) | ✅ |
| Orchestration | `orchestrator.py` + `scheduler.py` | ✅ |
| Dashboard | `/mlops/*` endpoints ready to consume | ✅ API |
| Model Registry | `model_versions` table (schema) | 🟡 schema only |
| Data Versioning | not implemented — see "next" | ⬜ |
| Retraining Pipeline | not implemented — see "next" | ⬜ |

---

## 3 · Changing the data source

**This was the explicit requirement: make switching easy.** One environment
variable is enough; no code to change:

```bash
MEWS_CLIMATE_SOURCE=open_meteo    # default — ERA5 reanalysis
MEWS_CLIMATE_SOURCE=nasa_power    # cross-check source
MEWS_CLIMATE_SOURCE=csv MEWS_CSV_SOURCE_PATH=/data/iot   # IoT drops / replay
```

Adding a source amounts to writing a class:

```python
from app.mlops.sources.base import ClimateSource, register_source

@register_source("my_sensor")
class MySensor(ClimateSource):
    def fetch(self, district, lat, lon, start, end) -> pd.DataFrame:
        ...   # return the shared schema; nothing downstream changes
```

The shared schema is the training file's
(`Location, Date, Temperature_C, Humidity_pct, Pressure_hPa, Precipitation_mm`),
so nothing downstream has to adapt. `GET /api/v1/mlops/sources` lists the
registered sources and the active one.

### Integrating the existing collection module

`9_NATIONAL_VALIDATION/fetch_climate_2023_2025.py` — written for the national
validation — became `sources/open_meteo.py`, now a service of the pipeline:
batching, per-district fallback, and a back-off specific to the HTTP 429 quota
(the API weights each request by the volume returned, as observed in production
across the 195 districts). It is called automatically, and is configurable by
district, period and source.

---

## 4 · Usage

### Running the pipeline

```bash
# Manual, a few districts
curl -X POST localhost:8000/api/v1/mlops/run \
  -H 'Content-Type: application/json' \
  -d '{"districts": ["Foumban", "Bafia"]}'

# Backfill a past period (replayable, idempotent)
curl -X POST localhost:8000/api/v1/mlops/run \
  -d '{"start": "2024-01-01", "end": "2025-12-31", "background": true}'
```

### Autonomous mode

```bash
MEWS_SCHEDULER_ENABLED=true python serve_all.py
```

Two triggers:

* **monthly cron** (`MEWS_SCHEDULE_CRON`, default `0 3 2 * *`) — the 2nd of the
  month at 03:00, giving ERA5 time to publish the month just ended;
* **new-data detection** every 6 h — compares the last predicted month against
  what the source exposes, and only starts the pipeline when there is something
  new. Essential for the `csv` source, which has no publication calendar.

### Monitoring

| Endpoint | Returns |
|---|---|
| `GET /mlops/health` | success rate, mean duration **per stage**, current major drifts |
| `GET /mlops/runs` | full history, failures included |
| `GET /mlops/drift` | PSI and KS per feature, over time |
| `GET /mlops/drift/performance` | concept drift, where ground truth exists |
| `GET /mlops/sources` | available / active sources |
| `GET /mlops/scheduler` | state and next scheduled runs |

---

## 5 · Design decisions

**Validation is blocking.** A failed critical check stops the run before the
model. Aberrant data caught costs a log line; the same data passed to the model
produces a false health alert. The bounds come from the training distribution
(136 290 readings), not arbitrary values.

**One single feature implementation.** `stages/features.py` is the source of
truth for the daily→monthly aggregation, the seasonal encoding and the lags.
That is the protection against *training/serving skew* — the costliest and most
silent failure mode of an ML system.

**Runs are idempotent.** Replaying a window replaces the predictions for the same
district-month. Verified: two identical runs leave 44 predictions in the
database, not 88.

**Drift monitors dynamic features only.** `SHP_lat`, `SHP_lon`, `SHP_Area` and
`cluster` are constant per district: their PSI would only measure which subset of
districts was processed, and would raise "major drift" on every partial run. Only
climate and seasonality are tracked (`features.DYNAMIC_FEATURES`).

**The pipeline ignores the database.** `orchestrator.py` returns its results;
`service.py` persists them. The pipeline is therefore testable without a
database.

**The automated pipeline uses the NO-LAG model.** It runs without reported case
history. As soon as a district declares real cases, the API switches to the
recursive chain (`services/inference.predict_chain`), which is markedly more
accurate — the Foumban study measures the gap: MAE 664 → 261 (−61 %).

**All timestamps are timezone-aware.** `app/utils.utc_now()` wraps
`datetime.now(UTC)`; the matching columns are `DateTime(timezone=True)`. Python
3.12 deprecates `datetime.utcnow()` precisely because it returned a *naive*
value that merely happened to hold UTC, which breaks silently when compared with
an aware one.

**⚠️ `SHP_lat`/`SHP_lon` are transposed in the static file.** They are put back
the right way round **only** to call the weather API (`orchestrator._targets`)
and for the map. The features pass them through unchanged, because that is the
training convention: correcting them would break every prediction.

---

## 6 · Verified

`python test_mlops.py` covers the whole chain, offline (`csv` source):

| Check | Result |
|---|---|
| Source registry | 3 sources registered and instantiable |
| Collection | 1 462 rows, 2 districts, schema conforms |
| Validation, nominal | 16/16 checks passed |
| Validation, corrupted data | correctly rejected on `bounds::Temperature_C` |
| Features | 48 months built → 44 scorable (missing lags dropped) |
| Full pipeline | `success`, 44 predictions, 4 stages timed |
| Backfill via API | `success`, run traced in the database |
| **Idempotence** | replay → 44 in the database, not 88 |
| Drift, identical distribution | max PSI 0.13 → no alert |
| Drift, shifted distribution | max PSI 9.0 → major alert |
| `/mlops/*` endpoints | 6/6 returning HTTP 200 |

---

## 7 · Next

In order of value:

1. **Retraining pipeline** — the `model_versions` schema exists; what is missing
   is the trigger on major drift, the retrain itself, *challenger vs champion*
   validation and promotion. Prerequisite: at least
   `MEWS_RETRAIN_MIN_NEW_MONTHS` of ground truth. The parameters are measured in
   `11_FOUMBAN_INCREMENTAL/`.
2. **Data versioning** — a digest of the ingested batch per run, so the exact
   input of any past prediction can be replayed (DVC, or a manifest table).
3. **Monitoring page in the dashboard** — the endpoints are ready; the screen
   (PSI curves, per-stage timings, run log) is not.
4. **Alerting** — notify on pipeline failure or major drift.
5. **Real-case ingestion** — PNLP cases arrive as files today. Bringing them in
   as a source would trigger the recursive chain automatically, with the accuracy
   gain measured on Foumban.
