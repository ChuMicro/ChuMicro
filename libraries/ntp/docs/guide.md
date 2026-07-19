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
object satisfying the duck-typed UDP contract below (`sendto` /
`recvfrom_into` / `close` / `setblocking`).  Tests inject
`FakeUDPSocket` from `chumicro_sockets.testing`; apps inject a real
socket directly from `chumicro_sockets.udp_socket`.

A few notes on dependencies:

- `chumicro-sockets` is a hard dependency — `pip install chumicro-ntp` brings the whole stack.
- `NTPClient.from_config` builds the default UDP wiring through the shared `chumicro_sockets.sockets_factory` module, imported lazily.  Apps that supply their own UDP socket never trigger that import, so `chumicro-sockets` doesn't get deployed to the device for those apps.
- No `chumicro-logging` dep.  The library exposes no callbacks — the result handle returned by `query()` is the observation surface.

## Getting started

```python
from chumicro_ntp import NTPClient
from chumicro_sockets import udp_socket
from chumicro_timing import ticks_ms

sock = udp_socket(radio=wifi.adapter.radio)
sock.setblocking(False)

client = NTPClient(socket=sock, server="pool.ntp.org")
request = client.query()

while not request.done:
    now = ticks_ms()
    if client.check(now):
        client.handle(now)

if request.error is not None:
    print(f"NTP failed: {request.error}")
else:
    print(f"unix seconds: {request.unix_seconds}")

sock.close()
```

`request.unix_seconds` is the server's transmit-timestamp converted
to Unix-epoch seconds — feed it into `time.gmtime` (CPython) /
`utime.localtime` (MP/CP) for date components.

## Bring your own transport

`NTPClient` doesn't care which library produces its UDP socket.  The `socket=` (or `transport_factory=`) you pass returns any object exposing the four-method UDP contract:

| Method | Contract |
|---|---|
| `sendto(payload, host, port) -> int` | Sends `payload` (a `bytes`) to `(host, port)` as separate args.  Raises `OSError(EAGAIN \| EWOULDBLOCK)` when the send buffer is full. |
| `recvfrom_into(buffer) -> (nbytes, address)` | Reads into `buffer`, returning the byte count and sender.  Raises `OSError(EAGAIN \| EWOULDBLOCK)` on no data. |
| `close() -> None` | Releases the socket. |
| `setblocking(flag) -> None` | Best-effort.  Absence is tolerated. |

`chumicro_sockets.udp_socket` is the built-in producer; `chumicro_sockets.testing.FakeUDPSocket` is the test double.  A raw stdlib `socket.socket(AF_INET, SOCK_DGRAM)` does **not** fit directly — its `sendto` takes `(data, address)`, not the separated `(data, host, port)` this contract calls — so wrap it in a small adapter if you must:

```python
import socket as stdlib_socket

class _StdlibUdpAdapter:
    def __init__(self, sock):
        self._sock = sock
    def sendto(self, payload, host, port):
        return self._sock.sendto(payload, (host, port))
    def recvfrom_into(self, buffer):
        return self._sock.recvfrom_into(buffer)
    def close(self):
        self._sock.close()
    def setblocking(self, flag):
        self._sock.setblocking(flag)

raw = stdlib_socket.socket(stdlib_socket.AF_INET, stdlib_socket.SOCK_DGRAM)
raw.setblocking(False)
client = NTPClient(socket=_StdlibUdpAdapter(raw), server="my.lan.ntp")
```

If you supply your own transport and want `chumicro_sockets` dropped from the deploy entirely, add a module-level constant to your entrypoint and the chumicro-workspace deployer will filter the default factory out of the import graph:

```python
# code.py / app.py
__chumicro_skip_factories__ = ("sockets_factory",)
```

Family form (the bare stem) or exact path (`"chumicro_sockets.sockets_factory"`).  An unmatched entry fails the deploy with a typo message rather than silently shipping the default.  Calling `NTPClient.from_config(...)` when `chumicro_sockets.sockets_factory` is missing — either skipped at deploy time or not installed by `circup` / `mip` — raises `RuntimeError` naming the bypass kwargs.

For the full single-library adoption recipe — your transport, your `ticks=`, the runner-less drive loop, and host tests with no board — see [Standalone integration](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/standalone-integration.md).

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
in `__init__` so `handle` doesn't allocate on the hot path.  The
client request is a 48-byte module-level `bytes` constant, sent
directly each `query()` — no per-call packet construction.  The
parse step reads through a `memoryview` window into the recv
buffer, so the success path doesn't copy bytes either.

`NTPResult` is a tiny holder — a handful of integer / object fields.

## Platform notes

Runs identically on CPython, MicroPython, and CircuitPython.  The default tick source is the `chumicro_timing.ticks` submodule — an object that exposes `ticks_ms` / `ticks_diff` / `ticks_add`, each picking the right underlying primitive per runtime (`supervisor.ticks_ms` on CircuitPython, `time.ticks_ms` on MicroPython, `time.monotonic_ns` on CPython).  Inject a custom source via the `ticks=` constructor kwarg if you have your own — must expose those same three names.  All UDP work goes through the injected socket, so `chumicro-sockets` hides the per-runtime adapter chase.

Tested on real CircuitPython and MicroPython boards with live `pool.ntp.org` queries before each release; returned timestamps validated against a 2024-2030 plausibility window.

## Failure modes

`NTPResult.error` carries the failure when the exchange ends badly:

| Cause | Exception |
|---|---|
| `sendto` failed (kernel rejected, address invalid) | `OSError` (raw, not wrapped) |
| Recv timeout (`timeout_ms` elapsed without data) | `NTPError("SNTP query timed out after N ms")` |
| Short response (< 48 bytes) | `NTPError("short SNTP response (N bytes)")` |
| Wrong mode in the response | `NTPError("unexpected SNTP mode N")` |
| Stratum-0 kiss-of-death | `NTPError("SNTP kiss-of-death (stratum=0)")` |
| Canceled via `client.cancel()` | `NTPError("canceled")` |
| Socket recv failed (non-EAGAIN OSError) | `OSError` (raw, not wrapped) |

`NTPError` is an `OSError` subclass so handlers that do
`except OSError` catch both wrapped and unwrapped failures.

## Examples

| Example | What it shows |
|---|---|
| [`examples/ntp_query.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/ntp/examples/ntp_query.py) | Real query against `pool.ntp.org` from a wifi-capable board (CircuitPython or MicroPython). |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/ntp) · \
[PyPI](https://pypi.org/project/chumicro-ntp/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
