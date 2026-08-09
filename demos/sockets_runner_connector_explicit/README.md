# sockets_runner_connector_explicit: sockets via runner with a user-defined service

The explicit `check` / `handle` expansion of
[`sockets_runner_connector`](../sockets_runner_connector/): the same
TCP echo round trip written as a hand-rolled runner-service instead of
a generator.  Read it to see what the `connect` / `send_all` /
`recv_until` generator helpers collapse.  For new custom-protocol code,
reach for the generator demo first.

`EchoService` here writes it all out: a short state machine (`idle` →
`connecting` → `sending` → `receiving` → `done`) plus the runner-ABI
surface (`io_socket` / `io_interest(now_ms)`) that
let the runner sleep on socket-ready events instead of polling.  Only
the wire-format logic in `_handle_sending` / `_handle_receiving`
changes for a real custom protocol.

## What it shows

- **User-defined runner-service.**  `runner.add(echo)` where `echo`
  is the user's `EchoService` class, same registration shape as
  `runner.add(wifi)` / `runner.add(mqtt)`.  The class is local to
  the app; no library scaffolding involved.
- **The service drives its own connector.**  `EchoService.start()`
  builds the `SocketConnector`; the service's own `handle` calls
  `connector.tick(now_ms)` during `connecting` and inspects the
  connector's state inline.  Single runner entry, deterministic
  ordering, no sibling state polling between two entries.  The
  service's `io_socket` / `io_interest` delegate to the connector during
  the connect phase, then own the socket once `ready`.
- **Service owns the socket after `ready`.**  `_handle_connecting`
  grabs `self._socket = self.connector.socket`; from then on the
  service's own `io_socket` / `io_interest(now_ms)`
  describe the send and receive phases.  The connector goes inert
  (terminal state, `io_interest` returns `0`) and the runner ignores it.
- **Real send loop, not a one-shot.**  `_handle_sending` loops on
  `send()` and tracks `_send_offset` so a short return (including
  `EAGAIN`) resumes from the right byte on the next wake.  The
  shape any custom-protocol service uses for outbound bytes.
- **Single `while not echo.done` loop at the end.**  Everything else
  is declarative: services register before the loop, and the loop
  is just `now_ms = runner.tick(); runner.wait(now_ms)`.

## Run it

```bash
.venv/bin/python demos/sockets_runner_connector_explicit/driver.py
```

The driver is deliberately identical to `sockets_runner_connector`'s:
only the deployed `app.py` differs, so the two demos contrast the app
shapes under the same host harness.

Defaults: targets the first CircuitPython device in `devices.yml`.

Override:

- `--device <id>`: a specific device id from `devices.yml`.
- `--runtime micropython`: pick the first MicroPython device.
- `--wifi-timeout-s <n>`: how long to wait for `WIFI_OK` (default 45 s).
- `--connect-timeout-s <n>`: how long to wait for `CONNECTED` after
  `CONNECTING` (default 15 s).
- `--completion-timeout-s <n>`: how long to wait for `DEMO_COMPLETE`
  after `CONNECTED` (default 30 s).

## Expected output

```
driver: tcp echo server up on 10.0.0.5:54321
driver: targeting pi-pico-w-circuitpython-board (circuitpython @ /dev/cu.usbmodem...)
driver: board WIFI_OK ip=10.0.0.42
driver: board CONNECTING host=10.0.0.5 port=54321
driver: board CONNECTED
driver: board SENT bytes=15
driver: board ECHO_RECEIVED bytes=14 payload_hex=68656c6c6f206368756d6963726f
driver: demo completed cleanly.
```

## What it requires

- A board registered in `devices.yml`.
- `secrets.toml` at the repo root with `wifi.ssid` + `wifi.password`.
- A reachable wifi network the board can join: the board needs to
  reach the host's LAN IP that the echo server binds to.

## When to use this pattern

- **You're speaking a custom TCP wire protocol** (industrial,
  embedded device telemetry, proprietary) that isn't HTTP / MQTT /
  WebSockets.
- **You need it under a runner** because you're sharing the loop
  with wifi management, an LED blink, sensor reads, etc.

If your protocol IS one of HTTP / MQTT / WebSockets, use those
libraries instead: they own the wire-format codec and the runner
integration for you.  See `demos/mqtt_pub_sub` for the
already-built-in-client equivalent.

One-shot by design: this demo exits after one round trip.  For
reconnect-capable adapters (wifi-up / wifi-down cycles), add a small
`reset()` to clear `connector` / `_socket` / buffers back to `idle`
and call it from the wifi `DISCONNECTED` callback.

## Substrate honesty for the connect phase

- **CPython** (host pytest, sim runs): truly non-blocking via
  `BlockingIOError`(EINPROGRESS) + `select.select(POLLOUT)` + `SO_ERROR`.
- **MicroPython rp2 / esp32**: truly non-blocking via
  `OSError(EINPROGRESS)` + `select.poll(POLLOUT)`.
- **CircuitPython**: `socketpool` does not expose a non-blocking
  connect, so the TCP step blocks for the handshake duration.
  Honest documented compromise on CP; other runner tasks pause for
  the duration of that one call.

## Related

- [`sockets_tcp_roundtrip`](../sockets_tcp_roundtrip/): runner-driven
  connect, then synchronous send/recv on the ready socket, with no
  custom service.  Simpler app code once connected.
- [`sockets_tls_roundtrip`](../sockets_tls_roundtrip/): TLS variant
  of the synchronous demo with a custom-CA trust anchor.
- [`mqtt_pub_sub`](../mqtt_pub_sub/): the same `runner.add(service)`
  shape but with the protocol absorbed into `MQTTClient` (no
  user-defined service needed).
