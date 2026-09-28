# Reconciliation — what disagrees across the three sources, and what to do

Three sources describe this system and they do not fully agree:

| Source | What it is |
|---|---|
| **A** `malaria_thesis_package/` | the prediction work, including `data/meteo_log.csv` and `sensor_validation/` |
| **B** `Transfert_PC_fixe/` | the transfer folder: Mosquitto, Python, VS Code installers, and **three divergent copies** of the collector |
| **C** Pierre's report (113 pp. PDF) | the IoT design, configuration appendices and deployment record |

Fourteen discrepancies, ordered by how much damage each can do. Each entry gives
the evidence, so nothing here has to be taken on trust.

**Nothing in `Transfert_PC_fixe/` or `data/` has been modified.** Every fix
below is either applied in
[`collector/mqtt_logger.py`](collector/mqtt_logger.py) or recorded as a
recommendation for you to decide on.

---

## 1 · The collector points at three different brokers — one of them remote, with credentials

**Severity: high — blocks setup, and leaks a password.**

| Copy | Broker | Port | Auth |
|---|---|---|---|
| `scripts/mqtt_logger.py` | `187.77.168.222` | **58258** | `ENSPY` / `ENSPY2023` |
| `scripts/17.04.2026/mqtt_logger.py` | `192.168.0.102` (`192.168.1.187` commented out) | 1883 | none |
| `scripts/test30.03.2026/mqtt_logger.py` | `192.168.1.187` | 1883 | none |

The top-level copy — the one you would naturally run, since it sits at the root of
`scripts/` — is commented `# ---- MQTT CONFIG (ton serveur Hostinger) ----` and
points at a **remote host on a non-standard port with embedded credentials**. It
does not match the documented procedure at all: it will not connect to the local
Mosquitto broker, and the failure is a silent connect timeout.

The dated copies match the documented setup (local LAN, port 1883, anonymous), but
hard-code a LAN address that was correct on one particular day.

**Two problems, not one.** Beyond the wrong address: `mosquitto.conf` sets
`allow_anonymous true` and no credentials, while the top-level script sends
`ENSPY` / `ENSPY2023`. The broker as configured neither requires nor checks them.

**Fixed:** the consolidated collector takes `--broker` / `--port` as arguments
(env vars `MQTT_BROKER` / `MQTT_PORT`), defaults to `127.0.0.1:1883`, and sends
credentials only when supplied.

> **Action required (security).** `ENSPY2023` is a real credential sitting in
> plaintext in a folder destined for a thesis package. **Rotate it, and do not
> ship that file.** If the remote broker is still in use, keep its credentials in
> an environment variable or a local file that is never distributed.

---

## 2 · The timestamp column is named `time_utc` but holds local time

**Severity: high — silently corrupts hour-level analysis.**

The `17.04.2026` copy — the one that produced `data/meteo_log.csv` — comments
out the UTC conversion and substitutes naive local time:

```python
dt = datetime.now()
# if isinstance(ts, (int, float)):
#     dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
```

The other two copies do convert properly, from the message's own epoch timestamp.
The CSVs show the difference plainly:

| File | First timestamp | Written by |
|---|---|---|
| `test30.03.2026/meteo_log.csv` | `2026-03-30T15:54:23+00:00` | true UTC, tz-aware |
| `data/meteo_log.csv` | `2026-04-20T19:04:49.583153` | naive **local**, no offset |

So `data/meteo_log.csv` carries **local time on the fixed PC in a column named
`time_utc`**, and there is a second, subtler change: the value is no longer the
*measurement* time from the message, but the *reception* time on the PC.

**Fixed:** the consolidated collector writes true UTC into `time_utc` and adds a
`received_utc` column, so measurement time and reception time are distinguishable.

**Downstream consequence — see item 3.**

---

## 3 · `sensor_validation` shifts the clock by an hour that was never there

**Severity: high — affects a published result.**

Following from item 2. The validation notebook, `sensor_vs_reanalysis.ipynb`
cell 2:

```python
# Cameroon is UTC+1. The log is stamped UTC, so every local statistic shifts.
TZ_OFFSET = pd.Timedelta(hours=1)
```

and cell 3 applies it: `sensor['t'] = sensor['time_utc'] + TZ_OFFSET`.

The premise is false for this file. The log is **already local**, because the
collector that wrote it used `datetime.now()`. The notebook therefore shifts
everything **one hour too far**, then matches hour-by-hour against Open-Meteo
requested with `timezone=Africa/Douala` — that is, local.

`data/README.md` repeats the same assumption: *"`time_utc` — **UTC**, so add one
hour for Cameroon local time"*. `sensor_validation/README.md` states the
window as *"2026-04-20 20:05 to 2026-04-28 01:45, local"*, which is the raw
`19:04`/`00:45` already shifted.

**What this does and does not invalidate.** The headline finding — a **+7.3 °C
bias** — is robust, because the measured bias is *flat across the day*: +6.2 °C at
night, +6.7 °C at midday, with diurnal amplitude matching ERA5 (7.3 vs 7.4 °C).
A one-hour misalignment against a signal that flat barely moves the mean. The
dew-point agreement to 0.04 °C, which is the study's actual diagnostic, is
likewise unaffected.

What it **does** affect is anything that depends on the hour: the reported
day/night split, the diurnal-cycle figures, and the stated window.

> **Action required.** Set `TZ_OFFSET = pd.Timedelta(0)` for this file, re-run the
> notebook, and confirm the headline numbers hold — they are expected to move only
> slightly. Then correct the `time_utc` description in `data/README.md`. Do this
> before the results are defended, since it is an easy question to ask and a
> two-minute fix.

---

## 4 · The subscription topic cannot match the configured MQTT root

**Severity: high — would mean zero messages.**

| Source | Value |
|---|---|
| Report, Appendix B | `meshtastic --set mqtt.root msh/CMR_868` |
| All three collectors | `TOPIC = "msh/EU_868/+/json/#"` |

A subscription to `msh/EU_868/…` never matches a publication to `msh/CMR_868/…`.
MQTT wildcards do not span that level.

Since the CSVs contain real data, the working deployment cannot have used the
appendix value — the gateway was evidently left on the default root, which for
region `EU_868` yields `msh/EU_868/2/json/…`. **The appendix documents an intended
configuration that the deployed gateway did not have.**

**Fixed:** the consolidated collector subscribes to `msh/+/2/json/#`, matching any
root, and the `--topic` flag overrides it.

> **Verify** the actual root on the gateway with `meshtastic --info` and correct
> the appendix reference when writing this up.

---

## 5 · Spreading factor: 11 in the text, 12 in every appendix

**Severity: medium — a mismatch means no link at all.**

The report's §3.2.1 reasons explicitly to **SF 11**: enough range with a 1 km
margin, and low enough that a 24-node network still fits the channel — *"for a
network of 24 nodes, the spreading factor should be limited to 11."*

Appendices B, C and D all set `lora.spreadingFactor 12`.

Every node must share the same SF. There is no graceful degradation: a node at
SF 12 and a node at SF 11 are mutually invisible.

> **Action required.** Read the value off deployed hardware with
> `meshtastic --info` and treat that as authoritative. Document which was actually
> used, and note the discrepancy if citing the capacity argument — SF 12 halves
> the node capacity that argument concludes with.

---

## 6 · The gateway antenna: 2 dBi or 4 dBi?

**Severity: medium — risks configuring the wrong radio.**

| Source | Claim |
|---|---|
| Handover instruction | the gateway is *the small radio with the approximately 2 dBi antenna*, black enclosure, in the transparent box |
| Report, both deployments | gateway = **LilyGO T-Beam S3 Core with a 4 dBi antenna**; **2 dBi** is the *SenseCap Solar Pro router node* |

The 2 dBi figure in the handover matches the report's **router**, not its gateway.

Three readings are possible and the files cannot distinguish them: the handover
gain figure is approximate and informal; the antenna was swapped after the
deployment described in the report; or the kit handed over differs from the one
deployed.

> **Action required — physical verification.** The reliable identifier is the
> **board**, not the antenna. Read the silkscreen: the gateway must be a
> **T-Beam S3 Core**. Confirm with `meshtastic --info` that `device.role` is
> `CLIENT` and `mqtt.enabled` is `true`. Record the actual antenna gain once
> confirmed, and correct whichever source is wrong.

The physical descriptors — **black enclosure, transparent box, near the window** —
are unambiguous and are treated as authoritative in
[`SETUP_GUIDE.md`](SETUP_GUIDE.md) Step 0.

---

## 7 · The rainfall-in-`iaq` substitution is documented nowhere in the package

**Severity: medium — an unmarked data-interpretation trap.**

The report (§2.4.3) explains it fully: the protobuf telemetry message had no free
field, so rainfall intensity is written into the `iaq` slot and *still appears as
IAQ on the MQTT server*.

Outside the report, the only trace is an inline comment in two of the three
collector copies:

```python
"iaq", #here IAQ is the precipitation
```

The top-level copy does not even have that comment. Nothing in
`malaria_thesis_package/` mentions it.

Worse, the two package documents phrase it in a way that forecloses the question.
`data/README.md`: *"there is no precipitation channel at all."*
`sensor_validation/README.md`: *"The sensor has no precipitation channel."*

**Those statements are true of the captured data and false of the system.** The
system has a DFROBOT Rainfall tipping bucket; in the April window it reported
nothing, and `iaq` is empty on all 3 139 rows. But a reader concludes the hardware
cannot measure rain, which is not so.

**Fixed:** documented in [`README.md`](README.md) and
[`HARDWARE_AND_NETWORK.md`](HARDWARE_AND_NETWORK.md); the consolidated collector
labels the field and prints it as `RAIN=` in its log line.

> **Recommended wording** for the package documents: *"the rain channel reported
> no data during this capture; rainfall, when present, arrives in the `iaq` field
> as intensity in mm/h."*

---

## 8 · Three divergent copies of one script, and three CSVs

**Severity: medium — ambiguity about what is canonical.**

```
Transfert_PC_fixe/scripts/
├── mqtt_logger.py            remote broker, NO lux column, UTC timestamps
├── meteo_log.csv             2 699 rows — but HAS a lux column
├── 17.04.2026/
│   ├── mqtt_logger.py        LAN broker, lux, local timestamps, debug print
│   └── meteo_log.csv         3 139 rows   ← identical to data/meteo_log.csv
└── test30.03.2026/
    ├── mqtt_logger.py        LAN broker, lux, UTC timestamps
    └── meteo_log.csv         45 rows, 16 distinct `from` nodes
```

Verified by hash: `data/meteo_log.csv` is byte-identical to
`17.04.2026/meteo_log.csv` (`3816ede8402b4ea51ae1fa49f89c4a40`). So the
**`17.04.2026` copy is the one that produced the data the thesis actually uses**,
even though it is not the top-level script.

**A self-inconsistency worth noting:** `scripts/meteo_log.csv` contains a `lux`
column, but `scripts/mqtt_logger.py` does not write one. That CSV was not produced
by the script sitting beside it — most likely a partial copy of the 17.04 run.
Treat co-located files in that folder as unrelated.

**Fixed:** one collector, in [`collector/`](collector/), with a changelog in
[`collector/README.md`](collector/README.md).

> **Recommended:** keep `Transfert_PC_fixe/` as the untouched historical archive
> and treat `iot_acquisition/collector/` as canonical. Do not edit both.

---

## 9 · CLI option naming: camelCase vs snake_case

**Severity: low — causes confusion, not failure.**

| Source | Form |
|---|---|
| Report appendices | `network.wifiEnabled`, `network.wifiSsid`, `network.wifiPsk` |
| Handover procedure | `network.wifi_enabled`, `bluetooth.enabled` |

Both refer to the same protobuf fields; the accepted form depends on the CLI
version. Recent versions accept snake_case, and the report's own appendices mix
conventions internally (`power.is_power_saving` alongside `lora.usePreset`).

> **Recommended:** use snake_case as primary, note camelCase as the fallback. Done
> in [`SETUP_GUIDE.md`](SETUP_GUIDE.md) Step 5.

---

## 10 · The two captures come from different gateways with different topologies

**Severity: low — but it changes what each file can support.**

| | `test30.03.2026` | `17.04.2026` / `data` |
|---|---|---|
| Rows | 45 | 3 139 |
| `sender` (gateway) | `!435a7eb0` | `!a0cb4a5c` |
| Distinct `from` (originating nodes) | **16** | **2** |
| `lux` populated | 41 / 45 (91 %) | 0 |
| `iaq` populated | 3 / 45 | 0 |
| Humidity populated | 3 / 45 | 1 567 (50 %) |
| Timestamps | true UTC | local |

The March test is a **multi-node** capture with light and some rain readings; the
April capture is **effectively single-node**, with no light and no rain but
sustained temperature, humidity and pressure.

The package treats `!a0cb4a5c` as *"the deployed Meshtastic node"* without noting
that a different gateway, with far more nodes reporting, was captured three weeks
earlier. The March file is too short (13 minutes) for climate analysis, but it is
the better evidence that the **mesh and the light and rain channels work**.

> **Recommended:** cite the March capture as multi-node and multi-channel
> evidence, and the April capture for instrument agreement. Note that the
> gateways differ.

---

## 11 · `sensor_validation` assumes a node location the data does not carry

**Severity: low — already disclosed, repeated here for completeness.**

The notebook assumes node `!a0cb4a5c` sits in Yaoundé and uses the centroid of
Biyem Assi / Efoulan / Nkolndongo. The log carries no coordinates. The study
already states this as limitation 2. The gateway configuration in Appendix B sets
`lat 3.862458 / lon 11.499906 / alt 700`, which **is** Yaoundé and is consistent —
but that is the *gateway's* configured position, not the sensor node's, and a
configured position is not a measured one.

> **Recommended:** enable position broadcast on the sensor node, or record siting
> manually at install time. The +7.3 °C offset is only interpretable against a
> known location.

---

## 12 · `mosquitto.conf` is an open broker on every interface

**Severity: low on a lab LAN, high if exposed.**

```conf
listener 1883 0.0.0.0
allow_anonymous true
```

No authentication, no TLS, bound to every interface. Correct for the documented
setup and required for the radio to connect at all — Mosquitto 2.x otherwise binds
localhost-only. It is worth stating as a deliberate choice rather than leaving a
reader to infer it was an oversight.

> **Recommended:** document it as a lab-LAN decision; never port-forward 1883.
> Before any real deployment, add credentials and set `mqtt.username` /
> `mqtt.password` on the gateway to match.

---

## 13 · The package README opens with a stray token

**Severity: cosmetic.**

`malaria_thesis_package/README.md` line 1 reads:

```
FDCTA # Malaria Thesis — Complete Package
```

`FDCTA ` prefixes the H1, which stops it rendering as a heading. Almost certainly
an accidental paste.

> **Action:** delete the five characters. Not done here — it is your file and the
> token may mean something.

---

## 14 · The report's appendix cross-references are broken

**Severity: low — limits what can be recovered from the PDF.**

Several figure references render as `Appendix ??` — the sensor wiring diagrams in
particular (§2.4.2, §2.4.4). The LaTeX did not resolve them. Consequently
**pin-level wiring beyond GPIO 41/42 (I²C) and GPIO 4 (rain gauge) is not
recoverable from the document.**

> **Recommended:** ask Pierre for the source or a corrected build if the wiring
> needs reproducing.

---

## Terminology to standardise

The same thing is called different names across the three sources. Suggested
canonical terms, used consistently in this folder:

| Use | Not | Why |
|---|---|---|
| **Gateway radio** | *radio*, *MQTT bridge*, *LilyGO*, *T-Beam*, *the black one* | "radio" alone is ambiguous — every node is a radio |
| **Sensor node** | *node*, *Heltec*, *sensor* | distinguishes measuring nodes from routers and the gateway |
| **Router node** | *relay*, *SenseCap* | a distinct Meshtastic role |
| **Fixed PC** | *PC principal*, *main PC*, *the computer*, *MQTT server* | one machine runs both broker and collector; "MQTT server" invites confusion with the broker process |
| **Broker** (Mosquitto) | *MQTT server* | the process, as distinct from the machine |
| **Rainfall intensity (`iaq` field)** | *IAQ*, *air quality* | always name both, or someone will misread it |
| **`meteo_log.csv` — raw capture** | *the dataset*, *IoT data* | it is packet-level, not analysis-ready |
| **Canonical climate schema** | *the pipeline format* | it has a name in code: `CLIMATE_SCHEMA` |
| **Historical training data** | *the data* | must stay distinguishable from IoT measurements |
| **IoT acquisition layer** | *the IoT part* | names a layer with a defined boundary |

And the distinction the thesis depends on:

| Say | Never say |
|---|---|
| "trained and validated on historical PNLP and ERA5 data, 2019–2022" | "trained on IoT data" |
| "the IoT network is the operational acquisition layer for live inference" | "the IoT network provided the dataset" |
| "the deployed sensor was checked against the training reanalysis" | "the sensor data validated the model" |

---

## Proposed folder structure

`malaria_thesis_package/` is already well organised. Three changes:

### 1 · Add this folder — done

```
malaria_thesis_package/
├── …
├── sensor_validation/         sensor vs. reanalysis (existing)
└── iot_acquisition/         ← new: the acquisition layer
    ├── README.md                 boundary, chain, provenance rule
    ├── SETUP_GUIDE.md            the reproducible procedure
    ├── HARDWARE_AND_NETWORK.md   boards, sensors, radio, firmware
    ├── RECONCILIATION.md         this document
    └── collector/
        ├── mqtt_logger.py        consolidated collector
        └── README.md             changelog vs. the three originals
```

`13_` sits next to `sensor_validation`, which is its natural neighbour: one
documents how the data arrives, the other what the data turned out to be worth.

### 2 · Bring the IoT artefacts into the package

`Transfert_PC_fixe/` currently holds ~300 MB of installers (Python 3.14.2,
VS Code, Mosquitto) alongside the material that matters. Installers are
reproducible from the internet; the scripts, the config and the captures are not.

**Recommended:**

```
iot_acquisition/
├── config/
│   └── mosquitto.conf          ← copy of Transfert_PC_fixe/Mosquitto/mosquitto.conf
└── captures/
    ├── 2026-03-30_multinode.csv   ← test30.03.2026 (45 rows, 16 nodes, lux + rain)
    └── README.md                  ← provenance of each capture
```

`data/meteo_log.csv` stays where it is — `sensor_validation` depends on that
path.

Leave `Transfert_PC_fixe/` untouched as the historical archive, and **exclude the
installers** from anything distributed.

### 3 · Cross-link from the existing documents

| File | Add |
|---|---|
| `README.md` | a `iot_acquisition/` row in the folder layout and the start-here table |
| `data/README.md` | fix the `time_utc` description (item 2); note the `iaq`/rainfall substitution (item 7); link the setup guide |
| `sensor_validation/README.md` | `TZ_OFFSET` correction (item 3); rephrase "no precipitation channel" (item 7) |
| `webapp/app/mlops/README.md` | note that `CsvSource` is the intended IoT entry point, and that the adapter is unbuilt |

Only the root `README.md` is updated by this work; the rest are listed for you to
decide on.

---

## Summary of what needs a decision

| # | Item | Why it is yours to decide |
|---|---|---|
| 1 | Rotate `ENSPY2023`; keep it out of the package | credential hygiene |
| 3 | Re-run `sensor_validation` with `TZ_OFFSET = 0` | affects a published result |
| 5 | Confirm SF 11 vs 12 on hardware | needs the physical device |
| 6 | Confirm the gateway board and antenna | needs the physical device |
| 7 | Rephrase "no precipitation channel" in two READMEs | your wording |
| 11 | Record the sensor node's real location | needs a site visit |
| 13 | Delete the `FDCTA ` prefix | trivial, but your file |
| 14 | Request the report's corrected appendices | needs Pierre |
