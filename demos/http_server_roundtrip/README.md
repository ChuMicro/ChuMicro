# http_server_roundtrip: board serves, host drives

End-to-end demo of `chumicro_http_server` running on a real board,
with a host-side script firing HTTP requests against it. You see
three round trips on your terminal in one command: no curl in
another window, no IP discovery.

## What it shows

- `chumicro_wifi.WifiService` + `chumicro_http_server.HttpServer`
  registered with one `chumicro_runner.Runner` on the board, driven by a
  single `runner.run_until(...)` call with a deadline.
- Three registered routes (`GET /hello`, `GET /uptime`,
  `POST /echo`) with a `@server.route(...)` decorator.
- The host driver reads the `SERVER_READY` marker the board prints
  to learn the board's address, then opens stdlib
  `http.client.HTTPConnection` connections against it.
- Per-request markers (`ROUTE_HIT route=...`) let the driver see
  each handler fire in real time over USB serial, parallel to the
  HTTP responses arriving over wifi.

## Run it

```bash
.venv/bin/python demos/http_server_roundtrip/driver.py
```

Defaults: targets the first CircuitPython device in `devices.yml`.

Override:

- `--device <id>`: a specific device id from `devices.yml`.
- `--runtime micropython`: pick the first MicroPython device.
- `--ready-timeout-s <n>`: how long to wait for `SERVER_READY`
  (default 60 s; ESP32-S2 CP cold-boot + wifi can be slow).
- `--completion-timeout-s <n>`: how long to wait for the board to
  print `DEMO_COMPLETE` after the three requests land (default 90 s).

## Expected output

```
driver: targeting pi-pico-w-circuitpython-board (circuitpython @ /dev/cu.usbmodem...)
driver: waiting for SERVER_READY (up to 60.0s)...
driver: GET /hello -> 200 OK
{
  "message": "hello from chumicro_http_server"
}
driver: GET /uptime -> 200 OK
{
  "uptime_ms": 2341
}
driver: POST /echo -> 200 OK
{
  "echoed": {"from": "demo driver"}
}
driver: waiting for board to print DEMO_COMPLETE...
driver: demo completed cleanly.
```

## What it requires

- A board registered in `devices.yml` (run
  `chumicro-workspace add-device` if the registry is empty).
- `secrets.toml` at the repo root with `wifi.ssid` + `wifi.password`.
- A reachable wifi network the board can join.

## How it works

The host driver:

1. Picks the device from `devices.yml`.
2. Builds a transport via `build_transport_for_entry`.
3. Stages `app.py` plus every `chumicro_*` library it imports
   (`config`, `http_server`, `runner`, `sockets`, `test_harness`,
   `timing`, `wifi`) +
   `runtime_config.msgpack` (with the wifi credentials from
   `secrets.toml`).
4. Spawns a `DeviceBootstrapRunner` daemon thread that runs the
   bootstrap on the board with `on_line` wired to push parsed
   markers onto a `MarkerQueue`.
5. The `bind_to(runner)` helper returns a `hit(path, ...)`
   callable that waits for `SERVER_READY`, opens an
   `http.client.HTTPConnection` to the marker's `ip:port`, fires
   the request, returns an `HttpResponseSnapshot`.
6. Fires three requests in sequence; the board's handler prints
   `ROUTE_HIT route=...` each time, which streams back over USB
   serial in parallel with the HTTP response arriving over wifi.
7. Waits for `DEMO_COMPLETE` on the captured stdout, then exits.

The board side stays single-threaded cooperative; all concurrency is
host-side (one main thread plus the runner's serial-read background
thread, coordinating through a thread-safe `MarkerQueue`).
