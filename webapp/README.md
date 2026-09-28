# webapp — the prediction service and dashboard

The operational half of the thesis: a FastAPI backend that turns monthly climate
readings into malaria risk predictions, and a web dashboard for operators.

```
webapp/
├── app/                  FastAPI backend
├── frontend/             dashboard (see frontend/README.md)
├── deployment_bundle/    the 4 models + district_static + artifacts
└── docker-compose.yml    full stack: PostGIS + API + dashboard
```

> `app/README.md` (inside) is the original architecture document. **This file is
> the quick start** for running it from this package.

## Run the whole stack — no Docker needed

```bash
cd webapp
pip install -r app/requirements.txt
python serve_all.py
# dashboard  http://localhost:8000
# API docs   http://localhost:8000/docs
```

Serves the API and the dashboard on **one origin**, so no CORS configuration and
no second port.

> ⚠️ **Do not open `frontend/index.html` by double-clicking it.** Browsers block ES
> modules on `file://` (every such file is a separate security origin), so the page
> stays blank. It must be served over HTTP — that is all `serve_all.py` does.

## Run the whole stack with Docker

```bash
cd webapp
docker compose up --build
# dashboard  http://localhost:8080
# API docs   http://localhost:8000/docs
```

The dashboard's nginx proxies `/api` to the backend, so the browser stays on one
origin and CORS never comes into play.

## Run just the API

```bash
cd webapp
pip install -r app/requirements.txt
uvicorn app.main:app --reload
```

Then open **http://localhost:8000/docs** for the interactive Swagger UI.

That is the whole setup. It uses SQLite (`malaria.db`, created on first run) and
finds `deployment_bundle/` automatically — the models sit right next to `app/`,
which is exactly where `app/config.py` looks.

To add the dashboard without Docker, see [`frontend/README.md`](frontend/README.md).

## Try a prediction

```bash
curl -X POST http://localhost:8000/api/v1/predict \
  -H "Content-Type: application/json" \
  -d @app/sample_predict_request.json
```

Or paste this into `/docs`:

```json
{
  "readings": [
    {"district": "Mbalmayo", "year": 2026, "month": 4,
     "temperature_c": 24.1, "humidity_pct": 78,
     "pressure_hpa": 915, "precipitation_mm": 150}
  ]
}
```

You get back predicted cases, incidence per 1 000, the Low/High risk class, which
model was used (NO-LAG for month 1, LAG afterwards), and a SHAP explanation.

To supply real case counts and re-anchor the recursive chain, add
`"real_cases": 1742` to any reading — it overrides the synthetic lag from that
month forward.

**Verified working from this package** — booted, models loaded (197 districts),
sample request returned:

| Month | Model used | Predicted cases | Incidence | Risk |
|---|---|---|---|---|
| Apr 2026 | NO-LAG *(bootstrap)* | 1 238 | 9.49 /1000 | Low |
| May 2026 | LAG *(recursive)* | 1 158 | 8.88 /1000 | Low |
| Jun 2026 | LAG *(recursive)* | 1 098 | 8.42 /1000 | Low |

### `risk_level` and `risk_probability` can disagree — by design

In the response above, `risk_level` is **Low** while `risk_probability` is 0.68–0.86.
They come from different models and are not two views of the same number:

- **`risk_level`** is derived from the *regressor*: predicted cases ÷ population vs
  the district threshold (9.49 < 14.28 → Low). This is the authoritative signal.
- **`risk_probability`** is the *classifier*'s `P(high)`, and the classifier leans
  heavily on geographic features, so it can read high for a district that is
  structurally high-burden even when the predicted level for that month is not.

Treat `risk_level` as the alert and `risk_probability` as a secondary confidence
indicator. Do not present them side by side as if one validated the other — this is
the same tension discussed in the thesis, `../docs/memoirthesis.pdf`.

## Endpoints — `/api/v1`

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | service + model status |
| GET | `/districts` | district catalogue: coordinates, population, threshold |
| GET | `/districts/{name}` | one district |
| POST | `/sensor-data` | store raw IoT readings |
| POST | `/predict` | run the chain for one district, persist the result |
| GET | `/predictions` | recent runs |
| GET | `/prediction/{id}` | full detail of a run |
| GET | `/prediction/{id}/shap` | SHAP explanation for one forecast month |
| GET | `/history?district=` | per-district trend |

### Changes made to serve the dashboard

All additive; no existing behaviour and no scientific result changed.

- **`GET /districts`** (new `routers/districts.py`, `schemas/district.py`) — the
  map needs coordinates and thresholds; the table had them, nothing exposed them.
- **`prediction_id` on each `MonthlyPrediction`** — SHAP is keyed on it, so
  previously only a run's first month could be explained.
- **`/predict` returns the first month's id** — it used an unordered `.first()`,
  so the run id was arbitrary (a POST could report 1 while `/predictions` said 3).
- **SHAP compatibility fix** in `services/explain.py` — `shap ≤ 0.47` with
  `xgboost ≥ 3.0` made *every* SHAP request fail with
  `ValueError: could not convert string to float: '[5E-1]'`. Falls back to
  xgboost's own `pred_contribs`, which is the same TreeSHAP algorithm.
- **Coordinate correction** in `routers/districts.py` — `SHP_lat`/`SHP_lon` are
  transposed in `district_static.csv`. Verified against five known towns:
  swapping matches to ~0.06°, as-named is off by 7–18°. The models are unaffected
  (anonymous features, same convention throughout), but every map marker would
  otherwise land outside Cameroon.

## How it predicts

```
Month 1 (climate only, no case history)
   └─ NO-LAG model bootstraps          → predicted cases
Month 2 … N
   └─ LAG model runs recursively, feeding predicted cases back as cases_lag1
      Real reported cases, when supplied, override the synthetic lag
```

Both regressors predict `log_cases`; incidence and the Low/High class are derived
from predicted cases ÷ population against the district's per-region
75th-percentile threshold. The engineered feature vector is stored with every
prediction, so any past result can be re-explained later.

## Layout

```
webapp/
├── app/
│   ├── config.py                 settings (paths, DB URL, recursive flag)
│   ├── main.py                   FastAPI app, startup, district seeding
│   ├── db/base.py                engine, session, table creation
│   ├── models/orm.py             6 SQLAlchemy tables
│   ├── schemas/prediction.py     Pydantic request/response contract
│   ├── services/inference.py     model loader + recursive chain
│   ├── services/explain.py       SHAP TreeExplainer + text summary
│   ├── routers/predictions.py    all endpoints
│   ├── Dockerfile, docker-compose.yml, requirements.txt
│   └── sample_predict_request.json
└── deployment_bundle/            the 4 models + district_static + artifacts
```

`deployment_bundle/` is duplicated here (it also lives in `../models/`) so the
service runs standalone with no configuration. Override with
`MEWS_BUNDLE_DIR=/path/to/bundle` if you prefer a single copy.

## Configuration

Environment variables, all prefixed `MEWS_`:

| Variable | Default | Purpose |
|---|---|---|
| `MEWS_DATABASE_URL` | `sqlite:///./malaria.db` | PostgreSQL: `postgresql+psycopg://user:pass@host:5432/malaria` |
| `MEWS_BUNDLE_DIR` | `<app parent>/deployment_bundle` | model bundle location |
| `MEWS_ENABLE_RECURSIVE_CHAIN` | `true` | disable to use NO-LAG for every month |

## Before production

The service is a working skeleton, not a hardened deployment. It needs:

- **PostGIS** — swap the lat/lon floats on `districts` for `Geometry(POINT, 4326)`
  to enable spatial queries and serve district polygons
- **Alembic** migrations in place of `init_db()`
- **Auth** — the `users` table exists; JWT gating on write endpoints does not
- **Serving** — Uvicorn workers behind Nginx for TLS; the Dockerfile is provided

⚠️ `services/inference.py` loads the `.joblib` models. That works on the pinned
environment, but those files **fail under xgboost ≥ 3.0**. `.json` equivalents are
shipped in `deployment_bundle/` — switch to them before upgrading xgboost.

⚠️ Predictions are **relative risk within already-observed districts**, not
calibrated absolute incidence. The models did not transfer in the one external test
(see `../foumban_experiments/`). Do not deploy to a new region
without a local calibration period.

## Scope

Per `app/README.md`: the IoT mesh network (LoRa/Meshtastic hardware, sensor nodes)
is the collaborator's contribution. This backend, the data-science feature
pipeline, the model chain and the explainability layer are the thesis author's.
