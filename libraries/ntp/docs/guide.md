# User Guide

## Overview

A board with no battery-backed clock starts every boot with the wrong date.  `chumicro-ntp` asks a time server for the current time over SNTP (Simple Network Time Protocol, RFC 4330): it sends one 48-byte UDP packet, reads one back, and turns the server's timestamp into Unix seconds, the count of seconds since 1 January 1970 UTC.  It leaves out what full NTP adds on top, such as averaging many samples and correcting for network delay, and it drops the fraction of a second.  Whole seconds suit log timestamps, certificate dates, and running a task at a set time of day.

Three pieces do the work:

- `NTPClient` owns the UDP socket and talks to the server.
- `client.query()` sends one request and returns an `NTPResult` without waiting for the reply.
- The `NTPResult` fills in later.  `done` turns `True`, and then `unix_seconds` holds the time or `error` holds what went wrong.

Your loop picks up the reply.  On every pass it calls `client.check(now_ms)`, which is `True` while a reply is pending, and then `client.handle(now_ms)`, which reads the reply if it has landed or fails the query once `timeout_ms` (5000 ms by default) has passed.  `now_ms` comes from `chumicro_timing.ticks_ms()`, the millisecond counter the client also times its queries with.  `chumicro-runner` calls the same `check` / `handle` pair on every service it drives, so it can poll the client for you (see [Runner pattern](#runner-pattern)).

## Getting started

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

On MicroPython, join wifi with `network.WLAN` first, drop `import wifi`, and pass `radio=None`.  `ticks_diff` and `ticks_add` do the millisecond arithmetic, and stay correct when the counter wraps around.

Check `request.error` before reading `request.unix_seconds`: on a failed query, reading `unix_seconds` raises the stored error.

One query runs at a time.  `client.busy` is `True` from `query()` until the result is done, and calling `query()` again before then raises `RuntimeError`.  `client.cancel()` ends the query in flight with `NTPError("canceled")` and frees the client for the next one.

`query()` looks up the server's IP address before it sends, and that DNS lookup waits until the resolver answers or gives up.  Pass an IP address as `server=` to skip the lookup.  Waiting for the reply never blocks, because `handle()` only reads a packet that has already arrived.

## Turning Unix seconds into a date

The time of day needs only arithmetic, because every Unix day is exactly 86,400 seconds:

```python
hours = (unix_seconds // 3600) % 24
minutes = (unix_seconds // 60) % 60
seconds = unix_seconds % 60
```

For the date, hand the value to the runtime's `time` module, after checking which year its clock counts from.  CircuitPython and MicroPython's rp2 port (Pi Pico W) count from 1970, the same as Unix.  MicroPython's esp32 port counts from 2000, so subtract the 946,684,800 seconds between the two:

| Runtime | Date fields from `unix_seconds` |
|---|---|
| CircuitPython | `time.localtime(unix_seconds)` |
| MicroPython, rp2 port | `time.localtime(unix_seconds)` |
| MicroPython, esp32 port | `time.localtime(unix_seconds - 946_684_800)` |
| CPython | `time.gmtime(unix_seconds)` |

Each call returns UTC fields (year, month, day, hour, minute, second, and so on).  Add your own offset for local time.

## Building the client from config

`NTPClient.from_config(config, radio=...)` builds a client from a flat-key config mapping (a plain dict works) and opens its own non-blocking UDP socket through `chumicro-sockets` when the first query goes out.  It reads three optional keys:

| Key | Default |
|---|---|
| `ntp.server` | `"pool.ntp.org"` |
| `ntp.port` | `123` |
| `ntp.timeout_ms` | `5000` |

Pass `radio=wifi.radio` on CircuitPython; MicroPython and CPython ignore it.  A constructor keyword passed alongside, such as `timeout_ms=8000`, wins over the config value.  With `chumicro-workspace`, the keys come from an `[ntp]` table in `secrets.toml` or your project config.  [`examples/ntp_query.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/ntp/examples/ntp_query.py) builds its client this way.

A client built this way survives `client.close()`: the next `query()` opens a fresh socket.  A client built with `socket=` has no way to reopen one, so its next `query()` after `close()` raises `RuntimeError`.

## Bring your own UDP socket

`NTPClient` calls three methods on its socket, so any UDP layer that provides them works:

| Method | What the client expects |
|---|---|
| `sendto(payload, host, port)` | Sends `payload` (48 `bytes`) to `host` and `port`, passed as separate arguments.  Any `OSError` fails the query. |
| `recvfrom_into(buffer)` | Copies one waiting datagram into `buffer` and returns `(byte_count, sender)`.  With nothing waiting, raises `OSError` with `EAGAIN` or `EWOULDBLOCK`, or returns a count of 0. |
| `close()` | Releases the socket. |

The socket must already be non-blocking.  The client never calls `setblocking`, and a `recvfrom_into` that waits for data freezes your loop until a packet arrives.

Pass a ready socket as `socket=`, or pass `transport_factory=` a zero-argument function that returns one, which delays opening the socket until the first query.  `chumicro_sockets.udp_socket` builds the default socket, and `chumicro_sockets.testing.FakeUDPSocket` stands in for it in tests.

A raw stdlib `socket.socket(AF_INET, SOCK_DGRAM)` takes its address as one `(host, port)` tuple, so it needs a small adapter:

```python
import socket as stdlib_socket

from chumicro_ntp import NTPClient


class StdlibUdpAdapter:
    def __init__(self, sock):
        self._sock = sock

    def sendto(self, payload, host, port):
        return self._sock.sendto(payload, (host, port))

    def recvfrom_into(self, buffer):
        return self._sock.recvfrom_into(buffer)

    def close(self):
        self._sock.close()


raw = stdlib_socket.socket(stdlib_socket.AF_INET, stdlib_socket.SOCK_DGRAM)
raw.setblocking(False)
client = NTPClient(socket=StdlibUdpAdapter(raw), server="my.lan.ntp")
```

`NTPClient.from_config` is the only code in this library that imports `chumicro_sockets`, and it imports it inside the call.  When you supply your own socket and deploy with `chumicro-workspace`, add this constant to your `code.py` or `app.py`, and the deploy leaves the default socket factory, and with it `chumicro-sockets`, off the board:

```python
__chumicro_skip_factories__ = ("sockets_factory",)
```

An entry can be the module's short name (`"sockets_factory"`) or its full dotted path (`"chumicro_sockets.sockets_factory"`).  An entry that matches no module fails the deploy, so a typo cannot quietly ship the default.  If `from_config` runs on a board where `chumicro_sockets.sockets_factory` is missing, whether skipped at deploy time or never installed, it raises `RuntimeError` telling you to pass `socket=` or `transport_factory=`.

## Runner pattern

`chumicro-runner`'s `Runner` drives any object with a `check(now_ms)` / `handle(now_ms)` pair, so it can run the client alongside your other services.  While a reply is outstanding, the client's `next_deadline(now_ms)` asks the runner for a turn every 20 ms until the reply lands or `timeout_ms` passes, so `runner.wait()` sleeps between reads.  An idle client asks for nothing, so the sync itself goes on a periodic task: that task's timer is what wakes the board once a minute.

```python
from chumicro_runner import Runner

pending = []  # holds the query waiting for its reply, if there is one

def start_sync(now_ms):
    """Runs once a minute: send a query unless the last one is still waiting."""
    if not client.busy:
        pending.append(client.query())

runner = Runner()
runner.add(client)  # reads the reply while one is outstanding
runner.add_periodic(start_sync, period_ms=60_000, start_after_ms=0)

while True:
    now_ms = runner.tick()  # every registered job takes one small step

    if pending and pending[0].done:
        request = pending.pop()
        if request.error is None:
            print("unix seconds:", request.unix_seconds)
        else:
            print("no answer this time, retrying in a minute:", request.error)

    runner.wait(now_ms)  # sleeps until the next reply check or the next sync
```

This is the [Getting started](#getting-started) loop with the `check()` / `handle()` lines handed to the runner, the sync timer handed to `add_periodic`, and `time.sleep()` replaced by `runner.wait()`.

## Memory notes

`NTPClient` allocates its 48-byte receive buffer once, in `__init__`, and sends the same 48-byte request constant on every `query()`.  `handle()` reads into that buffer and parses it in place through a `memoryview`.  Each `query()` creates one small `NTPResult`.

## Platform notes

The client behaves the same on CircuitPython, MicroPython, and CPython; only date handling differs, as [Turning Unix seconds into a date](#turning-unix-seconds-into-a-date) shows.  Its default clock is `chumicro_timing.ticks`, which reads `supervisor.ticks_ms` on CircuitPython, `time.ticks_ms` on MicroPython, and `time.monotonic_ns` on CPython.  Pass `ticks=` to substitute your own clock.  It must provide `ticks_ms`, `ticks_diff`, and `ticks_add`, and the `now_ms` values you pass to `check()` and `handle()` must come from it.

The library's functional tests run a live `pool.ntp.org` query on CircuitPython and MicroPython boards and check that the answer falls between 2024 and 2030.

## Failure modes

When a query ends badly, `request.error` holds the reason:

| Cause | `request.error` |
|---|---|
| `sendto` failed, for example a DNS lookup that found nothing | the socket's `OSError`, unchanged |
| No reply within `timeout_ms` | `NTPError("SNTP query timed out after N ms")` |
| Reply shorter than 48 bytes | `NTPError("short SNTP response (N bytes)")` |
| Reply not marked as coming from a server | `NTPError("unexpected SNTP mode N (want 4)")` |
| Server refused to answer (stratum 0, a "kiss-of-death" reply that servers use to rate-limit or turn away a client) | `NTPError("SNTP kiss-of-death (stratum=0)")` |
| Reply carried a zero timestamp | `NTPError("SNTP zero transmit timestamp")` |
| `client.cancel()` ended the query | `NTPError("canceled")` |
| `recvfrom_into` failed with anything other than "no data yet" | the socket's `OSError`, unchanged |

`NTPError` subclasses `OSError`, so every failure in the table is an `OSError`.

The client accepts the first well-formed 48-byte reply that reaches its port, from any sender.  SNTP over UDP carries no authentication, so treat the result as a convenient clock rather than a trusted one.

## Examples

| Example | What it shows |
|---|---|
| [`examples/ntp_query.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/ntp/examples/ntp_query.py) | Joins wifi, then asks `pool.ntp.org` for the time once a minute and prints it as Unix seconds and a UTC clock time.  A failed query prints its reason and the next one goes out a minute later.  CircuitPython or MicroPython board with wifi. |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/ntp) · \
[PyPI](https://pypi.org/project/chumicro-ntp/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
