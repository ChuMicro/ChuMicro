# User Guide

## Overview

`chumicro-ntp` is a small Simple Network Time Protocol (SNTP) client
that runs identically on CircuitPython, MicroPython, and CPython.  It
implements the wire format from RFC 4330 — enough to ask any
standard NTP server "what time is it?" and parse the answer into
Unix-epoch seconds — and skips full NTP's stratum / dispersion /
round-trip-delay tracking (out of scope for embedded).

The client is **runner-shaped**: `query()` issues a request and
returns a result handle; `check(now_ms)` and `handle(now_ms)` drive
the recv side once per tick; `result.done` becomes `True` when the
exchange terminates.  Single in-flight query at a time, mirroring
`chumicro_requests.HttpClient.busy` semantics.

The UDP socket is **injected** — `NTPClient(socket=...)` accepts any
object that satisfies `chumicro_sockets.UDPSocket`.  Tests inject
`FakeUDPSocket` from `chumicro_sockets.testing`; apps inject a real
socket either directly or via the
`chumicro_ntp.sockets_factory.chumicro_sockets_factory()` helper.

Per the ChuMicro library-dependency policy:

- `chumicro-sockets` is a **hard dep** — single `pip install
  chumicro-ntp` brings the stack.
- The default-wiring helper lives in a **separate submodule**
  (`chumicro_ntp.sockets_factory`) — apps with a custom transport
  don't pull `chumicro-sockets` into their deploy graph.
- No `chumicro-events` or `chumicro-logging` deps; the library
  exposes no callbacks (the result handle is the observation
  surface).

## Getting started

```python
from chumicro_ntp import NTPClient
from chumicro_ntp.sockets_factory import chumicro_sockets_factory

sock = chumicro_sockets_factory(radio=wifi.adapter.radio)
sock.setblocking(False)

client = NTPClient(socket=sock, server="pool.ntp.org")
request = client.query()

while not request.done:
    if client.check(now_ms()):
        client.handle(now_ms())

if request.error is not None:
    print(f"NTP failed: {request.error}")
else:
    print(f"unix seconds: {request.unix_seconds}")

sock.close()
```

`request.unix_seconds` is the server's transmit-timestamp converted
to Unix-epoch seconds — feed it into `time.gmtime` (CPython) /
`utime.localtime` (MP/CP) for date components.

## Custom transport

Skip the helper and pass your own UDP socket — anything quack-typed
to `chumicro_sockets.UDPSocket` works:

```python
from chumicro_ntp import NTPClient

client = NTPClient(socket=my_custom_udp_socket, server="my.lan.ntp")
```

The deploy-graph walker never enters `chumicro_ntp.sockets_factory`
in this case, so `chumicro-sockets` is not shipped to the device.
This is the structural reason the helper lives in its own submodule:
the import-graph deploy walker only ships modules that are actually
imported, so a custom-transport app pays no `chumicro-sockets`
on-device cost.

## Runner pattern

`NTPClient` already implements the runner contract — register the
client with a `chumicro-runner.Runner` and the runner drives the
recv side automatically:

```python
from chumicro_runner import Runner

runner = Runner()
runner.add(client)        # check/handle wired up by the runner
# inside your tick loop:
runner.tick(now_ms())
if request.done:
    use(request.unix_seconds)
```

Single in-flight query — `client.busy` is `True` between `query()`
and `request.done`.  Calling `query()` again raises `RuntimeError`.
Cancel with `client.cancel()` to abort and free the slot.

## Memory notes

`NTPClient` pre-allocates a 48-byte `bytearray` for the recv buffer
in `__init__` so `handle` doesn't allocate on the hot path.
`_build_request` creates a fresh 48-byte `bytes` per `query()` —
the request is sent and immediately released, so the cost is one
allocation per query (acceptable for a once-every-N-minutes time
sync).

`NTPResult` is a tiny holder — three integer / object fields.

## Platform notes

Runs identically on CPython, MicroPython, and CircuitPython.  The
only stdlib import is `time` (for the default `_default_ticks_ms`
fallback when `time.ticks_ms` is unavailable on CPython).  All UDP
work goes through the injected socket — `chumicro-sockets` already
hides the per-runtime adapter chase.

The same NTPClient shape worked on:

- Pi Pico W (rp2040) on CircuitPython 10.2.0 + MicroPython 1.28.0
- Lolin S2 Mini (ESP32-S2) on CircuitPython 10.2.0 + MicroPython 1.28.0

Each board's `functional_tests/test_real_ntp.py` ran a real query
against `pool.ntp.org`, parsed the response, and asserted the
returned timestamp falls inside the 2024-2030 plausibility window.

## Failure modes

`NTPResult.error` carries the failure when the exchange ends badly:

| Cause | Exception |
|---|---|
| `sendto` failed (kernel rejected, address invalid) | `OSError` (raw, not wrapped) |
| Recv timeout (`timeout_ms` elapsed without data) | `NTPError("SNTP query timed out after N ms")` |
| Short response (< 48 bytes) | `NTPError("short SNTP response (N bytes)")` |
| Wrong mode in the response | `NTPError("unexpected SNTP mode N")` |
| Stratum-0 kiss-of-death | `NTPError("SNTP kiss-of-death (stratum=0)")` |
| Cancelled via `client.cancel()` | `NTPError("cancelled")` |
| Socket recv failed (non-EAGAIN OSError) | `OSError` (raw, not wrapped) |

`NTPError` is an `OSError` subclass so handlers that do
`except OSError` catch both wrapped and unwrapped failures.

## Examples

| Example | What it shows |
|---|---|
| [`examples/quickstart.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/ntp/examples/quickstart.py) | Synthetic SNTP exchange against `FakeUDPSocket` — host-runnable, no network. |
| [`examples/circuitpython_ntp_query.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/ntp/examples/circuitpython_ntp_query.py) | Real query against `pool.ntp.org` from a CircuitPython board. |

## What's new

*No changes yet — this section will be updated with each release.*

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/ntp) · \
[PyPI](https://pypi.org/project/chumicro-ntp/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
