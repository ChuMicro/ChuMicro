# User Guide

## Overview

A board with no battery-backed clock starts every boot with the wrong date.  `chumicro-ntp` asks a time server for the current time over SNTP (Simple Network Time Protocol, RFC 4330).  It sends one 48-byte UDP packet, reads one back, and turns the server's timestamp into Unix seconds, the count of seconds since 1 January 1970 UTC.  Each answer comes from a single reply, in whole seconds, with no correction for network delay.  Whole seconds suit log timestamps, certificate dates, and a job that runs at a set time of day.

`NTPClient` owns the UDP socket and talks to the server.  `client.query()` sends one request and returns an `NTPResult` at once.  The `NTPResult` fills in later: `done` turns `True`, and then `unix_seconds` holds the time or `error` holds what went wrong.

The main loop picks up the reply.  On every pass it calls `client.check(now_ms)`, which returns `True` while a reply is pending, and then `client.handle(now_ms)`.  `handle()` reads the reply once it has landed, and fails the query once `timeout_ms` (5000 ms by default) has passed.  `now_ms` comes from `chumicro_timing.ticks_ms()`, the clock the client times its queries with.

## Getting started

This program joins wifi, then asks for the time once a minute and prints it, for as long as the board has power:

```python
import time

from chumicro_ntp import NTPClient
from chumicro_sockets.sockets_factory import udp_socket_factory
from chumicro_timing import ticks_add, ticks_diff, ticks_ms
from chumicro_wifi import WifiConfig, WifiService

wifi = WifiService(WifiConfig(ssid="your-wifi-ssid", password="your-wifi-password"))

# The client opens a non-blocking UDP socket at its first query and asks
# pool.ntp.org unless you pass server=.
# CircuitPython needs radio=, and MicroPython ignores it.
client = NTPClient(transport_factory=udp_socket_factory(radio=wifi.adapter.radio))

request = None             # the query waiting for a reply, or None
next_sync_ms = ticks_ms()  # due now, so the first query goes out once wifi is up

while True:
    now_ms = ticks_ms()
    if wifi.check(now_ms):  # join wifi, and rejoin after a drop
        wifi.handle(now_ms)

    # Once a minute, while wifi is up, send a query.
    if wifi.connected and ticks_diff(now_ms, next_sync_ms) >= 0:
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

`WifiService` joins the network and rejoins after a drop, the same way on CircuitPython and MicroPython.  The [`chumicro-wifi` guide](https://chumicro.com/ChuMicro/wifi/stable/guide/) covers it.  `ticks_diff` and `ticks_add` do the millisecond arithmetic across the counter's [rollover](https://chumicro.com/ChuMicro/timing/stable/guide/#how-the-rollover-works).

Check `request.error` before reading `request.unix_seconds`.  On a failed query, reading `unix_seconds` raises the stored error.

One query runs at a time.  `client.busy` is `True` from `query()` until the result is done.  A second `query()` before then raises `RuntimeError`.  `client.cancel()` ends the query in flight with `NTPError("canceled")` and frees the client for the next one.

`query()` looks up the server's IP address before it sends.  That DNS lookup waits until the resolver answers or gives up.  An IP address passed as `server=` skips the lookup.  `handle()` reads only a packet that has already arrived, so waiting for the reply never pauses the loop.

## Turning Unix seconds into a date

The time of day needs only arithmetic, because every Unix day is exactly 86,400 seconds:

```python
hours = (unix_seconds // 3600) % 24
minutes = (unix_seconds // 60) % 60
seconds = unix_seconds % 60
```

The runtime's `time` module turns the value into a date.  Its clock counts from a year that depends on the runtime.  CircuitPython and MicroPython's rp2 port (Pi Pico W) count from 1970, the same as Unix.  MicroPython's esp32 port counts from 2000, so subtract the 946,684,800 seconds between the two:

| Runtime | Date fields from `unix_seconds` |
|---|---|
| CircuitPython | `time.localtime(unix_seconds)` |
| MicroPython, rp2 port | `time.localtime(unix_seconds)` |
| MicroPython, esp32 port | `time.localtime(unix_seconds - 946_684_800)` |
| CPython | `time.gmtime(unix_seconds)` |

Each call returns UTC fields: year, month, day, hour, minute, second, and the rest.  Add your own offset for local time.

## Building the client from config

`NTPClient.from_config(config, radio=...)` builds a client from a flat-key config mapping, such as a plain dict.  The client opens its own non-blocking UDP socket through `chumicro-sockets` when the first query goes out.  It reads three optional keys:

| Key | Default |
|---|---|
| `ntp.server` | `"pool.ntp.org"` |
| `ntp.port` | `123` |
| `ntp.timeout_ms` | `5000` |

Pass `radio=wifi.radio` on CircuitPython.  MicroPython and CPython ignore it.  A constructor keyword passed alongside, such as `timeout_ms=8000`, wins over the config value.  A `chumicro-workspace` deploy fills the keys from an `[ntp]` table in `secrets.toml` or the project config.  [`examples/ntp_query.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/ntp/examples/ntp_query.py) builds its client this way.

A client built from config or with `transport_factory=` survives `client.close()`: the next `query()` opens a fresh socket.  A client built with `socket=` has no way to reopen one, so its next `query()` after `close()` raises `RuntimeError`.

## Bring your own UDP socket

`NTPClient` calls three methods on its socket, and any UDP layer that provides them works:

| Method | What the client expects |
|---|---|
| `sendto(payload, host, port)` | Sends `payload` (48 `bytes`) to `host` and `port`, passed as separate arguments.  Any `OSError` fails the query. |
| `recvfrom_into(buffer)` | Copies one waiting datagram into `buffer` and returns `(byte_count, sender)`.  With nothing waiting, it raises `OSError` with `EAGAIN` or `EWOULDBLOCK`, or returns a count of 0. |
| `close()` | Releases the socket. |

The socket must already be non-blocking.  The client never calls `setblocking`.  A `recvfrom_into` that waits for data freezes the loop until a packet arrives.

Pass a ready socket as `socket=`.  Or pass `transport_factory=` a zero-argument function that returns one, and the client opens the socket at the first query.  `chumicro_sockets.udp_socket` builds the default socket.  `chumicro_sockets.testing.FakeUDPSocket` stands in for it in tests.

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

`NTPClient.from_config` is the only code in this library that imports `chumicro_sockets`.  It imports the module inside the call.  A program that supplies its own socket can keep `chumicro-sockets` off the board with one line in `code.py` or `app.py`:

```python
__chumicro_skip_factories__ = ("sockets_factory",)
```

[Slimming your deploy](https://chumicro.com/ChuMicro/guides/contributing/slimming-your-deploy/) explains the line.  On a board without `chumicro_sockets.sockets_factory`, `from_config` raises `RuntimeError` asking for `socket=` or `transport_factory=`.

## Runner pattern

A [`chumicro-runner`](https://chumicro.com/ChuMicro/runner/stable/guide/#services) `Runner` drives the client with the same `check()` and `handle()` calls, alongside the board's other jobs.  While a reply is outstanding, the client's `next_deadline(now_ms)` asks the runner for a step every 20 ms until the reply lands or `timeout_ms` passes.  `runner.wait()` sleeps in between.  An idle client asks for no steps, so a periodic job sends each query.  That job's timer wakes the board once a minute:

```python
from chumicro_ntp import NTPClient
from chumicro_runner import Runner
from chumicro_sockets.sockets_factory import udp_socket_factory
from chumicro_wifi import WifiConfig, WifiService

wifi = WifiService(WifiConfig(ssid="your-wifi-ssid", password="your-wifi-password"))
client = NTPClient(transport_factory=udp_socket_factory(radio=wifi.adapter.radio))
pending = []  # holds the query waiting for its reply, if there is one


def start_sync(now_ms):
    """Runs once a minute: send a query while wifi is up and the last one is done."""
    if wifi.connected and not client.busy:
        pending.append(client.query())


runner = Runner()
runner.add(wifi)    # joins wifi, and rejoins after a drop
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

## Memory notes

`NTPClient` allocates its 48-byte receive buffer once, in `__init__`, and sends the same 48-byte request constant on every `query()`.  `handle()` reads into that buffer and parses it in place through a `memoryview`.  Each `query()` creates one small `NTPResult`.

## Platform notes

The client behaves the same on CircuitPython, MicroPython, and CPython.  Date handling is the one difference, shown in [Turning Unix seconds into a date](#turning-unix-seconds-into-a-date).

The client reads time from `chumicro_timing.ticks` unless `ticks=` names another clock.  A replacement clock provides `ticks_ms`, `ticks_diff`, and `ticks_add`, and the `now_ms` values passed to `check()` and `handle()` must come from it.  The timing guide's [Platform notes](https://chumicro.com/ChuMicro/timing/stable/guide/#platform-notes) list where the default clock reads its time on each runtime.

The library's functional tests run a live `pool.ntp.org` query on CircuitPython and MicroPython boards and check that the answer falls between 2024 and 2030.

## Failure modes

When a query ends badly, `request.error` holds the reason:

| Cause | `request.error` |
|---|---|
| `sendto` failed, for example on a DNS lookup that found nothing | the socket's `OSError`, unchanged |
| No reply within `timeout_ms` | `NTPError("SNTP query timed out after N ms")` |
| Reply shorter than 48 bytes | `NTPError("short SNTP response (N bytes)")` |
| Reply marked with a mode other than server | `NTPError("unexpected SNTP mode N (want 4)")` |
| Server refused to answer, with stratum 0: a "kiss-of-death" reply that servers send to rate-limit or turn away a client | `NTPError("SNTP kiss-of-death (stratum=0)")` |
| Reply carried a zero timestamp | `NTPError("SNTP zero transmit timestamp")` |
| `client.cancel()` ended the query | `NTPError("canceled")` |
| `recvfrom_into` failed with an error other than "no data yet" | the socket's `OSError`, unchanged |

`NTPError` subclasses `OSError`, so every failure in the table is an `OSError`.

The client accepts the first well-formed 48-byte reply that reaches its port, from any sender.  SNTP over UDP carries no authentication, so any host that can send to that port can set the time the board reads.

## Examples

| Example | What it shows |
|---|---|
| [`examples/ntp_query.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/ntp/examples/ntp_query.py) | Joins wifi, then asks `pool.ntp.org` for the time once a minute and prints it as Unix seconds and a UTC clock time.  A failed query prints its reason.  The next query goes out a minute later.  CircuitPython or MicroPython board with wifi. |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/ntp) · \
[PyPI](https://pypi.org/project/chumicro-ntp/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
