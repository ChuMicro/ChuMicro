# sockets_runner_connector_explicit: the same echo, written as your own service class

This demo does exactly what
[`sockets_runner_connector`](../sockets_runner_connector/) does: every
five seconds the board connects to an echo server on your laptop, sends
`hello chumicro`, and reads it back, with a heartbeat printing once a
second the whole time. The difference is the code. Here the round trip
is `EchoService`, a class the runner calls over and over, instead of a
generator.

Read this one after its sibling. It is the shape every ChuMicro service
has, the wifi service and the MQTT client included, so it is the one to
copy when you write a library-style service other people will
`runner.add(...)`.

## What you need

- A wifi board (Pi Pico W, ESP32-S2, ESP32-S3) registered with
  `chumicro-workspace add-device`.
- `secrets.toml` at the repo root with `wifi.ssid` and `wifi.password`
  ([wiring wifi credentials](../../docs/wiring-wifi-credentials.md)).
- The board and your laptop on the same network.

## Run it

```bash
.venv/bin/python demos/sockets_runner_connector_explicit/driver.py
```

The driver deploys [`app.py`](app.py) to the first CircuitPython board
in `devices.yml`. Pick a board with `--device <id>`, or
`--runtime micropython` for the first MicroPython one. Its options and
output match `sockets_runner_connector`'s driver, so the only thing
that differs between the two runs is the code on the board.

## What you will see

Lines starting `board |` are what the board prints; `driver:` lines come
from the script on your laptop.

```
driver: tcp echo server up on 10.0.0.5:54321
driver: targeting pi-pico-w-circuitpython-board (circuitpython @ /dev/cu.usbmodem...)
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

## Try next

- Make a second `EchoService` with its own payload, `runner.add` it, and
  call its `start()` next to the first one's. Both round trips run on
  the same loop without waiting on each other.
- Open `app.py` next to the generator version and match each state here
  to the `yield from` line that replaces it there.

## How `app.py` works

- **The runner asks, then calls.** Each turn it calls
  `check(now_ms)` ("anything to do?") and, on `True`, `handle(now_ms)`
  ("go ahead").
- **`self.state` remembers the place.** A round walks `connecting`,
  `sending`, `receiving`, then `resting` until the next round is due.
  Each call does what it can without waiting and returns.
- **Three hooks tell the runner what to wake for.** `io_socket` and
  `io_interest` name the socket and whether to wake when it can be
  written to or read from. `next_deadline` names the time the next round
  starts. While dialing, all three hand over the connector's own answers.
- **`EAGAIN` means "not yet".** The socket is non-blocking, so `send`
  and `recv_into` raise `EAGAIN` instead of waiting. The service returns
  and the runner calls back once the socket is ready. `_send_step` also
  keeps a byte count, because `send` may take only part of the payload.
- **Any failure goes to `_fail`**, which prints `ECHO_FAILED`, closes the
  socket, and rests until the next round.

On CircuitPython, `socketpool` has no non-blocking connect, so the TCP
handshake itself blocks the loop for its length. MicroPython and CPython
connect without blocking.

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
