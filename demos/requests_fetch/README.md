# requests_fetch: one-shot HTTP GET as a generator

End-to-end demo of `chumicro_requests` generator API on a real board.
The driver runs a stdlib HTTP server on the host's LAN IP; the board
joins the same wifi and fetches one URL from it with a single
`yield from`.

The board reads top-to-bottom (connect, send, receive, return the
response) instead of polling a request handle or wiring an `on_done`
callback:

```python
def fetch_run(wifi, link_up, url):
    yield from wait_for(link_up)            # suspend until wifi is up
    factory = connector_factory(radio=wifi.adapter.radio)
    response = yield from get(factory, url)
    print(f"FETCHED status={response.status_code} bytes={len(response.body)}")

runner.add_generator(fetch_run(wifi, link_up, fetch_url))
```

## What it shows

- **One-shot fetch as a generator.** `chumicro_requests.generators.get`
  runs the whole request lifecycle under `Runner.add_generator`; the
  caller gets the `Response` back from the `yield from`.
- **Reuses the connector factory.** `connector_factory`
  is the same non-blocking connector the long-lived `HttpClient` uses.
- **Generator vs reactive client.** Pair with
  `libraries/requests/examples/periodic_get.py`, which drives the
  `check` / `handle` `HttpClient` for repeated requests on one client.

## Run it

```bash
.venv/bin/python demos/requests_fetch/driver.py
```

Defaults: targets the first CircuitPython device in `devices.yml`.

Override:

- `--device <id>`: a specific device id from `devices.yml`.
- `--runtime micropython`: pick the first MicroPython device.
- `--wifi-timeout-s <n>`: how long to wait for the board's `WIFI_OK`
  marker (default 45 s).
- `--completion-timeout-s <n>`: how long to wait for the board's
  `FETCHED` marker after `FETCHING` (default 30 s).

## Expected output

```
driver: http server up at http://10.0.0.5:54321/hello
driver: targeting raspberry-pi-pico-w-cp (circuitpython @ /dev/cu.usbmodem...)
driver: board WIFI_OK ip=10.0.0.42
driver: board FETCHING url=http://10.0.0.5:54321/hello
driver: board FETCHED status=200 bytes=49
driver: demo completed cleanly.
```
