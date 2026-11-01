# mqtt_sensor_motor: a temperature-controlled fan over MQTT

Your board reads its own chip temperature every two seconds and
publishes it to an MQTT broker on your laptop. When a fan speed from 0
to 100 arrives, the board drives a motor at that speed, lights its
onboard LED while the motor runs, and publishes the speed back. A
script on your laptop starts the broker, watches the readings, and
sends two speeds: 75, then 0.

No motor is needed on the bench. The motor is a PWM signal on one pin,
and the LED shows whether it is running.

## What you will see

The driver's own lines start with `driver:`. Everything the board
prints shows up as it happens, after `board |`. Each reading appears
twice: once as the board sends it, once as your laptop receives it.

```
driver: started mosquitto on 10.0.0.5:54321
driver: targeting pi-pico-w-circuitpython-board (circuitpython @ /dev/cu.usbmodem...)
driver: host MQTT client connected (chumicro-sensor-motor-driver)
driver: waiting for board MQTT_CONNECTED (up to 60.0s)...
board |   waiting for the broker...
board | WIFI_OK ip=10.0.0.42
board | MQTT_CONNECTED broker=10.0.0.5:54321 client_id=chumicro-sensor-motor-board
driver: board MQTT_CONNECTED client_id=chumicro-sensor-motor-board broker=10.0.0.5:54321
driver: HOST_RX demo/chumicro-sensor-motor-board/availability payload=online (retained)
board |   reading 1: 23.4 C, fan at 0%
driver: HOST_RX demo/chumicro-sensor-motor-board/telemetry payload={"celsius": 23.4, "speed": 0, "seq": 1}
board |   reading 2: 23.5 C, fan at 0%
driver: HOST_RX demo/chumicro-sensor-motor-board/telemetry payload={"celsius": 23.5, "speed": 0, "seq": 2}
board |   reading 3: 23.4 C, fan at 0%
driver: HOST_RX demo/chumicro-sensor-motor-board/telemetry payload={"celsius": 23.4, "speed": 0, "seq": 3}
driver: telemetry 3 received, celsius + seq plausible
driver: host published motor/set 75 to demo/chumicro-sensor-motor-board/motor/set
board | MOTOR_APPLIED speed=75
driver: HOST_RX demo/chumicro-sensor-motor-board/motor/state payload=75 (retained)
driver: motor at 75 confirmed (marker + state echo)
driver: host published motor/set 0 to demo/chumicro-sensor-motor-board/motor/set
board | MOTOR_APPLIED speed=0
board | DEMO_COMPLETE
driver: HOST_RX demo/chumicro-sensor-motor-board/motor/state payload=0 (retained)
driver: motor at 0 confirmed (state echo)
driver: demo completed cleanly; the board keeps publishing.
```

On the board itself, the LED lights for the speed 75 and goes dark for
0.

The driver stops there and takes its broker with it. The board carries
on and prints `waiting for the broker...` every two seconds until a
broker answers again. To watch it after the driver exits, run
`chumicro-workspace repl --tail 60 --device <id>`.

## What you need

- A board registered with `chumicro-workspace add-device`. The pin
  choices below suit a Pi Pico W or a Lolin S2 mini.
- `secrets.toml` at the repo root with `wifi.ssid` and `wifi.password`.
- A wifi network that your board and your laptop both join.
- `mosquitto` on your PATH (`brew install mosquitto` or
  `apt install mosquitto`). The driver starts and stops it for you.

## Run it

```bash
.venv/bin/python demos/mqtt_sensor_motor/driver.py
```

The driver picks the first CircuitPython board in `devices.yml`. Pass
`--device <id>` for a specific board or `--runtime micropython` for the
first MicroPython one. `--help` lists the timeouts, which matter on a
slow first wifi join.

## How it works

[`app.py`](app.py) is the whole board program. The block at the top is
the only part that differs between boards: it picks the temperature
sensor, the motor pin, and the LED. Everything after it is the same on
every board:

- **Readings.** `runner.add_periodic(...)` calls `publish_reading`
  every two seconds. It publishes while the broker is connected and
  prints `waiting for the broker...` while it is not.
- **Speed commands.** The board subscribes to its `motor/set` topic
  once, at startup, and the client renews that subscription on every
  reconnect. `on_motor_command` clamps the speed to 0-100, applies it,
  and publishes it back on `motor/state`.
- **Online and offline.** `set_will(...)` leaves a retained `offline`
  with the broker, published if the board drops off the network.
  `on_connect` publishes the matching `online`.
- **Wifi drops.** When wifi goes down, the board stops dialing the
  broker (`mqtt.hold()`), and it reconnects the moment wifi returns
  (`mqtt.connect()`).
- **The loop.** `wifi` and `mqtt` are registered with one `Runner`, and
  the program ends in the same `while True:` loop every board program
  runs.

[`driver.py`](driver.py) starts Mosquitto on your laptop's network
address, deploys `app.py` with that address baked into the board's
config, and runs its own MQTT client as the controller.

All topics sit under `demo/chumicro-sensor-motor-board/`:

| Topic | Who publishes | Retained | Payload |
|---|---|---|---|
| `availability` | board (and the broker, for the `offline` will) | yes | `online` or `offline` |
| `telemetry` | board, every two seconds | no | `{"celsius": 22.9, "speed": 75, "seq": 4}` |
| `motor/set` | your laptop | no | a whole number from `0` to `100` |
| `motor/state` | board, after each command | yes | the speed it applied |

## Temperature source per board

| Board | Runtime | Temperature |
|---|---|---|
| Pi Pico W | CircuitPython | `microcontroller.cpu.temperature` |
| Pi Pico W | MicroPython | `machine.ADC(4)`, the chip's built-in sensor |
| Lolin S2 mini | CircuitPython | `microcontroller.cpu.temperature` |
| Lolin S2 mini | MicroPython | a made-up wave between 17 and 33 C |

## Wiring a real motor

The demo runs with nothing attached. To drive a real fan or pump:

- **Signal:** GPIO16 (`GP16` on a Pico W, `IO16` on a Lolin S2 mini)
  to the PWM input of a motor driver board or ESC. Never wire a motor
  straight to a pin.
- **Power:** the motor driver gets its own supply, with its ground tied
  to the board's ground. The pin carries a 1 kHz signal only.

## Try next

- Change `READING_EVERY_MS` in `app.py` and run the demo again.
- Wire a real fan through a motor driver board and watch it spin up to
  75% and stop.
- Start with [`mqtt_pub_sub`](../mqtt_pub_sub/) if MQTT is new to you:
  it is the same pattern without the sensor and the motor.
