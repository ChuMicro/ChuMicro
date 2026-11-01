# chumicro-ntp

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Ask an internet time server what time it is, without pausing your `while True:` loop.**

A board with no battery-backed clock starts every boot with the wrong date.  `chumicro-ntp` asks a time server such as `pool.ntp.org` for the current time and hands it back as Unix seconds, the count of seconds since 1 January 1970 UTC.  `client.query()` sends the question and returns at once.  The loop checks for the answer on each pass, so an LED keeps blinking while the reply is on its way.  It speaks SNTP, the simple client form of the Network Time Protocol, in pure Python that runs on CircuitPython, MicroPython, and CPython.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family: small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_ntp

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_ntp

# CPython
pip install chumicro-ntp
```

The `Runner` loop in the quick example comes from `chumicro-runner`.  Install it the same way.

[Start here](https://chumicro.com/ChuMicro/guides/start-here/) takes a new board from flashing CircuitPython or MicroPython to running your own blink.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the pre-compiled `.mpy` packages, the experimental channel, and why package names use a hyphen on PyPI and an underscore on the board.

## Quick example

This CircuitPython `code.py` asks for the time once a minute and prints it.  It relies on CircuitPython's own wifi join, which runs at startup when `settings.toml` sets `CIRCUITPY_WIFI_SSID` and `CIRCUITPY_WIFI_PASSWORD`:

```python
import time

import wifi
from chumicro_ntp import NTPClient
from chumicro_sockets import udp_socket
from chumicro_timing import ticks_add, ticks_diff, ticks_ms

# The client polls for its reply, so the socket must not block.
sock = udp_socket(radio=wifi.radio)
sock.setblocking(False)
client = NTPClient(socket=sock)  # asks pool.ntp.org unless you pass server=

request = None             # the query waiting for a reply, or None
next_sync_ms = ticks_ms()  # due now, so the first query goes out right away

while True:
    now_ms = ticks_ms()

    # Once a minute, send a query.
    if ticks_diff(now_ms, next_sync_ms) >= 0:
        request = client.query()
        next_sync_ms = ticks_add(now_ms, 60_000)

    # check() is True while a reply is pending, and handle() reads it when it lands.
    if client.check(now_ms):
        client.handle(now_ms)

    if request is not None and request.done:
        if request.error is None:
            print("unix seconds:", request.unix_seconds)
        else:
            print("no answer this time, retrying in a minute:", request.error)
        request = None

    # Your own work, such as blinking an LED, goes in this loop too.
    time.sleep(0.02)  # rest 20 ms between passes
```

On MicroPython, join wifi with `network.WLAN` first, drop `import wifi`, and pass `radio=None`.

`ticks_ms()`, `ticks_diff`, and `ticks_add` come from `chumicro-timing` and keep the arithmetic correct when the millisecond count rolls over.  `client` is a service, an object a loop drives through two methods.  `check(now_ms)` returns `True` when the client has work to do.  `handle(now_ms)` does one small step of that work.

In a program with more going on, hand the loop to [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner).  A timed job sends the query once a minute, and the runner reads the reply:

```python
from chumicro_runner import Runner

pending = []  # the query waiting for its reply, if there is one

def start_sync(now_ms):
    if not client.busy:
        pending.append(client.query())

runner = Runner()
runner.add(client)                                                   # reads the reply while one is outstanding
runner.add_periodic(start_sync, period_ms=60_000, start_after_ms=0)  # every minute, starting now

while True:
    now_ms = runner.tick()

    if pending and pending[0].done:
        request = pending.pop()
        if request.error is None:
            print("unix seconds:", request.unix_seconds)
        else:
            print("no answer this time, retrying in a minute:", request.error)

    runner.wait(now_ms)  # sleeps until the next reply check or the next sync
```

The [user guide](https://chumicro.com/ChuMicro/ntp/stable/guide/) covers turning Unix seconds into a date, bringing your own UDP socket, and every way a query can fail.

## What's included

| Symbol | Description |
|---|---|
| `NTPClient(socket=None, *, transport_factory=None, server="pool.ntp.org", port=123, timeout_ms=5000, ticks=None)` | The time client.  Pass exactly one of `socket`, an open non-blocking UDP socket, or `transport_factory`, a function that opens one when the first query goes out |
| `NTPClient.from_config(config, *, radio=None)` | Builds a client from the optional `ntp.server`, `ntp.port`, and `ntp.timeout_ms` config keys and opens its own UDP socket through `chumicro-sockets` |
| `client.query()` | Sends one request and returns an `NTPResult` without waiting for the reply.  One query runs at a time.  `client.busy` is `True` until it finishes |
| `client.check(now_ms)` / `client.handle(now_ms)` | Call both on every pass of the loop.  `check` returns `True` while a reply is pending.  `handle` reads the reply, or fails the query once `timeout_ms` has passed |
| `client.cancel()` / `client.close()` | `cancel()` abandons the query in flight.  `close()` closes the UDP socket |
| `NTPResult` | One query's outcome.  Once `done` is `True`, `unix_seconds` holds the time or `error` holds what went wrong |
| `NTPError` | `OSError` subclass for a timeout, a malformed or refused reply, or a cancel |

## Where this fits

Depends on [`chumicro-sockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets) for the UDP socket and [`chumicro-timing`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) for the millisecond clock.  Both install with this library.  Runs as a service on a [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) loop, as the quick example shows.

## Platform support

Works on CPython, MicroPython, and CircuitPython, in pure Python.

`query()` looks up the server's address before it sends, and that DNS lookup holds the loop until the answer comes.  An IP address passed as `server=` skips the lookup.  Waiting for the time server's reply never holds the loop.

## Examples

| Example | What it shows |
|---|---|
| [`ntp_query.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/ntp/examples/ntp_query.py) | Joins wifi, then asks `pool.ntp.org` for the time once a minute and prints it as Unix seconds and a UTC clock time.  A failed query prints its reason, and the next one goes out a minute later.  CircuitPython or MicroPython board with wifi |

### Running the examples

The example joins wifi through `helpers.py`, which sits beside it in `examples/`.  Set `WIFI_SSID` and `WIFI_PASSWORD` at the top of the example.  Copy it to the board as `code.py` on CircuitPython or `main.py` on MicroPython, together with `helpers.py` and the libraries it imports.  From a clone of the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), `chumicro-workspace deploy-example ntp ntp_query` does the copying and takes the wifi settings from `secrets.toml`.  [Wiring wifi credentials](https://chumicro.com/ChuMicro/guides/wiring-wifi-credentials/) walks through both ways.

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran it on this board and here's what happened", some of the most useful feedback a hardware project can get.  Development happens in the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose contributing guide covers setup and the test workflow.

## Docs

📖 **[Stable docs](https://chumicro.com/ChuMicro/ntp/stable/)** · **[Experimental docs](https://chumicro.com/ChuMicro/ntp/experimental/)**

## Find this library

- **PyPI:** [chumicro-ntp](https://pypi.org/project/chumicro-ntp/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_ntp) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_ntp)
- **Source:** [libraries/ntp](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/ntp)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
