# mqtt_pub_sub — board and host both talk to a local broker

End-to-end demo of `chumicro_mqtt` running on a real board, with a
local Mosquitto broker bridging it to a CPython-side `chumicro_mqtt`
counterparty.  Exercises connect, retained messages, wildcard
subscriptions, QoS 1 publish-with-PUBACK in both directions, and a
pattern handler — in one command, with no broker setup beyond
`brew install mosquitto`.

The board uses the canonical libraries — `chumicro_runner.Runner`
drives `chumicro_wifi.WifiService` + `chumicro_mqtt.MQTTClient` in
one `while True: runner.tick(); runner.wait(now_ms)` loop, with
orchestration entirely event-driven through library callbacks.

## What it shows

- **Canonical composition.** `Runner` + `WifiService` +
  `MQTTClient.from_config` + `chumicro_config.load_runtime_config`.
  No hand-rolled drive loops, no test-harness shortcuts.
- **Local broker.** The driver spawns Mosquitto on the host's LAN IP
  via `chumicro_pytest_device.fixtures.mosquitto.start_mosquitto_broker`
  so the board (joining the same wifi) can reach it.
- **Retained messages.** Board publishes `demo/<client_id>/state` →
  `"online"` with `retain=True`.  Host subscribes to `demo/+/state`
  and gets the retained payload back on SUBACK without the board
  republishing.
- **Wildcard subscriptions.** Host subscribes to `demo/+/state` and
  `demo/+/telemetry` — the `+` matches the per-board client id.
- **QoS 1 in both directions.** Board publishes three telemetry
  samples with `on_publish` callbacks proving each PUBACK landed.
  Host publishes a command to `demo/<client_id>/cmd` with its own
  PUBACK proof.
- **Pattern handler.** Board registers a handler for `demo/+/cmd`
  alongside its `on_message` — both fire when the host's cmd arrives.

## Run it

```bash
.venv/bin/python demos/mqtt_pub_sub/driver.py
```

Defaults: targets the first CircuitPython device in `devices.yml`.

Override:

- `--device <id>` — a specific device id from `devices.yml`.
- `--runtime micropython` — pick the first MicroPython device.
- `--connect-timeout-s <n>` — how long to wait for the board's
  `MQTT_CONNECTED` marker (default 60 s).

## Expected output

```
driver: started mosquitto on 10.0.0.5:54321
driver: targeting pi-pico-w-circuitpython-board (circuitpython @ /dev/cu.usbmodem...)
driver: waiting for board MQTT_CONNECTED (up to 60.0s)...
driver: board MQTT_CONNECTED client_id=chumicro-mqtt-demo-board broker=10.0.0.5:54321
driver: host MQTT client connected (chumicro-mqtt-demo-driver)
driver: HOST_RX demo/chumicro-mqtt-demo-board/state payload=online (retained)
driver: host published cmd to demo/chumicro-mqtt-demo-board/cmd (qos=1) — PUBACK in
driver: HOST_RX demo/chumicro-mqtt-demo-board/telemetry payload={"seq": 1, "value": 21, "uptime_ms": 412}
driver: HOST_RX demo/chumicro-mqtt-demo-board/telemetry payload={"seq": 2, "value": 22, "uptime_ms": 1934}
driver: HOST_RX demo/chumicro-mqtt-demo-board/telemetry payload={"seq": 3, "value": 23, "uptime_ms": 3447}
driver: telemetry 3/3 received
driver: demo completed cleanly.
```

## What it requires

- A board registered in `devices.yml`.
- `secrets.toml` at the repo root with `wifi.ssid` + `wifi.password`.
- A reachable wifi network the board can join.
- `mosquitto` on PATH (`brew install mosquitto` /
  `apt install mosquitto`).

## Known issues

- **Pi Pico W CP wifi `ConnectionError: Unknown failure 1` after deploy.**
  The same `wifi_up()` call works in the `http_server_roundtrip` demo on
  the same board, so the AP + credentials are valid; something in the
  mqtt demo's deploy ordering puts the CP wifi radio into a state where
  the first `wifi.radio.connect` returns ConnectionError until a
  power-cycle.  End-to-end has been validated on an ESP32-S2 Lolin S2
  CP board.  Rooting out the Pico-W-specific path is tracked in
  `plans/next-up.md`.
