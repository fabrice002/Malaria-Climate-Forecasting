# Malaria Early Warning System — backend architecture

Operational (deployment) phase of the thesis *"Malaria Prediction Based on
Environmental Data Collected Through IoT Sensors."* This service turns monthly
climate readings into malaria risk predictions using the trained model bundle,
and runs that conversion **autonomously** through an MLOps pipeline.

---

## 1 · System architecture

Three layers. Each can be run, tested and deployed on its own.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  PRESENTATION                                     frontend/  (no build step) │
│  Leaflet map (vendored) + Cameroon boundaries · district picker · SHAP chart  │
│  native ES modules, fetch against /api/v1                                    │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │  HTTP  (same origin via serve_all.py)
┌───────────────────────────────────▼─────────────────────────────────────────┐
│  API                                                       app/routers/      │
│  predictions.py · districts.py · climate.py · mlops.py    FastAPI + Pydantic │
└──────────┬───────────────────────────────────────────────┬──────────────────┘
           │                                               │
┌──────────▼────────────────────────┐   ┌──────────────────▼──────────────────┐
│  DOMAIN SERVICES     app/services/ │   │  MLOPS PLATFORM        app/mlops/   │
│                                    │   │                                     │
│  inference.py                      │   │  scheduler.py    cron + new-data     │
│    bundle loader                   │   │       │                              │
│    two-stage recursive chain       │   │       ▼                              │
│                                    │   │  orchestrator.py                     │
│  explain.py                        │   │    ingest -> validate -> features    │
│    SHAP TreeExplainer              │   │           -> predict                 │
│    + pred_contribs fallback        │   │       │                              │
│                                    │◄──┤       ▼                              │
│  (called on demand, one district)  │   │  service.py      persistence, drift  │
└──────────┬─────────────────────────┘   └──────────────────┬──────────────────┘
           │                                                │
┌──────────▼────────────────────────────────────────────────▼─────────────────┐
│  PERSISTENCE                                app/db/base.py · SQLAlchemy      │
│  app/models/orm.py   districts · raw_sensor_data · engineered_features       │
│                      predictions · shap_explanations · users                 │
│  app/mlops/orm.py    pipeline_runs · data_quality · drift_reports            │
│                      model_versions                                          │
│  SQLite by default · PostgreSQL/PostGIS by changing one env var              │
└─────────────────────────────────────────────────────────────────────────────┘

                 ▲                                    ▲
     deployment_bundle/                        app/mlops/sources/
     4 XGBoost models (.json)                  open_meteo · nasa_power · csv
     district_static.csv                       swappable by env var
     artifacts.json
```

### The two paths through the system

There are two ways a prediction gets made, and they are deliberately different:

| | **Interactive** (`POST /predict`) | **Autonomous** (pipeline) |
|---|---|---|
| Triggered by | a user, from the dashboard | the scheduler, or `POST /mlops/run` |
| Input | climate readings in the request | fetched from the active source |
| Model | NO-LAG, then **recursive LAG** | NO-LAG only |
| Why | the user supplies, or the DB holds, a case history | no reported case history exists at run time |
| Output | one district, N months, with SHAP | all districts, one month, persisted |

The recursive chain is markedly more accurate when a case history exists — the
Foumban study measures the gap at MAE 664 -> 261 (−61 %). As soon as a district
reports real cases, the interactive path is the one to use.

---

## 2 · The two-stage chain (core logic)

```
Month 1 (climate only, no case history)
   └─ NO-LAG model bootstraps  -> predicted cases_1
Month 2..N
   └─ LAG model runs recursively, feeding predicted cases back as cases_lag1.
      Real reported cases, when supplied, override the synthetic lag.
```

Both regressors predict `log_cases`; incidence and the **binary Low/High** risk
class are derived from predicted cases ÷ population against the district's
per-region 75th-percentile threshold.

Feature regimes:

| Regime | Count | Contents |
|---|---|---|
| RAW | 5 | the four climate variables + month |
| NO-LAG | 16 | RAW + seasonal encoding + geography + climate lags 1–2 |
| LAG | 20 | NO-LAG + `cases_lag1..3` + `incidence_lag1` |

---

## 3 · Directory layout

```
webapp/
├── serve_all.py            one-command launcher: API + frontend, single origin
├── test_mlops.py           end-to-end check of the platform, offline
├── README.md               start here
│
├── app/
│   ├── main.py               FastAPI app, startup, district seeding, /health
│   ├── config.py             settings (paths, DB URL, recursive flag)
│   ├── utils.py              utc_now() — timezone-aware timestamps
│   │
│   ├── db/base.py            engine, session factory, table creation
│   ├── models/orm.py         6 core tables
│   ├── schemas/              Pydantic request/response contracts
│   │
│   ├── services/
│   │   ├── inference.py      model bundle loader + recursive chain
│   │   ├── outlook.py        forward climate: 16-day forecast, then seasonal
│   │   └── explain.py        SHAP TreeExplainer + text summary
│   │
│   ├── routers/
│   │   ├── predictions.py    predict, history, SHAP, latest-per-district
│   │   ├── districts.py      district catalogue
│   │   ├── climate.py        climate for any district and period, for /predict
│   │   └── mlops.py          run, runs, health, drift, sources, scheduler
│   │
│   └── mlops/                the autonomous platform — see mlops/README.md
│       ├── orchestrator.py   stage chaining, timing, failure traces
│       ├── service.py        persistence + drift, the DB-facing half
│       ├── scheduler.py      APScheduler cron + 6-hourly new-data detection
│       ├── config.py         MEWS_* settings
│       ├── orm.py            4 platform tables
│       ├── sources/          base (registry) · open_meteo · nasa_power · csv
│       ├── stages/           validation (16 blocking checks) · features
│       └── monitoring/       drift.py — PSI, KS, Mann-Whitney, cross-check
│
├── deployment_bundle/      4 models (.json + .joblib) + district_static.csv
└── frontend/               see frontend/README.md
```

---

## 4 · Running it

```bash
pip install -r app/requirements.txt
python serve_all.py                     # API + dashboard on one origin
# open http://localhost:8000/
```

`serve_all.py` mounts the frontend under the API deliberately: browsers block ES
modules loaded over `file://`, and a separate static server would put the
dashboard on a different origin and reintroduce CORS. One origin, no CORS, no
build step.

API only:

```bash
uvicorn app.main:app --reload           # http://localhost:8000/docs
```

SQLite is the default so the service runs with no external dependency. For
PostgreSQL/PostGIS:

```bash
export MEWS_DATABASE_URL="postgresql+psycopg://user:pass@localhost:5432/malaria"
```

Autonomous mode, and swapping the climate source:

```bash
MEWS_SCHEDULER_ENABLED=true python serve_all.py
MEWS_CLIMATE_SOURCE=nasa_power python serve_all.py
```

---

## 5 · Endpoints (prefix `/api/v1`)

**Predictions**

| Method | Path | Purpose |
|---|---|---|
| GET  | `/health` | service + model status |
| POST | `/sensor-data` | store raw readings |
| POST | `/predict` | run the chain for one district, persist |
| GET  | `/predictions` | recent runs |
| GET  | `/predictions/latest` | latest prediction per district — feeds the map |
| GET  | `/prediction/{id}` | full detail of a run |
| GET  | `/prediction/{id}/shap` | SHAP explanation |
| GET  | `/history?district=` | per-district trend |
| GET  | `/districts`, `/districts/{name}` | district catalogue |
| GET  | `/climate?district=&months=&end=` | that district's climate for any period, past or up to 3 months ahead, shaped for `/predict` |

**MLOps**

| Method | Path | Purpose |
|---|---|---|
| POST | `/mlops/run` | trigger the pipeline (or backfill a past window) |
| GET  | `/mlops/runs` | execution history, failures included |
| GET  | `/mlops/health` | success rate, per-stage timings, current drifts |
| GET  | `/mlops/drift` | PSI and KS per feature, over time |
| GET  | `/mlops/drift/performance` | concept drift, where ground truth exists |
| GET  | `/mlops/sources` | available sources and the active one |
| GET  | `/mlops/scheduler` | scheduler state and next runs |

### Example `/predict` request

```json
{
  "readings": [
    {"district":"Mbalmayo","year":2026,"month":4,
     "temperature_c":24.1,"humidity_pct":78,
     "pressure_hpa":915,"precipitation_mm":150}
  ]
}
```

To override synthetic lags with real data, add `"real_cases": 1742` to any
reading; the chain re-anchors from that month forward.

---

## 6 · Design decisions worth knowing

**One feature implementation, `mlops/stages/features.py`.** The daily→monthly
aggregation, the seasonal encoding and the lags exist once. That is the
protection against *training/serving skew* — the costliest and most silent
failure mode of an ML system, and the reason the same code is reachable from
both the interactive and the autonomous path. `GET /climate` goes through it too,
rather than aggregating its own way, so a hand-driven forecast from the dashboard
and a pipeline run see identical inputs.

**Forecasting the month ahead needs weather that has not happened.** An
early-warning system that can only score past months is not one. `/climate`
therefore stitches three tiers by date — the reanalysis archive for days already
recorded, a 16-day forecast for the near term, then the seasonal ensemble — and
tags every month `observed`, `partly observed` or `projected`. The tiers live in
`services/outlook.py`, which is deliberately **not** a registered
`ClimateSource`: the MLOps pipeline must never train, score for the record, or
measure drift against predicted weather. Only the interactive path may look
forward.

**`GET /climate` reuses the MLOps source layer.** It could have called Open-Meteo
directly in a dozen lines. Going through `app.mlops.sources` instead means
switching provider stays a matter of setting `MEWS_CLIMATE_SOURCE`, and the
dashboard inherits the batching and the HTTP 429 back-off already written for the
pipeline. One collection implementation, not two.

**Models are loaded from `.json`, not `.joblib`.** Pickled XGBoost models from
older versions fail to load under xgboost ≥ 3.0 (`input stream corrupted`). The
`.json` exports were verified to give bit-identical predictions (max |Δ| = 0.0)
and are the format the code actually reads; the `.joblib` files are kept only for
provenance.

**SHAP has a fallback.** `shap.TreeExplainer` breaks on models saved by xgboost
≥ 3.0 (`could not convert string to float: '[5E-1]'`, because `base_score` is now
serialised as a one-element array). `explain.py` falls back to the booster's own
`pred_contribs=True`, which returns the same values.

**⚠️ `SHP_lat` / `SHP_lon` are transposed in `district_static.csv`.** Verified
against five known towns: swapped they match to ~0.06°, as-named they are off by
7–18°. They are corrected **only** at the boundaries that need real coordinates —
`GET /predictions/latest` for the map, and `orchestrator._targets` for the
weather API. The features pass them through **uncorrected**, because that is the
training convention: correcting them there would break every prediction.

**All timestamps are timezone-aware.** `app/utils.utc_now()` wraps
`datetime.now(UTC)` and the columns are `DateTime(timezone=True)`. Python 3.12
deprecates `datetime.utcnow()` precisely because it returned a *naive* value that
merely happened to hold UTC, which breaks silently on comparison with an aware
one.

**Feature vectors are stored per prediction.** Any past result can be re-explained
later without recomputing its inputs — the reproducibility requirement.

---

## 7 · Production notes

- **PostGIS**: swap the lat/lon floats on `districts` for a
  `Geometry(POINT, 4326)` column (GeoAlchemy2) to enable spatial queries and
  serve district polygons.
- **Migrations**: replace `init_db()` with Alembic.
- **Auth**: the `users` table + JWT (python-jose) gate the write endpoints.
- **Serving**: Uvicorn workers behind Nginx (TLS termination); containerised via
  the provided Dockerfile and `docker-compose.yml`.
- **Scaling**: the model bundle is stateless and loaded per process, so the API
  scales horizontally behind a load balancer. The scheduler must run in **one**
  process only.

## Contribution boundary

The IoT mesh network (LoRa/Meshtastic hardware, sensor nodes) is the deployment
substrate delivering climate readings; it is the collaborator's contribution.
This backend, the data-science feature pipeline, the model chain, the
explainability layer and the MLOps platform are the thesis author's contribution.
