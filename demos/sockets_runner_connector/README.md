# sockets_runner_connector: sockets via runner with a generator

End-to-end demo of a **custom TCP protocol running under the
runner**: write a generator that yields wait-tokens between each
I/O step, hand it to `runner.add_generator`, and let the runner
schedule it across ticks.  Start from this demo for any TCP
protocol `HttpClient` / `MQTTClient` / `WebSocketClient` don't
already cover.

`echo_run` here is the template, a 14-line function that calls
`connect` / `send_all` / `recv_until` in straight-line order.  The
runner ticks the underlying socket events; the generator body reads
top-to-bottom.  For the same wire behaviour expressed as an
explicit `check` / `handle` state machine, see
[`sockets_runner_connector_explicit`](../sockets_runner_connector_explicit/):
useful when you want to see what the helpers collapse, or when
your protocol has state the generator shape doesn't fit (parallel
fan-out, complex error recovery, long-lived multi-phase sessions).

## What it shows

- **One generator, one `runner.add_generator(echo_run(...))`.**  The
  generator waits for the wifi link with `yield from wait_for(link_up)`
  (a `Signal` the wifi state-change callback sets), then connects,
  sends, and receives top-to-bottom, returning when the round trip
  completes.  No user-defined class, no `io_*` plumbing, no
  callback-set module global.
- **`connect` drives the connector across ticks.**  Wraps the
  existing `SocketConnector` lifecycle (DNS -> TCP -> ready) and
  yields `WriteReady` / `ReadReady` so the runner sleeps on the
  right socket-ready event instead of polling.  PEP 380's `return`
  hands the connected socket back via `sock = yield from connect(...)`.
- **`send_all` and `recv_until` carry their own EAGAIN loops.**  Each
  caches its wait-token outside the EAGAIN retry path so the
  steady-state allocation is zero: the helpers are safe for hot
  loops on a 256 KB device.
- **`try / finally` for cleanup.**  `sock.close()` in the finally
  runs whether the generator returns normally, raises, or gets
  cancelled mid-flight via `handle.cancel()`.  No separate teardown
  path.
- **Single `while not handle.done` loop at the end.**  The runner
  flips `handle.done` to True the moment `echo_run` returns; the
  outer loop exits cleanly.

## Run it

```bash
.venv/bin/python demos/sockets_runner_connector/driver.py
```

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
- **The work is naturally sequential.**  One connect, one (or a
  small number of) send/recv pairs, then done.  For long-lived
  reactive protocols (subscribe-and-route, broker-like multiplexers),
  the explicit `check` / `handle` shape composes better; reach for
  it via `runner.add(service)`.

If your protocol IS one of HTTP / MQTT / WebSockets, use those
libraries instead: they own the wire-format codec and the runner
integration for you.  See `demos/mqtt_pub_sub` for the
already-built-in-client equivalent.

One-shot by design: this demo exits after one round trip.  For
reconnect-capable services, register a new generator from the wifi
`DISCONNECTED` / `CONNECTED` callback each time the link comes back.

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

- [`sockets_runner_connector_explicit`](../sockets_runner_connector_explicit/):
  the same wire behaviour, written as an explicit per-state
  `check` / `handle` service.  Read it to see the state machine, the
  `io_socket` / `io_interest` bookkeeping, and the partial-send
  handling that `connect` / `send_all` / `recv_until` keep out of
  your code.
- [`sockets_tcp_roundtrip`](../sockets_tcp_roundtrip/): synchronous
  TCP, no runner-driven connect.  Simpler app code; blocks for the
  full TCP handshake.
- [`sockets_tls_roundtrip`](../sockets_tls_roundtrip/): TLS variant
  of the synchronous demo with a custom-CA trust anchor.
- [`mqtt_pub_sub`](../mqtt_pub_sub/): the same `runner.add(service)`
  shape but with the protocol absorbed into `MQTTClient` (no
  user-defined service or generator needed).
