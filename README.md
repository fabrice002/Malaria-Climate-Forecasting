# Malaria Prediction from Environmental Data

**Climate-based malaria forecasting for Cameroon health districts, with an IoT acquisition layer**

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![scikit-learn](https://img.shields.io/badge/scikit--learn-1.8-f7931e.svg)](https://scikit-learn.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688.svg)](https://fastapi.tiangolo.com/)
[![Thesis PDF](https://img.shields.io/badge/thesis-PDF-red.svg)](docs/memoirthesis.pdf)

Master's thesis — *Malaria Prediction Based on Environmental Data Collected
Through Internet of Things (IoT) Sensors* — by **Ouandji Njanang Herve Fabrice**,
Department of Computer Engineering, National Advanced School of Engineering of
Yaoundé (ENSPY), University of Yaoundé I. Supervised by Dr Chana Anne Marie.

Everything needed to understand, reproduce and continue this work is in this
repository: the data, the notebooks, the trained models, the API and dashboard
that serve them, and five follow-up studies that test where the model breaks.

📄 **The full thesis is at [`docs/memoirthesis.pdf`](docs/memoirthesis.pdf).**

---

## Start here

| If you want to… | Go to |
|---|---|
| **Read the research in full** | [`docs/memoirthesis.pdf`](docs/memoirthesis.pdf) |
| **Get the results in 5 minutes** | [§ The research in one page](#the-research-in-one-page) below |
| **Regenerate every thesis figure** | [`figure_regeneration/`](figure_regeneration/) — open the notebook, Run All |
| **Run the API + dashboard** | [`webapp/`](webapp/) — `python serve_all.py` |
| **Read the methodology notebook** | [`notebooks/1_malaria_full_protocol.ipynb`](notebooks/1_malaria_full_protocol.ipynb) |
| **See how far the model actually transfers** | [`national_validation/`](national_validation/) and [`foumban_experiments/`](foumban_experiments/) |
| **Set up the IoT network and MQTT feed** | [`iot_acquisition/SETUP_GUIDE.md`](iot_acquisition/SETUP_GUIDE.md) |
| **Understand the software architecture** | [§ Architecture](#architecture) below, then [`webapp/app/README.md`](webapp/app/README.md) |
| **Understand the MLOps platform** | [`webapp/app/mlops/README.md`](webapp/app/mlops/README.md) |

Every top-level folder has its own `README.md` explaining what is in it, how it was
produced and what it concluded. Those are the primary documentation.

---

## Repository layout

```
.
├── README.md                     ← you are here
├── LICENSE                       MIT
├── CITATION.cff                  how to cite this work
├── requirements.txt              pinned, verified environment
│
├── docs/
│   └── memoirthesis.pdf              the thesis
│
├── data/                             6 input files (the only data you need)
│
├── figures/
│   ├── thesis_figures/               the 19 figures used in the thesis
│   └── regenerated/                  output of figure_regeneration (starts empty)
│
├── figure_regeneration/
│   └── generate_all_figures.ipynb    ★ one notebook → all 19 figures, ~11 min
│
├── notebooks/                        9 original notebooks, numbered in workflow order
│
├── models/
│   ├── protocol/                     the thesis models (Optuna-tuned)
│   └── deployment_bundle/            the 4 operational models
│
├── webapp/                           API + dashboard, runs out of the box
│   ├── app/                          FastAPI backend
│   ├── frontend/                     operator dashboard (map, forecast, SHAP)
│   └── deployment_bundle/            the 4 operational models
│
├── foumban_experiments/              forecasting-strategy study on the external test
│   └── foumban_forecasting_experiments.ipynb
│
├── national_validation/              external test across 194 districts, all 10 regions
│   ├── fetch_climate_2023_2025.py
│   └── national_spatial_validation.ipynb
│
├── regional_models/                  global vs regional vs grouped models
│   └── global_vs_regional_models.ipynb
│
├── foumban_incremental/              6-monthly incremental learning study
│   └── foumban_incremental_learning.ipynb
│
├── sensor_validation/                deployed IoT hardware vs the training reanalysis
│   └── sensor_vs_reanalysis.ipynb
│
└── iot_acquisition/                  the IoT acquisition layer: node → MQTT → CSV
    ├── SETUP_GUIDE.md                reproducible procedure, commands, troubleshooting
    ├── HARDWARE_AND_NETWORK.md       boards, sensors, radio parameters, firmware
    ├── RECONCILIATION.md             inconsistencies across the three sources
    └── collector/mqtt_logger.py      consolidated MQTT collector
```

The folder numbering is the order the work happened in, not a dependency order —
folders `8` through `13` are follow-up studies, each self-contained. Numbers `0`
and `7` are absent by design: they hold internal working documents and the thesis
LaTeX sources, which are not published here (see
[§ What is not in this repository](#what-is-not-in-this-repository)).

---

## The research in one page

**Question.** Can malaria risk at health-district resolution be predicted a month
ahead from environmental variables an IoT sensor network can measure — and **where
does that prediction stop being trustworthy**?

**Data.** 197 Cameroonian health districts × 36 months (2019–2022). PNLP confirmed
malaria cases fused with ERA5 daily climate reanalysis (temperature, humidity,
pressure, precipitation).

**Method.** Three nested feature regimes — RAW (5 features) → RAW+ENG (16, adds
season, geography, climate lags) → +lag_cases (20, adds case history) — evaluated
with 13 regressors and 12 classifiers, Optuna-tuned, under four progressively
stricter validation regimes.

**Headline results.**

| Evaluation | Best F1 | R² | Meaning |
|---|---|---|---|
| RAW · KFold | 0.518 | 0.198 | raw climate is weak |
| ENG · KFold *(leaky)* | 0.725 | 0.769 | interpolation within the window |
| **ENG · TimeSeriesSplit** | **0.651** | **0.628** | **forecasting future months — the operational number** |
| ENG · Leave-One-Region-Out | 0.372 | −0.461 | deployment in an unseen region |
| **External: Foumban 2023–25** | **0.250** | **−1.74** | **real unseen years — it fails** |

**National external test** (added 1 Aug 2026, see [`national_validation/`](national_validation/)):
across **194 districts × 2 years** the model ranks district burden with **Spearman
ρ = 0.859** and correctly identifies **68 %** of the worst-quartile districts
(25 % by chance). Absolute prediction fails; relative *ranking* transfers well.
That materially softens the Leave-One-Region-Out pessimism — though the ground
truth is 97 % stable year to year, so "last year's ranking" still beats the model.

**Conclusion.** The system is usable for future months in already-observed
districts. It does **not** transfer to unseen regions without local calibration,
and it failed its one external test — which is the most important and most
defensible finding in the thesis.

### Follow-up studies

| Study | Question | Answer |
|---|---|---|
| [`foumban_experiments/`](foumban_experiments/) | which forecasting strategy on a real unseen district? | teacher forcing, MAE 261 vs 664 recursive (−61 %) |
| [`national_validation/`](national_validation/) | does it transfer nationwide? | ranking does (ρ = 0.859), absolute values do not |
| [`regional_models/`](regional_models/) | one global model or one per region? | indistinguishable (0.0123 of R²) — **keep the global model** |
| [`foumban_incremental/`](foumban_incremental/) | retrain, recalibrate, or leave alone? | **never leave alone** — frozen MAE 434 vs 218 fine-tuned, and it degrades over time |
| [`sensor_validation/`](sensor_validation/) | does the deployed sensor agree with the training data? | **no** — a +7.3 °C siting offset costs 38 % of the forecast; corrected, 1.3 % |
| [`iot_acquisition/`](iot_acquisition/) | how does live environmental data actually reach the system? | LoRa mesh → gateway → Mosquitto → Python → CSV. The **adapter into the model schema is specified but not built** |

---

## Architecture

The project has two halves that meet at one artefact: the **model bundle**.
Research produces it; the operational system consumes it.

Upstream of both sits a third piece, built by a different project: the **IoT
acquisition layer** — a LoRa/Meshtastic sensor mesh feeding an MQTT broker,
documented in [`iot_acquisition/`](iot_acquisition/).

> **Provenance.** The models below were trained and validated **exclusively** on
> historical PNLP cases and ERA5 reanalysis (197 districts × 36 months,
> 2019–2022). No IoT measurement was used for training, tuning, or any validation
> regime. The IoT network is the *operational acquisition layer* for live
> measurement and future inference. Its one appearance in the research —
> [`sensor_validation/`](sensor_validation/) — asks whether the deployed
> instrument agrees with the training reanalysis, which is a hardware question,
> not a modelling one.

```
   RESEARCH  (notebooks, run once, reproducible)
   ────────────────────────────────────────────────────────────────────────
                data/
       PNLP cases (.csv/.xls)      ERA5 climate (daily, 197 districts)
                  │                            │
                  └──────────┬─────────────────┘
                             ▼
                    fusion  (fuzzy match 197 <-> 118 climate stations)
                             ▼
                    district x month panel  (7 092 rows)
                             ▼
              feature regimes   RAW (5) -> NO-LAG (16) -> LAG (20)
                             ▼
        ┌────────────────────┴─────────────────────┐
        ▼                                          ▼
   model selection                          4 validation regimes
   13 regressors / 12 classifiers           KFold · TimeSeriesSplit
   Optuna-tuned                             Leave-One-Region-Out · external
        └────────────────────┬─────────────────────┘
                             ▼
                    ★  models/deployment_bundle/  ★
                       regressor / classifier  x  NO-LAG / LAG
                       + district_static.csv + artifacts.json
                             │
   ══════════════════════════│══════════════════════════════════════════════
                             │
   OPERATIONS  (webapp/, runs continuously)
   ────────────────────────────────────────────────────────────────────────
                             ▼
        ┌────────────────────────────────────────────────────────┐
        │  MLOPS PLATFORM            app/mlops/                   │
        │                                                         │
        │  sources/       open_meteo | nasa_power | csv           │
        │      │          swappable by one env var                │
        │      ▼                                                  │
        │  ingestion -> validation -> features -> prediction       │
        │                 (blocking)   (shared)                    │
        │      │                                                  │
        │      ▼          scheduler: monthly cron + new-data every 6 h
        │  monitoring     PSI · Kolmogorov-Smirnov · Mann-Whitney  │
        └───────────────────────────┬─────────────────────────────┘
                                    ▼
        ┌────────────────────────────────────────────────────────┐
        │  API  app/routers/   FastAPI + Pydantic                 │
        │  /predict  /predictions/latest  /history  /shap         │
        │  /districts  /climate  (any district's own weather)     │
        │  /mlops/run  /mlops/health  /mlops/drift  /mlops/runs   │
        └───────────────────────────┬─────────────────────────────┘
                                    ▼
        ┌────────────────────────────────────────────────────────┐
        │  DASHBOARD  frontend/   native ES modules, no build      │
        │  Leaflet map, 197 districts, Cameroon boundaries vendored│
        │  district picker -> load real climate -> forecast -> SHAP│
        └────────────────────────────────────────────────────────┘

              persistence: SQLAlchemy · SQLite by default, PostGIS-ready
              10 tables — 6 domain, 4 platform
```

**The one thing to understand about the runtime:** predictions are made along two
different paths. Interactive requests (`POST /predict`) use the **two-stage
recursive chain** — the NO-LAG model bootstraps month 1, then the LAG model
recurses, feeding its own predictions back as `cases_lag1`. The autonomous
pipeline uses **NO-LAG only**, because it runs without any reported case history.
The chain is worth MAE 664 → 261 (−61 %) when a history exists, so a district
that reports real cases should go through the interactive path.

Both paths share **one** feature implementation
(`app/mlops/stages/features.py`). That is deliberate: divergent feature code
between training and serving — *training/serving skew* — is the costliest and
most silent failure mode an ML system has.

Details: [`webapp/app/README.md`](webapp/app/README.md) for the backend,
[`webapp/app/mlops/README.md`](webapp/app/mlops/README.md) for the platform,
[`webapp/frontend/README.md`](webapp/frontend/README.md) for the dashboard.

---

## Quick start

### 1 · Environment

```bash
git clone <this-repository>
cd Malaria-Prediction-Env-data
pip install -r requirements.txt
```

Verified with Python 3.12 · pandas 2.3.3 · scikit-learn 1.8.0 · xgboost 3.3.0 ·
lightgbm 4.6.0 · catboost 1.2.10 · optuna 4.8.0 · shap 0.46.0 · matplotlib 3.10.9.

### 2 · Regenerate every thesis figure

```bash
cd figure_regeneration
jupyter lab generate_all_figures.ipynb      # then Run All
```

Runs top to bottom with no manual intervention, ~11 minutes. All 19 figures land
in `figures/regenerated/`. The originals in `figures/thesis_figures/` are
never touched, so you can compare side by side.

### 3 · Run the API and dashboard

```bash
cd webapp && pip install -r app/requirements.txt
python serve_all.py
# everything on http://localhost:8000/  · API docs at /docs
```

One command, one origin, no build step and no database setup (SQLite). Opening
`frontend/index.html` directly will **not** work — browsers block ES modules over
`file://`; that is exactly what `serve_all.py` exists to avoid.

Containerised instead:

```bash
cd webapp && docker compose up --build     # dashboard :8080 · API :8000
```

Post a month of climate readings to `/api/v1/predict` and it returns predicted
cases, incidence, the Low/High risk class and a SHAP explanation. The dashboard
does this across districts and draws the result on a map of all 197 — see
[`webapp/frontend/README.md`](webapp/frontend/README.md).

### 4 · Check the MLOps platform end to end

```bash
cd webapp && python test_mlops.py     # offline, ~30 s
```

Exercises the source registry, collection, validation (including a negative test
on corrupted data), features, the full pipeline, idempotence, drift detection and
all six `/mlops/*` endpoints.

---

## Reading order for someone new to the project

1. [§ The research in one page](#the-research-in-one-page) above — what was found
   and what it means
2. [`docs/memoirthesis.pdf`](docs/memoirthesis.pdf) — the full argument, with the
   literature review and the methodology written out
3. [`figures/thesis_figures/`](figures/thesis_figures/) — the 19 figures, with
   [`figures/README.md`](figures/README.md) explaining what each one shows
4. [`figure_regeneration/generate_all_figures.ipynb`](figure_regeneration/generate_all_figures.ipynb)
   — run it; it is also the most readable single implementation of the whole
   pipeline
5. [`notebooks/1_malaria_full_protocol.ipynb`](notebooks/1_malaria_full_protocol.ipynb)
   — the methodology in full
6. The five follow-up studies in folders `8`–`12`, each with its own README

---

## Known issues carried over from the original project

These are stated plainly because they affect how the results should be read.
The three that matter:

1. **The 2026 forecast notebook shows a "regressor↔classifier contradiction"** that
   is *not real* — it came from a stale model artifact. Re-scored against the models
   in [`models/`](models/), the regressor gives 14.60/1000 (May) and 12.86/1000
   (June), consistent with the classifier and with the observed 14.04/1000. Re-run
   [`notebooks/9_predictions_yaounde_mai_juin_2026.ipynb`](notebooks/9_predictions_yaounde_mai_juin_2026.ipynb)
   and drop that discussion.
2. **The naive-baseline section (Phase 3.5)** exists only in
   [`notebooks/2_malaria_full_protocol_PLUS_naive_baselines.ipynb`](notebooks/2_malaria_full_protocol_PLUS_naive_baselines.ipynb),
   not in the source of truth. It answers the most predictable examiner question
   and should be merged in.
3. **`8_evaluation_foumban_2023_2025.ipynb`** reports two contradictory results.
   Its written diagnostic (+28 % bias) is correct; its stored output (R² −68.65,
   −85 % bias) came from a corrupted model load. The real baseline is **R² −1.74
   with a +28 % over-prediction**. Evidence and a full re-derivation in
   [`foumban_experiments/`](foumban_experiments/). One cell also errors out.

---

## Data sources and licensing

| Asset | Source | Terms |
|---|---|---|
| Confirmed malaria cases, 197 districts, 2019–2025 | PNLP (Programme National de Lutte contre le Paludisme), Cameroon | Redistributed here as district-month aggregates; no individual-level records |
| Daily climate reanalysis, 2019–2026 | ERA5 / Open-Meteo, NASA POWER | Open data under their respective terms |
| Administrative boundaries (`cameroon_adm0/adm1.json`) | public administrative boundary datasets | as published by the source |
| Leaflet (`webapp/frontend/vendor/leaflet/`) | Leaflet project | BSD-2-Clause, vendored unmodified |

The **code** in this repository is MIT-licensed ([`LICENSE`](LICENSE)). The
**data files** in [`data/`](data/) and
[`national_validation/`](national_validation/) remain subject to the terms of
the organisations that produced them; cite those sources, not this repository,
when you reuse them. [`data/README.md`](data/README.md) documents each file.

> **Not a medical device.** These models are a research artefact. They were built
> and validated on historical aggregates, they fail on unseen regions and they
> failed their one external test. Do not use them for clinical or operational
> public-health decisions without local recalibration and independent validation.

---

## What is not in this repository

- **Internal working documents** — the results summary, workflow reconstruction,
  figure inventory and notebook map written for supervisors during the project,
  and the thesis LaTeX sources. The thesis PDF in [`docs/`](docs/) supersedes all
  of them for a reader.
- **~31 exploratory notebooks.** The original project holds around 40 notebooks
  accumulated over four months. The 9 in [`notebooks/`](notebooks/)
  are the ones that produce thesis results; the rest are earlier iterations,
  duplicates and dead ends.
- **Intermediate CSVs** that are rebuilt from the raw data, ~100 superseded
  figures, and CatBoost training logs.

---

## Citing this work

If you use this code, the models or the results, please cite the thesis — see
[`CITATION.cff`](CITATION.cff), or:

> Ouandji Njanang, H. F. (2026). *Malaria Prediction Based on Environmental Data
> Collected Through Internet of Things (IoT) Sensors.* Master's thesis,
> Department of Computer Engineering, National Advanced School of Engineering of
> Yaoundé (ENSPY), University of Yaoundé I.

---

## Acknowledgements

Supervised by **Dr Chana Anne Marie**, Senior Lecturer, University of Yaoundé I.
Examination committee: Prof. Batchakui Bernabé (President), Dr Kameni Homte
Jaurès (Examiner), Dr Chana Anne Marie (Rapporteur). Malaria surveillance data by
the **PNLP**; climate reanalysis by **ECMWF ERA5** via Open-Meteo, and **NASA
POWER**.

---

*Package assembled 31 July 2026. Nothing in it was retrained or recomputed — all
models and figures are the originals, with format conversions only.*
