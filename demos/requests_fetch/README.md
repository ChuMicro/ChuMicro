# requests_fetch: your board fetches a web page every five seconds

Your board joins wifi and fetches a page from a small web server the
driver runs on your laptop. It prints what came back, waits five
seconds, and fetches it again, forever. A heartbeat prints once a
second the whole time, so you can see the board never freezes while it
waits on the network.

## What you will see

The driver's own lines start with `driver:`. Everything the board
prints shows up as it happens, after `board |`:

```
driver: http server up at http://10.0.0.5:54321/hello
driver: targeting pi-pico-w-circuitpython-board (circuitpython @ /dev/cu.usbmodem...)
board |   ...still ticking
board |   ...still ticking
board | WIFI_OK ip=10.0.0.42
driver: board WIFI_OK ip=10.0.0.42
driver: board fetching http://10.0.0.5:54321/hello
board |   GET http://10.0.0.5:54321/hello
board | FETCHED status=200 bytes=49
board | DEMO_COMPLETE
board |   {"message": "hello from the requests_fetch demo"}
driver: board FETCHED status=200 bytes=49
driver: demo completed cleanly; the board keeps fetching.
```

The driver stops there and takes its web server with it. The board
carries on: the heartbeat keeps printing every second, and every five
seconds the board tries the page again and prints `FETCH_FAILED` now
that nothing answers. To watch it after the driver exits, run
`chumicro-workspace repl --tail 60 --device <id>`.

## What you need

- A board registered with `chumicro-workspace add-device`.
- `secrets.toml` at the repo root with `wifi.ssid` and `wifi.password`.
- A wifi network that your board and your laptop both join.

## Run it

```bash
.venv/bin/python demos/requests_fetch/driver.py
```

The driver picks the first CircuitPython board in `devices.yml`. Pass
`--device <id>` for a specific board or `--runtime micropython` for the
first MicroPython one. `--help` lists the timeouts.

## How it works

The fetch in [`app.py`](app.py) reads top to bottom, the way you would
describe it out loud:

```python
def fetch_forever(wifi, link_up, url):
    yield from wait_for(link_up)                 # wait for wifi
    factory = connector_factory(radio=wifi.adapter.radio)
    while True:
        response = yield from get(factory, url)  # fetch the page
        print(f"FETCHED status={response.status_code} bytes={len(response.body)}")
        yield from sleep_until(ticks_add(ticks_ms(), FETCH_EVERY_MS))  # wait five seconds
```

Each `yield from` is a place the fetch pauses and the rest of the board
runs, which is how the heartbeat keeps printing. `runner.add_generator`
registers the function with the same `Runner` that drives wifi and the
heartbeat, and the program ends in the `while True:` loop every board
program runs. The real file wraps the fetch in `try`/`except`, so a
failed fetch prints `FETCH_FAILED` and the board tries again five
seconds later.

[`driver.py`](driver.py) starts the web server on your laptop's network
address, deploys `app.py` with that URL baked into the board's config,
and waits for the first `FETCHED`.

## Try next

- Change `FETCH_EVERY_MS` in `app.py` and run the demo again.
- [`press_through_fetch`](../press_through_fetch/) adds a button to
  this loop, and the press lands even mid-fetch.
- [`libraries/requests/examples/periodic_get.py`](../../libraries/requests/examples/periodic_get.py)
  does the same repeated fetch with `HttpClient`, checking a request
  object on each pass of the loop instead of using `yield from`.
