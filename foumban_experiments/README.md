# foumban_experiments

Dedicated forecasting-strategy experiments on the Foumban 2023–2025 external test.

```
foumban_experiments/
├── foumban_forecasting_experiments.ipynb   ★ the notebook — Run All, ~3 minutes
├── figures/                                 9 figures, written on run
└── foumban_experiment_results.json          every metric, written on run
```

## Run it

```bash
cd foumban_experiments
jupyter lab foumban_forecasting_experiments.ipynb      # Cell → Run All
```

Runs top to bottom on a fresh kernel in about 3 minutes. It **reuses the trained
models as-is** — nothing is retrained — and reads only `../data` and
`../models`. It also works if dropped into the original `mal_proj/` root.

`8_evaluation_foumban_2023_2025.ipynb` is **not modified**; this notebook
re-implements its preprocessing exactly so the baseline is directly comparable.

---

## The question

The Foumban external test scores far worse than internal cross-validation. The
existing evaluation scores each month **independently from climate alone**, never
telling the model what malaria did last month — even though 36 months of real
PNLP case reports exist for Foumban. Is the poor score the district, or the
evaluation protocol?

## Prediction target

Stated explicitly in the notebook before any experiment runs:

| | |
|---|---|
| **Source of truth** | `cases_confirmed` — monthly confirmed cases (PNLP, *FOSA + Communauté*, row 7 of each year sheet) |
| Derived | `incidence_rate = cases_confirmed / 257 429 × 1000` |
| Protocol regressor target | `log_incidence = log1p(incidence_rate)` |
| Deployment regressor target | `log_cases = log1p(cases_confirmed)` |
| Classifier target | `high = incidence_rate > 9.3986` |

All metrics are reported on the **natural cases scale** so strategies trained on
different targets stay comparable.

## Results — identical 24-month window (2024-01 → 2025-12)

| Strategy | MAE | RMSE | R² | MAPE | Bias |
|---|---|---|---|---|---|
| **Teacher forcing (real case lags)** | **261** | **381** | **+0.05** | **14.7 %** | **−1.3 %** |
| Recursive (6-month blocks) | 333 | 408 | −0.09 | 18.2 % | −10.7 % |
| *Expanding seasonal mean* (naive) | *339* | *445* | *−0.30* | *20.3 %* | *+8.1 %* |
| *Persistence y(t−1)* (naive) | *341* | *441* | *−0.28* | *19.1 %* | *+0.8 %* |
| NO-LAG deployment model | 434 | 531 | −0.86 | 22.0 % | −23.1 % |
| Baseline — climate only (current) | 664 | 801 | −3.23 | 35.8 % | +31.6 % |

## What the experiments found

**Case history is the whole story.** Giving the model real case lags cuts MAE by
61 % and removes the systematic bias (+31.6 % → −1.3 %). Ablation confirms it is
almost entirely `cases_lag1`: neutralising that one feature sends MAE from 246 to
1 084. SHAP attributes 77 % of the total mass to case-history features.

**More history does not help — the model has a 3-month memory.** With a fixed
test window, history lengths of 3, 6, 9, 12 and 18 months give *byte-identical*
forecasts. Nothing older than `cases_lag3` can physically reach the model. The
apparent "more history hurts" trend in the naive version of the experiment is
purely an artefact of the test set shifting.

**Recursive error accumulates, roughly doubling over 12 months.** Rolling-origin
evaluation over 29 origins: teacher-forced MAE stays ~246 → 287 (+17 %), recursive
goes 246 → 463 (+88 %). Identical at h=1 by construction.

**Recursive forecasting is no better than a naive expanding mean** (333 vs 339 —
noise on 24 points). Only teacher forcing clears the naive references, and it is
the only strategy with a positive R².

**Foumban's problem is temporal drift, not geography.** The district averaged
9.67 / 1000 during 2019–2022 training and 7.59 / 1000 during 2023–2025 — a 21.5 %
decline. The baseline over-predicts by 28.2 %. The model faithfully reproduces a
Foumban that no longer exists. Foumban sat at the **67th national percentile**
during training, so this is not the "below-average district" story.

---

## ⚠️ A correction to the reported Foumban result

`8_evaluation_foumban_2023_2025.ipynb` contains **two contradictory results**: its
executed output reports `R² = −68.65` with predictions 85 % *below* reality, while
its own written diagnostic (§6.1) reports **+28 %** *above* reality. This notebook
settles it.

`final_regressor.joblib` raises `XGBoostError: input stream corrupted` on any
modern xgboost. The `.json` export is verifiably the genuine Phase-8.5 model —
500 trees of depth 5 matching the recorded Optuna parameters, `base_score`
2.1156 equal to the training mean of `log_incidence`, in-sample R² 0.918. It
reproduces the written diagnostic exactly.

| Quantity | Quoted from the stored output | **Verified correct** |
|---|---|---|
| R² (log_incidence) | −68.65 | **−1.74** |
| MAPE | 85.3 % | **31.4 %** |
| Mean predicted incidence | 1.13 / 1000 | **9.73 / 1000** |
| Bias | −85 % (under-predicts) | **+28.2 % (over-predicts)** |
| Classification F1 | 0.250 | **0.250 — unaffected** |

Only the **regressor** result was corrupted; the classifier numbers (F1 0.250,
precision 0.15, recall 0.75, confusion `[[15,17],[1,3]]`) reproduce exactly and
stand as reported.

**The qualitative conclusion survives** — R² is still negative, so the
climate-only model remains worse than predicting the mean, and external validity
is still the project's binding limitation. But the magnitude and the *direction*
both change, and the cause becomes identifiable: a district that improved by 21 %
after the training window closed.

## Deployment recommendation

| Situation | Strategy | Expected MAE |
|---|---|---|
| Monthly case reports available | Teacher forcing — re-anchor every month | ~261 (14.7 % MAPE) |
| Sensors only, recent seed | Recursive, re-seeded when a report arrives | ~333 (18.2 % MAPE) |
| No case data at all | Climate-only **with bias correction** | ~664 (35.8 % MAPE) |

`predict_chain()` in the deployment bundle already supports re-anchoring via
`real_cases`. Recursion should be the fallback, never the default.

## No-leakage guarantees

1. A prediction for month *t* never reads any observation at or after *t* — the
   lag window is strictly `[:t]`, and the target is never a feature.
2. Models are frozen: trained on 2019–2022 national data, only ever called with
   `.predict()`. Foumban 2023–2025 is fully out-of-sample, so using real case
   history as an *input* is teacher forcing, not training leakage.
3. Cold-start lags use **training medians**, never Foumban statistics.
4. Naive references are leakage-free by construction. The notebook explicitly
   shows the trap: a seasonal mean computed over the whole frame scores MAE 208
   and would "beat" every model, because it averages each test month into its own
   prediction. Its honest counterpart scores 339.
