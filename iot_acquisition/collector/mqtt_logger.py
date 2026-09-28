"""
MQTT collector for the Meshtastic environmental sensor network.

Subscribes to the Mosquitto broker on the fixed PC, keeps telemetry messages,
flattens them and appends one row per packet to a CSV.

Consolidates the three divergent copies in `Transfert_PC_fixe/scripts/`; see
README.md in this folder for what changed and why.

    python mqtt_logger.py --broker 192.168.1.187 --port 1883

Configuration comes from the command line, or from the environment
(MQTT_BROKER, MQTT_PORT, MQTT_TOPIC, MQTT_USERNAME, MQTT_PASSWORD, MQTT_CSV).
Nothing is hard-coded to a particular deployment, because the three original
copies each hard-coded a *different* one and only one of them was ever right.

Requires: paho-mqtt >= 2.0
    pip install paho-mqtt
    # or the vendored wheel:
    # pip install ../../../Transfert_PC_fixe/packages/paho_mqtt-2.1.0-py3-none-any.whl
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt

# ── Defaults ────────────────────────────────────────────────────────────────
# The broker runs on the fixed PC. Give it the PC's own IPv4 address (from
# `ipconfig`) when running the collector on a *different* machine; the loopback
# default is correct when broker and collector share the PC, which is the
# documented setup.
DEFAULT_BROKER = "127.0.0.1"
DEFAULT_PORT = 1883

# Meshtastic publishes to  <mqtt.root>/2/json/<channel>/<node-id>.
# The single-level '+' absorbs the root's region segment, so this matches both
# the default `msh/EU_868/...` and the `msh/CMR_868/...` of the report's
# Appendix B. The original scripts pinned EU_868 and would have silently
# matched nothing had the appendix value been in use. See RECONCILIATION.md #4.
DEFAULT_TOPIC = "msh/+/2/json/#"

DEFAULT_CSV = "meteo_log.csv"

# Column order is unchanged from the log in `data/meteo_log.csv`, so existing
# consumers (sensor_validation) keep working, with `received_utc` appended.
#
# `iaq` carries RAINFALL INTENSITY in mm/h, not air quality: the Meshtastic
# protobuf telemetry message had no free field, so the modified firmware reuses
# the IAQ slot. The label survives into the payload and into this column.
# See HARDWARE_AND_NETWORK.md.
CSV_HEADER = [
    "time_utc",              # measurement time, UTC, from the message itself
    "from",                  # originating node id (numeric)
    "sender",                # gateway that published the packet
    "temperature",           # degC
    "relative_humidity",     # %
    "barometric_pressure",   # hPa
    "gas_resistance",        # ohm
    "iaq",                   # ← RAINFALL INTENSITY, mm/h
    "lux",                   # ambient light; 120 lux = 1 W/m2
    "rssi",                  # dBm      ─┐
    "snr",                   # dB        ├ link telemetry, not weather
    "hops_away",             # mesh hops ─┘
    "received_utc",          # when this PC received it, UTC
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Log Meshtastic environmental telemetry from MQTT to CSV.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--broker", default=os.environ.get("MQTT_BROKER", DEFAULT_BROKER),
                   help="broker address: the fixed PC's IPv4 address")
    p.add_argument("--port", type=int, default=int(os.environ.get("MQTT_PORT", DEFAULT_PORT)),
                   help="broker port; 1883 is plain MQTT")
    p.add_argument("--topic", default=os.environ.get("MQTT_TOPIC", DEFAULT_TOPIC),
                   help="subscription filter")
    p.add_argument("--username", default=os.environ.get("MQTT_USERNAME", ""),
                   help="leave empty for an anonymous broker")
    p.add_argument("--password", default=os.environ.get("MQTT_PASSWORD", ""))
    p.add_argument("--csv", default=os.environ.get("MQTT_CSV", DEFAULT_CSV),
                   help="output file; appended to, header written once")
    p.add_argument("--client-id", default="meteo_logger")
    p.add_argument("--raw", action="store_true",
                   help="print every message before parsing (debugging: use when "
                        "mosquitto_sub shows traffic but no rows are written)")
    return p.parse_args(argv)


def ensure_csv_header(path: Path) -> None:
    """Write the header only if the file is new or empty."""
    if path.exists() and path.stat().st_size > 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(CSV_HEADER)


def on_connect(client, userdata, flags, rc, properties=None):
    if rc != 0:
        # rc 5 is bad credentials; rc 3 is broker unreachable. A *timeout* here
        # rather than an rc means the address or the firewall is wrong --
        # see SETUP_GUIDE.md, Troubleshooting A.
        print(f"[MQTT] Connect failed rc={rc}", file=sys.stderr)
        return
    print("[MQTT] Connected")
    client.subscribe(userdata["topic"], qos=0)
    print(f"[MQTT] Subscribed to {userdata['topic']}")


def on_message(client, userdata, msg):
    if userdata["raw"]:
        print(f"[RAW] {msg.topic}  {msg.payload!r}")

    try:
        data = json.loads(msg.payload.decode("utf-8"))
    except Exception:
        # Not JSON. Almost always means the gateway is publishing protobuf
        # because its JSON output is off -- SETUP_GUIDE.md step 6.3.
        return

    if data.get("type") != "telemetry":
        return                                    # node info, position, routing

    payload = data.get("payload") or {}
    now = datetime.now(timezone.utc)

    # Prefer the message's own timestamp (epoch seconds, UTC) over reception
    # time, so the row records when the reading was *taken*. The 17.04.2026
    # copy substituted a naive `datetime.now()` here, which is why
    # `data/meteo_log.csv` holds local time in a column named `time_utc`.
    # See RECONCILIATION.md #2.
    ts = data.get("timestamp")
    measured = (datetime.fromtimestamp(float(ts), tz=timezone.utc)
                if isinstance(ts, (int, float)) else now)

    row = [
        measured.isoformat(),
        data.get("from"),
        data.get("sender"),
        payload.get("temperature"),
        payload.get("relative_humidity"),
        payload.get("barometric_pressure"),
        payload.get("gas_resistance"),
        payload.get("iaq"),                       # rainfall intensity, mm/h
        payload.get("lux"),
        data.get("rssi"),
        data.get("snr"),
        data.get("hops_away"),
        now.isoformat(),
    ]

    with userdata["csv_path"].open("a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(row)

    # Weather fields absent means this was link telemetry -- roughly half of a
    # healthy capture. Flagged so it is obvious at a glance which kind arrived.
    t = payload.get("temperature")
    kind = "link" if t is None else "data"
    print(f"[{kind.upper()}] {measured.isoformat()} sender={data.get('sender')} "
          f"T={t} RH={payload.get('relative_humidity')} "
          f"P={payload.get('barometric_pressure')} RAIN={payload.get('iaq')} "
          f"LUX={payload.get('lux')} rssi={data.get('rssi')} snr={data.get('snr')}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    csv_path = Path(args.csv)
    ensure_csv_header(csv_path)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=args.client_id,
                         userdata={"topic": args.topic, "csv_path": csv_path,
                                   "raw": args.raw})
    if args.username:
        client.username_pw_set(args.username, args.password)

    client.on_connect = on_connect
    client.on_message = on_message

    print(f"[MQTT] Connecting to {args.broker}:{args.port} ...")
    print(f"[CSV ] Appending to {csv_path.resolve()}")
    try:
        client.connect(args.broker, args.port, keepalive=60)
    except OSError as e:
        print(f"[MQTT] Cannot reach {args.broker}:{args.port} -- {e}", file=sys.stderr)
        print("       Check: Mosquitto running? port 1883 listening on 0.0.0.0? "
              "firewall rule? correct IPv4 from ipconfig?", file=sys.stderr)
        return 1

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n[MQTT] Stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
