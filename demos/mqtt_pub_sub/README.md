# mqtt_pub_sub: board and host both talk to a local broker

End-to-end demo of `chumicro_mqtt` running on a real board, with a
local Mosquitto broker bridging it to a CPython-side `chumicro_mqtt`
counterparty.  Exercises connect, retained messages, wildcard
subscriptions, and QoS 1 publish-with-PUBACK in both directions, in
one command, with no broker setup beyond `brew install mosquitto`.

The board wires `chumicro_wifi.WifiService` + `chumicro_mqtt.MQTTClient`
into one `chumicro_runner.Runner` and drives them with
`runner.run_until(..., timeout_ms=...)` (the packaged form of the
tick-and-wait loop), the same shape the root README's
["Give WiFi a deadline and keep blinking"](../../README.md#give-wifi-a-deadline-and-keep-blinking)
walkthrough uses.  It reads like a mainstream MQTT quickstart: set a
Last Will, set the callbacks once, connect, let the loop run.  All the
connect-time setup lives in one `on_connect` (the publish and the
subscribe fire independently, neither waiting on the other's ack), so
there is no callback cascade.

## What it shows

- **Runner-driven composition.** `WifiService` and `MQTTClient`
  added with `runner.add(...)`, telemetry pacing through
  `runner.add_periodic(...)`, the same pattern beginners read first
  in the top-level README.
- **Local broker.** The driver spawns Mosquitto on the host's LAN IP
  via `chumicro_pytest_device.fixtures.mosquitto.start_mosquitto_broker`
  so the board (joining the same wifi) can reach it.
- **Presence via Last Will.** Board sets a retained `"offline"` Last
  Will, then publishes a retained `"online"` on connect.  The broker
  publishes the `"offline"` automatically if the board drops uncleanly.
- **Retained messages.** Board publishes `demo/<client_id>/state` →
  `"online"` with `retain=True`.  Host subscribes to `demo/+/state`
  and gets the retained payload back on SUBACK without the board
  republishing.
- **Wildcard subscriptions.** Host subscribes to `demo/+/state` and
  `demo/+/telemetry`: the `+` matches the per-board client id.
- **QoS 1 in both directions.** Board publishes three telemetry
  samples with `on_publish` callbacks proving each PUBACK landed.
  Host publishes a command to `demo/<client_id>/cmd` with its own
  PUBACK proof.

## Run it

```bash
.venv/bin/python demos/mqtt_pub_sub/driver.py
```

Defaults: targets the first CircuitPython device in `devices.yml`.

Override:

- `--device <id>`: a specific device id from `devices.yml`.
- `--runtime micropython`: pick the first MicroPython device.
- `--connect-timeout-s <n>`: how long to wait for the board's
  `MQTT_CONNECTED` marker (default 60 s).
- `--telemetry-timeout-s <n>`: how long to wait for all three
  telemetry receipts on the host (default 30 s).
- `--completion-timeout-s <n>`: how long to wait for `DEMO_COMPLETE`
  after the round trip (default 120 s).

## Expected output

```
driver: started mosquitto on 10.0.0.5:54321
driver: targeting pi-pico-w-circuitpython-board (circuitpython @ /dev/cu.usbmodem...)
driver: host MQTT client connected (chumicro-mqtt-demo-driver)
driver: waiting for board MQTT_CONNECTED (up to 60.0s)...
driver: board MQTT_CONNECTED client_id=chumicro-mqtt-demo-board broker=10.0.0.5:54321
driver: HOST_RX demo/chumicro-mqtt-demo-board/state payload=online (retained)
driver: host published cmd to demo/chumicro-mqtt-demo-board/cmd (qos=1), PUBACK received
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
