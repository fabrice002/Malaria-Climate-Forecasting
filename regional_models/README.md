# regional_models

One global model, regional models, or models per group of regions?

```
regional_models/
├── global_vs_regional_models.ipynb   * the notebook — Run All, ~2 minutes
├── figures/                          2 figures
└── regional_comparison_results.json  every metric
```

## Running it

```bash
cd regional_models
jupyter lab global_vs_regional_models.ipynb     # Cell -> Run All, ~2 min
```

---

## Main result

**The three approaches are indistinguishable.** Over 3 temporal folds and 3 546
test rows, the largest gap is **0.0123 of R²** — that is 1.8 % of performance,
measured on three splits only.

| Approach | R² | MAE | RMSE | F1 | Models to maintain |
|---|---|---|---|---|---|
| Global model | +0.6852 | 2.356 | — | — | **2** |
| Regional models | +0.6762 | **2.284** | — | — | 20 |
| Group models | **+0.6885** | **2.284** | — | — | 6 |

Regional wins in **5/10** regions, groups in **6/10**.

## Recommendation

**Keep the global model.** A gap of 0.012 of R² measured over 3 folds is not
significant, and does not justify multiplying by 10 the number of models to
train, monitor and retrain — which, on the MLOps platform (`webapp/app/mlops/`),
would mean 10 retraining pipelines, 10 sets of drift thresholds and 10 version
registries.

**Grouping by families of regions is the lead to watch**: better R² *and* better
MAE, with 6 models instead of 20. If its advantage is confirmed on more data,
that is the route to favour before any full specialisation.

---

## What else the experiment teaches

### Training volume does not explain where specialisation pays

Correlation between available volume and the regional model's gain: **+0.12**.
The intuition "the more data a region has, the more a dedicated model pays off"
is **false here**. Sud (360 rows, the smallest region) gains +0.08 of R², while
Nord-Ouest (720 rows) loses −0.09.

What matters more is **epidemiological specificity**: a region whose
climate-to-incidence relationship differs from the rest of the country benefits
from being modelled alone, even with little data.

### A low R² is not necessarily a failure

Est and Sud are the only regions where no approach exceeds R² = 0.30. Yet their
coefficient of variation (0.42 and 0.34) is **below** the national average
(0.69): their incidence is more stable, so there is less variance to explain, so
R² collapses mechanically.

The correlation between target variance and attainable R² (+0.33) confirms the
effect. **Judging a region on its R² alone would wrongly declare it
unpredictable** — its MAE stays acceptable.

### Regression and MAE do not rank the approaches the same way

The regional model has the **best MAE** (2.284 vs 2.356) but the **worst R²**
(0.6762 vs 0.6852). It predicts ordinary months better and misses more of the
extremes. For an early-warning system the extremes are what matter — R² and F1
are therefore more relevant here than MAE alone.

---

## Protocol

* **Strictly identical evaluation** for the three approaches: same test rows
  (3 546, all predicted by all three), same metrics.
* **Rolling origins**: 3 temporal splits (2020-09, 2021-03, 2021-09), training on
  everything earlier, testing on the following 6 months.
* **No leakage**: the test set is always later than the training set; the
  clustering is learnt **on each fold's training set only**.
* Regression target `log_incidence`, classification target `high` (incidence >
  75th percentile **of its own region**).

### Resulting groups

k-means (k = 3) on the regional profile — incidence level, seasonal amplitude,
mean climate, latitude:

| Group | Regions | Rows | Mean incidence |
|---|---|---|---|
| 0 | Extrême-Nord, Nord | 1 692 | 9.20 |
| 1 | Littoral, Nord-Ouest, Ouest, Sud, Sud-Ouest | 3 348 | 7.09 |
| 2 | Adamaoua, Centre, Est | 2 052 | 11.23 |

The grouping recovers a coherent geographic structure: the Sahelian belt, the
south/west seaboard, the centre-east plateau.

---

## Limitations

1. **Only 36 months** -> 3 temporal origins. Small gaps are not necessarily
   significant; that is the main reason the recommendation is cautious.
2. **Identical hyperparameters** for the three approaches. A regional model
   trained on 360 rows would probably benefit from being shallower; tuning per
   approach could change the ranking.
3. **The grouping depends on `k`** and on the profile variables retained.
4. **Temporal evaluation only.** The spatial question — does a regional model
   transfer to a never-seen district of its own region? — belongs to
   Leave-One-Region-Out, handled in
   `notebooks/1_malaria_full_protocol.ipynb` and confronted with real
   data in `national_validation/`.

## A note on reading the figures

The y-axis of the overall comparison starts at **0**, deliberately. An axis
truncated around [0.65, 0.70] would make a 0.012 difference look decisive when it
is not.
