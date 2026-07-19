# sockets_tcp_roundtrip: one-shot TCP via the connector, wifi via runner

End-to-end demo of `chumicro_sockets.connector` against a host
echo server.  Wifi comes up via `chumicro_wifi.WifiService` driven by
`chumicro_runner.Runner`; once up, the board registers a
`connector(host, port, radio=...)` with the runner, drives it to
`ready` via `runner.run_until`, then uses the socket with `send` /
`recv_into` synchronously.

## What it shows

- **The full chumicro stack for wifi.**  `WifiService` configured from
  `chumicro_config.load_runtime_config()`, added to `chumicro_runner.Runner`,
  driven until `WifiState.CONNECTED`.  No `wifi_up()` shortcut: the
  ecosystem brings the link up.
- **Entry-level sockets API.**  `connector(host, port, radio=...)`
  is a runner service: `runner.add(dial)` + `runner.run_until(...)`
  drive DNS → TCP to `ready` without blocking a tick.  The app then
  calls `send` / `recv_into` / `close` synchronously, same shape as
  the `libraries/sockets/examples/tcp_roundtrip.py` example but with
  a host echo server so the round-trip data is visible.
- **Round trip on the wire.**  Board sends `b"hello chumicro\n"`,
  echo server bounces it back, board confirms the payload.

## Run it

```bash
.venv/bin/python demos/sockets_tcp_roundtrip/driver.py
```

Defaults: targets the first CircuitPython device in `devices.yml`.

Override:

- `--device <id>`: a specific device id from `devices.yml`.
- `--runtime micropython`: pick the first MicroPython device.
- `--wifi-timeout-s <n>`: how long to wait for the board's `WIFI_OK`
  marker (default 45 s).

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

## Related

- [`sockets_tls_roundtrip`](../sockets_tls_roundtrip/): same shape
  with TLS + a self-signed CA the driver embeds in runtime config.
- [`sockets_runner_connector`](../sockets_runner_connector/): the
  non-blocking connector form.  `runner.add(connector)` keeps a 500 ms
  heartbeat firing through the connect for code that can't pause its
  tick budget.
