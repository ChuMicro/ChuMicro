# mqtt_sensor_motor: a temperature-controlled fan node

A board reads its on-chip temperature, publishes it as JSON telemetry
over `chumicro_mqtt`, and drives a PWM "motor" (fan/pump) from speed
commands the broker delivers. A local Mosquitto broker bridges the
board to a CPython-side counterparty, and one command starts both
ends, so the setup stops at `brew install mosquitto`.

No motor hardware is needed on the bench: the demo drives a PWM duty
cycle on a GPIO (exactly how a real fan/pump ESC is commanded) and
mirrors that duty onto the onboard LED, so the board visibly brightens
and dims as the commanded speed changes.

## Scenario

The board is a fan node. Every two seconds it samples temperature and
publishes `{"celsius", "speed", "seq"}` telemetry. When a controller
publishes a speed (`0`-`100`) to the node's `motor/set` topic, the
board clamps it, applies it to the motor PWM, and echoes the applied
value back on a retained `motor/state` topic, a closed command loop.
Presence is a retained `online`/`offline` pair.

## Wiring (for a real motor)

The demo runs with nothing attached, but to drive a real load:

- **Motor signal** → **GPIO16** (Pico W header `GP16`, Lolin S2 mini
  header `IO16` / `D4`). Wire this to the PWM/signal input of a motor
  driver or ESC, never straight to a motor. A ~1 kHz PWM duty of
  0-100% comes out here.
- **Motor power** → the driver/ESC's own supply and ground, with its
  ground tied to the board's ground. The GPIO carries signal only.
- **Onboard LED** mirrors the duty automatically (brightness = speed on
  the Lolin S2 mini; on/off on the Pico W, whose LED lives on the wifi
  coprocessor and can't PWM), a wiring-free speed indicator.

## Topics

All under `demo/<client_id>/`, where `<client_id>` is baked in by the
driver (`chumicro-sensor-motor-board`).

| Topic | Direction | QoS | Retained | Payload |
|---|---|---|---|---|
| `…/availability` | board → broker | 1 | yes | `online` / `offline` (also the Last Will) |
| `…/telemetry` | board → broker | 1 | no | `{"celsius": 22.9, "speed": 75, "seq": 4}` |
| `…/motor/set` | broker → board | 1 | no | integer speed `0`-`100` |
| `…/motor/state` | board → broker | 1 | yes | applied speed, echoed back |

## What it shows: library behavior the demo leans on

The board code is short because it reimplements none of this:

- **Pre-connect queue.** Telemetry calls `publish()` with no CONNECTED
  guard. Samples produced before the broker session is up buffer in the
  client's bounded pre-connect queue and flush on CONNACK (the default
  `when_disconnected="queue"` policy).  The cadence never state-checks.
- **Declarative subscribe.** The `motor/set` subscription is declared
  once at startup with `subscribe()`, before `connect()`, not inside
  `on_connect`. The client records it in its desired set, sends it on
  the first CONNACK, and replays it on every self-heal reconnect, so
  there is no reconnect bookkeeping. (`on_connect` keeps only the
  retained `online` publish, which is genuinely connect-time.)
- **Availability via Last Will.** A retained `offline` will the broker
  publishes if the board drops uncleanly, paired with a retained
  `online` on connect. A clean shutdown suppresses the will, so the
  shutdown path publishes `offline` explicitly.
- **Wifi-drop self-heal.** The wifi callback holds mqtt while the link
  is down (`mqtt.hold()`) and reconnects the moment it returns
  (`mqtt.connect()`); the socket-factory transport rebuilds the
  connection.
- **Runner composition.** `WifiService` and `MQTTClient` added with
  `runner.add(...)`, telemetry paced by `runner.add_periodic(...)`, all
  in one cooperative loop.

## Run it

```bash
.venv/bin/python demos/mqtt_sensor_motor/driver.py
```

Defaults: targets the first CircuitPython device in `devices.yml`.

Override:

- `--device <id>`: a specific device id from `devices.yml`.
- `--runtime micropython`: pick the first MicroPython device.
- `--connect-timeout-s <n>`: how long to wait for the board's
  `MQTT_CONNECTED` marker (default 60 s; ESP32-S2 cold-boot + wifi can
  be slow).
- `--telemetry-timeout-s <n>`: how long to wait for the first three
  telemetry receipts (default 30 s).

## Expected output

```
driver: started mosquitto on 10.0.0.5:54321
driver: targeting pi-pico-w-circuitpython-board (circuitpython @ /dev/cu.usbmodem...)
driver: host MQTT client connected (chumicro-sensor-motor-driver)
driver: waiting for board MQTT_CONNECTED (up to 60.0s)...
driver: board MQTT_CONNECTED client_id=chumicro-sensor-motor-board broker=10.0.0.5:54321
driver: HOST_RX demo/chumicro-sensor-motor-board/availability payload=online (retained)
driver: HOST_RX demo/chumicro-sensor-motor-board/telemetry payload={"celsius": 22.9, "speed": 0, "seq": 1}
driver: HOST_RX demo/chumicro-sensor-motor-board/telemetry payload={"celsius": 23.1, "speed": 0, "seq": 2}
driver: HOST_RX demo/chumicro-sensor-motor-board/telemetry payload={"celsius": 23.0, "speed": 0, "seq": 3}
driver: telemetry 3 received, celsius + seq plausible
driver: host published motor/set 75 to demo/chumicro-sensor-motor-board/motor/set
driver: HOST_RX demo/chumicro-sensor-motor-board/motor/state payload=75 (retained)
driver: motor at 75 confirmed (marker + state echo)
driver: host published motor/set 0 to demo/chumicro-sensor-motor-board/motor/set
driver: HOST_RX demo/chumicro-sensor-motor-board/motor/state payload=0 (retained)
driver: motor at 0 confirmed (state echo)
driver: HOST_RX demo/chumicro-sensor-motor-board/availability payload=offline (retained)
driver: demo completed cleanly.
```

## Sensor source per board

The on-chip temperature source is the only sensor difference across the
sweep boards; the board prints a `SENSOR_SOURCE` marker naming which it
used:

| Board | Runtime | Source |
|---|---|---|
| Pi Pico W | CircuitPython | `microcontroller.cpu.temperature` (real) |
| Pi Pico W | MicroPython | `machine.ADC(4)`, Pico formula (real) |
| Lolin S2 mini | CircuitPython | `microcontroller.cpu.temperature` (real) |
| Lolin S2 mini | MicroPython | synthetic wave (no CPU temp sensor) |

## What it requires

- A board registered in `devices.yml`.
- `secrets.toml` at the repo root with `wifi.ssid` + `wifi.password`.
- A reachable wifi network the board can join.
- `mosquitto` on PATH (`brew install mosquitto` /
  `apt install mosquitto`).
