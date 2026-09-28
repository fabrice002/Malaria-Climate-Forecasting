# sensor_validation

Does the deployed IoT hardware agree with the ERA5 reanalysis the models were
trained on?

```
sensor_validation/
├── sensor_vs_reanalysis.ipynb        * the notebook - Run All, ~1 minute
├── figures/                          3 figures
└── sensor_validation_results.json    every metric
```

Input: `data/meteo_log.csv`, the first real capture from the deployed
Meshtastic node `!a0cb4a5c`.

## Running it

```bash
cd sensor_validation
jupyter lab sensor_vs_reanalysis.ipynb     # Cell -> Run All
```

Needs network: it fetches the matching reanalysis hours from Open-Meteo.

---

## Main result

**The sensor is sound, but it is sited badly, and that one fault costs 38 % of
the forecast.**

| | IoT sensor | ERA5 | bias |
|---|---|---|---|
| Temperature | 30.73 | 23.46 | **+7.27 degC** |
| Relative humidity | 56.8 | 87.4 | **-30.6 points** |
| Pressure | 927.90 | 923.63 | +4.27 hPa |
| **Dew point** | **21.02** | **21.06** | **-0.04 degC** |

The dew point is the diagnostic. Warming air raises its temperature and lowers
its relative humidity but leaves its moisture content untouched. The two
instruments agree on moisture to **four hundredths of a degree**, so they are
measuring the same air: the element is fine, the air reaching it is not.

Everything else follows from that single offset. Relative humidity predicted from
a +7.27 degC offset at unchanged moisture is **57.0 %**; the sensor reads
**56.8 %**. There is no separate humidity fault.

## Cost, in predicted cases

Biyem Assi, April 2026, scored through the deployed NO-LAG regressor:

| Scenario | Predicted cases | vs baseline |
|---|---|---|
| A - reanalysis only | 5 482 | baseline |
| B - **raw sensor** | 3 406 | **-37.9 %** |
| C - offset-corrected sensor | 5 413 | **-1.3 %** |

Subtracting the offset and recomputing humidity at the sensor's own dew point
brings it back to within 1.3 % of the reanalysis. No retraining, no new data.

---

## What else the experiment teaches

### Feature importance does not predict what a sensor fault costs

Temperature carries **2.0 %** of the model's gain; geography carries **84.9 %**.
Yet a temperature offset moved the forecast by 38 %.

The reason is not weight but **position**. 30.73 degC is **7.8 standard
deviations** above Yaounde's training mean, and **0 of the 114** Yaounde-area
training months ever reached it. Nationally it is unremarkable - 4.8 % of all
district-months are hotter, because the Sahelian north routinely is. The trees
therefore route the sample down branches learnt from a different climate zone.
The model is asked about a place that does not exist and answers accordingly.

### The missing rain gauge is the lesser problem

The sensor has no precipitation channel, which was the obvious worry. Measured:
rainfall across its whole plausible range, 0 to 400 mm, moves this forecast by
**3.2 %**. The temperature offset moved it by 37.9 %.

**The channel the sensor lacks matters about 12 times less than the channel it
mis-measures.** Rainfall still has to come from the reanalysis, but a hybrid feed
is an adequate answer whereas a mis-sited thermometer is not.

### The pipeline validator does not catch it

`validate_climate` **passes** the raw sensor stream. Its bounds are nationwide
(5 to 50 degC), so a value that is normal for Maroua survives even when it is
impossible for Yaounde. A global range cannot catch a locally impossible
reading. This is a real gap in `webapp/app/mlops/stages/validation.py`.

---

## Recommendations

1. **Re-site or shield the node.** Ventilated radiation shield, away from
   anything that dissipates heat, the board included. The dew-point agreement
   already proves the element is good, so the offset should simply vanish.
2. **Until then, correct in software**: subtract the measured offset and
   recompute relative humidity from the corrected temperature and the sensor's
   own dew point, rather than trusting the reported percentage.
3. **Add a per-district plausibility check** to the validator - a z-score beyond
   about 4 against that district's own training history should block the run.
4. **Keep rainfall on the reanalysis feed.**
5. **Draw no accuracy conclusions from this capture.** It establishes instrument
   agreement, which is a prerequisite, not forecast skill.

## Why the bias is a mounting fault, not sunshine

| | measured |
|---|---|
| bias at night, 3-7 h | +6.2 degC |
| bias at midday, 11-15 h | +6.7 degC |
| diurnal amplitude, IoT | 7.3 degC |
| diurnal amplitude, ERA5 | 7.4 degC |

Solar loading on the housing would give a large daytime bias and almost none at
night. The bias here is flat across the day and the amplitude is unchanged, which
is the signature of **self-heating or a poorly ventilated enclosure**.

---

## Data quality of the capture

| | |
|---|---|
| Window | 2026-04-20 20:05 to 2026-04-28 01:45, local |
| Rows in the log | 3 139, of which **1 567 carry readings** (the rest is link telemetry) |
| Sampling interval | 180 s |
| Days spanned | 9 |
| **Complete days** | **1** (21 April) |
| Days entirely missing | 25 and 26 April |
| Matched hours against ERA5 | 82 |
| Channels reporting | temperature, humidity, pressure |
| Channels silent | `gas_resistance`, `iaq`, `lux`, and there is no rain channel at all |

Because only one day is complete, every daily or monthly mean from this log is
sampling-biased. That is why the comparison is done **hour by hour on matched
timestamps**, never on daily means.

## Limitations

1. **Seven days, one complete, two missing.** Enough for instrument agreement,
   not for forecast skill.
2. **One node, and its location is assumed.** The log carries no coordinates.
   Yaounde is taken from the deployment described in the thesis and is consistent
   with the observed pressure. If the node is elsewhere, the offset must be
   re-measured against that district.
3. **The pressure comparison is convention-dependent.** The project's own Yaounde
   file and a fresh Open-Meteo call differ by about 8 hPa for the same month, so
   the +4.27 hPa should not be read too precisely.
4. **One week, one season.** The offset should be re-estimated on a longer
   record; it may not be constant across the year.
