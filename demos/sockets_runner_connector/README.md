# sockets_runner_connector: an echo every five seconds that never freezes the board

Your board joins wifi and, every five seconds, connects to an echo
server the driver starts on your laptop, sends `hello chumicro`, and
reads it back. A heartbeat line prints once a second the whole time. The
heartbeat never stalls, because no step of the round trip makes the
board sit and wait.

This is the shape to start from when you speak your own protocol over
TCP and your board has other work to do at the same time: blink an LED,
read a sensor, run a web server.

## What you need

- A wifi board (Pi Pico W, ESP32-S2, ESP32-S3) registered with
  `chumicro-workspace add-device`.
- `secrets.toml` at the repo root with `wifi.ssid` and `wifi.password`
  ([wiring wifi credentials](../../docs/wiring-wifi-credentials.md)).
- The board and your laptop on the same network.

## Run it

```bash
.venv/bin/python demos/sockets_runner_connector/driver.py
```

The driver deploys [`app.py`](app.py) to the first CircuitPython board
in `devices.yml`. Pick a board with `--device <id>`, or
`--runtime micropython` for the first MicroPython one.

## What you will see

Lines starting `board |` are what the board prints; `driver:` lines come
from the script on your laptop.

```
driver: tcp echo server up on 10.0.0.5:54321
driver: targeting pi-pico-w-circuitpython-board (circuitpython @ /dev/cu.usbmodem...)
board |   ...still ticking
board | WIFI_OK ip=10.0.0.42
board | CONNECTING host=10.0.0.5 port=54321
board |   ...still ticking
board | CONNECTED
board | SENT bytes=15
board | ECHO_RECEIVED bytes=14 payload_hex=68656c6c6f206368756d6963726f
board |   echo 1: 'hello chumicro' came back
board | DEMO_COMPLETE
driver: first round trip done; watching 2 more
board |   ...still ticking
board |   ...still ticking
board |   ...still ticking
board |   ...still ticking
board | CONNECTING host=10.0.0.5 port=54321
board |   ...still ticking
board | CONNECTED
board | SENT bytes=15
board | ECHO_RECEIVED bytes=14 payload_hex=68656c6c6f206368756d6963726f
board |   echo 2: 'hello chumicro' came back
...
board |   echo 3: 'hello chumicro' came back
driver: done, stopping the echo server.  The board keeps running; its next rounds print ECHO_FAILED and retry.
```

The UPPERCASE lines are the ones the driver waits for. The indented
lines are for you: the heartbeat, and each echo as plain text.

## Try next

- Register a second job, such as `runner.add_periodic(...)` printing a
  sensor reading, and watch it keep its timing through every round trip.
- Change `PROBE_PAYLOAD` or `ECHO_EVERY_MS` and run the driver again.
- After the driver exits, run `chumicro-workspace repl --tail 30` and
  watch the heartbeat keep going while each round reports `ECHO_FAILED`.

## How `app.py` works

- **`echo_once` is one round trip, read top to bottom.** `connect`,
  `send_all`, and `recv_until` each pause with `yield from` whenever the
  socket is not ready, and the runner hands the turn to wifi and the
  heartbeat until it is.
- **`echo_forever` repeats it.** It waits for wifi with
  `yield from wait_for(link_up)`, then runs `echo_once`, sleeps five
  seconds with `sleep_until`, and goes again. One
  `runner.add_generator(...)` call registers the whole thing.
- **`try` / `finally` closes the socket** whether the round trip finished
  or raised, and a failed round prints `ECHO_FAILED` before the next try.
- **The main loop is the same two lines as every other demo:**
  `runner.tick()`, then `runner.wait(now_ms)`.

On CircuitPython, `socketpool` has no non-blocking connect, so the TCP
handshake itself blocks the loop for its length. MicroPython and CPython
connect without blocking.

## Next to the other sockets demos

- [`sockets_tcp_roundtrip`](../sockets_tcp_roundtrip/) does the same
  echo with plain blocking `send` and `recv_into`. Shorter, but the loop
  stops while it waits for bytes.
- [`sockets_runner_connector_explicit`](../sockets_runner_connector_explicit/)
  does exactly this round trip as a service class with `check` and
  `handle`, which shows what each `yield from` here stands in for.

If your protocol is HTTP, MQTT, or WebSockets, use `chumicro_requests`,
`chumicro_mqtt`, or `chumicro_websockets` instead. They own the wire
format and the runner wiring for you, as the
[`requests_fetch`](../requests_fetch/), [`mqtt_pub_sub`](../mqtt_pub_sub/),
and [`websockets_stream`](../websockets_stream/) demos show.

## Driver options

- `--device <id>`: a device id from `devices.yml`.
- `--runtime micropython`: pick the first MicroPython board.
- `--wifi-timeout-s <n>`: how long to wait for `WIFI_OK` (default 45 s).
- `--connect-timeout-s <n>`: how long to wait for `CONNECTED` after
  `CONNECTING` (default 15 s).
- `--completion-timeout-s <n>`: how long to wait for `DEMO_COMPLETE`
  after `CONNECTED` (default 30 s).
- `--watch-rounds <n>`: echoes to watch after `DEMO_COMPLETE` before the
  driver stops the echo server (default 2, `0` stops at the first).

`run.py sweep-devices` runs this driver against every registered board as
its smoke test.
