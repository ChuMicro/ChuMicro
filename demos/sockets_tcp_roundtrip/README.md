# sockets_tcp_roundtrip: send a line, get it back, every five seconds

Your board joins wifi, connects to a small echo server the driver starts
on your laptop, sends `hello chumicro`, and reads the same line back.
Five seconds later it does it again, and it keeps going for as long as
the board has power. This is the simplest of the four sockets demos:
no generators and no classes, a plain `send` and `recv_into` once the
connection is open.

## What you need

- A wifi board (Pi Pico W, ESP32-S2, ESP32-S3) registered with
  `chumicro-workspace add-device`.
- `secrets.toml` at the repo root with `wifi.ssid` and `wifi.password`
  ([wiring wifi credentials](../../docs/wiring-wifi-credentials.md)).
- The board and your laptop on the same network, so the board can reach
  the echo server.

## Run it

```bash
.venv/bin/python demos/sockets_tcp_roundtrip/driver.py
```

The driver starts the echo server, deploys [`app.py`](app.py) to the
first CircuitPython board in `devices.yml`, and shows you everything the
board prints. Pick a board with `--device <id>`, or
`--runtime micropython` for the first MicroPython one.

## What you will see

Lines starting `board |` are what the board prints; `driver:` lines come
from the script on your laptop.

```
driver: tcp echo server up on 10.0.0.5:54321
driver: targeting pi-pico-w-circuitpython-board (circuitpython @ /dev/cu.usbmodem...)
board | WIFI_OK ip=10.0.0.42
board | CONNECTING host=10.0.0.5 port=54321
board | CONNECTED
board | SENT bytes=15
board | ECHO_RECEIVED bytes=14 payload_hex=68656c6c6f206368756d6963726f
board |   echo 1: 'hello chumicro' came back
board | DEMO_COMPLETE
driver: first round trip done; watching 2 more
board | CONNECTING host=10.0.0.5 port=54321
board | CONNECTED
board | SENT bytes=15
board | ECHO_RECEIVED bytes=14 payload_hex=68656c6c6f206368756d6963726f
board |   echo 2: 'hello chumicro' came back
...
board |   echo 3: 'hello chumicro' came back
driver: done, stopping the echo server.  The board keeps running; its next rounds print ECHO_FAILED and retry.
```

The UPPERCASE lines are the ones the driver waits for. The indented
`echo` line is for you: the same text, without the hex.

## Try next

- Change `PROBE_PAYLOAD` or `ECHO_EVERY_MS` at the top of `app.py` and
  run the driver again.
- Pass `--watch-rounds 10` to keep the echo server up for ten more
  echoes.
- After the driver exits, run `chumicro-workspace repl --tail 30` and
  watch the board keep trying every five seconds now that the echo
  server is gone.

## How `app.py` works

- **Connecting goes through the runner.** `connector(host, port, radio=...)`
  is a runner service, like the wifi service. The board adds it with
  `runner.add(dial)` and turns the loop until the dial says `ready` or
  `failed`, so wifi keeps getting its turns during the DNS lookup and
  the TCP handshake.
- **Talking is plain and blocking.** Once the socket is open, `send` and
  `recv_into` wait for the network, and the loop waits with them. That
  is fine for an echo that comes straight back, and it is the tradeoff
  the other sockets demos remove.
- **The main loop repeats the work.** An `if` before `runner.wait()`
  fires once wifi is up and five seconds have passed. A failure prints
  `ECHO_FAILED` and the next round tries again.

## Next to the other sockets demos

- [`sockets_tls_roundtrip`](../sockets_tls_roundtrip/) is this demo over
  an encrypted link, trusting a certificate your board has never seen.
- [`sockets_runner_connector`](../sockets_runner_connector/) keeps the
  loop turning through the send and the receive too, which is the shape
  to copy once your board has other work to do.
- [`sockets_runner_connector_explicit`](../sockets_runner_connector_explicit/)
  writes that non-blocking round trip as your own service class.

## Driver options

- `--device <id>`: a device id from `devices.yml`.
- `--runtime micropython`: pick the first MicroPython board.
- `--wifi-timeout-s <n>`: how long to wait for `WIFI_OK` (default 45 s).
- `--completion-timeout-s <n>`: how long to wait for `DEMO_COMPLETE`
  (default 30 s).
- `--watch-rounds <n>`: echoes to watch after `DEMO_COMPLETE` before the
  driver stops the echo server (default 2, `0` stops at the first).
