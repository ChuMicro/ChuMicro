# Decision 0031: `chumicro-sockets` — thin protocol + per-runtime adapters

Status: `accepted`
Date: `2026-04-21`
Summary: `chumicro-sockets` is a thin protocol + per-runtime adapters behind one `connector()` entry (Decision 0098); `recv_into()` only, no `recv()` (CP idiom).
Related: Decision 0029 (project workspace), Decision 0042 (library dependency policy), Decision 0043 (UDP), Decision 0040 (requests), Decision 0041 (http_server), Decision 0045 (websockets)

## Context

`chumicro-mqtt` (Phase 6 of `plans/workstreams/archive/project-workspace.md`) and a future `chumicro-requests` HTTP client both need portable TCP sockets with non-blocking semantics and optional TLS.  Source-level research confirmed the runtimes diverge in ways a library cannot paper over implicitly:

- **CircuitPython** has no raw `socket` module.  Sockets come from `socketpool.SocketPool(radio)`.  **CircuitPython has no `recv()`** — only `recv_into()`.  There is no `ssl` module; TLS is delivered via a radio-specific `TLS_MODE` flag, typically abstracted by `adafruit_connection_manager`.
- **MicroPython** exposes stdlib-style `import socket`.  `recv()` and `recv_into()` both available on most ports.  TLS: `ssl` module present on both ESP32 and Pi Pico W builds — `MICROPY_SSL_MBEDTLS=1` + `MICROPY_PY_SSL=1` are set in `ports/rp2/mpconfigport.h` (confirmed in MP 1.26.0).  Older builds (~MP 1.21 era) lacked mbedTLS on Pico W, which is where the "no TLS on Pico W" folklore came from; current-LTS and newer builds have it.
- **CPython** has stdlib `socket` and stdlib `ssl` with full feature coverage.

`adafruit_connection_manager` solves the CP side of this neatly and is the reason `adafruit_minimqtt` + `adafruit_requests` are portable across CP radios — but it is **CP-only**, which is precisely the wall the pythonProject3 MQTT client hit when we needed MicroPython support.

Non-blocking error semantics converge: `OSError(errno=11)` (`EAGAIN`) on would-block across all three runtimes.  `select.poll()` works correctly on all three for **client-side connected sockets** — CP and MP share `extmod/modselect.c`.  A quirk has been reported on listening sockets waiting for `accept()` (spurious `POLLIN`); MQTT and HTTP clients are connected-socket users only and are not affected.

## Decisions

### 1. `chumicro-sockets` is built; it is the base for `chumicro-mqtt` and future `chumicro-requests`

A new library under `libraries/sockets/`.  Sits below any library that talks TCP to a remote server.  Ships `TCPClientSocket` as the portable surface and per-runtime implementations behind it.

### 2. Architecture: thin protocol + runtime-specific adapters

```
chumicro_sockets/
  __init__.py           # tcp_client_socket() factory, TCPClientSocket protocol
  _adapters/
    cp.py               # CircuitPythonTCPSocket  (socketpool + radio.TLS_MODE)
    mp.py               # MicroPythonTCPSocket    (socket + ssl module; substrate-aware: ESP-IDF vs CYW43)
    cpython.py          # CPythonTCPSocket        (socket + ssl stdlib)
  testing.py            # FakeSocket for unit tests
```

Adapter selection via `sys.implementation.name` + board probe, wrapped in one connect entry — non-blocking and tick-driven ([Decision 0081](0081-non-blocking-connect-via-tick-driven-connector.md)); the connect surface itself is [Decision 0098](0098-sockets-connect-collapse.md)'s:

```python
# The one connect state machine — returns a tick-driven SocketConnector.
# Runner-shaped libraries register/drive it; one-shot scripts drive it
# to terminal inline.
connector(host, port, *, tls=False, context=None, radio=None) -> SocketConnector
```

**Protocol surface** (minimum that downstream libs touch):

- `send(data: bytes | memoryview) -> int`
- `recv_into(buffer: bytearray | memoryview, nbytes: int | None = None) -> int`
- `close() -> None`
- `setblocking(flag: bool) -> None`
- `settimeout(seconds: float | None) -> None`

Connector behaviour: the entry returns immediately with a `SocketConnector` whose `tick(now_ms)` advances DNS → TCP → TLS one phase per tick.  See [Decision 0081](0081-non-blocking-connect-via-tick-driven-connector.md) for the connector contract, the per-runtime substrate caveats (CP blocks per phase; MP+CPython are truly non-blocking), and the sanctioned one-shot forms.

No `recv()`.  Downstream code allocates its own buffer and uses `recv_into()` — the CP-compatible idiom.  MP + CPython adapters implement `recv_into()` using stdlib `sock.recv_into()` directly.  Older MP ports without `recv_into` fall back to `recv()` + memcpy internally.

**Rejected alternative (b):** "A copy of CP's `socketpool` shape with MP/CPython adapters."  Rejected because `socketpool.SocketPool(radio)` ceremony is CP-specific; forcing every other runtime to fake a radio object is overhead for no gain.

**Rejected alternative (c):** "A lower-level byte-stream abstraction that hides 'is this a socket' entirely."  Rejected because MQTT and HTTP care about connect-shutdown-reconnect lifecycle, not just byte streams; hiding the socket boundary hides bugs.

### 3. TLS parameterization

Superseded — see [Decision 0098](0098-sockets-connect-collapse.md) §1: TLS is a `tls=` flag plus a separately injected `context=<ssl.SSLContext>` on the single `connector()` entry.  (The shape this section originally rejected — one 3-types-in-1 `ssl=False|True|context` argument — remains rejected; the settled form keeps the boolean and the dependency as two parameters.)

A helper `ssl_context_with_ca(ca_pem: bytes) -> ssl.SSLContext` is provided for the common "custom CA + default everything else" path on every runtime.

**Rejected:** separate post-connect `wrap_socket()` step.  Works on CPython and MP-ESP32, breaks on CP radios and pre-mbedTLS MP builds where TLS must be declared at connect time.  Non-starter.

### 4. `FakeSocket` ships in `testing.py`

Testability across 94 % coverage requires injectable sockets.  `chumicro_sockets.testing.FakeSocket` implements the full `TCPClientSocket` protocol against an in-memory bytearray pair (one for `sent`, one for `recv_buffer`).  Assertions on sent bytes, scripted recv sequences, scripted `EAGAIN` injection for non-blocking testing.

Shipped with the library (not in a separate `-testing` package) so downstream libs can `from chumicro_sockets.testing import FakeSocket` without extra deps.  Mirrors the Decision 0010 pattern (testing submodules in every library).

### 5. Don't depend on `adafruit_connection_manager`; borrow ideas in-adapter

`adafruit_connection_manager` (ACM) is the mature CP-only answer for socketpool + radio TLS.  The chumicro-sockets CP adapter **reimplements the small well-understood patterns in-tree** rather than taking ACM as a runtime dependency.

Reasons:

- ACM is CP-only.  Requiring it would make CP builds carry an extra `circup install` step while MP builds do not — asymmetric footprint for a cross-runtime library.
- The CP surface ACM covers (roughly 100 lines: `SocketPool(radio)` memoization, `TLS_MODE`-flag TLS fake-context wrapping) is small, well-understood, and reimplements cleanly.
- Adafruit's release cadence should not dictate chumicro's.
- ACM's module-level singleton `get_connection_manager()` conflicts with chumicro's constructor-injection policy (Decision 0010).  Our factories take explicit `radio=` args.

Ideas borrowed from reading ACM source, reimplemented in the CP adapter:

1. **Stdlib-shaped `SSLContext` fake** — mimics `ssl.SSLContext` API on CP radios so downstream code written against stdlib shapes Just Works.  Our `ssl_context_with_ca()` helper follows this pattern (ACM's `_FakeSSLContext`).
2. **Radio → SocketPool memoization** — module-level cache keyed by radio id, one pool per radio, prevents reinit on every connect.
3. **Explicit close-on-shutdown tracking** — weakly-held set of open sockets, close all at adapter teardown so CP's late-GC doesn't leak sockets across soft-resets.
4. **CP-specific error translation** — normalize socketpool errors into stdlib-shaped `ConnectionError` / `TimeoutError` subclasses so downstream code (`chumicro-mqtt`, future `chumicro-requests`) has one error shape across runtimes.

Ideas **not** borrowed:

- Module-level singleton access (`get_connection_manager()`) — hidden state, conflicts with DI.
- Broad cross-caller connection reuse/pooling — downstream-lib concern.  MQTT never reuses; a future HTTP lib may add its own pooling layer.
- Per-host CA cert dict — ACM has deprecated this; `ssl_context_with_ca()` covers the common case more cleanly.

**Rejected:** take ACM as a CP-side runtime dependency.  Asymmetric cross-runtime footprint and release-cadence coupling outweigh the re-implementation cost.

### 6. No SSL certificate validation enforcement in the library

Adapters default to "trust the system's default CA bundle" on CPython / MP-ESP32 and "radio default" on CP / MP Pico W.  Users who need custom validation pass a pre-configured context (where supported).  The library does not attempt to bundle or enforce a CA policy — out of scope, varies by deployment.

**Rejected:** bundling a Mozilla CA bundle.  Adds tens of KB on constrained devices and creates a maintenance burden for security updates.

## Consequences

- `chumicro-sockets` lands as Phase 5 of the project-workspace workstream, before `chumicro-mqtt` (Phase 6).  Current Phase 5 ("`chumicro-mqtt` refactor + first sensor template") splits to accommodate.
- Library count in Decision 0029 goes from five to six new libraries; Decision 0029 §1 consequences and the workstream Scope list updated accordingly.
- `chumicro-mqtt` depends on `chumicro-sockets` and does not import `socketpool`, `socket`, or `ssl` directly.
- A future `chumicro-requests` library (not in this workstream) will also depend on `chumicro-sockets`.  Designing the protocol now with both consumers in mind keeps the surface minimal.
- The pythonProject3 MQTT client's dependency on `adafruit_connection_manager` is replaced at refactor time by `chumicro-sockets`.
- Documentation: `libraries/sockets/docs/` explains why this library exists (CP/MP/CPython divergence with concrete examples) and how it compares to `adafruit_connection_manager` (CP-only subset) and `umqtt.simple`'s raw-socket pattern (MP-only).
- No functional-device tests required for the sockets library itself — behavior is covered by the MQTT and requests libraries that consume it, and by host-side `FakeSocket` unit tests on all three runtimes via the existing cross-runtime harness.
- This charter is TCP/TLS only.  UDP was added to the library after the fact — the `UDPSocket` protocol, `udp_socket()` factory, and `FakeUDPSocket` extension are recorded in [Decision 0043](0043-chumicro-sockets-udp.md), which extends this one rather than replacing it.
