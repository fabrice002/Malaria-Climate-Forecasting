# 11_FOUMBAN_INCREMENTAL

Incremental learning every six months on Foumban: should the model be retrained,
recalibrated, or left alone when new data arrives?

```
11_FOUMBAN_INCREMENTAL/
├── foumban_incremental_learning.ipynb   * the notebook — Run All, ~1 minute
├── figures/                             3 figures
└── incremental_results.json             every metric
```

---

## ⚠️ Foumban does not have 5 continuous years

Checked before any experiment:

| Source | Indicator | Period | Months | Mean |
|---|---|---|---|---|
| **A** | `MAPE16_H_13` | 2019-01 -> 2022-02 | 38 | 2 554 cases/month |
| **B** | row 7, *facility + community* | 2023-01 -> 2025-12 | 36 | 1 955 cases/month |

Two obstacles to splicing them:

1. **A 10-month hole** — March to December 2022, no data at all.
2. **An indicator break — A/B ratio = 1.31.** Splicing the two would teach the
   model a 23 % drop that is a **change of definition, not epidemiology**.

**Strategy adopted (option c)**: main study on **source B alone** (36 months, one
definition, out of sample), then the spliced A+B series used **only** to
demonstrate drift detection on a known cause.

---

## Results — 4 iterations, 12-month seed, 6-month step

| Strategy | MAE | \|bias\| | F1 | vs Frozen |
|---|---|---|---|---|
| **Fine-tuning** | **218** | 7.7 % | 0.000 | **−50 %** |
| Recalibration | 271 | 9.7 % | **0.167** | −37 % |
| Hybrid retrain | 288 | 11.1 % | 0.000 | −34 % |
| Local retrain | 327 | 10.0 % | 0.000 | −25 % |
| **Frozen** (current situation) | **434** | 22.6 % | 0.000 | baseline |

### The four lessons

**1 · Doing nothing is by far the worst option.** The frozen model is beaten by
all four strategies, with an error about **twice** that of the best. It is the
only gap whose magnitude puts it beyond statistical doubt over 4 iterations.

**2 · The frozen model *degrades* over time** (+108 MAE per iteration) while
every adaptive strategy improves (−19 to −122 per iteration). A system that never
updates does not stagnate — it goes backwards.

**3 · Fine-tuning wins, but it is fragile.** Best MAE (218), yet the sweep shows
performance varying by a **factor of 119** on the setting alone (247 -> 29 290).
Recalibration has **no hyperparameter**: it cannot be mis-tuned, for 25 % more
error.

**4 · No strategy rescues the alert.** Maximum F1 is 0.167, and exactly zero for
the other four — they never predict a "High" month at all. Foumban has just
4 months above the threshold out of 36, and that threshold sits at 9.40 / 1 000,
i.e. 2 419 cases in a series whose maximum is 2 748. **Improving the regression
does not improve risk detection** — which is nonetheless the whole point of an
early-warning system.

---

## Drift detection on the spliced series

A second part, with no claim to performance: the A+B series is knowingly
distorted, and what is checked is that the detector in
`6_APP/app/mlops/monitoring/drift.py` spots it.

| Measure | Value | Threshold |
|---|---|---|
| **PSI** | **3.99** | 0.25 = major |
| Kolmogorov-Smirnov | 0.444 (p = 1.4·10⁻³) | — |
| Verdict | **MAJOR DRIFT** | — |

Detected cleanly. But the lesson lies elsewhere: **a detected drift does not
imply a retrain is needed.** Here, retraining on the spliced series would learn a
23 % drop that never happened. That is exactly the distinction an operator must
be able to make.

---

## Recommendations for the platform

1. **Update, whatever the method.** The gap between "do nothing" and any strategy
   far exceeds the gaps between strategies.
2. **Periodic per-district recalibration as the default**, from 12 months of real
   cases onwards: no hyperparameter, hence no risk of mis-tuning.
3. **Fine-tuning only with mandatory validation** — it produces both the best
   *and* the worst error depending on the setting. Never promoted without a
   comparison against the champion (the role of the `model_versions` registry).
4. **Retrain on confirmed *performance* drift**, never on plain *data* drift.
5. **Treat alerting separately**: set the decision threshold against an explicit
   false-alarm cost, independently of model updating.

---

## Protocol

* **12-month seed -> 4 iterations of 6 months.** At each iteration the previous
  six real months are added to the history, the strategy is updated, then it
  predicts the following six. No test month enters training.
* **24-month seed** ("the first two years" of the brief) computed in addition —
  only 2 iterations, too few for a trend.
* **Fine-tuning hyperparameters fixed a priori** (depth 1, lr 0.01, L2 = 50),
  *not* optimised on the test set. The chosen setting ranks 5th out of 18 in the
  sweep: picking it in view of the test would have been leakage.
* **Hybrid strategy**: the national panel (7 092 rows) is mixed with the Foumban
  history converted to the national scale by the 1.31 factor, and replicated 30x
  so as not to be drowned out.

## Limitations

1. **36 months, 4 iterations, a single district.** Only the gap to the frozen
   model is robust; the gaps between adaptive strategies are not.
2. **Source B is not the training indicator.** Part of the corrected bias comes
   from the difference of definition, not from real drift. The measured gain does
   not transpose as-is to a district whose indicator is consistent with training.
3. **The 10-month hole in 2022** rules out any continuous study over seven years.
   Recovering that data — or a single 2019–2025 export with a constant indicator
   — would be the main available gain.
4. **NO-LAG model** (climate only). Strategies with a case history are covered in
   `8_FOUMBAN_EXPERIMENTS/`.
