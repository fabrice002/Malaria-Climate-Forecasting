# collector/ — the consolidated MQTT collector

One script, replacing the three divergent copies in
`Transfert_PC_fixe/scripts/`. Subscribes to the Mosquitto broker, keeps telemetry
messages, appends one row per packet to a CSV.

```powershell
pip install paho-mqtt
python mqtt_logger.py --broker 192.168.xxx.xxx --port 1883 --csv meteo_log.csv
```

The vendored wheel works too, if the PC is offline:

```powershell
pip install ..\..\..\Transfert_PC_fixe\packages\paho_mqtt-2.1.0-py3-none-any.whl
```

Configuration is by flag or environment variable — `MQTT_BROKER`, `MQTT_PORT`,
`MQTT_TOPIC`, `MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_CSV`. `--help` lists
everything.

---

## What it prints

Every accepted message produces one line, tagged by what it carried:

```text
[DATA] 2026-04-20T19:05:14+00:00 sender=!a0cb4a5c T=31.45 RH=54.32 P=926.02 RAIN=2.8 LUX=1200 rssi=-30 snr=9.75
[LINK] 2026-04-20T19:05:30+00:00 sender=!a0cb4a5c T=None RH=None P=None RAIN=None LUX=None rssi=-29 snr=7.25
```

`[DATA]` carried environmental measurements. `[LINK]` was radio telemetry only —
`rssi`/`snr`/`hops_away`, no weather. **Roughly half of a healthy capture is
`[LINK]`**; in the April 2026 log it was 1 572 of 3 139 rows. Seeing `[LINK]`
lines is normal. Seeing *only* `[LINK]` lines is the symptom described in
[`../SETUP_GUIDE.md`](../SETUP_GUIDE.md) Troubleshooting B.

`RAIN=` is the `iaq` field. It is labelled `iaq` in the payload and in the CSV
because Pierre's firmware reuses that slot for rainfall intensity in mm/h — see
[`../HARDWARE_AND_NETWORK.md`](../HARDWARE_AND_NETWORK.md).

---

## Output schema

Column order is **unchanged** from `1_DATA/meteo_log.csv`, with one column
appended, so `12_SENSOR_VALIDATION` keeps working against files this script
writes.

| Column | Meaning | Kind |
|---|---|---|
| `time_utc` | **measurement** time, true UTC, from the message | time |
| `from` | originating node id (numeric) | identity |
| `sender` | gateway that published the packet | identity |
| `temperature` | °C | **environmental** |
| `relative_humidity` | % | **environmental** |
| `barometric_pressure` | hPa | **environmental** |
| `gas_resistance` | Ω (BME680) | environmental |
| `iaq` | **rainfall intensity, mm/h** | **environmental** |
| `lux` | ambient light; 120 lux = 1 W/m² | environmental |
| `rssi` | dBm | link telemetry |
| `snr` | dB | link telemetry |
| `hops_away` | mesh hops traversed | link telemetry |
| `received_utc` | when this PC received it, UTC | time *(new)* |

Header is written once, on a new or empty file; runs append.

---

## What changed, and why

The three originals differed in ways that mattered. Each change below is
traceable to a numbered entry in [`../RECONCILIATION.md`](../RECONCILIATION.md).

| # | Was | Now | Why |
|---|---|---|---|
| 1 | Three hard-coded brokers — `187.77.168.222:58258` with credentials `ENSPY`/`ENSPY2023`, `192.168.0.102:1883`, `192.168.1.187:1883` | `--broker` / `--port`, defaulting to `127.0.0.1:1883` | the top-level copy pointed at a remote host and would never reach the local broker. Credentials do not belong in a distributed file. |
| 2 | `17.04.2026` wrote naive local time into `time_utc`; the others wrote true UTC | always true UTC, from the message's own timestamp; reception time moved to `received_utc` | the column name was a lie in the copy that produced the shipped data |
| 4 | `msh/EU_868/+/json/#` | `msh/+/2/json/#`, overridable with `--topic` | pinned the region segment, so it would match nothing if `mqtt.root` were `msh/CMR_868` as the report's Appendix B specifies |
| 7 | `lux` in two copies, absent in the third; `iaq` meaning recorded only in a stray comment | union of all columns; `iaq` documented as rainfall in the header comment, the schema table and the log line | the top-level script could not write `lux` at all, yet the CSV beside it had the column |
| 8 | Three copies, silently divergent | one script | nobody could tell which was canonical |
| — | `json.loads` failure returned silently | still returns, but `--raw` prints every message pre-parse | a gateway publishing protobuf instead of JSON produced total silence with no clue why |
| — | Connection refusal printed `rc=N` and continued | unreachable broker exits 1 with the checklist | the most common first-run failure deserved a pointer |
| — | No CLI | `argparse` with `--help` | the originals required editing source to change a broker |

### Behaviour deliberately preserved

- Only `type == "telemetry"` messages are kept; node info, position and routing
  are dropped.
- Measurements are read from `payload`; `rssi` / `snr` / `hops_away` from the top
  level.
- Rows are appended immediately, file reopened per row — slow, but a `Ctrl-C` or
  power cut loses nothing.
- QoS 0, keepalive 60, as before.

---

## Verified

Parsing logic was exercised against four synthetic payloads:

| Input | Expected | Result |
|---|---|---|
| telemetry with T/RH/P/iaq/lux | one row, 13 columns, `[DATA]` | ✅ |
| telemetry with empty payload | one row, weather blank, `[LINK]` | ✅ |
| `type: nodeinfo` | dropped | ✅ |
| malformed non-JSON bytes | dropped without raising | ✅ |

Not tested against a live broker — that requires the hardware. The connection
path is unchanged from the originals, which are known to work.

---

## The originals

Left untouched in `Transfert_PC_fixe/scripts/` as the historical record:

| Copy | Broker | Timestamps | `lux` | Produced |
|---|---|---|---|---|
| `mqtt_logger.py` | remote, credentialed | UTC | ✗ | — |
| `17.04.2026/mqtt_logger.py` | `192.168.0.102` | **local** | ✓ | `1_DATA/meteo_log.csv` (3 139 rows) |
| `test30.03.2026/mqtt_logger.py` | `192.168.1.187` | UTC | ✓ | 45-row multi-node capture |

`1_DATA/meteo_log.csv` is byte-identical to the `17.04.2026` capture
(md5 `3816ede8402b4ea51ae1fa49f89c4a40`), so **the 17.04 copy — not the top-level
one — is what produced the data the thesis uses**.
