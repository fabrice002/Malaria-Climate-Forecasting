# 5_MODELS

Two model sets with different purposes. Both are the **originals** — nothing was
retrained; the only change is that `.json` exports were added alongside the
`.joblib` files (format conversion, verified to give bit-identical predictions).

```
5_MODELS/
├── protocol/            the thesis models — used for evaluation and reporting
└── deployment_bundle/   the operational models — used by the API in 6_APP/
```

---

## `protocol/` — the thesis models

Produced by `../4_SOURCE_NOTEBOOKS/1_malaria_full_protocol.ipynb` (Phase 8.5),
refit on all 7 092 district-months after Optuna tuning.

| File | Contents |
|---|---|
| `final_regressor.json` / `.joblib` | XGBRegressor → `log_incidence` |
| `final_classifier.json` / `.joblib` | XGBClassifier → `high` (incidence > region 75th pct) |
| `district_static.csv` | 197 districts: lat/lon/area/cluster/population/threshold |
| `artifacts.json` | feature list, targets, tuned params, both score regimes, fuzzy map |

**Features (16, "ENG"):** `sin_month`, `cos_month`, `SHP_lat`, `SHP_lon`,
`SHP_Area`, `cluster`, the four current climate variables, and lag1/lag2 for
temperature, precipitation and humidity.

**Tuned hyper-parameters and scores** (from `artifacts.json`):

| | Regressor | Classifier |
|---|---|---|
| Params | 500 trees, depth 5, lr 0.062, subsample 0.715, colsample 0.817 | 400 trees, depth 5, lr 0.110, subsample 0.936, colsample 0.831 |
| KFold *(optimistic)* | R² 0.769 | F1 0.725 |
| **TimeSeriesSplit** *(honest)* | **R² 0.628** | **F1 0.655** |

```python
import xgboost as xgb, pandas as pd, numpy as np, json
art = json.load(open('protocol/artifacts.json'))
reg = xgb.XGBRegressor();  reg.load_model('protocol/final_regressor.json')
clf = xgb.XGBClassifier(); clf.load_model('protocol/final_classifier.json')

X = ...                                    # DataFrame with art['feature_list']
incidence = np.expm1(reg.predict(X))       # per 1 000 population
p_high    = clf.predict_proba(X)[:, 1]
```

---

## `deployment_bundle/` — the operational models

Produced by `../4_SOURCE_NOTEBOOKS/7_malaria_deployment.ipynb`. **Four** models
supporting a two-stage recursive chain, all trained on all 2019–2022 data.

| Model | Features | Target |
|---|---|---|
| `regressor_nolag` | 16 (climate + geography + season) | `log_cases` |
| `classifier_nolag` | 16 | `high` |
| `regressor_lag` | 20 (+ `cases_lag1/2/3`, `rolling_mean_3m`) | `log_cases` |
| `classifier_lag` | 20 | `high` |

Plus `district_static.csv` and `artifacts.json` (feature lists, thresholds, all
scores, **feature medians for cold start**, fuzzy map).

**Why four models — the deployment chain:**

```
Month t  (climate only, no case history)
   └─ NO-LAG model bootstraps           → predicted cases_t
Month t+1 … N
   └─ LAG model runs recursively, feeding predicted cases_t back as cases_lag1.
      Real reported cases, when supplied, override the synthetic lag.
```

Both regressors predict `log_cases` (not incidence) precisely so the loop can feed
cases back. Incidence and the Low/High class are then derived from
predicted cases ÷ population vs the district's threshold.

**Scores:**

| Model | KFold | TimeSeriesSplit |
|---|---|---|
| Regressor NO-LAG | R² 0.898 | 0.839 |
| Regressor LAG | R² 0.941 | 0.915 |
| Classifier NO-LAG | F1 0.742 | 0.668 |
| Classifier LAG | F1 0.769 | 0.697 |

Recursive chain (the honest deployment number): **R² 0.875** vs oracle 0.927.

---

## Use `.json`, not `.joblib`

⚠️ The `.joblib` files **fail to load under xgboost ≥ 3.0** with
`XGBoostError: input stream corrupted` — the binary serialisation format changed.
They are kept for provenance only.

The `.json` files are the version-portable format and are what you should load.
For `deployment_bundle/` these were exported as part of assembling this package
(the original project had only `.joblib`); the export was verified to give
**bit-identical predictions** (max |Δ| = 0.0) before being written.

```python
reg = xgb.XGBRegressor();  reg.load_model('deployment_bundle/regressor_nolag.json')
```

Note that `6_APP/services/inference.py` still loads `.joblib`, which works on the
current pinned environment. If you upgrade xgboost, switch that file to `.json`.

---

## A caution on absolute predictions

Feature importance is dominated by **geography** (`SHP_lat`, `SHP_lon`,
`SHP_Area`, `cluster` occupy the top four positions). The models largely learn
*where* a district is and adjust at the margin for climate. Two consequences:

1. They do **not** transfer to unseen regions — Leave-One-Region-Out gives mean
   F1 0.372 and mean R² −0.461.
2. On the one external test (Foumban 2023–25, 36 unseen months) they gave
   R² −1.74 and F1 0.250, **over**-predicting incidence by 28 % — a district that
   had improved 21 % since the training window closed. See
   `../8_FOUMBAN_EXPERIMENTS/`, which also shows that supplying real case history
   cuts the error by 61 %.

Treat the outputs as a **relative risk ranking within already-observed districts**,
not as calibrated absolute incidence, until a local calibration period is done.
Full discussion in the thesis, `../docs/memoirthesis.pdf`.
