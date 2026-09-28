# notebooks

The nine notebooks that produce thesis results, renumbered in **workflow order**.
They are a curated selection: the original project accumulated around 40
notebooks over four months, the remainder being earlier iterations, duplicates
and dead ends.

> These are the **originals, unmodified**, with their stored outputs intact. Their
> file paths assume the original project layout, so they will not run as-is from
> this folder — see "Running them" below. They are here to be **read**; to
> **execute** the pipeline, use `../figure_regeneration/`.

| # | Notebook | Role | Produces |
|---|---|---|---|
| 1 | `1_malaria_full_protocol.ipynb` | ★ **SOURCE OF TRUTH** — the 10-phase methodology | Figure 18, `models/protocol/` |
| 2 | `2_malaria_full_protocol_PLUS_naive_baselines.ipynb` | same + **Phase 3.5 naive baselines** | the persistence/seasonal comparison |
| 3 | `3_yaounde_climate_eda.ipynb` | Yaoundé climate exploration | Figures 1–4 |
| 4 | `4_yaounde_target_eda.ipynb` | target + risk threshold exploration | Figures 5–10 |
| 5 | `5_malaria_showcase_lag.ipynb` | defence-ready results chapter | Figures 11–17 |
| 6 | `6_malaria_lagcases.ipynb` | three-regime analysis, recursive forecasting | tables (no savefig) |
| 7 | `7_malaria_deployment.ipynb` | trains the 4 operational models | `models/deployment_bundle/` |
| 8 | `8_evaluation_foumban_2023_2025.ipynb` | ★ **external test** on real 2023–25 data | the key negative result |
| 9 | `9_predictions_yaounde_mai_juin_2026.ipynb` | operational 2026 forecast + SHAP | 10 figures |

---

## Reading order and why

**Start with 1.** `malaria_full_protocol` is the declared source of truth: 10
phases from climate dispersion statistics through Optuna tuning to
Leave-One-Region-Out validation. Everything else either feeds it or consumes it.

**Then 3 and 4** for the exploratory analysis that motivates the feature design —
the bimodal rainfall regime, the 75th-percentile threshold, and the lagged
climate↔malaria correlation.

**Then 5** for the results chapter. It introduces the third feature regime
(`+lag_cases`) and the recursive-deployment stress test, and it is the only
notebook whose `savefig` targets land directly in the thesis figure folder.

**Then 8.** This is the most important notebook scientifically, and the easiest to
overlook: the only test against genuinely unseen ground truth. It fails
(**R² −1.74**, F1 0.250), and reporting that plainly is stronger than leading with
the internal cross-validation numbers. ⚠️ Its stored output quotes R² −68.65 from
a corrupted model load — see `../foumban_experiments/`, which re-derives the
correct figures and tests five forecasting strategies on the same data.

**7 and 9** are the operational layer — training the deployment bundle and using it.

---

## Notebook 2 deserves attention

`2_malaria_full_protocol_PLUS_naive_baselines.ipynb` is identical to notebook 1
except for an added **Phase 3.5**, which compares the model against trivial
predictors on the same TimeSeriesSplit folds:

| Target | Persistence (ŷₜ = yₜ₋₁) | Seasonal mean | **Environment model (ENG)** |
|---|---|---|---|
| `log_incidence` | **0.751** | 0.533 | 0.623 |
| `log_cases` | **0.892** | 0.799 | 0.836 |

The deployable environment-only model **beats pure seasonality** but **loses to
trivial persistence**. Persistence is not deployable — PNLP reporting latency means
last month's confirmed count is unavailable at forecast time — so that gap is the
measured *cost of deployability*, which is exactly what the recursive case-history
chain is designed to recover.

⚠️ **This section is missing from the source of truth.** It pre-empts the most
predictable examiner question. Merging it into notebook 1 is recommended.

---

## Running them

These notebooks reference data by bare filename (`PNLP_AS_COMPLETE_...csv`,
`cameroon_districts_climate.csv`) expecting them in the working directory. To run
one, copy it next to the data:

```bash
cp notebooks/1_malaria_full_protocol.ipynb data/
cd data && jupyter lab 1_malaria_full_protocol.ipynb
```

Two of them need more than that:

- **`4_yaounde_target_eda.ipynb`** does `from pipeline_lib import build` after
  `sys.path.insert(0, '/home/claude')`. **`pipeline_lib.py` is not in the
  repository** and this notebook cannot be run as-is. Its pipeline is reimplemented
  as `build_panel()` in `../figure_regeneration/generate_all_figures.ipynb`.
- **`8_evaluation_foumban_2023_2025.ipynb`** loads `final_regressor.joblib` /
  `final_classifier.joblib`, which **fail to load under xgboost ≥ 3.0**
  (`XGBoostError: input stream corrupted`). Use the `.json` equivalents in
  `../models/protocol/` instead:
  ```python
  reg = xgb.XGBRegressor();  reg.load_model('final_regressor.json')
  clf = xgb.XGBClassifier(); clf.load_model('final_classifier.json')
  ```

Notebooks 1, 2, 5, 6 and 7 rebuild everything from the two core CSVs and run
cleanly once placed beside them.

---

## Known issues in these files

Carried over as-is; also summarised in the root `../README.md`.

- **Notebook 9** documents a "regressor↔classifier contradiction" (regressor
  ~2.10/1000 vs classifier HIGH). **It is not real** — re-scored against the models
  in `../models/`, the regressor gives 14.60/1000 (May) and 12.86/1000 (June),
  agreeing with the classifier and with Biyem Assi's observed 14.04/1000. The
  stored output came from a stale model artifact. Re-run it and delete that section.
- **Notebook 8** contradicts itself — its markdown reports a +28 % bias while its
  own output shows −85 %. **The markdown is right**; the output came from a
  corrupted `.joblib` load. Real baseline: R² −1.74, MAPE 31.4 %, +28.2 % bias.
  Classification numbers are unaffected. Cell 14 also raises
  `TypeError: cannot convert the series to <class 'int'>`, leaving the per-year
  table empty. One-paren fix:
  `int(((s['high']==1) & (s['pred_class']==1)).sum())`.
