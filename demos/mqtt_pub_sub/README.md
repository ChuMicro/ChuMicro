# mqtt_pub_sub: your board talks MQTT both ways

Your board joins wifi and connects to an MQTT broker that the driver
starts on your laptop. The board announces that it is online, publishes
a message every two seconds, and prints any command your laptop sends
it. A script on your laptop plays the other side: it watches the board's
messages and sends one command back.

MQTT is a small publish/subscribe protocol. Everyone connects to one
broker, publishes messages to named topics, and subscribes to the
topics they care about.

## What you will see

The driver's own lines start with `driver:`. Everything the board
prints shows up as it happens, after `board |`. Each message the board
sends appears twice: once as the board sends it, once as your laptop
receives it.

```
driver: started mosquitto on 10.0.0.5:54321
driver: targeting pi-pico-w-circuitpython-board (circuitpython @ /dev/cu.usbmodem...)
driver: host MQTT client connected (chumicro-mqtt-demo-driver)
driver: waiting for board MQTT_CONNECTED (up to 60.0s)...
board |   waiting for the broker...
board | WIFI_OK ip=10.0.0.42
board | MQTT_CONNECTED broker=10.0.0.5:54321 client_id=chumicro-mqtt-demo-board
board | RETAINED_STATE_SENT topic=demo/chumicro-mqtt-demo-board/state
driver: board MQTT_CONNECTED client_id=chumicro-mqtt-demo-board broker=10.0.0.5:54321
board | SUBSCRIBED topic=demo/chumicro-mqtt-demo-board/cmd
driver: HOST_RX demo/chumicro-mqtt-demo-board/state payload=online (retained)
driver: host published cmd to demo/chumicro-mqtt-demo-board/cmd (qos=1), PUBACK received
board | CMD_RECEIVED topic=demo/chumicro-mqtt-demo-board/cmd payload_hex=70696e67
board |   text: ping
board | DEMO_COMPLETE
board |   sent message 1: {"seq": 1, "uptime_ms": 9412}
driver: HOST_RX demo/chumicro-mqtt-demo-board/telemetry payload={"seq": 1, "uptime_ms": 9412}
board |   sent message 2: {"seq": 2, "uptime_ms": 11412}
driver: HOST_RX demo/chumicro-mqtt-demo-board/telemetry payload={"seq": 2, "uptime_ms": 11412}
board |   sent message 3: {"seq": 3, "uptime_ms": 13412}
driver: HOST_RX demo/chumicro-mqtt-demo-board/telemetry payload={"seq": 3, "uptime_ms": 13412}
driver: first 3 telemetry messages received
driver: demo completed cleanly; the board keeps publishing.
```

The driver stops there and takes its broker with it. The board carries
on and prints `waiting for the broker...` every two seconds until a
broker answers again. To watch it after the driver exits, run
`chumicro-workspace repl --tail 60 --device <id>`.

## What you need

- A board registered with `chumicro-workspace add-device`.
- `secrets.toml` at the repo root with `wifi.ssid` and `wifi.password`.
- A wifi network that your board and your laptop both join.
- `mosquitto` on your PATH (`brew install mosquitto` or
  `apt install mosquitto`). The driver starts and stops it for you.

## Run it

```bash
.venv/bin/python demos/mqtt_pub_sub/driver.py
```

The driver picks the first CircuitPython board in `devices.yml`. Pass
`--device <id>` for a specific board or `--runtime micropython` for the
first MicroPython one. `--help` lists the timeouts.

## How it works

[`app.py`](app.py) is the whole board program:

- **Online and offline.** Before connecting, the board hands the broker
  a retained `offline` with `set_will(...)`, which the broker publishes
  if the board ever drops without saying goodbye. On connect it
  publishes a retained `online` to the same topic.
- **Connect-time setup.** `on_connect` publishes `online` and subscribes
  to the command topic, every time the broker session comes up.
  [`mqtt_sensor_motor`](../mqtt_sensor_motor/) shows the other way:
  call `subscribe()` once at startup, and the client sends it on every
  connect by itself.
- **A message every two seconds.** `runner.add_periodic(...)` calls
  `publish_uptime` on a timer. It publishes while the broker is
  connected and prints `waiting for the broker...` while it is not.
- **Commands.** `on_command` runs for each message on the command topic
  and prints it.
- **The loop.** `wifi` and `mqtt` are registered with one `Runner`, and
  the program ends in the same `while True:` loop every board program
  runs.

[`driver.py`](driver.py) starts Mosquitto on your laptop's network
address, deploys `app.py` with that address baked into the board's
config, and runs its own MQTT client. It subscribes to `demo/+/state`
and `demo/+/telemetry` (the `+` matches any board name), checks the
retained `online` and three telemetry messages, and publishes `ping` to
the board's command topic once the board prints `SUBSCRIBED`.

## Try next

- Change `PUBLISH_EVERY_MS` in `app.py` and run the demo again.
- Run the bigger sibling, [`mqtt_sensor_motor`](../mqtt_sensor_motor/):
  the same pattern with a real temperature reading and a motor you
  command over MQTT.
