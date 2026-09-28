# 13_IOT_ACQUISITION — the acquisition layer

How environmental measurements get from a sensor node in Yaoundé to a CSV file on
the fixed PC, and where that CSV meets the malaria prediction pipeline.

```
13_IOT_ACQUISITION/
├── README.md                  ← you are here: the boundary, the chain, the provenance rule
├── SETUP_GUIDE.md             ★ the reproducible procedure — node to CSV, with commands
├── HARDWARE_AND_NETWORK.md      reference: boards, sensors, radio parameters, firmware
├── RECONCILIATION.md            inconsistencies across the three sources, and the fixes
└── collector/
    ├── mqtt_logger.py           consolidated MQTT collector (one script, was three)
    └── README.md                what changed relative to the three original copies
```

**Read [`SETUP_GUIDE.md`](SETUP_GUIDE.md) if you have the hardware in front of
you.** Everything else is reference.

---

## Two projects, one chain

This package documents work from two separate pieces of research that share a data
path. Keeping them distinct matters, because they were evaluated separately and
their claims do not transfer to each other.

| | IoT infrastructure | Malaria prediction |
|---|---|---|
| **Author** | 2Lt Pierre ALMERAS de DIESBACH | this thesis |
| **Institution** | Saint-Cyr Coëtquidan / CentraleSupélec, hosted at NASEY | NASEY |
| **Deliverable** | LoRa/Meshtastic mesh WSN, gateway, MQTT bridge | models, validation, API, dashboard |
| **Source document** | `2023-2026_ALMERASdeDIESBACH_Pierre_CNE_DESSERTAUX_SDI.pdf` (113 pp.) | [`docs/memoirthesis.pdf`](../docs/memoirthesis.pdf) |
| **What it establishes** | that ground-based high-resolution weather capture is feasible and affordable in a dense tropical city | that district-month malaria risk is predictable from climate, and **where that prediction stops being trustworthy** |
| **Covered by** | this folder | folders `1_DATA` … `12_SENSOR_VALIDATION` |

Pierre's report is titled *Design of a LoRa-Based Mesh Sensor Network for Malaria
Risk Prediction*, and states that the meteorological data it collects "are
exploited for a complementary thesis about malaria risk prediction". That sentence
describes the **intent** linking the two projects. It does not describe the
provenance of the training data. See the next section.

---

## The provenance rule

> **The models in `5_MODELS/` were trained and validated exclusively on historical
> PNLP case data and ERA5 climate reanalysis — 197 districts × 36 months,
> 2019–2022. No measurement from the IoT network was used for training, for
> hyper-parameter selection, or in any of the four validation regimes.**

The IoT network is the **operational acquisition layer**: it is how live
environmental measurements would reach the system in production, and how future
inference would be fed. It is not a data source for the results reported in the
thesis.

The one place IoT data is used is [`12_SENSOR_VALIDATION/`](../12_SENSOR_VALIDATION/),
and there it answers a *hardware* question — does the deployed sensor agree with
the reanalysis the models were trained on? — not a modelling one. That study is
explicit about its own limits: **"Draw no accuracy conclusions from this capture.
It establishes instrument agreement, which is a prerequisite, not forecast
skill."**

Phrase it that way in the thesis. "The IoT network supplies the operational feed,
and the deployed instrument was checked against the training reanalysis" is
supportable. "The models were trained on IoT data" is not.

---

## The chain, end to end

```
                    IoT ACQUISITION LAYER          (Pierre's work)
                    ─────────────────────
                 ┌────────────────────────────┐
                 │  Environmental sensor node  │  Heltec V3 (ESP32)
                 │  temperature   ┐            │  + BME680   → T / RH / P
                 │  humidity      │ BME680     │  + DFROBOT Rainfall
                 │  pressure      ┘            │  + VEML7700 → ambient light
                 │  rainfall intensity         │  role = SENSOR
                 │     ↳ travels in `iaq`  ▲   │  telemetry every 295 s
                 └─────────────┬──────────────┘
                               │  LoRa · EU_868 · BW 125 kHz · CR 4/5 · TX 14 dBm
                        Meshtastic mesh                      hop limit 3
                               │  (optional SenseCap Solar Pro router node)
                               ▼
                 ┌────────────────────────────┐
                 │  Gateway radio + MQTT bridge│  LilyGO T-Beam S3 Core (ESP32)
                 │                             │  role = CLIENT, mqtt.enabled true
                 └─────────────┬──────────────┘  black enclosure, near a window
                               │  Wi-Fi  →  LAN  ←  Ethernet
                               ▼
                 ┌────────────────────────────┐
                 │  MQTT broker · Mosquitto    │  on the fixed PC, port 1883
                 │  topic  msh/<root>/…/json/… │  listener 1883 0.0.0.0
                 └─────────────┬──────────────┘
                               │  subscribe
                               ▼
                 ┌────────────────────────────┐
                 │  Python collector           │  collector/mqtt_logger.py
                 │  paho-mqtt; keeps           │  flattens JSON → CSV row
                 │  type == "telemetry"        │
                 └─────────────┬──────────────┘
                               ▼
                        meteo_log.csv              raw capture, one row per packet
                               │
   ════════════════════════════│═════════════════════════════════════════════════
                               │   ADAPTER — specified below, NOT IMPLEMENTED
                               ▼
                 ┌────────────────────────────┐
                 │  Canonical climate schema   │  Location · Date ·
                 │  CLIMATE_SCHEMA             │  Temperature_C · Humidity_pct ·
                 └─────────────┬──────────────┘  Pressure_hPa · Precipitation_mm
                               ▼
                    MLOps pipeline  6_APP/app/mlops/          (this thesis)
                    ingestion → validation → features → prediction
                               ▼
                    Malaria risk service    FastAPI  /api/v1/predict
                               ▼
                    Dashboard / Leaflet map, 197 districts
```

▲ **The `iaq` field carries rainfall, not air quality.** This is the single most
surprising fact in the chain and the one most likely to waste someone's afternoon.
The Meshtastic protobuf telemetry message had no free field for rainfall
intensity, so Pierre's modified firmware writes rainfall intensity (mm/h) into the
`iaq` slot. The name `iaq` survives into the MQTT payload and into the CSV column.
Details in [`HARDWARE_AND_NETWORK.md`](HARDWARE_AND_NETWORK.md).

---

## Where the two halves meet

The acquisition layer produces `meteo_log.csv`. The prediction pipeline consumes
the **canonical climate schema**, defined once in
[`6_APP/app/mlops/sources/base.py`](../6_APP/app/mlops/sources/base.py):

```python
CLIMATE_SCHEMA = ["Location", "Date", "Temperature_C", "Humidity_pct",
                  "Pressure_hPa", "Precipitation_mm"]
```

The pipeline already has a file-based source built for exactly this purpose —
`CsvSource`, whose own docstring names the IoT network as its first use case. It is
selected by two environment variables and no code change:

```powershell
$env:MEWS_CLIMATE_SOURCE  = "csv"
$env:MEWS_CSV_SOURCE_PATH = "D:\path\to\incoming"
```

`CsvSource` scans that path recursively and accepts **any CSV carrying the schema
columns**, whatever its filename.

### The gap, stated plainly

`meteo_log.csv` does **not** carry those columns, and no adapter between the two
exists in this package. The IoT → pipeline link is a designed and documented path,
not currently executing code.

Anyone wiring it up must supply five transformations. Each needs a decision that
the captured data cannot make on its own — which is precisely why no adapter is
shipped here rather than one that guesses:

| # | Transformation | Decision required |
|---|---|---|
| 1 | packet rows → daily rows | aggregate T/RH/P by **mean**, rainfall by **sum** (it is a flux, not a state). The April capture has **one complete day in nine**, so daily means drawn from it are sampling-biased. |
| 2 | node id → `Location` | the log carries **no coordinates**. Node `!a0cb4a5c` is assumed to sit in Yaoundé from the deployment description; *which* of the three Yaoundé districts is **unverified**. |
| 3 | `iaq` → `Precipitation_mm` | `iaq` is rainfall **intensity in mm/h** sampled every 295 s. A daily total is properly derived from the tipping-bucket count (`R = N × 0.2794 mm`), not from averaging an intensity. **Unresolved.** |
| 4 | temperature correction | [`12_SENSOR_VALIDATION`](../12_SENSOR_VALIDATION/) measures a **+7.3 °C siting offset** costing 38 % of the forecast. Correcting in software is its recommendation #2; re-siting the node is #1. |
| 5 | precipitation fallback | in the April capture the rain channel never reported. `12_SENSOR_VALIDATION` recommendation #4 is **keep rainfall on the reanalysis feed** — so the realistic operational source is a **hybrid**, not pure IoT. |

Do not implement these silently. Each row changes what the resulting predictions
mean.

### A validator gap you will hit

`validate_climate` in
[`6_APP/app/mlops/stages/validation.py`](../6_APP/app/mlops/stages/validation.py)
bounds temperature at `(5.0, 50.0)` nationwide. The raw sensor stream, +7.3 °C
offset and all, **passes**. A reading that is normal for Maroua survives even where
it is impossible for Yaoundé. `12_SENSOR_VALIDATION` recommendation #3 is a
per-district plausibility check — a z-score beyond about 4 against that district's
own training history should block the run. Until that exists, *validation passing
is not evidence the feed is sound.*

---

## Related reading

| Question | Where |
|---|---|
| I have the hardware, what do I type? | [`SETUP_GUIDE.md`](SETUP_GUIDE.md) |
| What board, what sensor, what radio setting? | [`HARDWARE_AND_NETWORK.md`](HARDWARE_AND_NETWORK.md) |
| Why do the three collector copies disagree? | [`RECONCILIATION.md`](RECONCILIATION.md) |
| Does the sensor agree with the training data? | [`../12_SENSOR_VALIDATION/`](../12_SENSOR_VALIDATION/) |
| What is actually in the captured log? | [`../1_DATA/README.md`](../1_DATA/README.md) |
| How does the serving pipeline work? | [`../6_APP/app/mlops/README.md`](../6_APP/app/mlops/README.md) |
