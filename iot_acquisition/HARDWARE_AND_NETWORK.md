# Hardware and network reference

What the IoT layer is made of, how it is configured, and why. Everything here is
drawn from Pierre ALMERAS de DIESBACH's internship report,
`2023-2026_ALMERASdeDIESBACH_Pierre_CNE_DESSERTAUX_SDI.pdf` (113 pp., Saint-Cyr
Coëtquidan, defended April 2026), unless marked otherwise. Page-level claims are
attributed inline so they can be checked.

This is **reference material**. To actually set the system up, use
[`SETUP_GUIDE.md`](SETUP_GUIDE.md).

---

## 1 · What the project was for

> *Design of a LoRa-Based Mesh Sensor Network for Malaria Risk Prediction.*

Malaria transmission is driven by temperature, relative humidity, rainfall
intensity, atmospheric pressure and surface irradiance. Existing surveillance
relies on satellite observation and multi-model climate forecasts, which are
coarse in both space and time. The project's premise is that ground-based,
high-resolution measurement can do better — if it can be made cheap enough and
low-power enough to deploy densely in a city like Yaoundé.

The engineering problem is that dense urban environments attenuate radio badly,
and that cost and battery life are the binding constraints on how many nodes you
can put up.

The work proceeded in two architectures:

| | First prototype | Hybrid architecture |
|---|---|---|
| Sensor nodes | Heltec V3 (ESP32) | Wyres boards (STM32, LoRaWAN) integrated into Meshtastic |
| Deployment | 5 nodes, Messa + NASEY, Yaoundé | 25 nodes, incl. 20 Wyres |
| Purpose | validate the end-to-end chain and LoRa parameters | reduce cost and power; validate multi-hop over 3 hops |

**The chain documented in this package is the first architecture**: Heltec V3
sensor nodes → Meshtastic mesh → T-Beam S3 Core gateway → Mosquitto → Python. The
Wyres integration changes what sits at the sensor end; it does not change the
gateway, the broker or the collector, which are described in the report as
unchanged between deployments.

---

## 2 · The nodes

Meshtastic assigns each radio a **role**, and the role is what determines whether
a radio measures, relays or bridges. Getting the role wrong is the most common
way to make a working radio look broken.

| Role | Board | Antenna | Cost | What it does |
|---|---|---|---|---|
| **SENSOR** | Heltec V3 | onboard | ≈ $25 (before sensors) | measures weather, transmits over LoRa |
| **ROUTER** | SenseCap Solar Pro | 2 dBi | — | relays packets; solar-powered |
| **CLIENT** (gateway) | LilyGO T-Beam S3 Core | 4 dBi external | ≈ $30 | bridges LoRa ↔ Wi-Fi ↔ MQTT |
| — | PC running Eclipse Mosquitto | — | — | the broker |

### Sensor node — Heltec V3

ESP32 microcontroller with an integrated LoRa transceiver, Wi-Fi and Bluetooth.
Powered by a 3.7 V / 3 700 mAh LiPo battery.

Wi-Fi, Bluetooth and the onboard display are **disabled** on sensor nodes: they
are the three most power-hungry modules and none is needed in the field. Even
then, idle consumption of 47 mA gives only about three days of battery life, which
is why the sleep/wake cycle below exists.

**Sleep/wake.** The board uses **light sleep** (≈ 0.8 mA), not deep sleep
(≈ 0.15 mA), despite the latter being far more efficient. The reason is the rain
gauge: deep sleep powers down peripherals and each wake is effectively a reset
taking 200–500 ms, and the pulses produced by the tipping bucket are too short for
the microcontroller to catch. Light sleep uses clock gating, preserves RAM, and
wakes in under 1 ms — fast enough to register a tip.

Pierre also had to modify the `EnvironmentTelemetry` firmware module, because
telemetry acquisition on its own did not wake the board from light sleep. The
resulting cycle:

| Phase | Duration |
|---|---|
| Awake — wake, acquire, transmit | 10 s |
| Light sleep | 290 s |
| **Telemetry update interval** | **300 s** (configured as 295 s) |

### Gateway — LilyGO T-Beam S3 Core

ESP32 with LoRa transceiver, Wi-Fi module and a 4 dBi external antenna. It gathers
telemetry from the mesh over LoRa and republishes it to the MQTT broker over
Wi-Fi: the single point where the LoRa network meets the IP network.

Three consequences follow, and all three matter operationally:

1. **It is a single point of failure.** Any gateway fault interrupts the entire
   network's data flow. Nothing else bridges to MQTT.
2. **It cannot sleep.** Unlike sensor and router nodes it has no sleep/wake cycle,
   because sleeping would drop packets in flight. It is therefore continuously
   powered — mains, or a 5 W solar panel.
3. **It has to be outside, or at a window.** It must be near the LAN to reach the
   broker, but walls attenuate 868 MHz severely, so it cannot be buried indoors.
   In the deployment it is housed in an **IP67-rated junction box** against water,
   dust and temperature swing. *This is the reason for the handover instruction to
   place the gateway radio near the window.*

---

## 3 · The sensors

All three are **I²C** devices on the Heltec V3's default bus (GPIO 41 / 42),
scanned automatically at startup, powered at 3.3 V from the board.

| Sensor | Measures | Cost | Notes |
|---|---|---|---|
| **BME680** | temperature, relative humidity, atmospheric pressure, gas resistance, IAQ | ≈ $10 | the primary weather sensor |
| **DFROBOT Rainfall** | rainfall intensity (mm/h) | — | tipping bucket / reed switch |
| **VEML7700** | ambient light → surface irradiance | ≈ $9 | conversion applied in Python: **120 lux = 1 W/m²**. Compare a dedicated irradiance sensor at $250–750. |

### The rain gauge

The DFROBOT Rainfall sensor is a **tipping bucket** closing a reed-switch contact
once per tip. Given the bucket resolution:

```
R = N · k                    total rainfall (mm)
I = N · k · 3600 / Δt        rainfall intensity (mm/h)

  N = number of bucket tips
  k = 0.2794 mm per tip      (DFROBOT Rainfall bucket resolution)
  Δt = interval (s)
```

Two integration decisions have downstream consequences. The sensor normally ships
with a Gravity board that does the counting; to reduce size it was wired directly
to the Heltec V3 GPIO instead, so the **firmware** counts tips by GPIO interrupt
and computes intensity over the update interval. This is what
`detection_sensor.enabled true` / `monitor_pin 4` / `internal_pullup true` in the
node configuration is doing.

### Rainfall travels in the `iaq` field

**The most important quirk in the entire system.**

A sensor node must send exactly one telemetry message per update interval, or the
channel congests. But the Meshtastic protobuf telemetry message is byte-limited
and had no room for an additional field, so rainfall intensity could not simply be
appended.

The BME680's **Indoor Air Quality** reading is not useful for this application —
and is in any case disabled to save power, so it always reads 0. Pierre's modified
firmware therefore **writes rainfall intensity into the `iaq` slot**.

The renaming was never completed. The report is candid about why: the `iaq`
variable has a large number of dependencies throughout the firmware, so the field
continues to be **labelled `iaq` all the way to the MQTT payload** — and from
there into the CSV column of the same name.

**Consequences for anyone reading this data:**

- A column named `iaq` holds **rainfall intensity in mm/h**, not air quality.
- A payload with no field named for rain does **not** mean rain is unmeasured.
- The three collector copies in `Transfert_PC_fixe/scripts/` carry the inline
  comment `#here IAQ is the precipitation`. That comment is the only place this
  was recorded outside the report.
- **In the April 2026 capture the `iaq` column is empty on all 3 139 rows**, so
  the rain channel was not reporting during that deployment window regardless.

---

## 4 · Radio parameters

Every node in a Meshtastic network must share identical radio parameters —
frequency, spreading factor, coding rate, bandwidth — or they cannot hear each
other at all. There is no partial-compatibility mode.

| Parameter | Value | Why |
|---|---|---|
| **Region** | `EU_868` | stated in the report as the legal band for Meshtastic in Cameroon |
| **Bandwidth** | 125 kHz | balances data rate against robustness |
| **Coding rate** | 4/5 | same trade-off |
| **Spreading factor** | **11 or 12 — see below** | range vs. time-on-air vs. channel capacity |
| **Transmit power** | 14 dBm | maximises range within the power budget |
| **Hop limit** | 3 | validated over three hops in the second deployment |
| **Preset** | `usePreset false` | parameters set explicitly, not via a named preset |
| **Channel 0 name** | `MALA_NTW` | must match on every node |
| **Channel 0 PSK** | `AQ==` | ⚠️ see security note |

> ⚠️ **Spreading factor: the report is internally inconsistent.** The body text
> (§3.2.1) reasons to **SF 11** — high enough for the required range with a 1 km
> margin, low enough that a 24-node network still fits the channel. The
> configuration appendices B, C and D all set `lora.spreadingFactor 12`.
> **Read the value off the deployed hardware with `meshtastic --info` before
> configuring a new node**, and match whatever is already in the field. A
> mismatched SF is not a degraded link; it is no link. See
> [`RECONCILIATION.md`](RECONCILIATION.md) item 5.

> ⚠️ **`psk "AQ=="` is the Meshtastic default public key**, not a secret. Channel
> traffic is effectively unencrypted to anyone with a Meshtastic radio in range.
> Acceptable for a research deployment carrying weather readings; it should be
> replaced with a generated key before any deployment carrying anything else.

### Why these values, briefly

Spreading factor sets symbol duration: higher SF means greater receiver
sensitivity and range, but lower data rate and longer **time on air**. Time on air
drives both energy consumption and channel occupancy, and channel occupancy caps
how many nodes the network can hold — in the EU868 band, duty cycle is typically
limited to 10 %. Each step up in SF roughly **doubles** time on air and therefore
**halves** the number of nodes a channel supports. For a 24-node network the
report concludes SF must stay at or below 11.

---

## 5 · Data flow and MQTT

Two flows:

- **Flow A, uplink** — telemetry from sensor nodes to the gateway to the broker.
- **Flow B, downlink** — configuration and instructions from the PC back to the
  mesh, over the Meshtastic **admin channel** (`security.admin_channel_enabled
  true` plus an admin key on the receiving node). This is what lets nodes be
  reconfigured over the air rather than by physical recovery.

The gateway publishes telemetry as **JSON** on a telemetry topic. A Python script
subscribed to that topic reformats and appends to a CSV. The MQTT server is a
computer in the laboratory running **Eclipse Mosquitto**, reached from the gateway
over Wi-Fi on the local area network.

### Topic structure

Meshtastic publishes under a configurable root:

```
<mqtt.root>/2/json/<channel>/<node-id>
```

> ⚠️ **The report and the collector disagree about the root.** Appendix B sets
> `mqtt.root msh/CMR_868`. All three collector copies subscribe to
> `msh/EU_868/+/json/#`. **These cannot both be right** — a subscription to
> `msh/EU_868/…` never matches a publication to `msh/CMR_868/…`. Since the
> captured CSVs contain real data, the working deployment evidently used the
> default root rather than the appendix value. The consolidated collector
> subscribes to `msh/+/2/json/#`, which matches either. See
> [`RECONCILIATION.md`](RECONCILIATION.md) item 4.

### Example payload

Structure as parsed by the collector:

```json
{
  "type": "telemetry",
  "from": 1130004144,
  "sender": "!a0cb4a5c",
  "timestamp": 1745175914,
  "rssi": -30,
  "snr": 9.75,
  "hops_away": 0,
  "payload": {
    "temperature": 31.45,
    "relative_humidity": 54.32,
    "barometric_pressure": 926.02,
    "iaq": null,
    "lux": null,
    "gas_resistance": null
  }
}
```

The collector keeps only messages where `type == "telemetry"`; everything else —
node info, position, routing — is discarded. Measurements come from `payload`;
`rssi`, `snr` and `hops_away` sit at the top level, which is the structural reason
link telemetry and weather telemetry end up on the same CSV row.

---

## 6 · Node configuration, by role

Transcribed from appendices B (gateway), C (router) and D (sensor node). The
appendices use camelCase; current CLI versions generally accept snake_case. Only
the settings that differ meaningfully between roles are shown.

### Gateway (Appendix B)

```powershell
meshtastic --set device.role CLIENT

# LoRa — identical on every node
meshtastic --set lora.usePreset false
meshtastic --set lora.region EU_868
meshtastic --set lora.bandwidth 125
meshtastic --set lora.spreadingFactor 12      # body text argues 11 — verify
meshtastic --set lora.codingRate 5
meshtastic --set lora.txPower 14
meshtastic --set lora.hopLimit 3
meshtastic --set lora.configOkToMqtt true
meshtastic --set lora.ignoreMqtt false

# Telemetry — the gateway relays, it does not measure
meshtastic --set telemetry.deviceTelemetryEnabled false
meshtastic --set telemetry.environmentMeasurementEnabled false
meshtastic --set telemetry.deviceUpdateInterval 86400
meshtastic --set telemetry.environmentUpdateInterval 295

# Wi-Fi — enabled ONLY on the gateway
meshtastic --set network.wifiEnabled true
meshtastic --set network.wifiSsid "<WIFI_SSID>"
meshtastic --set network.wifiPsk  "<WIFI_PASSWORD>"

# MQTT
meshtastic --set mqtt.enabled true
meshtastic --set mqtt.address "<MQTT_BROKER_ADDRESS>"      # the PC's IPv4
meshtastic --set mqtt.username "<MQTT_USERNAME>"           # empty if anonymous
meshtastic --set mqtt.password "<MQTT_PASSWORD>"
meshtastic --set mqtt.tlsEnabled false                     # port 1883, plain
meshtastic --set mqtt.root msh/CMR_868                     # ⚠ see topic note above

# Power / display — no sleep cycle on the gateway
meshtastic --set power.is_power_saving false
meshtastic --set display.enabled false
meshtastic --set display.screen_on_secs 5

# Position (Yaoundé)
meshtastic --setlat 3.862458014253491
meshtastic --setlon 11.499905923343643
meshtastic --setalt 700

# Channel — must match on every node
meshtastic --ch-index 0 --ch-set name "MALA_NTW"
meshtastic --ch-index 0 --ch-set psk "AQ=="
meshtastic --ch-index 0 --ch-set uplinkEnabled true
meshtastic --ch-index 0 --ch-set downlinkEnabled true

meshtastic --commit-edit
meshtastic --reboot
```

`display.screen_on_secs 5` is why the radio's screen goes dark while you are
reading it during Step 7a of the setup guide.

### Sensor node (Appendix D)

Same LoRa block. The differences:

```powershell
meshtastic --set device.role SENSOR

# MQTT off — sensor nodes speak LoRa only
meshtastic --set mqtt.enabled false
meshtastic --set lora.ignoreMqtt true

# Telemetry ON — this is the node that measures
meshtastic --set telemetry.deviceTelemetryEnabled true
meshtastic --set telemetry.environmentMeasurementEnabled true
meshtastic --set telemetry.deviceUpdateInterval 86400
meshtastic --set telemetry.environmentUpdateInterval 295

# Over-the-air administration
meshtastic --set security.admin_channel_enabled true
meshtastic --set security.admin_key "<ADMIN_KEY>"

# The rain gauge — reed switch on GPIO 4
meshtastic --set detection_sensor.enabled true
meshtastic --set detection_sensor.monitor_pin 4
meshtastic --set detection_sensor.internal_pullup true

# Sleep/wake — light sleep, see §2
meshtastic --set power.is_power_saving true
meshtastic --set power.ls_secs 240
meshtastic --set power.min_wake_secs 60
```

The `mqtt.enabled false` / `lora.ignoreMqtt true` pair is worth internalising: a
sensor-role radio will **never** connect to the broker, no matter how correct the
network configuration is. If you configure the wrong radio as a gateway, this is
the setting that silently defeats you.

---

## 7 · The deployments

### First deployment — validating the chain

| | |
|---|---|
| Location | Messa residential area + National Advanced School of Engineering, Yaoundé |
| Nodes | 5 — 1 MQTT server, 1 gateway, 1 router, 2 sensors |
| Gateway ↔ router | 1.4 km |
| Router ↔ sensors | 390 m and 350 m |
| Gateway siting | third floor, ≈ 6 m, above surrounding rooftops |
| Router siting | highest point of NASEY, ≈ 8 m |
| Duration | 2 days |
| Sampling | every 5 minutes; node info hourly (to measure battery life) |
| Not measured | ambient light |

Yaoundé's terrain is undulating, and the gateway–router path crosses a 22 m
descent followed by a 25 m rise. That relief causes shadowing and is treated in
the report as a material contributor to attenuation — relevant when interpreting
RSSI figures from this deployment.

Of the two sensor nodes, one ran the sleep/wake cycle and one stayed awake
throughout, specifically to measure what the cycle costs and saves.

### Second deployment — validating the hybrid architecture

25 nodes: MQTT server, gateway, one SenseCap router, two Heltec V3 router/sensor
nodes, and **twenty Wyres boards** with BME680. Furthest sensor 2 000 m from the
gateway, multi-hop validated over three hops, Wyres nodes within 500 m of a
router. Radio parameters and node configuration unchanged from the first
deployment, so that performance differences are attributable to the architecture
rather than the settings.

---

## 8 · Known limitations of the acquisition layer

Stated in the report, and each one has an operational consequence worth carrying
into how the data is used.

| Limitation | Consequence |
|---|---|
| **No transmission validation** — no implicit acknowledgement | packet loss is expected and normal. Gaps in the CSV are not evidence of a fault. |
| **Limited channel capacity** | the network congests as nodes are added; SF and telemetry interval trade directly against node count |
| **Node autonomy below target** | battery life remains a constraint despite the light-sleep cycle |
| **IAQ field reused for rainfall** | the label is wrong everywhere downstream; see §3 |
| **`psk "AQ=="`** | channel traffic is effectively unencrypted |
| **Single gateway** | one point of failure for the whole network |

And from this package's own [`sensor_validation/`](../sensor_validation/),
measured rather than reported:

| Finding | Consequence |
|---|---|
| **+7.3 °C siting offset** on node `!a0cb4a5c` | costs **38 %** of a forecast; corrected, 1.3 %. Dew-point agreement to 0.04 °C proves the *element* is sound — the enclosure or ventilation is not. |
| Bias flat across day and night | signature of **self-heating / poor ventilation**, not solar loading |
| No precipitation in the capture | rainfall must come from the reanalysis feed for now |
| 1 complete day in 9 | no daily or monthly mean from this log is unbiased |

---

## 9 · What is not documented here

Marked explicitly so nobody assumes it was checked:

- **The Wyres board integration and firmware modifications** — Chapter 4 of the
  report. Out of scope for the Heltec → T-Beam → Mosquitto chain described here.
- **Packet delivery ratio, RSSI/SNR and energy results** — measured and reported
  by Pierre; not reproduced or re-derived in this package.
- **Physical wiring diagrams** — the report's Appendix cross-references for sensor
  integration figures are broken in the PDF (`Appendix ??`), so the pin-level
  wiring beyond GPIO 41/42 (I²C) and GPIO 4 (rain gauge) is **not recoverable from
  the document**. Take it from the hardware.
- **Where exactly node `!a0cb4a5c` was sited.** The log carries no coordinates.
  Yaoundé is inferred from the deployment description and is consistent with the
  observed pressure, but the specific district is **unverified** — which matters,
  because the +7.3 °C offset is only meaningful against a known location.
