# laptop_roundtrip: watch the loop stay live, no board required

Every other demo here needs a board on your desk. This one needs nothing but
Python. It runs an HTTP server, an HTTP client, and a blinking LED in a single
CPython process on `127.0.0.1`, so you can see the concurrency story before you
own any hardware.

One `Runner` drives all three:

- a `chumicro_http_server` serving a `/slow` route,
- a `chumicro_requests` generator fetching that route,
- a simulated LED, a `chumicro_timing` `Rate` toggling a printed on/off state.

The server hands its response back one line at a time on a timer, so the single
request stays in flight for about a second. That is long enough to watch the
LED keep blinking while the fetch runs.

## What it proves

The loop never blocks while the request completes, and you can watch that
happen. The `fetch: GET` line prints, the LED toggles a dozen times, and only
then does `fetch: 200` arrive. The request and the blink share one loop and
neither waits on the other. `runner.wait()` idles the CPU between events rather
than spinning, the same way it would on a battery-powered board.

There is no board, no external network, and no second terminal. The server and
the client are the same process talking to itself over the loopback interface.

## Run it

After the repo's normal setup:

```bash
python3 scripts/prepare_workspace.py     # one-time: creates .venv, installs everything
source .venv/bin/activate
```

run it from this directory:

```bash
cd demos/laptop_roundtrip
python app.py
```

## Expected output

```
laptop_roundtrip: serving http://127.0.0.1:51579/slow
laptop_roundtrip: one fetch in flight, LED blinking on the same loop

  fetch: GET http://127.0.0.1:51579/slow
  LED on
  LED off
  LED on
  LED off
  LED on
  LED off
  LED on
  LED off
  LED on
  LED off
  LED on
  fetch: 200, 224 bytes received
  LED off

laptop_roundtrip: request finished; the LED blinked 12 times without the loop ever stalling.
```

The port is chosen by the OS, so it changes each run. The blink count can vary
by one or two depending on scheduling, which is the honest picture: the LED
blinks on its own cadence regardless of what the fetch is doing.

## How this demo differs from the others

The board demos split into `app.py` (deployed to a board) and `driver.py` (runs
on your laptop and drives the board). This one has no board and no driver: `app.py`
is the whole thing, run directly with `python app.py`. It is the demo to reach
for when you want to evaluate the loop model and have no silicon to hand.
