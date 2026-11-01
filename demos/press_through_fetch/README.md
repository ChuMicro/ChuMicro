# press_through_fetch: a button that never misses, even mid-fetch

Your board joins wifi and fetches a page from your laptop every three
seconds, forever. Press a button whenever you like, in the middle of a
fetch included, and the board reports the press and how long you held
it. The hold time is measured from the moment your finger landed, not
from whenever the loop got around to noticing.

The board's hardware catches the press underneath the loop:
`keypad` firmware on CircuitPython, a pin interrupt on MicroPython.
`chumicro-buttons` reads what it caught, while `chumicro-wifi`,
`chumicro-requests`, and `chumicro-runner` keep the network side moving
in the same `while True:` loop.

## What you will see

The driver's own lines start with `driver:`. Everything the board
prints shows up as it happens, after `board |`. The fetches keep coming
every three seconds while the driver waits for your press:

```
driver: http server up at http://10.0.0.5:54321/hello
driver: targeting pi-pico-w-circuitpython-board (circuitpython @ /dev/cu.usbmodem...)
board | WIFI_OK ip=10.0.0.42
driver: board WIFI_OK ip=10.0.0.42
board | FETCHED status=200 bytes=54
driver: board FETCHED status=200 bytes=54
driver: press the button on pin GP3 now
board | FETCHED status=200 bytes=54
board | FETCHED status=200 bytes=54
board | PRESS count=1
driver: board PRESS count=1
board | RELEASE held_ms=142
board | DEMO_COMPLETE
driver: board RELEASE held_ms=142
driver: demo completed cleanly; the board is still fetching.
```

The driver stops there and takes its web server with it. The board
carries on: every press still prints `PRESS` and `RELEASE`, and every
three seconds it tries the page again and prints `FETCH_FAILED` now that
nothing answers. To watch it after the driver exits, run
`chumicro-workspace repl --tail 60 --device <id>`.

## What you need

- A board registered with `chumicro-workspace add-device`.
- `secrets.toml` at the repo root with `wifi.ssid` and `wifi.password`.
- A wifi network that your board and your laptop both join.
- A momentary push button between one GPIO pin and GND. The board turns
  on the pin's internal pull-up, so no resistor is needed. The default
  pin is `GP3` on CircuitPython and `3` on MicroPython.

## Run it

```bash
.venv/bin/python demos/press_through_fetch/driver.py
.venv/bin/python demos/press_through_fetch/driver.py --runtime micropython --button-pin 3
```

`--button-pin` takes a board attribute name on CircuitPython (`GP3`)
and a pin number on MicroPython (`3`). `--help` lists the device,
runtime, and timeout options. The driver waits up to 60 seconds for
your press.

## How it works

[`app.py`](app.py) registers three things with one `Runner`: wifi, the
button, and `fetch_forever`, a function that fetches the page, pauses
three seconds with `yield from sleep_until(...)`, and repeats. Each
`yield from` hands the loop back so the button gets its turn.

The button is registered with `period_ms=20`, so it gets a turn every
20 ms. `runner.wait()` rests the CPU until a network socket
or a timer needs it, and a pin changing is neither, so the timer is
what brings the loop back to check the button. The hardware recorded
the press the moment it happened, so `held_ms` comes out exact either
way. The button's `on_press` and `on_release` callbacks print `PRESS`
and `RELEASE`, and the first release prints `DEMO_COMPLETE`.

[`driver.py`](driver.py) starts a web server on your laptop, deploys
`app.py` with the URL and the pin baked into the board's config, waits
for wifi and the first fetch, then asks you to press. It checks that a
positive `held_ms` came back and exits. The board keeps fetching.

## Try next

- Hold the button for a few seconds so the hold spans a whole fetch.
  `held_ms` still comes back right.
- Wired to a keypad on the bench? A jumper from one column pin to GND
  turns that column's keys into plain buttons on their row pins.
- [`requests_fetch`](../requests_fetch/) is the same fetch loop without
  the button, with a heartbeat that shows the loop never stops.
