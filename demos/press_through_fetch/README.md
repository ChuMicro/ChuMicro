# press_through_fetch

A button and a live HTTP fetch share one loop, and the press never loses.
The board joins wifi and fetches a page from your laptop every three
seconds, forever. You press a button whenever you like, mid-fetch
included, and the board reports the press and how long you held it,
measured from the edge your finger made.

This is `chumicro-buttons`' headline claim run as a system: capture
happens in hardware underneath the loop (firmware `keypad` on
CircuitPython, a library-owned interrupt on MicroPython), while
`chumicro-wifi`, `chumicro-requests`, and `chumicro-runner` keep the
network side moving in the same `while True`.

## Wiring

A momentary button between one GPIO and GND; the internal pull-up is
switched on for you. On a keypad wired to the bench, a jumper from one
column pin to GND turns that column's keys into plain buttons on their
row pins.

## Run it

```bash
.venv/bin/python demos/press_through_fetch/driver.py
.venv/bin/python demos/press_through_fetch/driver.py --runtime micropython --button-pin 3
```

The driver starts a local HTTP server, deploys `app.py` with the fetch
URL and pin baked into the config, waits for wifi and the first fetch,
then asks you to press. It exits after confirming the press, the held
duration, and `DEMO_COMPLETE`; the board keeps fetching after it leaves.

## What to expect

```
driver: http server up at http://10.0.0.5:54321/hello
driver: board WIFI_OK ip=10.0.0.42
driver: board FETCHED status=200 bytes=54
driver: press the button on pin 3 now
driver: board PRESS count=1
driver: board RELEASE held_ms=142
driver: demo completed cleanly; the board is still fetching.
```

`driver.py --help` lists the device, runtime, pin, and timeout options.
