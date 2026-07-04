"""Optional host-side companion to ``bench.py``.

``bench.py`` is fully self-driving.  It runs every scenario on-device,
prints a summary table to serial, and publishes a one-line verdict to
``<client_id>/bench-summary``.  Nothing here is required for the
self-driving run.

What this script adds (when you want it):

* **Verdict capture from the host.**  Subscribes to
  ``<client_id>/bench-summary`` and prints the device's verdict line.
  Useful in headless / CI setups where you don't want to babysit a
  serial console.
* **Truly hostile oversized payloads.**  Optionally publishes a much
  larger payload than the device could comfortably build on its own
  (e.g. 64 KB) so you can verify the on-device oversize-drain path
  stays heap-bounded even against a hostile sender.  Use ``--hostile``.

Prerequisites
=============

::

    pip install paho-mqtt    # one-time host-side install

Usage
=====

::

    # Default: just listen for the device's bench-summary verdict.
    python bench_host.py --broker mqtt.example.com

    # Publish a 64 KB hostile payload first, then listen for the verdict.
    python bench_host.py --broker mqtt.example.com --hostile

    # Different client_id (matches the CLIENT_ID constant in bench.py).
    python bench_host.py --broker mqtt.example.com --client-id my-thing

The device's bench publishes its verdict after the keepalive scenario
ends (~3.5 minutes after start).  This script exits after the verdict
arrives or after ``--timeout`` seconds.
"""

import argparse
import sys
import time

try:
    import paho.mqtt.client as mqtt  # noqa: PLC0415 - host-side optional dep
except ImportError:
    sys.stderr.write(
        "this example needs paho-mqtt; install with `pip install paho-mqtt`\n"
    )
    sys.exit(1)


DEFAULT_CLIENT_ID = "chumicro-mqtt-bench"
DEFAULT_TIMEOUT = 300


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--broker", required=True,
                        help="Broker hostname / IP (must match the device's broker).")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument(
        "--client-id", default=DEFAULT_CLIENT_ID,
        help=f"Match the CLIENT_ID constant in bench.py (default: {DEFAULT_CLIENT_ID}).",
    )
    parser.add_argument(
        "--hostile", action="store_true",
        help="Publish a 64 KB payload before listening — extra oversized-tier stress.",
    )
    parser.add_argument(
        "--hostile-bytes", type=int, default=65536,
        help="Size of the hostile payload in bytes (default 65536).",
    )
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT,
        help=f"Max seconds to wait for the device's verdict (default {DEFAULT_TIMEOUT}).",
    )
    args = parser.parse_args()

    summary_topic = f"{args.client_id}/bench-summary"
    inbound_topic = f"{args.client_id}/inbound"

    verdict = {"line": None}

    def on_connect(client, _userdata, _flags, _rc, _properties=None):
        client.subscribe(summary_topic, qos=0)
        print(f"[host] subscribed to {summary_topic}")

    def on_message(_client, _userdata, message):
        verdict["line"] = message.payload.decode(errors="replace")
        print(f"[device verdict] {verdict['line']}")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"{args.client_id}-host")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(args.broker, args.port, keepalive=60)
    client.loop_start()

    # Give SUBACK a moment to land before we publish the hostile payload.
    time.sleep(0.5)

    if args.hostile:
        payload = b"H" * args.hostile_bytes
        client.publish(inbound_topic, payload, qos=0)
        print(f"[host] published hostile payload bytes={args.hostile_bytes} -> {inbound_topic}")

    deadline = time.time() + args.timeout
    while verdict["line"] is None and time.time() < deadline:
        time.sleep(0.5)

    client.loop_stop()
    client.disconnect()

    if verdict["line"] is None:
        print(f"[host] TIMEOUT — no verdict within {args.timeout}s")
        return 1
    if verdict["line"].startswith("ALL_OK"):
        print("[host] PASS")
        return 0
    print("[host] FAIL")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
