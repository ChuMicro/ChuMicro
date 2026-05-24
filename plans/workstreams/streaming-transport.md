# Workstream: streaming-transport execute

Status: **shipped 2026-05-24.** All four phases landed in a single session. The marker-protocol substrate from [Decision 0085](../decisions/0085-board-to-host-sync-stdout-markers.md) is live; the first Category 1 host-driver test (`libraries/http_server/functional_tests/test_real_serve.py` + `test_real_serve_host.py`) consumes it. Future server-side libraries reuse the same shape.

Originally surfaced 2026-05-24 when [Decision 0085](../decisions/0085-board-to-host-sync-stdout-markers.md) needed line-by-line stdout to dispatch sync markers to host fixtures, but `TransportProtocol.execute(bootstrap) -> str` was request/response — the board ran to completion, then the host received the full captured stdout in one shot.

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

### Phase 3 — Concurrent runner + `http_client_against_board` fixture

The host fixture has to interleave with a running board bootstrap: the test body calls `hit("/")`, which blocks on `MarkerQueue.wait_for("SERVER_READY")`, then opens an HTTP connection to the marker's `ip:port`. For that overlap to exist, the board's bootstrap must run concurrently with the test body. Today's `device_backend.runtest` is synchronous on pytest's main thread, so Phase 3 lands the concurrent-execution shape underneath the fixture.

Concurrency is host-side only. The board stays single-threaded cooperative — a standard `while True: runner.tick(...)` loop on the device, printing markers and handling one TCP accept. The host runs two threads: the pytest main thread (test body + `http.client.HTTPConnection`) and a serial-read background thread (`transport.execute` + `on_line` + `MarkerQueue.push`).

Phase 3 splits into a load-bearing infrastructure slice landing here and a follow-up integration slice that waits on Phase 4's file-layout decisions:

**This slice (one commit):**

1. **`chumicro_pytest_device.concurrent_runner.DeviceBootstrapRunner`** — pure-Python, no pytest dependency. Owns the background thread, the `MarkerQueue`, the captured-stdout future. Surface: `start()` spawns the thread and wires `on_line` to push parsed markers; `wait_for(name, timeout_s)` forwards to the queue; `wait_for_completion(timeout_s)` joins the thread and returns captured stdout; `shutdown()` is idempotent and joins-if-alive. Context-manager support so test teardown reliably joins on errors.

2. **`fixtures/host_driver.py` — `http_client_against_board`** — pytest fixture returning a factory: `bind_to(runner)` returns the actual `hit(path, *, timeout_s=10)` callable. The callable calls `runner.wait_for("SERVER_READY", timeout_s=timeout_s)`, then opens `http.client.HTTPConnection(marker.values["ip"], int(marker.values["port"]), timeout=timeout_s)` and returns the response. The two-step shape lets a Phase 4 fixture or test directly hand the runner in without yet committing to *how* the runner gets created from the session.

3. **End-to-end integration test** — `FakeTransport` printing a `SERVER_READY ip=127.0.0.1 port=<n>` marker, against a real stdlib `http.server` running on the same port. Proves runner + fixture compose against real HTTP.

**Deferred to Phase 4** (depends on file-layout decisions):

- A `device_bootstrap_runner` pytest fixture that grabs the cached transport from `_TransportCache`, picks a device from the session, builds the bootstrap from a board-side file (location convention TBD: `<host_file>_board.py` sibling, an explicit marker, a discrete subdirectory), calls `runner.start()`, and teardown-feeds captured stdout into `result_parser` so board-side PASS / FAIL / SUMMARY still rejoins the existing pipeline.
- A `device_backend.runtest` dispatch fork that skips synchronous execute when a host-driver fixture is in `item.fixturenames`.
- A collection-layer rule that prevents the existing `DeviceRuntimeItem` collector from treating a host-driver test file as a device test.

**On host-side failure**, the board self-times-out (Decision 0085 specifies the board has its own deadline). The host fixture raises fast, the test fails fast on the host side, the runner joins on fixture teardown after the board exits ~10 s later. Slower than mid-exec interrupt but keeps the raw-REPL session consistent for the next test. Revisit if test-iteration speed becomes painful.

Coverage: `DeviceBootstrapRunner` unit tests against a `FakeTransport` (start + wait_for + completion happy path; wait_for_completion timeout; shutdown idempotency; context-manager exit on exception); a fixture-integration test using a fake transport that prints `SERVER_READY ip=127.0.0.1 port=<n>` and a stdlib `http.server` running in-process as the HTTP target.

**On host-side failure**, the board self-times-out (Decision 0085 specifies the board has its own deadline). The host fixture raises fast, the test fails fast on the host side, the runner joins on fixture teardown after the board exits ~10 s later. Slower than mid-exec interrupt but keeps the raw-REPL session consistent for the next test. Revisit if test-iteration speed becomes painful.

Coverage: `DeviceBootstrapRunner` unit tests against a `FakeTransport` (start + wait_for + completion happy path; wait_for_completion timeout; shutdown idempotency; context-manager exit on exception); a fixture-integration test using a fake transport that prints `SERVER_READY ip=127.0.0.1 port=<n>` and a stdlib `http.server` running in-process as the HTTP target.

### Phase 4 — Rewrite `libraries/http_server/functional_tests/test_real_serve.py`

Drop `chumicro_requests` + `chumicro_requests.sockets_factory` imports. Board side: bring wifi up via the harness, start `HttpServer`, print `SERVER_READY ip=<ip> port=<port>` after `server.handle()` returns from accept-loop init, loop ticking the server until a route handler fires or the deadline expires, print `SERVER_REQUEST_OBSERVED route=<path>` from inside the handler, assert on the locally-observed request, exit. Host side: the `http_client_against_board` fixture from Phase 3.

Bake-validation: deploy + run against a Pi Pico W (CP + MP) + ESP32-S2 (CP + MP). Expect the host driver's response and the board's locally-asserted request to round-trip.

### Phase 5 — Live bake-output downstream win

The streaming hook unlocks live stdout for long-running deploys outside the test harness too (the mqtt bake harness today goes silent for minutes between heartbeats). Out of scope for this workstream but worth queuing once Phase 1 lands — the streaming dispatcher in `chumicro-workspace tail` and the bake harness can both consume the same `on_line` callback shape.

## Validation history

<!-- One line per phase as it lands. Format: `- **YYYY-MM-DD** Phase N. <short summary> + commit hash.` -->

- **2026-05-24** Phase 1. `TransportProtocol.execute` + `ExtendedTransportProtocol.execute_scripts` gain `on_line: Callable[[str], None] | None` parameter; cp `_read_until` gains `on_chunk` hook plumbing the `StreamingLineDispatcher` (skip `OK` prefix, stop at `\x04`); mp wires mpremote's native `data_consumer`; `FakeTransport` mirrors the shape. 19 new unit tests; preflight green at coverage 94 across CPython + MP + CP runtimes.
- **2026-05-24** Phase 2. New `chumicro_pytest_device.markers` submodule — `Marker` dataclass, `parse_marker(line) -> Marker | None` (rejects the result-parser reserved set `{PASS, FAIL, SKIP, SUMMARY, HEAP}` — `SUMMARY total=N failed=N time=N.Ns` collides with the marker shape exactly, so the reserved-name filter is load-bearing, not belt-and-suspenders), `MarkerQueue.wait_for(name, timeout_s)` blocking primitive with thread-safe push. `execute_device_bootstrap` gains a `marker_queue` kwarg that builds the `on_line` closure internally; default `None` keeps the existing call shape. 26 new unit tests including a concurrent producer (background thread) + consumer pair. Preflight green at coverage 94.
- **2026-05-24** Phase 3 (infra slice). New `chumicro_pytest_device.concurrent_runner.DeviceBootstrapRunner` — daemon-thread wrapper around `transport.execute(bootstrap, on_line=...)` with `start` / `wait_for` / `wait_for_completion` / `shutdown` and context-manager support. Re-raises bg-thread transport errors on the main thread; routes list bootstraps to `execute_scripts` for CP RAM mode. New `chumicro_pytest_device.fixtures.host_driver` — `bind_to(runner) -> hit(...)` plain function plus the `http_client_against_board` fixture wrapping it; returns an `HttpResponseSnapshot` (status / reason / headers / body) after closing the underlying connection so callers carry no socket lifetime. 16 new tests including an end-to-end integration that drives a stdlib `http.server.HTTPServer` on 127.0.0.1 with a `FakeTransport`-printed marker — proves the runner + fixture + dispatcher chain composes against real TCP, not just fakes. Preflight green. Phase 3 follow-up (the `device_bootstrap_runner` session-cache fixture + `device_backend.runtest` dispatch fork + collection-layer host-vs-device file rule) waits on Phase 4's file-layout decisions.
- **2026-05-24** Phase 4 (4a + 4b in one commit). File-layout convention: host file `test_real_<scenario>_host.py` with `__chumicro_host_only__ = True` paired with sibling board file `test_real_<scenario>.py` via strip-suffix rule, optional `@pytest.mark.device_bootstrap("<file>")` override. Collection-layer change: `pytest_collect_file` + `pytest_pycollect_makemodule` return `None` for host-only functional-test files so pytest's default Module factory collects them as ordinary CPython tests (the board file still routes through `DeviceTestFile` as today). `device_bootstrap_runner` fixture in `fixtures/host_driver.py` resolves the board file, picks the active device (first registered target or `_load_fallback_device`), stages the library + board file via `transport.stage`, builds the bootstrap, starts the runner. Teardown joins with a 60 s timeout + idempotent shutdown. `device_bootstrap` marker registered in `pytest_configure` (required under `--strict-markers`). Sub-plugin registration via `pytest_plugins = ("chumicro_pytest_device.fixtures.host_driver",)` so the new fixtures load without per-consumer conftest wiring. Test rewrite: `libraries/http_server/functional_tests/test_real_serve.py` is now the board side of the Category 1 shape (HttpServer + SERVER_READY + handler + SERVER_REQUEST_OBSERVED + exit); `test_real_serve_host.py` is the new host driver that asserts on the HTTP response. 6 new plumbing tests (collection skip + `_resolve_board_file` resolution). The original self-loopback variant that broke on Pi Pico W consumer routers is retired. Preflight green at coverage 94. Real-board bake-validation pending — the harness is live, but the host test against a Pi Pico W needs to be run interactively.

## Out of scope

- Reworking the marker syntax Decision 0085 established. The protocol is fixed; this workstream lands the substrate that runs it.
- A separate stdout channel (UART2, named pipe). Decision 0085 rejected those.
- Live-output integration in `chumicro-workspace tail` / bake harness. Phase 5 is a placeholder, not a deliverable here.

## Pointers

- [Decision 0085](../decisions/0085-board-to-host-sync-stdout-markers.md) — the marker protocol this workstream implements the substrate for.
- [Decision 0083](../decisions/0083-functional-test-endpoint-taxonomy.md) — names the Category 1 host-driver shape that depends on this substrate.
- [Decision 0027](../decisions/0027-device-testing-infrastructure.md) — the existing transport / result-parser layer this extends.
- [`workstreams/test-harness-promotion-and-network-helper.md`](test-harness-promotion-and-network-helper.md) — Phase 2 of that workstream is blocked on this one for the `http_server/test_real_serve.py` rewrite.
