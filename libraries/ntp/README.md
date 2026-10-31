# chumicro-ntp

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Ask an internet time server what time it is, without pausing your `while True:` loop.**

A board with no battery-backed clock starts every boot with the wrong date.  `chumicro-ntp` asks a time server such as `pool.ntp.org` for the current time and hands it back as Unix seconds, the count of seconds since 1 January 1970 UTC.  You send the question, then check for the answer on each pass of your loop, so an LED keeps blinking while the reply is on its way.  It speaks SNTP (Simple Network Time Protocol, the simplified client form of NTP) in pure Python that runs unchanged on CircuitPython, MicroPython, and CPython.

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

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [ChuMicro install guide](https://chumicro.com/ChuMicro/guides/install/).

## Quick example

This `code.py` asks for the time once a minute and prints it, for as long as the board has power.  It assumes CircuitPython has already joined your wifi, which it does at startup when `settings.toml` sets `CIRCUITPY_WIFI_SSID` and `CIRCUITPY_WIFI_PASSWORD`.

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

    # check() is True while a reply is pending; handle() reads it when it lands.
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

On MicroPython, join wifi with `network.WLAN` first, drop `import wifi`, and pass `radio=None`.  Each `ticks_ms()` value is a millisecond count from `chumicro-timing`, and `ticks_diff` / `ticks_add` do the arithmetic on it safely when the count wraps around.

`query()` looks up the server's address before it sends, and that DNS lookup waits for the answer; pass an IP address as `server=` to skip it.  Waiting for the time server's reply never blocks.

The [user guide](https://chumicro.com/ChuMicro/ntp/stable/guide/) covers turning Unix seconds into a date, running the client under [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner), bringing your own UDP socket, and every way a query can fail.

## What's included

| Symbol | Purpose |
|---|---|
| `NTPClient(socket=None, *, transport_factory=None, server="pool.ntp.org", port=123, timeout_ms=5000, ticks=None)` | The time client.  Pass exactly one of `socket` (an open, non-blocking UDP socket) or `transport_factory` (a function that opens one when the first query goes out). |
| `NTPClient.from_config(config, *, radio=None)` | Builds a client from the optional `ntp.server`, `ntp.port`, and `ntp.timeout_ms` config keys and opens its own UDP socket through `chumicro-sockets`. |
| `client.query()` | Sends one request and returns an `NTPResult` without waiting for the reply.  One query runs at a time; `client.busy` is `True` until it finishes. |
| `client.check(now_ms)` / `client.handle(now_ms)` | Call both on every pass of your loop.  `check` is `True` while a reply is pending; `handle` reads the reply, or fails the query once `timeout_ms` has passed. |
| `client.cancel()` / `client.close()` | Abandon the query in flight; close the UDP socket. |
| `NTPResult` | One query's outcome.  Once `done` is `True`, `unix_seconds` holds the time or `error` holds what went wrong. |
| `NTPError` | `OSError` subclass for a timeout, a malformed or refused reply, or a cancel. |

## Where this fits

Depends on [`chumicro-sockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets) for the UDP socket and [`chumicro-timing`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) for the millisecond clock; `pip install chumicro-ntp` brings both.  Your application calls it directly; no other ChuMicro library depends on it.

## Platform support

Pure Python, with the same behavior on CircuitPython, MicroPython, and CPython.

## Examples

| Example | What it shows |
|---|---|
| [`examples/ntp_query.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/ntp/examples/ntp_query.py) | Joins wifi, then asks `pool.ntp.org` for the time once a minute and prints it as Unix seconds and a UTC clock time.  A failed query prints its reason and the next one goes out a minute later.  CircuitPython or MicroPython board with wifi. |

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
