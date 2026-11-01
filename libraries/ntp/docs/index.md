---
title: "chumicro-ntp: network time (SNTP) for CircuitPython and MicroPython"
---

# chumicro-ntp

**Ask an internet time server what time it is, without pausing your `while True:` loop.**

A board with no battery-backed clock starts every boot with the wrong date.  `chumicro-ntp` asks a time server such as `pool.ntp.org` for the current time and hands it back as Unix seconds, the count of seconds since 1 January 1970 UTC.  `client.query()` sends the question and returns at once.  The loop checks for the answer on each pass, so an LED keeps blinking while the reply is on its way.  It speaks SNTP, the simple client form of the Network Time Protocol, in pure Python that runs on CircuitPython, MicroPython, and CPython.

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

In a program with more going on, hand the loop to [`chumicro-runner`](https://chumicro.com/ChuMicro/runner/stable/).  A timed job sends the query once a minute, and the runner reads the reply:

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

## Documentation

- [User Guide](guide.md): the polling loop explained, turning Unix seconds into a date, building the client from config, bringing your own UDP socket, the runner pattern, and every way a query can fail
- [API Reference](api.md): `NTPClient`, the `NTPResult` that `query()` returns, and `NTPError`

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/ntp) · \
[PyPI](https://pypi.org/project/chumicro-ntp/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
