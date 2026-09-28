# From sensor node to CSV — the reproducible procedure

Everything needed to take the hardware out of its box, configure the gateway
radio, start the MQTT broker on the fixed PC, confirm the radio reaches it, run
the Python collector, and satisfy yourself that what arrives is real environmental
data rather than radio telemetry.

Written to be followed without access to the original handover conversation.

**Time:** about 45 minutes the first time, 5 minutes on a restart.
**You need:** the gateway radio, a USB data cable, the fixed PC, and the Wi-Fi
SSID and password of the network the radio will join.

---

## Conventions used below

| Term | Means |
|---|---|
| **Sensor node** | a Heltec V3 out in the field measuring weather. Not touched in this guide. |
| **Gateway radio** | the LilyGO T-Beam S3 Core that bridges LoRa ↔ Wi-Fi ↔ MQTT. **This is the one you configure.** |
| **Fixed PC** | the desktop running Mosquitto and the Python collector. |
| **Broker** | Eclipse Mosquitto, on the fixed PC, TCP port 1883. |

Throughout, `192.168.xxx.xxx` is a placeholder for the fixed PC's real IPv4
address, which you determine in Step 3.

---

## Step 0 · Identify the correct radio — do this first

There is more than one radio in the kit, and they are not interchangeable. The
gateway radio is identified as follows:

- **black enclosure**
- **antenna attached**
- the **small** radio, with a short antenna (roughly 2 dBi by the handover
  description)
- stored in the **transparent box**
- when operating, it is **positioned near a window**

Do not use the other radio. A radio configured as a sensor or router node will
not bridge to MQTT, and the symptom — broker running, nothing connecting — looks
identical to a network fault, so you can lose an hour to it.

> ⚠️ **Verify this against the hardware before proceeding.** The handover
> description says roughly **2 dBi**. Pierre's report specifies the gateway
> (LilyGO T-Beam S3 Core) with a **4 dBi** antenna, and assigns the **2 dBi**
> antenna to the *SenseCap Solar Pro router node*. The physical description —
> black enclosure, transparent box — is the authoritative identifier here; the
> antenna gain figure is the part that conflicts between sources. Confirm the
> board silkscreen reads **T-Beam S3 Core** before configuring. See
> [`RECONCILIATION.md`](RECONCILIATION.md) item 6.

**Position of the antenna matters.** Mount it **vertically**. LoRa link budget at
this range is sensitive to antenna orientation, and a horizontal antenna against a
vertically-polarised transmitter costs you a large fraction of the link.

---

## Step 1 · Install the serial driver

Before plugging the radio into the PC, install the USB-to-serial driver. Without
it, Windows enumerates the board but no COM port appears, and the Meshtastic CLI
reports that it cannot find a device.

**Which driver you need depends on the chip, not on Meshtastic.**

| Board | MCU | Driver |
|---|---|---|
| **LilyGO T-Beam S3 Core** (the gateway) | ESP32-S3 | **ESP32 serial driver** |
| Heltec V3 (sensor nodes) | ESP32-S3 | ESP32 serial driver |
| nRF52-based boards (RAK, T-Echo) | nRF52 | nRF52 serial driver — *not used in this deployment* |

For this deployment you need the **ESP32** driver. The nRF52 page is listed here
only because it appears in the original handover notes; no nRF52 hardware is part
of this system.

The current official pages, which supersede any link pasted in a chat:

- ESP32 serial drivers — <https://meshtastic.org/docs/getting-started/serial-drivers/esp32/>
- nRF52 serial drivers — <https://meshtastic.org/docs/getting-started/serial-drivers/nrf52/>
- Driver installation test — <https://meshtastic.org/docs/getting-started/serial-drivers/test-driver/>

**Confirm the driver took.** Plug in the radio with a **data** USB cable — many
cheap cables are charge-only and will produce exactly the same symptom as a
missing driver — then:

```powershell
Get-CimInstance Win32_SerialPort | Select-Object DeviceID, Description
```

A new `COMn` entry should appear. If nothing does, run the driver installation
test page above before going further.

---

## Step 2 · Start the Mosquitto broker

The broker runs **on the fixed PC**. Everything in the chain converges on it: the
gateway radio publishes to it, and the Python collector subscribes to it.

Open a **first PowerShell window** and leave it open for the whole session:

```powershell
& "C:\Program Files\mosquitto\mosquitto.exe" -c "C:\mosquitto\mosquitto.conf" -v
```

`-v` is verbose mode. You want it: without it the window stays silent and you lose
your single best connection diagnostic.

Expected output, within a second or two:

```text
mosquitto version 2.x.x starting
Config loaded from C:\mosquitto\mosquitto.conf.
Opening ipv4 listen socket on port 1883.
Opening ipv6 listen socket on port 1883.
mosquitto version 2.x.x running
```

### The configuration file

`C:\mosquitto\mosquitto.conf` for this setup is two lines — the copy in
`Transfert_PC_fixe/Mosquitto/mosquitto.conf`:

```conf
listener 1883 0.0.0.0
allow_anonymous true
```

- `listener 1883 0.0.0.0` — listen on TCP **1883**, the standard unencrypted MQTT
  port, on **every** network interface. Mosquitto 2.x binds to localhost only by
  default, which would make the broker unreachable from the radio. This line is
  what makes the radio able to connect at all.
- `allow_anonymous true` — no username or password. Acceptable on a trusted lab
  LAN, and it is what the gateway is configured against.

> ⚠️ **Security.** These two lines make an open MQTT broker on every interface.
> Keep the PC on a LAN you control, and do not port-forward 1883 to the internet.
> If the broker must be reachable from outside, put credentials in
> `mosquitto.conf` and set `mqtt.username` / `mqtt.password` on the radio to
> match — see [`RECONCILIATION.md`](RECONCILIATION.md) item 1.

**Leave this window running.** Closing it stops the broker and everything
downstream goes silent.

---

## Step 3 · Find the fixed PC's IPv4 address

Open a **second PowerShell window**:

```powershell
ipconfig
```

Read the **IPv4 Address** of the **Ethernet** adapter — the connection the fixed
PC actually uses. Ignore `127.0.0.1`, ignore any `Wireless LAN adapter` you are
not using, and ignore virtual adapters (`vEthernet`, VirtualBox, VMware, WSL,
Hyper-V), which are a common source of a plausible-looking but useless address.

```text
Ethernet adapter Ethernet:

   IPv4 Address. . . . . . . . . . . : 192.168.xxx.xxx
   Subnet Mask . . . . . . . . . . . : 255.255.255.0
   Default Gateway . . . . . . . . . : 192.168.xxx.1
```

A narrower command if `ipconfig` output is cluttered:

```powershell
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' } |
    Select-Object InterfaceAlias, IPAddress
```

### Why this address matters

The radio and the PC are two independent devices on the LAN. The radio needs an
address to publish to, and `localhost` means *the radio itself*, so it must be
given the PC's address explicitly.

Three things must all hold:

1. **The broker runs on the fixed PC** — this is the address the radio connects to.
2. **The radio must be able to reach that address over the network.** The radio
   joins by Wi-Fi; the PC may be on Ethernet. That is fine *provided both sit on
   the same subnet or are routed to each other*. Same first three octets
   (`192.168.1.x` both sides) is the usual quick check.
3. **Port 1883** is the MQTT port used throughout this setup — plain,
   unencrypted MQTT. It is what `mosquitto.conf` listens on and what the radio
   must be pointed at. `mqtt.tlsEnabled` stays `false`.

> ⚠️ **This address is not stable.** Most LANs hand out addresses by DHCP, so it
> can change after a reboot or a lease expiry — and when it does, the radio keeps
> publishing to an address nobody is listening on, silently. If the setup goes
> quiet after having worked, **re-run `ipconfig` first.** Ask whoever runs the
> network for a DHCP reservation for the PC if this is to be permanent.

**Allow the port through the firewall.** Windows Firewall will block inbound 1883
by default, and this is the most common cause of "Mosquitto is running but the
radio never connects". Run once, in an **Administrator** PowerShell:

```powershell
New-NetFirewallRule -DisplayName "Mosquitto MQTT 1883" -Direction Inbound `
    -Protocol TCP -LocalPort 1883 -Action Allow
```

---

## Step 4 · Monitor everything arriving at the broker

Open a **third PowerShell window**:

```powershell
& "C:\Program Files\mosquitto\mosquitto_sub.exe" -v -t "#"
```

- `-t "#"` subscribes to the **wildcard topic** — every topic on the broker.
- `-v` prints the topic name alongside each payload, which is what lets you see
  what the radio actually publishes rather than guessing.

This window is your ground truth. If a message does not appear *here*, no
Python-side debugging will help — the problem is upstream.

**Leave this window running too.** You should now have three PowerShell windows
open: broker, spare/ipconfig, subscriber.

---

## Step 5 · Configure the radio over USB

Connect the gateway radio to the PC with the USB cable.

The Meshtastic CLI is a Python package:

```powershell
pip install --upgrade meshtastic
meshtastic --info
```

If `--info` reports no device, revisit Step 1 — driver, then cable.

### The two handover commands

```powershell
meshtastic --set bluetooth.enabled true
meshtastic --set network.wifi_enabled false
```

**What each one does, and why in this order:**

- `bluetooth.enabled true` — turns the radio's Bluetooth radio on so a phone can
  pair with it. The remaining configuration (MQTT server address, Wi-Fi SSID,
  Wi-Fi password) is done from the Meshtastic phone app over Bluetooth, so this
  must be enabled *before* you unplug the USB cable. Do this even though the
  deployment configuration ultimately disables Bluetooth to save power — you need
  it as the configuration channel first.

- `network.wifi_enabled false` — turns Wi-Fi **off for now**. On ESP32 boards
  Wi-Fi and Bluetooth share one radio front end; leaving both on during setup
  causes the Bluetooth link to drop and reconnect while you are typing settings
  into the phone app. You will switch Wi-Fi back on from the phone in Step 6,
  once the SSID and password are actually in place. Enabling Wi-Fi before it has
  credentials just makes the radio retry against a network it cannot join.

> **A note on option naming.** The CLI accepts `network.wifi_enabled`
> (snake_case). Pierre's report appendices write the same settings in camelCase —
> `network.wifiEnabled`, `network.wifiSsid`, `network.wifiPsk`. Both refer to the
> same protobuf fields. Use whichever your installed CLI version accepts; if one
> form errors, try the other. See [`RECONCILIATION.md`](RECONCILIATION.md) item 9.

### Verify the settings were actually saved

This is the step people skip, and it is the one that catches a silent failure:

```powershell
meshtastic --info
```

Read the output and confirm:

| Look for | Expect |
|---|---|
| `bluetooth` → `enabled` | `true` |
| `network` → `wifiEnabled` | `false` (for now) |
| `lora` → `region` | `EU_868` |
| `device` → `role` | `CLIENT` |
| The node's own ID | note it — `!xxxxxxxx`, you will match it against MQTT later |

A `--set` that returned no error but did not persist is a real failure mode —
usually from a dropped USB link mid-write. If `--info` does not show what you set,
set it again before continuing.

### Restart the radio

```powershell
meshtastic --reboot
```

Configuration changes take effect on reboot. Wait for the radio to come back up —
the screen flickers and the boot splash appears — before unplugging.

---

## Step 6 · Finish the configuration from the phone

With Bluetooth now on, the rest is done from the Meshtastic app.

1. **Pair the phone to the radio over Bluetooth.** In the Meshtastic app, add the
   device; it appears under its node name. If the app asks for a pairing code, it
   is shown on the radio's screen.
2. **Open the Meshtastic application** and select the radio.
3. **Set the MQTT address** to the fixed PC's IPv4 address from Step 3 —
   `192.168.xxx.xxx`. Under *Module Settings → MQTT*:
   - **Address**: `192.168.xxx.xxx` (append `:1883` only if the field requires an
     explicit port; 1883 is the default)
   - **Username / Password**: leave empty — the broker is `allow_anonymous true`
   - **Encryption / TLS**: **off**
   - **MQTT enabled**: on
   - **JSON output**: **on** — the Python collector parses JSON, not protobuf.
     Without this the broker still shows traffic but the collector sees nothing it
     can decode.
4. **Configure the Wi-Fi network** under *Radio Configuration → Network*:
   - **SSID** of the network the radio will join
   - **Password** for that network
   - The radio supports **2.4 GHz only**. A 5 GHz-only SSID will never associate.
5. **Enable Wi-Fi on the radio** — now, and not before, because the credentials
   are in place.
6. **Disable Bluetooth last**, after every other step is done and verified.

### Why Bluetooth is disabled last

Bluetooth is the only channel you have to the radio once the USB cable is
unplugged. Disabling it before the Wi-Fi and MQTT settings are confirmed working
leaves you with no way to correct a mistake — a wrong SSID or a mistyped IP means
the radio is unreachable over Wi-Fi *and* unreachable over Bluetooth, and
recovering it requires plugging the USB cable back in.

There is also a functional reason to disable it eventually: Bluetooth and Wi-Fi
share the ESP32 front end and Bluetooth is among the most power-hungry modules on
the board. Pierre's deployment configuration disables Bluetooth and the display on
all nodes for exactly this reason.

**So: configure everything, verify it works end to end (Steps 7 and 8), and only
then turn Bluetooth off.**

---

## Step 7 · Verify the radio reached the network

Two independent checks. Do both — each catches a failure the other misses.

### 7a · On the radio's own screen

The radio has a small OLED screen and a button.

1. **Press the button once to wake the screen.** It sleeps quickly to save power.
2. **Press it repeatedly to page through** the displayed screens — node list,
   position, and so on.
3. **Find the Network page.**
4. **Confirm it shows a connected status** — an assigned IP address and the SSID
   it joined.

The screen times out after a few seconds (`display.screen_on_secs` is 5 in the
deployment configuration), so you will likely need to wake it again to read the
page properly. That is expected, not a fault.

If the Network page shows no IP, the radio has not joined Wi-Fi — the SSID,
password, or 2.4 GHz band is wrong. Go back to Step 6.4.

### 7b · In the Mosquitto window — the main validation step

Look at the **first PowerShell window**, the one running the broker. Within a few
seconds of the radio joining Wi-Fi it should print:

```text
New connection from 192.168.xxx.xxx on port 1883.
New client connected from 192.168.xxx.xxx as <client-id> (p2, c1, k60).
```

**This line is the single most important confirmation in the whole procedure.** It
means, in one stroke: the radio is on the network, it resolved and reached the
PC's address, the firewall let it through, port 1883 is open, and the broker
accepted it. Everything before this step is setup; everything after depends on it.

The address in that line should be the **radio's** address, not the PC's — both
sit on the same subnet, so they look similar. If you see no such line, go to
[Troubleshooting → the broker receives no connection](#a--the-broker-receives-no-connection).

---

## Step 8 · Validate that real measurements arrive

A connection is not data. This step separates the two.

### 8a · Watch the raw MQTT stream

With the broker still running, look at the **third window** (`mosquitto_sub -v -t
"#"`). Messages should appear on topics shaped like:

```text
msh/<root>/2/json/<channel>/<node-id>
```

### Read the payload carefully — this is where people go wrong

Not every message carries weather. Two kinds arrive, and they look similar at a
glance:

**Network / MQTT metadata** — link and housekeeping information:

| Field | Meaning |
|---|---|
| `rssi` | received signal strength, dBm — a radio measurement, not a weather one |
| `snr` | signal-to-noise ratio, dB |
| `hops_away` | how many mesh hops the packet travelled |
| `from`, `sender`, `id` | routing identity |
| connection notices, node-info, position broadcasts | housekeeping |

**Environmental measurements** — what the system exists to collect:

| Field | Meaning | Unit |
|---|---|---|
| `temperature` | air temperature | °C |
| `relative_humidity` | relative humidity | % |
| `barometric_pressure` | atmospheric pressure | hPa |
| `iaq` | **rainfall intensity** — see note | mm/h |
| `lux` | ambient light (→ surface irradiance at 120 lux = 1 W/m²) | lux |
| `gas_resistance` | BME680 gas sensor | Ω |

> **`iaq` is rainfall.** Pierre's firmware repurposes the `iaq` (indoor air
> quality) slot to carry rainfall intensity, because the protobuf telemetry
> message had no room for another field. The label `iaq` persists in the payload
> and in the CSV. Do not read it as air quality, and do not assume rainfall is
> missing because you see no field named for it.

> **A message containing only `rssi` and `snr` does not mean the environmental
> sensors are working.** It means a packet arrived. In the April 2026 capture,
> **half of all rows carry no reading at all** — 1 567 of 3 139 rows have
> temperature; the rest are pure link telemetry. That ratio is normal for this
> system, not a fault. What matters is whether *any* message carries
> `temperature`, `relative_humidity` and `barometric_pressure`.

Only when you have seen a payload containing actual measurements should you move
on.

### 8b · Run the Python collector

Install the dependency — the wheel is vendored in
`Transfert_PC_fixe/packages/paho_mqtt-2.1.0-py3-none-any.whl`, or:

```powershell
pip install paho-mqtt
```

Then run the consolidated collector:

```powershell
cd <package>\13_IOT_ACQUISITION\collector
python mqtt_logger.py --broker 192.168.xxx.xxx --port 1883 --csv meteo_log.csv
```

Substitute the address from Step 3. Configuration can also come from environment
variables (`MQTT_BROKER`, `MQTT_PORT`, `MQTT_TOPIC`, …) — see
[`collector/README.md`](collector/README.md).

> The original scripts in `Transfert_PC_fixe/scripts/` hard-code three *different*
> broker addresses between them, one of them a remote host with embedded
> credentials. The consolidated script takes the address as an argument instead.
> [`RECONCILIATION.md`](RECONCILIATION.md) item 1 explains the divergence.

Expected output:

```text
[MQTT] Connecting to 192.168.xxx.xxx:1883 ...
[MQTT] Connected
[MQTT] Subscribed to msh/+/2/json/#
[LOG] 2026-04-20T19:05:14 sender=!a0cb4a5c T=31.45 RH=54.32 P=926.02 RAIN=None
```

### 8c · The four things to verify, in order

| # | Check | How |
|---|---|---|
| 1 | **MQTT messages are received at all** | the `mosquitto_sub` window is printing |
| 2 | **The collector receives them** | `[LOG]` lines appear in the collector window |
| 3 | **Environmental measurements are extracted** | those `[LOG]` lines show `T=`, `RH=` and `P=` with **numbers**, not `None` |
| 4 | **Rows reach the CSV** | inspect the file |

For check 4:

```powershell
Get-Content meteo_log.csv -Tail 5
```

And to confirm the readings are genuinely landing rather than only the link
telemetry:

```powershell
python -c "import csv;r=list(csv.DictReader(open('meteo_log.csv',encoding='utf-8')));print(len(r),'rows;',sum(1 for x in r if x['temperature']),'carry temperature')"
```

If that second number is `0`, messages are arriving but no environmental payload
is reaching the parser — go to
[Troubleshooting → messages arrive but carry no environmental data](#b--messages-arrive-but-carry-no-environmental-data).

### 8d · About the timestamp column

The column is named `time_utc`, but **what it holds depends on which collector
wrote it.** The consolidated script writes a true UTC timestamp and also records
the local receive time in a separate column. The historical
`1_DATA/meteo_log.csv` was written by a variant using `datetime.now()`, so its
`time_utc` values are **local time on the fixed PC, despite the column name**.

This matters when aligning against reanalysis data by hour.
[`RECONCILIATION.md`](RECONCILIATION.md) item 3 documents the consequence for
`12_SENSOR_VALIDATION`.

---

## Troubleshooting

### A · The broker receives no connection

*Symptom: Mosquitto is running, but no `New connection from …` line ever appears.*

Work down this list in order — it is ordered by how often each turns out to be
the cause.

| # | Check | How |
|---|---|---|
| 1 | **Mosquitto is actually running** | the first window shows `mosquitto version … running` and has not exited. `Get-Process mosquitto` |
| 2 | **Port 1883 is listening on all interfaces** | `Get-NetTCPConnection -LocalPort 1883 -State Listen` — `LocalAddress` must be `0.0.0.0`, not `127.0.0.1`. If it is localhost-only, `mosquitto.conf` is not being read or lacks `listener 1883 0.0.0.0`. |
| 3 | **The firewall permits inbound 1883** | the rule from Step 3. This is the most common single cause. |
| 4 | **The PC IPv4 address is correct and current** | re-run `ipconfig`. DHCP may have changed it since you configured the radio. Confirm you read the *Ethernet* adapter, not a virtual one. |
| 5 | **The radio joined the correct Wi-Fi network** | radio screen → Network page shows an IP and the expected SSID (Step 7a). 2.4 GHz only. |
| 6 | **The MQTT address on the radio matches the PC** | re-open the phone app and read the MQTT address field back. A single wrong digit produces exactly this symptom. |
| 7 | **Radio and PC are on the same subnet** | compare the first three octets. A radio on a guest VLAN, or on `192.168.0.x` while the PC is on `192.168.1.x`, cannot reach the broker even though both have working internet. |
| 8 | **This is the gateway radio** | Step 0. A sensor- or router-role radio has `mqtt.enabled false` and `lora.ignoreMqtt true` and will never connect. Confirm with `meshtastic --info`. |
| 9 | **The radio has network and radio connectivity** | it is powered, the antenna is attached and vertical, and it is near the window. |

A quick end-to-end test of everything except the radio — from **another machine**
on the same LAN:

```powershell
Test-NetConnection 192.168.xxx.xxx -Port 1883
```

`TcpTestSucceeded : True` proves the broker is reachable across the network, which
narrows the fault to the radio's configuration.

### B · Messages arrive but carry no environmental data

*Symptom: `mosquitto_sub` prints traffic, but no temperature ever appears.*

| # | Check | Notes |
|---|---|---|
| 1 | **Is this only radio/network telemetry?** | `rssi`, `snr`, `hops_away`, node-info and position broadcasts are not weather. Roughly **half** of all packets in a healthy capture are exactly this. Look at more messages before concluding anything. |
| 2 | **Is JSON output enabled on the gateway?** | if the gateway publishes protobuf rather than JSON, `mosquitto_sub` shows binary noise and the collector's `json.loads` fails silently on every message. Step 6.3. |
| 3 | **Is the correct sensor node powered and in range?** | the gateway relays only what it receives. A gateway with no sensor node in range connects to MQTT perfectly and reports nothing but its own telemetry. |
| 4 | **Is the sensor node transmitting environmental measurements?** | on the sensor node, `telemetry.environmentMeasurementEnabled` must be `true` and `telemetry.environmentUpdateInterval` set (295 s in this deployment). Note the **gateway** has this deliberately `false` — it relays, it does not measure. |
| 5 | **Is the gateway radio the correct one?** | Step 0 again. |
| 6 | **Is the radio positioned correctly?** | antenna vertical, near the window, away from metal. |
| 7 | **Does the parser expect the right payload shape?** | the collector keeps only messages where `type == "telemetry"` and reads measurements from `payload`. A firmware or Meshtastic version change that alters that shape makes every message parse to nothing. Print a raw message and compare against the field table in Step 8a. |
| 8 | **Is the topic filter matching?** | the subscription must match the gateway's `mqtt.root`. See item C3 below — this is a known discrepancy in this project. |

A one-line way to see whether *any* environmental payload is on the wire,
independent of the collector:

```powershell
& "C:\Program Files\mosquitto\mosquitto_sub.exe" -v -t "#" | Select-String "temperature"
```

### C · No data from the physical sensor network

*Symptom: the broker is healthy and the gateway is connected, but nothing from the
field.*

| # | Check |
|---|---|
| 1 | **The correct black-enclosure radio with antenna is in use** — Step 0 |
| 2 | **The antenna is connected and vertical** — never power a LoRa radio with the antenna detached; it risks the transmitter as well as costing range |
| 3 | **The radio is near the window** — the gateway needs line of sight toward the mesh; concrete and rebar attenuate 868 MHz severely |
| 4 | **The mesh is connected** — the radio's node list screen should show the sensor node. Radio parameters must match **exactly** across every node: region `EU_868`, bandwidth 125 kHz, coding rate 4/5, spreading factor, and the same channel name and PSK. A single mismatched parameter makes nodes mutually invisible. |
| 5 | **The gateway is connected to Wi-Fi** — Step 7a |
| 6 | **Mosquitto shows the radio connection** — Step 7b |
| 7 | **The sensor node is powered** — it runs on a LiPo battery with a sleep/wake cycle; a flat battery is silent, not noisy |
| 8 | **Enough time has elapsed** — telemetry interval is **295 s**. Wait at least 10 minutes before calling it a failure. |

> **Known limitation, not a fault.** Pierre's report records that the mesh has no
> transmission-validation mechanism such as implicit acknowledgement, so **packet
> loss is expected and unremarkable**. Intermittent gaps are a property of this
> system. The April 2026 capture spans nine days and contains **one complete
> day**; two days are entirely missing. Judge the link by whether data flows at
> all, not by whether it is continuous.

### D · The setup worked yesterday and is silent today

The overwhelmingly likely cause is a **DHCP lease change on the fixed PC**. The
radio is still publishing, to an address that no longer belongs to the PC.

1. `ipconfig` on the PC.
2. Compare against the MQTT address stored on the radio.
3. If they differ, update the radio — which means re-enabling Bluetooth, so plug
   the USB cable back in and use `meshtastic --set bluetooth.enabled true`, or set
   the MQTT address directly over USB.
4. Ask for a DHCP reservation so it does not recur.

---

## Restarting after a reboot

The short version, once everything is configured:

```powershell
# window 1 — broker
& "C:\Program Files\mosquitto\mosquitto.exe" -c "C:\mosquitto\mosquitto.conf" -v

# window 2 — raw monitor
& "C:\Program Files\mosquitto\mosquitto_sub.exe" -v -t "#"

# window 3 — check the address has not changed, then collect
ipconfig
python mqtt_logger.py --broker 192.168.xxx.xxx --port 1883 --csv meteo_log.csv
```

Power the gateway radio; watch window 1 for `New connection from …`.

---

## What happens to the CSV

`meteo_log.csv` is a **raw capture**, one row per received packet. It is not in
the schema the prediction pipeline consumes, and the adapter between the two does
not exist yet. Before feeding it to anything, read:

- [`README.md`](README.md) — the five transformations required, and the decision
  each one needs
- [`../12_SENSOR_VALIDATION/`](../12_SENSOR_VALIDATION/) — the **+7.3 °C siting
  offset** on the deployed node, worth 38 % of a forecast
