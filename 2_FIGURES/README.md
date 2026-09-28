# 2_FIGURES

```
2_FIGURES/
├── thesis_figures/   the 19 figures used in the thesis (originals — do not edit)
└── regenerated/      output of ../3_REGENERATE_FIGURES (starts empty)
```

Run `../3_REGENERATE_FIGURES/generate_all_figures.ipynb` to fill `regenerated/`,
then compare side by side. The originals are never overwritten.

Each figure listed below names the notebook it came from. `../4_SOURCE_NOTEBOOKS/README.md`
places those notebooks in the workflow; `../3_REGENERATE_FIGURES/generate_all_figures.ipynb`
reproduces all of them in one pass.

---

## The 19 figures, in thesis order

### Exploratory analysis — Yaoundé climate (thesis §3.1.3)
*from `te/yaounde_climate_eda.ipynb`; prose in the thesis, `../docs/memoirthesis.pdf` §3.1.3*

| # | File | Shows |
|---|---|---|
| 1 | `yde_climate_2019_2022.png` | Monthly evolution of the four environmental variables, 2019–2022 |
| 2 | `yde_climatology.png` | Mean seasonal cycle — the bimodal rainfall regime |
| 3 | `yde_climate_2026.png` | Daily climate over the IoT deployment window (Apr–Jun 2026) |
| 4 | `yde_2026_vs_hist.png` | Deployment window against the 2019–2021 historical envelope |

### Exploratory analysis — the malaria target
*from `te/yaounde_target_eda.ipynb`*

| # | File | Shows |
|---|---|---|
| 5 | `yde_target_districts.png` | Monthly cases and incidence for the three Yaoundé districts |
| 6 | `yde_target_threshold.png` | Incidence vs the 75th-pct threshold — the Low/High target made concrete |
| 7 | `yde_target_distribution.png` | Where the threshold sits in the distribution (histogram + boxplots) |
| 8 | `yde_climate_malaria.png` | Rainfall and incidence overlaid — the delayed response |
| 9 | `yde_lag_correlation.png` | Incidence × climate correlation at lags 0–3 months |
| 10 | `yde_seasonal_cases.png` | Mean seasonal incidence cycle |

### Results — models and the honesty envelope
*from `malaria_showcase_lag.ipynb`; these carry the `fig1`–`fig7` numbering of the results chapter*

| # | File | Shows |
|---|---|---|
| 11 | `fig1_regimes_lag.png` | Three feature regimes: R² 0.18 → 0.77 → 0.84, F1 0.50 → 0.74 → 0.76 |
| 12 | `fig2_temporal_leak_lag.png` | 12 classifiers, KFold (leaky) vs TimeSeriesSplit (honest) — gap +0.07 F1 |
| 13 | `fig3_envelope_lag.png` | The full validation envelope, weakest baseline → hardest spatial test |
| 14 | `fig4_shap_lag.png` | SHAP summary — `cases_lag1` dominates when case history exists |
| 15 | `fig5_loro_lag.png` | Leave-One-Region-Out per region — the binding constraint |
| 16 | `fig6_confusion_lag.png` | Confusion matrix + ROC on genuinely future months |
| 17 | `fig7_recursive.png` | Recursive deployment: oracle R² 0.927 vs synthetic-lag 0.895 |

### Explainability and deployment

| # | File | Shows |
|---|---|---|
| 18 | `native_importance_crosstask.png` | Native importance, tuned regressor and classifier — geography dominates both |
| 19 | `pred2026_shap.png` | SHAP drivers of the NO-LAG model's May/June 2026 forecast |

---

## Two figures are special

**`native_importance_crosstask.png` (18)** — the source notebook renders it inline
and never calls `savefig()`. It was exported by hand from the notebook output.

**`pred2026_shap.png` (19)** — **no surviving notebook produces it.** It was
identified from its content and reconstructed in
`../3_REGENERATE_FIGURES/generate_all_figures.ipynb` Part 6, from the saved NO-LAG
model (loaded, not retrained, so the SHAP values are exact). The reconstruction was
checked against the published PNG and matches on all top-five drivers, their order,
their magnitudes and every sign.

## What to expect from regeneration

| Figures | Result |
|---|---|
| 1–4 | **MD5-identical** to the originals |
| 5–10 | content-identical, re-rendered (the source notebook ran in a Linux sandbox with different font rasterisation) |
| 11–18 | content-identical; third-decimal drift from xgboost/scikit-learn versions |
| 19 | reconstruction — values exact, cosmetic layout inferred |

No scientific result changes. Details and the full comparison table are in
`../3_REGENERATE_FIGURES/README.md`.
