# Workstream: streaming-transport execute

Status: **proposed.** Surfaced 2026-05-24 when [Decision 0085](../decisions/0085-board-to-host-sync-stdout-markers.md) needed line-by-line stdout to dispatch sync markers to host fixtures, but `TransportProtocol.execute(bootstrap) -> str` is request/response — the board runs to completion, then the host receives the full captured stdout in one shot.

## Problem

The stdout-marker sync protocol named by Decision 0085 requires the host to react to a marker line *while the board is still running*. The current transport buffers all stdout and returns it after `execute` completes; a marker line printed mid-test is invisible to the host until execution is over. That defeats the entire shape Decision 0083 specifies for Category 1 server-side tests.

Underneath, both transports already read line-by-line: mpremote streams subprocess stdout incrementally and pyserial reads byte-by-byte. The sync interface is buffering a natural stream and returning at end. Adding an `on_line` callback to `execute` lifts a capability that already exists in the implementation, just hidden behind the synchronous return.

## Consumers (named, not hypothetical)

- **`http_server/test_real_serve.py`** — board runs the server, host fires the client request. Today's self-loopback variant fails on Pi Pico W (lwIP short-circuits the board's own packets). Blocked here.
- **`mqtt/test_real_broker.py` inbound-delivery coverage** — today's test does publish-then-subscribe loopback on the board (board sends → broker → board receives). The *external-publish* path (a second MQTT client on the host publishes; the board's subscriber receives) is currently untested. With streaming + a host-fixture publisher callback, the board prints `SUBSCRIBED topic=...` and the host fires the publish — the inbound delivery path gets actual coverage.
- **Long-running bake output** — the mqtt bake harness today goes silent for minutes between heartbeats. The streaming hook unlocks `chumicro-workspace tail` showing board output as it lands instead of after-the-fact.
- **Future websockets server tests** — same shape as http_server; reuses the substrate.
- **Future Category 3 (two-board) orchestration** — needs cross-board sync mid-execution, builds on this primitive.

The pattern under all of these is the same: "test code on the board reaches a checkpoint and needs the host to do something before it can continue." A registered-callback model on the host side, signalled by a marker on the board's stdout, is the generic shape.

## Decision space

A streaming-capable `execute` is one of:

1. **New optional parameter on existing `execute`**: `execute(bootstrap, on_line=None) -> str`. When `on_line` is `None`, behaviour is identical to today. When passed, each line is dispatched as it arrives. Backwards-compatible.
2. **New sibling method**: `execute_streaming(bootstrap, on_line) -> str`. Avoids changing the existing signature; surface area splits.
3. **Generator interface**: `execute(bootstrap) -> Iterator[str]`. Breaking change; the test_runner layer rewrites entirely.

Option 1 keeps the existing call sites unchanged and lets the new dispatch path live next to the old. Recommended unless a constraint surfaces during implementation.

## Implementation phases

### Phase 1 — Add `on_line` to `TransportProtocol.execute`

Update `workbench/deploy/src/chumicro_deploy/protocol.py:TransportProtocol.execute` signature: `execute(bootstrap, on_line: Callable[[str], None] | None = None) -> str`. Same for `execute_scripts` on `ExtendedTransportProtocol`. Implementations in `mpremote_transport.py`, `circuitpython_transport.py`, and `testing.py` (the FakeTransport) honour the new parameter.

For the FakeTransport, `on_line` fires per line of the pre-configured stdout stream so unit tests for marker dispatch can exercise the path without a real board.

Coverage: per-transport unit test that feeds known stdout and asserts `on_line` got called per line in order.

### Phase 2 — Wire `chumicro_pytest_device` stdout dispatcher

New `chumicro_pytest_device.markers` submodule. Owns:

- A `MarkerQueue` (thread-safe queue.Queue) the test_runner pushes parsed markers into.
- A `parse_marker(line) -> Marker | None` helper that recognises `<NAME> key=value ...` lines (per Decision 0085's syntax) and ignores everything else.
- A `wait_for(name, timeout_s) -> Marker` primitive for host fixtures.

`chumicro_pytest_device.test_runner.execute_device_bootstrap` (around line 292) gains an `on_line` callback that calls `parse_marker` for each line and pushes matches onto the active marker queue. The full string return shape stays — the existing result-parser code keeps working unchanged.

Coverage: tests that exercise `MarkerQueue.wait_for` with concurrent producers (the stdout dispatcher thread) and consumers (the fixture call).

### Phase 3 — `chumicro_pytest_device.fixtures.http_client_against_board`

First inhabitant of the `fixtures/` directory named by Decision 0083. A pytest fixture that returns a callable; the callable blocks on `markers.wait_for("SERVER_READY")`, then opens a stdlib `http.client.HTTPConnection` to the marker's `ip:port`, fires the request, returns the response. Tests register the fixture in their function signature; the fixture handles teardown.

### Phase 4 — Rewrite `libraries/http_server/functional_tests/test_real_serve.py`

Drop `chumicro_requests` + `chumicro_requests.sockets_factory` imports. Board side: bring wifi up via the harness, start `HttpServer`, print `SERVER_READY ip=<ip> port=<port>` after `server.handle()` returns from accept-loop init, loop ticking the server until a route handler fires or the deadline expires, print `SERVER_REQUEST_OBSERVED route=<path>` from inside the handler, assert on the locally-observed request, exit. Host side: the `http_client_against_board` fixture from Phase 3.

Bake-validation: deploy + run against a Pi Pico W (CP + MP) + ESP32-S2 (CP + MP). Expect the host driver's response and the board's locally-asserted request to round-trip.

### Phase 5 — Live bake-output downstream win

The streaming hook unlocks live stdout for long-running deploys outside the test harness too (the mqtt bake harness today goes silent for minutes between heartbeats). Out of scope for this workstream but worth queuing once Phase 1 lands — the streaming dispatcher in `chumicro-workspace tail` and the bake harness can both consume the same `on_line` callback shape.

## Validation history

<!-- One line per phase as it lands. Format: `- **YYYY-MM-DD** Phase N. <short summary> + commit hash.` -->

- **2026-05-24** Phase 1. `TransportProtocol.execute` + `ExtendedTransportProtocol.execute_scripts` gain `on_line: Callable[[str], None] | None` parameter; cp `_read_until` gains `on_chunk` hook plumbing the `StreamingLineDispatcher` (skip `OK` prefix, stop at `\x04`); mp wires mpremote's native `data_consumer`; `FakeTransport` mirrors the shape. 19 new unit tests; preflight green at coverage 94 across CPython + MP + CP runtimes.

## Out of scope

- Reworking the marker syntax Decision 0085 established. The protocol is fixed; this workstream lands the substrate that runs it.
- A separate stdout channel (UART2, named pipe). Decision 0085 rejected those.
- Live-output integration in `chumicro-workspace tail` / bake harness. Phase 5 is a placeholder, not a deliverable here.

## Pointers

- [Decision 0085](../decisions/0085-board-to-host-sync-stdout-markers.md) — the marker protocol this workstream implements the substrate for.
- [Decision 0083](../decisions/0083-functional-test-endpoint-taxonomy.md) — names the Category 1 host-driver shape that depends on this substrate.
- [Decision 0027](../decisions/0027-device-testing-infrastructure.md) — the existing transport / result-parser layer this extends.
- [`workstreams/test-harness-promotion-and-network-helper.md`](test-harness-promotion-and-network-helper.md) — Phase 2 of that workstream is blocked on this one for the `http_server/test_real_serve.py` rewrite.
