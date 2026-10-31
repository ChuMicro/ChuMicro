---
title: "chumicro-ntp: network time (SNTP) for CircuitPython and MicroPython"
---

# chumicro-ntp

**Ask an internet time server what time it is, without pausing your `while True:` loop.**

A board with no battery-backed clock starts every boot with the wrong date.  `chumicro-ntp` asks a time server such as `pool.ntp.org` for the current time and hands it back as Unix seconds, the count of seconds since 1 January 1970 UTC.  You send the question, then check for the answer on each pass of your loop, so an LED keeps blinking while the reply is on its way.  The same pure-Python code runs on CircuitPython, MicroPython, and CPython.

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_ntp

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_ntp

# CPython
pip install chumicro-ntp
```

No board running yet?  [Start here](https://chumicro.com/ChuMicro/guides/start-here/) goes from a new board to your own code running on it.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the experimental channel, and the pre-compiled `.mpy` packages.

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

On MicroPython, join wifi with `network.WLAN` first, drop `import wifi`, and pass `radio=None`.

## Documentation

- [User Guide](guide.md): the polling loop explained, turning Unix seconds into a date, running under `chumicro-runner`, bringing your own UDP socket, and every way a query can fail
- [API Reference](api.md): `NTPClient`, the `NTPResult` that `query()` returns, and `NTPError`

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/ntp) · \
[PyPI](https://pypi.org/project/chumicro-ntp/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
