# figure_regeneration

One notebook that rebuilds **all 19 thesis figures** from raw data and the saved
models, in the order they appear in the thesis.

## Run it

```bash
cd figure_regeneration
jupyter lab generate_all_figures.ipynb     # Cell → Run All
```

- **Runtime ≈ 11 minutes** on a laptop CPU. One cell (Figure 12: 12 classifiers ×
  2 CV schemes, including `SVC(probability=True)` and an MLP on 6 895 rows) takes
  ~8 of those minutes and prints per-model progress as it goes.
- **No manual intervention.** Runs top to bottom on a fresh kernel.
- **Output → `../figures/regenerated/`.** The originals in
  `../figures/thesis_figures/` are never overwritten, so you can diff them.

The notebook auto-detects its location: dropped back into the original `mal_proj/`
project root it reads from `files (2)/`, `te/` etc. instead. No edits needed either
way.

## Why this notebook exists

The 19 figures were originally produced by **four different notebooks** (plus one
that no longer exists), each re-implementing the same data fusion. This
consolidates them behind a single `build_panel()` and a small set of shared
helpers, so the pipeline, the feature engineering and the target definition are
written **once**.

It also repairs two things that stop the originals from running:

| Problem | Fix |
|---|---|
| `te/yaounde_target_eda.ipynb` does `from pipeline_lib import build` after `sys.path.insert(0,'/home/claude')`. **`pipeline_lib.py` does not exist in the repository** — that notebook cannot be re-run as-is. | `build_panel()` reimplements it from the identical pipeline in `malaria_full_protocol.ipynb`. Proof it is correct: Figures 1–4 regenerate **MD5-identical** to the originals. |
| `shap ≤ 0.47` with `xgboost ≥ 3.0` raises `ValueError: could not convert string to float: '[2.12E0]'` — xgboost now serialises `base_score` as a one-element array. Breaks Figures 14 and 19. | `shap_values_xgb()` catches exactly that and falls back to xgboost's own `pred_contribs=True` — the same TreeSHAP algorithm, verified identical to ~1e-6. |

## Structure

| Part | Figures | Content |
|---|---|---|
| 0 | — | setup, configuration, 5 reusable helpers |
| 1 | — | `build_panel()` — the shared data fusion, written once |
| 2 | 1–4 | Yaoundé climate EDA |
| 3 | 5–10 | malaria target and the risk threshold |
| 4 | 11–17 | modelling results and the honesty envelope |
| 5 | 18 | native feature importance, both tasks |
| 6 | 19 | deployment SHAP (reconstructed) |

## Verification

Executed end-to-end twice: **19/19 figures, 0 errors, 627 s.**

| Quantity | Published | Regenerated |
|---|---|---|
| Three-regime R² | 0.183 / 0.774 / 0.843 | 0.181 / 0.773 / 0.843 |
| Three-regime F1 | 0.503 / 0.736 / 0.759 | 0.506 / 0.733 / 0.762 |
| Temporal-leakage gap | +0.065 F1 | +0.066 F1 |
| LORO mean | F1 0.403, R² −0.330 | F1 0.414, R² −0.362 |
| Recursive simulation | oracle 0.927 / recursive 0.895 | oracle 0.927 / recursive 0.895 |
| Yaoundé threshold | 14.28 /1000, 18/114 High | 14.28 /1000, 18/114 High |

Differences sit in the third decimal and come from xgboost/scikit-learn version
drift, not from pipeline divergence. **No scientific result changes.**

Figures 1–4 come out byte-identical to the originals. Figures 5–10 are
content-identical but re-rendered (the source notebook ran in a Linux sandbox with
different font rasterisation). Figures 11–18 are content-identical within the
tolerances above. Figure 19 is a **reconstruction** — see below.

## Figure 19 is reconstructed, not copied

`pred2026_shap.png` is the one thesis figure with no `savefig()` anywhere in the
repository and no surviving producer notebook. It was identified from its content
(title "SHAP — Drivers of the Predicted **Cases** (**NO-LAG** model)", panels May
and June 2026, 16 features with no `cases_lag`) as the
`deployment_bundle/regressor_nolag` model applied to the Yaoundé 2026 window.

Part 6 rebuilds it from that model — **loaded, not retrained**, so the SHAP values
are exact. Checked against the published PNG: the top five drivers, their order and
their magnitudes all match (`SHP_Area` ≈ 0.66, `cluster` ≈ 0.6, `SHP_lat` ≈ 0.45,
`SHP_lon` ≈ 0.12, `Pressure_hPa` ≈ 0.09), and every contribution agrees in sign.
Only a few near-zero features below rank 5 swap places.

## Settings you may want to change

Both are in the configuration cell at the top of Part 0:

- `RERUN_OPTUNA = False` — Figure 18 refits from the tuned parameters recorded in
  `artifacts.json` (identical result, ~20 min faster). Set `True` to redo the
  25-trial search from scratch.
- `OUT_DIR` — where figures are written. Point it at `../figures/thesis_figures`
  only if you deliberately want to overwrite the originals.
