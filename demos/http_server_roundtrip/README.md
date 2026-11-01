# http_server_roundtrip: your board serves web pages

Your board joins wifi and runs a small web server. A script on your
laptop finds the board's address, sends it three requests, and prints
each answer. After that the board keeps serving, so you can point your
own browser at it.

## What you will see

The driver's own lines start with `driver:`. Everything the board
prints shows up as it happens, after `board |`:

```
driver: targeting pi-pico-w-circuitpython-board (circuitpython @ /dev/cu.usbmodem...)
driver: waiting for SERVER_READY (up to 60.0s)...
board |   starting up...
board | WIFI_OK ip=10.0.0.42
board | SERVER_READY ip=10.0.0.42 port=8080
board | ROUTE_HIT route=/hello
driver: GET /hello -> 200 OK
{
  "message": "hello from chumicro_http_server"
}
board | ROUTE_HIT route=/uptime uptime_ms=9873
driver: GET /uptime -> 200 OK
{
  "uptime_ms": 9873
}
board | ROUTE_HIT route=/echo
board | DEMO_COMPLETE
driver: POST /echo -> 200 OK
{
  "echoed": {
    "from": "demo driver"
  }
}
driver: waiting for board to print DEMO_COMPLETE...
driver: demo completed cleanly; the board keeps serving.
```

The driver stops there, and the board carries on. Every five seconds it
prints a status line such as
`serving http://10.0.0.42:8080/hello (3 requests so far)`, for as long
as it has power. To watch it after the driver exits, run
`chumicro-workspace repl --tail 60 --device <id>`.

## What you need

- A board registered with `chumicro-workspace add-device`.
- `secrets.toml` at the repo root with `wifi.ssid` and `wifi.password`.
- A wifi network that your board and your laptop both join.

## Run it

```bash
.venv/bin/python demos/http_server_roundtrip/driver.py
```

The driver picks the first CircuitPython board in `devices.yml`. Pass
`--device <id>` for a specific board or `--runtime micropython` for the
first MicroPython one. `--help` lists the timeouts, which matter on a
slow first wifi join.

## How it works

[`app.py`](app.py) is the whole board program. It registers three
routes with `@server.route(...)`, waits for wifi, starts the server,
and prints `SERVER_READY` with its address. Then it runs the same
`while True:` loop every board program runs: `runner.tick()` gives wifi,
the server, and the status line their turn, and `runner.wait()` rests
the CPU until the next request or timer.

[`driver.py`](driver.py) deploys `app.py`, reads the address off the
`SERVER_READY` line, and sends `GET /hello`, `GET /uptime`, and
`POST /echo` from your laptop. The board prints `ROUTE_HIT` as each one
arrives and `DEMO_COMPLETE` after the third.

## Try next

- Open `http://<ip>:8080/hello` in a browser, with the ip from the
  `SERVER_READY` line, while `chumicro-workspace repl --tail 60 --device <id>`
  follows the board. Watch the request count climb each time you reload.
- Add a route to `app.py`, such as `/led` that switches the onboard LED,
  and run the driver again.
