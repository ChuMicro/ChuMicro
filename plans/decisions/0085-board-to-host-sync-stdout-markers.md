# Decision 0085: Board-to-host sync via stdout markers for Category 1 server-side functional tests

Status: `accepted`
Date: `2026-05-24`
Summary: Category 1 server-side tests sync board and host via stdout markers (`SERVER_READY ip=X port=N`); `chumicro_pytest_device` parses and dispatches to host fixtures.
Related: Decision [0027](0027-device-testing-infrastructure.md) (the result-parser layer that already reads `PASS` / `FAIL` / `SKIP` / `SUMMARY` / `HEAP` markers off board stdout), Decision [0083](0083-functional-test-endpoint-taxonomy.md) (Category 1 host-driver-as-client shape for server-side tests + the fixture home at `workbench/pytest-device/src/chumicro_pytest_device/fixtures/`), Decision [0058](0058-test-skips-must-be-loud.md) (skip semantics when the host driver can't reach the board).

## Context

Decision 0083 names host-driver-as-client as the Category 1 shape for server-side libraries (`http_server`, future `websockets` server tests). The board runs the server; the host runs a stdlib client. That shape needs a coordination primitive the host doesn't have today: the host fixture has to wait until the board's server is listening, learn its address, fire the request, and let the board test know the request landed.

Three constraints shape the design. (1) The host fixture evaluates *before* the device deploys + executes, so it can't synchronously read stdout that doesn't exist yet — the coordination has to be asynchronous from the fixture's view. (2) Decision 0027 already reads structured `<NAME>: ...` markers off board stdout via `chumicro_pytest_device.result_parser`; a second marker channel would duplicate plumbing. (3) The board side can't depend on the host's IP or port being known up front — DHCP, ephemeral ports, multiple board mounts all mean the test should be free to print the address it actually bound.

## Decision

**Category 1 server-side functional tests coordinate board and host through newline-delimited stdout markers. The board prints `SERVER_READY ip=<ip> port=<port>` once its listener is accepting; the host fixture registers a callback that `chumicro_pytest_device` invokes when a matching line lands.**

### Marker syntax

One marker per line, at the start of the line, format `<MARKER_NAME> key=value key=value ...`. Keys are ASCII identifiers (`[a-z_][a-z0-9_]*`); values are URL-safe (no spaces, no `=`). Mixed-case marker names; the parser splits on the first space and treats anything after as `key=value` pairs.

Example: `SERVER_READY ip=192.168.1.50 port=8765`.

### Defined markers (initial set)

- **`SERVER_READY ip=<ip> port=<port>`** — board's listener is accepting connections. Printed once, after the first `server.handle(ticks_ms())` returns from accept-loop init. The host fixture's callback fires; the driver issues its request.
- **`SERVER_REQUEST_OBSERVED route=<path>`** — board's route handler ran. Printed inside the handler. Lets the board test break its loop deterministically without polling a shared list.

Additional markers extend this enum (commit + ADR appendix) as new server-side libraries land.

### Marker discipline

- Markers are protocol output, not test output. Test prose (`WIFI_OK ip=...`, `GOT 200 bytes=...`) stays lowercased / mixed-form and is not consumed by the parser. The parser only matches lines whose first word is uppercase and in the defined enum.
- A marker is printed *after* its contract is satisfied. Printing `SERVER_READY` before `server.handle()` returns the accept-bound state would race the host driver against an unready socket.
- Marker values name what they describe at that moment. `port=8765` is the actually-bound port (board chose it or got it from `_LISTEN_PORT`); the host doesn't assume.

### Host-fixture shape

The fixture lives at `workbench/pytest-device/src/chumicro_pytest_device/fixtures/` (per Decision 0083). Pattern:

```python
@pytest.fixture
def http_client_against_board(device_stdout_markers):
    def hit(path, *, timeout_s=10):
        # Blocks waiting for the next SERVER_READY marker, then opens
        # a stdlib HTTP connection to ip:port and returns the response.
        marker = device_stdout_markers.wait_for("SERVER_READY", timeout_s=timeout_s)
        ...
    return hit
```

`device_stdout_markers` is a new chumicro_pytest_device fixture exposing a thread-safe queue of parsed markers. The backend's stdout-reader pushes each parsed marker onto the queue; host fixtures pop via `wait_for(name, timeout_s)`.

Tests that need no host driver (Mosquitto-fixture mqtt, UDP-echo sockets) ignore the marker channel — the existing per-library `conftest.py` fixture flow stays intact.

### When the marker never arrives

The host fixture's `wait_for(name, timeout_s)` raises `TimeoutError` on the host side. The board side handles the same case independently: its test loop has its own deadline (already standard practice) and raises `AssertionError`. Both sides surfacing the failure independently is the right shape — neither is the source of truth for the other's liveness.

## Rejected

- **Sync via filesystem marker on the board.** Host has no filesystem access during a CP RAM-mode run and only mediated access in flash mode; not viable cross-runtime.
- **Sync via an out-of-band MQTT broker or sentinel topic.** Drags an external broker dependency into every server-side test for what is a single-line primitive. Cross-test interference if any two boards target the same sentinel topic.
- **Hardcode a known port + discover the IP from the device backend.** The backend knows the serial address, not the board's wifi IP. The board still has to print its IP somehow, which is the same channel — punting the marker design accomplishes nothing.
- **Block the host fixture on `subprocess.PIPE.readline()` synchronously inside the fixture body.** Pytest fixture evaluation happens *before* the device backend runs; there is no stdout to read yet. A callback-on-arrival model is the only correct shape.
- **A second log channel (UART2, named pipe, side socket).** Real boards mostly have one serial line out. Reusing the existing stdout stream is the only path that doesn't require additional hardware-side wiring.

## Substrate prerequisite

The protocol assumes the host receives board stdout incrementally — the `wait_for(name, timeout_s)` primitive blocks until a matching line arrives, which only works if lines arrive one at a time. `TransportProtocol.execute(bootstrap) -> str` today is request/response: the board runs the bootstrap to completion, then the host receives the full captured stdout. Implementing this ADR requires lifting that interface to streaming — an `on_line` callback on `execute`, plumbed through the mpremote subprocess and pyserial transports (both already read line-by-line internally; the current sync interface buffers and returns at end). The implementation is tracked under [`plans/workstreams/streaming-transport.md`](../workstreams/streaming-transport.md). Until that lands, this ADR's protocol is `accepted` as the design but not yet active — no Category 1 server-side test uses it.

## Consequences

- `chumicro_pytest_device.result_parser` gains a `parse_marker(line)` path that recognises the `<NAME> key=value ...` shape, in parallel to the existing `PASS` / `FAIL` / etc. parser. Backwards-compatible: a line that doesn't start with a known marker name is passed through to stdout verbatim, same as today.
- A new `chumicro_pytest_device.markers` submodule owns the marker queue + the `wait_for` primitive that host fixtures call. Thread-safe (queue.Queue under the hood); the backend's reader thread pushes, the pytest main thread waits.
- `chumicro_pytest_device.fixtures` (the directory named by Decision 0083) lands with this slice. First inhabitant: an `http_client_against_board` fixture for `http_server/test_real_serve.py`. Future server-side libraries (websockets server) reuse the pattern.
- `http_server/functional_tests/test_real_serve.py` shifts from self-loopback (board hits its own `wifi.ip:port` via `chumicro_requests`, broken by router hairpinning) to host-driver. The test imports neither `chumicro_requests` nor any HTTP client — just `chumicro_http_server` + `chumicro_test_harness.network`. The host fixture does the GET.
- The marker syntax is documented at the head of `chumicro_pytest_device.markers` so a contributor adding a new marker has one place to read the rules.
- Tests printing marker-shaped lines accidentally (a stray `print("SERVER_READY")` in normal test prose) get caught the first time the host fixture fires unexpectedly. Reviewer-visible. Acceptable failure mode; the alternative (escaped output channel) is more plumbing than the cost.
