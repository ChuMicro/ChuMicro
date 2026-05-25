# sockets_runner_connector — sockets via runner with a user-defined service

End-to-end demo of the canonical pattern for **custom TCP protocols
under runner**: write a tiny runner-service that owns a
`SocketConnector` for the connect phase and drives send / recv in its
own `check` / `handle`.  Drop-in template for any protocol not
covered by `HttpClient` / `MQTTClient` / `WebSocketClient`.

`EchoService` here is the template — ~40 lines of state machine
(`idle` → `connecting` → `sending` → `receiving` → `done`) plus the
runner-ABI properties (`io_socket` / `io_wants_read` /
`io_wants_write`) that let the runner sleep on socket-ready events
instead of polling.  Real custom-protocol code follows the same shape
— only the wire-format logic in `handle` changes.

## What it shows

- **User-defined runner-service.**  `runner.add(echo)` where `echo`
  is the user's `EchoService` class — same registration shape as
  `runner.add(wifi)` / `runner.add(mqtt)`.  The class is local to
  the app; no library scaffolding involved.
- **`SocketConnector` for the connect phase.**  `tcp_client_connector`
  returns a runner-shaped connector the service drives via
  `connector.tick(now_ms)` inside its own `handle`.  Once
  `connector.state == "ready"`, the service grabs `connector.socket`
  and does protocol I/O.
- **Event-driven runner integration.**  The service exposes
  `io_socket` / `io_wants_read` / `io_wants_write`, so the runner's
  `wait(now_ms)` sleeps on socket events.  No 50 ms blind polling.
- **Single `while not echo.done` loop at the end.**  Everything else
  is declarative — all the services and periodic tasks register
  before the loop, and the loop is just
  `now_ms = runner.tick(); runner.wait(now_ms)`.
- **Heartbeat through connect + I/O.**  A 500 ms periodic heartbeat
  fires throughout.  The driver counts heartbeats between
  `CONNECTING` and `CONNECTED` markers — at least one proves the
  connect didn't block.

## Run it

```bash
.venv/bin/python demos/sockets_runner_connector/driver.py
```

Defaults: targets the first CircuitPython device in `devices.yml`.

Override:

- `--device <id>` — a specific device id from `devices.yml`.
- `--runtime micropython` — pick the first MicroPython device.
- `--wifi-timeout-s <n>` — how long to wait for `WIFI_OK` (default 45 s).
- `--connect-timeout-s <n>` — how long to wait for `CONNECTED` after
  `CONNECTING` (default 15 s).

## Expected output

```
driver: tcp echo server up on 10.0.0.5:54321
driver: targeting pi-pico-w-circuitpython-board (circuitpython @ /dev/cu.usbmodem...)
driver: board WIFI_OK ip=10.0.0.42
driver: board CONNECTING host=10.0.0.5 port=54321
driver: board CONNECTED (heartbeats during connect: 2)
driver: board SENT bytes=15
driver: board ECHO_RECEIVED bytes=14 payload=b'hello chumicro'
driver: demo completed cleanly.
```

The heartbeat count between `CONNECTING` and `CONNECTED` is the
demo's key signal — if it's zero, the connect blocked the runner.

## What it requires

- A board registered in `devices.yml`.
- `secrets.toml` at the repo root with `wifi.ssid` + `wifi.password`.
- A reachable wifi network the board can join — the board needs to
  reach the host's LAN IP that the echo server binds to.

## When to use this pattern

- **You're speaking a custom TCP wire protocol** (industrial,
  embedded device telemetry, proprietary) that isn't HTTP / MQTT /
  WebSockets.
- **You need it under a runner** because you're sharing the loop
  with wifi management, an LED blink, sensor reads, etc.

If your protocol IS one of HTTP / MQTT / WebSockets, use those
libraries instead — they own the wire-format codec and the runner
integration for you.  See `demos/mqtt_pub_sub` for the
already-built-in-client equivalent.

## Substrate honesty for the connect phase

- **CPython** (host pytest, sim runs) — truly non-blocking via
  `BlockingIOError`(EINPROGRESS) + `select.select(POLLOUT)` + `SO_ERROR`.
  Heartbeats land throughout.
- **MicroPython rp2 / esp32** — truly non-blocking via
  `OSError(EINPROGRESS)` + `select.poll(POLLOUT)`.  Heartbeats land
  throughout.
- **CircuitPython** — `socketpool` does not expose a non-blocking
  connect, so the TCP step blocks for the handshake duration.
  Honest documented compromise on CP; heartbeats may not land
  between `CONNECTING` and `CONNECTED` on a fast LAN, but land
  everywhere else.

## Related

- [`sockets_tcp_roundtrip`](../sockets_tcp_roundtrip/) — synchronous
  TCP, no runner-driven connect, no custom service.  Simpler app
  code; blocks for the full TCP handshake.
- [`sockets_tls_roundtrip`](../sockets_tls_roundtrip/) — TLS variant
  of the synchronous demo with a custom-CA trust anchor.
- [`mqtt_pub_sub`](../mqtt_pub_sub/) — the same `runner.add(service)`
  shape but with the protocol absorbed into `MQTTClient` (no
  user-defined service needed).
