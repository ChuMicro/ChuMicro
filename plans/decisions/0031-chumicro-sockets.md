# Decision 0031: `chumicro-sockets` — thin protocol + per-runtime adapters

Status: `proposed`
Date: `2026-04-21`
Related: Decision 0029

## Context

`chumicro-mqtt` (Phase 6 of `plans/workstreams/project-workspace.md`) and a future `chumicro-requests` HTTP client both need portable TCP sockets with non-blocking semantics and optional TLS.  Source-level research confirmed the runtimes diverge in ways a library cannot paper over implicitly:

- **CircuitPython** has no raw `socket` module.  Sockets come from `socketpool.SocketPool(radio)`.  **CircuitPython has no `recv()`** — only `recv_into()`.  There is no `ssl` module; TLS is delivered via a radio-specific `TLS_MODE` flag, typically abstracted by `adafruit_connection_manager`.
- **MicroPython** exposes stdlib-style `import socket`.  `recv()` and `recv_into()` both available on most ports.  TLS: `ssl` module present on ESP32-family builds, **absent on Pi Pico W (CYW43)** where TLS requires a radio-specific wrapper or third-party lib.
- **CPython** has stdlib `socket` and stdlib `ssl` with full feature coverage.

`adafruit_connection_manager` solves the CP side of this neatly and is the reason `adafruit_minimqtt` + `adafruit_requests` are portable across CP radios — but it is **CP-only**, which is precisely the wall the pythonProject3 MQTT client hit when we needed MicroPython support.

Non-blocking error semantics converge: `OSError(errno=11)` (`EAGAIN`) on would-block across all three runtimes.  `select.poll()` works on all three, with a documented CP quirk on listening sockets (non-issue for client-side use).

## Decisions

### 1. `chumicro-sockets` is built; it is the base for `chumicro-mqtt` and future `chumicro-requests`

A new library under `libraries/sockets/`.  Sits below any library that talks TCP to a remote server.  Ships `TCPClientSocket` as the portable surface and per-runtime implementations behind it.

### 2. Architecture: thin protocol + runtime-specific adapters

```
chumicro_sockets/
  __init__.py           # tcp_client_socket() factory, TCPClientSocket protocol
  _adapters/
    cp.py               # CircuitPythonTCPSocket  (socketpool + radio.TLS_MODE)
    mp_esp32.py         # MicroPythonTCPSocket    (socket + ssl module)
    mp_rp2.py           # MicroPythonRP2TCPSocket (socket + radio TLS fallback)
    cpython.py          # CPythonTCPSocket        (socket + ssl stdlib)
  testing.py            # FakeSocket for unit tests
```

Adapter selection via `sys.implementation.name` + board probe, wrapped in `tcp_client_socket(host, port, ssl=False, radio=None)`.

**Protocol surface** (minimum that downstream libs touch):

- `connect(host: str, port: int, ssl: bool = False) -> None`
- `send(data: bytes | memoryview) -> int`
- `recv_into(buffer: bytearray | memoryview, nbytes: int | None = None) -> int`
- `close() -> None`
- `setblocking(flag: bool) -> None`
- `settimeout(seconds: float | None) -> None`
- `fileno() -> int` (for `select.poll()` registration)

No `recv()`.  Downstream code allocates its own buffer and uses `recv_into()` — the CP-compatible idiom.  MP + CPython adapters implement `recv_into()` using stdlib `sock.recv_into()` directly.  Older MP ports without `recv_into` fall back to `recv()` + memcpy internally.

**Rejected alternative (b):** "A copy of CP's `socketpool` shape with MP/CPython adapters."  Rejected because `socketpool.SocketPool(radio)` ceremony is CP-specific; forcing every other runtime to fake a radio object is overhead for no gain.

**Rejected alternative (c):** "A lower-level byte-stream abstraction that hides 'is this a socket' entirely."  Rejected because MQTT and HTTP care about connect-shutdown-reconnect lifecycle, not just byte streams; hiding the socket boundary hides bugs.

### 3. TLS is a first-class parameter, not a separate wrap step

`connect(host, port, ssl=True)` rather than `connect(host, port)` followed by `ssl_context.wrap_socket(sock)`.  Reasoning:

- CP radios require TLS mode passed to `connect()` — wrapping afterwards is not supported.
- MP on Pico W has no `ssl` module — TLS must be delivered via the radio at connect time.
- Keeping TLS as a connect-time flag lets each adapter route it correctly.

Users who need `ssl.SSLContext`-style advanced config pass a context object as `ssl=context`; adapters that support it (CPython, MP on ESP32) use it; adapters that don't (CP radios, MP Pico W) raise `UnsupportedSSLConfigError` with a clear message.

**Rejected:** separate `wrap_socket()` step.  Works on CPython and MP-ESP32, breaks on CP and MP Pico W.  Non-starter.

### 4. `FakeSocket` ships in `testing.py`

Testability across 94 % coverage requires injectable sockets.  `chumicro_sockets.testing.FakeSocket` implements the full `TCPClientSocket` protocol against an in-memory bytearray pair (one for `sent`, one for `recv_buffer`).  Assertions on sent bytes, scripted recv sequences, scripted `EAGAIN` injection for non-blocking testing.

Shipped with the library (not in a separate `-testing` package) so downstream libs can `from chumicro_sockets.testing import FakeSocket` without extra deps.  Mirrors the Decision 0010 pattern (testing submodules in every library).

### 5. No SSL certificate validation enforcement in the library

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
