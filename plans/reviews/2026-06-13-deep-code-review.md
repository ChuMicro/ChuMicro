# Deep code review — ChuMicro (2026-06-13)

> Findings report for conversion into actionable phases. Each finding carries a stable ID (`AREA-N`), a `file:line` anchor, severity, evidence, fix, and a **verification status** so the remediation phase knows whether the claim was re-derived from source or still needs confirmation.

## Scope and method

Reviewed all 16 device libraries (`libraries/*/src/`, ~21k lines), the 5 workbench tools (`workbench/*/src/`, ~38k lines), `support/test_harness`, and `conftest.py`. The rubric was the project's own documented invariants — `AGENTS.md` "Library code rules", `plans/patterns.md`, and the relevant ADRs (0073 decode trust boundary, 0080 runner reactor / ≤5 ms tick, 0084 gc policy, 0087 generators-not-async, 0088 phase anchoring, 0052/0053/0066/0077 host-tool rules, 0058 loud skips).

Eight read-based audits ran on `opus` subagents (one per library cluster + workbench), each returning candidate findings with `file:line` evidence. Per the repo rule that "sub-agent reports describe intent, not state," every CRITICAL/HIGH and a sample of MEDIUM findings were re-derived against source before landing here. That re-derivation **overturned two agent claims**:

- The mqtt "negative `bytearray` crash" reported as CRITICAL is **unreachable** — see `MQTT-FALSE-1`.
- The http_server "414 bypass" reported as HIGH is a **soft-cap overshoot of ≤one recv chunk**, not an arbitrary-length DoS — reclassified to MEDIUM (`HTTP-3`).

A third finding (msgpack truncated-header exception type, `MSG-1`) was found by direct reading, not a subagent.

Severity key: **CRITICAL** = remote/peer-triggered crash, hang, OOM, data loss, or a test/lint gap that lets real failures pass green; **HIGH** = a real bug, a device perf/memory invariant violation in a hot path, or an unflagged blocking call in a tick; **MEDIUM** = quality, efficiency, cross-runtime divergence, or a soft-cap gap; **LOW** = comment/doc drift and nits.

---

## Executive summary

The codebase is strong where it matters most for embedded safety. The trust boundaries that handle hostile input — `msgpack` decode, MQTT remaining-length, HTTP `Content-Length` and chunked bodies, WebSocket frame length and RFC-6455 masking/opcode validation — are genuinely defended: peer-controlled lengths are bounded before allocation, recursion is depth-capped, malformed framing reaches a classified error. Time math routes through `chumicro_timing` everywhere checked; the ticks-wrap arithmetic is correct; `__slots__`/passthrough-`@property`/`typing`/`__future__` bans hold; FIFO queues use `deque`. The host tooling is careful: subprocess calls are argv-based (no `shell=True`), binaries resolve through `shutil.which`, and the rsync `--delete` data-loss surface is guarded by resolve-then-verify.

The most important finding is structural, not a parse bug: **the runner — the scheduler every library rides on — has no per-handler fault isolation** (`RUN-1`). One service's `handle()` raising kills the whole reactor loop, and the failed tick leaves the pending list uncleared so already-fired handlers re-fire on recovery. `EventBus` and `Logger` both isolate handler exceptions with a drop counter; the runner, the layer where isolation matters most, does not.

The second cluster worth front-loading is **test/lint infrastructure integrity**. Two CHU lint rules that enforce ADR-0058 "loud skips" have confirmed false-negatives (`TEST-2`, `TEST-3`), the on-device test summary is parsed but never reconciled against per-test results (`TEST-1`), and the "never ship an entrypoint containing `microcontroller.reset()`/`machine.reset()`" rule is mechanized nowhere (`TEST-4`). These don't break the product, but they weaken the guarantees that every green preflight rests on.

Counts: 1 CRITICAL, 11 HIGH, 18 MEDIUM, ~12 LOW, plus 1 ecosystem-integrity callout (`ECO-1`).

---

## CRITICAL

### RUN-1 — Runner `tick()` has no per-handler exception boundary; one service's failure kills the reactor and re-fires handlers
- **file:** `libraries/runner/src/chumicro_runner/core.py:420-426`
- **category:** correctness / availability · **verified:** yes (re-read source)
- **evidence:**
  ```python
  for entry in pending:
      entry.handler_function(now_ms)        # no try/except
      if entry.run_count is not None:
          entry.run_count -= 1
          if entry.run_count <= 0:
              self._remove(entry)
  pending.clear()                            # skipped if a handler raised
  ```
- **why:** The batch-fire loop wraps nothing. Any service `handle()` (or handler callable) raising a non-handled exception propagates out of `tick()`, so every other due service that tick never runs, and the app's `while True: runner.tick()` loop dies unless the app itself wraps `tick()`. Because `pending.clear()` (line 426) sits after the loop, it is skipped on the exception path: `self._pending` keeps the entries, and the next `tick()` appends newly-due entries on top, so handlers that already ran re-fire (compounding each tick). `EventBus.handle` (`events/core.py:146`) and `Logger.log` (`logging/core.py:117`) both isolate handler exceptions and bump a counter; the runner is inconsistent with its own siblings.
- **fix:** Wrap `entry.handler_function(now_ms)` in `try/except Exception` (let `KeyboardInterrupt`/`SystemExit`/`GeneratorExit` propagate), route failures to a counter or an injected error hook, and move `pending.clear()` into a `finally` (or clear before the fire loop) so a raised handler can't leave stale pending entries. Confirm against Decision 0080 that `tick` fault-propagation isn't an intended contract — the EventBus/Logger precedent says it isn't.

---

## HIGH

### TEST-1 — On-device test `SUMMARY total=/failed=` is parsed but never reconciled with per-test lines; a truncated batch can report green
- **file:** `workbench/pytest-device/src/chumicro_pytest_device/result_parser.py:109` + `collection.py:551`
- **category:** test-integrity · **verified:** agent-reported with quoted evidence — confirm during remediation
- **why:** The harness prints an authoritative `SUMMARY total=N failed=M`, but the pass/fail path only inspects `result.tests` (non-empty + per-name lookup). If a board truncates output after some `PASS` lines but before a crashing test's line, or a serial glitch drops a `FAIL` line, the surviving `result.tests` are all passing and the device-reported failure is silently discarded.
- **fix:** In `_require_batch_result`, after the emptiness check, assert `result.summary is not None`, `result.summary.total == len(result.tests)`, and `result.summary.failed == count(status=="FAIL")`; `pytest.fail` on mismatch. Pairs with `TEST-5`.

### TEST-2 — CHU010 counts an assertion inside an unfired nested closure, so assertionless tests pass the lint
- **file:** `workbench/checks/src/chumicro_checks/rules/chu009_chu010.py:128`
- **category:** lint-false-negative (ADR-0058) · **verified:** yes (re-read source)
- **evidence:** `_function_has_assertion` uses `for node in ast.walk(func):` which descends into nested `def`/`lambda`; the sibling `_ifs_in_scope` deliberately stops at nested defs and documents why ("a return inside a closure is that callable's logic, not the test silently passing"). A test whose only `assert` lives in a registered-but-never-driven callback satisfies CHU010.
- **fix:** Make `_function_has_assertion` walk the function's own control flow only — mirror `_ifs_in_scope`'s manual stack that skips `FunctionDef`/`AsyncFunctionDef`/`Lambda`/`ClassDef`.

### TEST-3 — CHU009 never inspects `else:` bodies, so `if HARDWARE: assert…; else: return` is an unflagged silent pass
- **file:** `workbench/checks/src/chumicro_checks/rules/chu009_chu010.py:201-213` (+ docstring 169-170)
- **category:** lint-false-negative (ADR-0058) · **verified:** yes (re-read source)
- **why:** `_silent_return_findings` checks `node.body[-1]` of each `ast.If` but never `node.orelse`. `elif` is caught (it is a nested `If` in `orelse`), but a plain `else: return` — the canonical "skip on missing hardware" shape ADR-0058 bans — is invisible.
- **fix:** Also check `node.orelse`: when non-empty, its last statement isn't itself an `ast.If` (a real `else`, not `elif`), and that statement is `Return`/`Pass`, emit CHU009.

### TEST-4 — No mechanized guard blocks deploying a `code.py`/`app.py` containing `microcontroller.reset()`/`machine.reset()`
- **file:** `workbench/workspace/src/chumicro_workspace/boot_shim.py:159` (project walker) + `cli/deploy.py`
- **category:** boot-shim / drift-mechanization (ADR-0074) · **verified:** yes (grep: the strings appear only in deploy's own bootloader code + docstrings, never in a scan/guard)
- **why:** `AGENTS.md` lists "Never deploy `code.py`/`main.py` containing `microcontroller.reset()`/`machine.reset()`" as non-negotiable, but it is a prose-only contract. The synthesized shim is a fixed safe string, yet the user `app.py` it invokes (or a plain-mode `code.py`) ships verbatim with no AST scan — a top-level or `run()`-reachable hard reset ships unblocked and crash-loops the board on boot.
- **fix:** Add an AST scan in the project/flat walker (or at `cli/deploy.py` next to the existing `project_app_exports_async_run` guard) that refuses, or at minimum warns on, a shipped entrypoint with a reachable `microcontroller.reset()`/`machine.reset()` call.

### TEST-5 — `run_module` returns exit 0 on zero discovered tests; "did it run" rests on host/device name agreement
- **file:** `support/test_harness/src/chumicro_test_harness/runner.py:202-207`
- **category:** test-integrity · **verified:** agent-reported with quoted evidence — confirm during remediation
- **why:** `return 1 if failed else 0` returns 0 when `total == 0`. The only thing converting "zero ran" into failure is the host-side empty-`result.tests` check plus per-name lookup, which relies on host AST discovery and device `dir()`-based discovery agreeing name-for-name. A partial divergence (host expects 5, device runs 3) is correct only by the lookup guard's luck.
- **fix:** Adopt `TEST-1`'s SUMMARY reconciliation; separately consider `return 1` when `total == 0` and no name filter was supplied.

### HTTP-1 — Server response headers are emitted without CRLF validation → handler-reflected response splitting
- **file:** `libraries/http_server/src/chumicro_http_server/server.py:433`
- **category:** security / http-parse · **verified:** yes (re-read source)
- **evidence:**
  ```python
  for name, value in headers.items():
      parts.append(f"{name}: {value}\r\n".encode("ascii"))
  ```
  `\r` and `\n` are ASCII, so they encode cleanly; there is no `_reject_control_chars` guard, unlike the client's `encode_request`.
- **why:** A handler reflecting request-derived data into a response header (`Location`, `X-Echo`, etc.) lets a `\r\n` in that value splice arbitrary headers or a body — classic HTTP response splitting. Query values reach handlers undecoded, so a literal CR/LF is plausible.
- **fix:** Reuse the client's `_reject_control_chars` over each response header name/value (and `reason`) inside `encode_response`, raising `ServerProtocolError` on `\r`/`\n`/`\x00`.

### SOCK-1 — Connector `AWAITING_DNS` tick calls blocking `getaddrinfo`, undocumented as a tick-budget compromise
- **file:** `libraries/sockets/src/chumicro_sockets/_adapters/cpython.py:104`, `mp.py:577`, `cp.py:411`
- **category:** blocking / tick-budget (ADR-0080) · **verified:** yes (re-read source)
- **why:** The tick-driven connector exists so connect doesn't block, and its TCP/TLS phases carry per-runtime "honest blocking" docstrings. The DNS phase resolves synchronously inside `tick()` with no such disclosure — a cache miss against a slow resolver freezes the whole runner for the lookup, the exact "freeze that looks like a stalled service" the reactor model prevents.
- **fix:** Either document the DNS-phase blocking compromise in the `tcp_client_connector`/`tls_client_connector` docstrings alongside the TCP/TLS notes, or use a non-blocking resolver where the platform supports it. Silent is the failure mode.

### WIFI-1 — CircuitPython wifi connect blocks the runner up to 15 s inside `handle()`
- **file:** `libraries/wifi/src/chumicro_wifi/_adapters/cp.py:83`
- **category:** blocking / tick-budget (ADR-0080) · **verified:** agent-reported with quoted evidence — high confidence
- **why:** `radio.connect(..., timeout=connect_timeout_ms/1000)` (default 15 s) is called from `WifiService.handle()` → stalls every co-scheduled service (MQTT keepalive, NTP, socket connectors) for the connect duration. CP has no non-blocking connect, so it is partly substrate-imposed, but nothing at the service level warns of it.
- **fix:** Document the CP blocking constraint at the `WifiService`/adapter-base level, and/or clamp the CP `connect_timeout_ms` to a small per-tick budget and re-arm across ticks.

### NTP-1 — would-block handling catches only `EAGAIN`, not `EWOULDBLOCK`; non-`EAGAIN` permanently fails the exchange
- **file:** `libraries/ntp/src/chumicro_ntp/core.py:320`
- **category:** correctness / cross-runtime · **verified:** agent-reported, pattern confirmed
- **why:** The `__init__` docstring promises `OSError(EAGAIN | EWOULDBLOCK)`, but the code only retries on `EAGAIN`. On device EWOULDBLOCK == EAGAIN == 11, so the board is fine; on macOS-CPython a real non-blocking socket raises errno 35, marking the exchange permanently failed. `FakeUDPSocket` pins to `EAGAIN`, hiding the gap in host tests — the "fake returns the convenient value" trap.
- **fix:** `if recv_error.errno in (errno.EAGAIN, errno.EWOULDBLOCK):` (alias for MP if absent; the constants are equal there).

### DEP-1 — `_run_mpremote` has no subprocess timeout; a wedged MP board hangs the deploy forever
- **file:** `workbench/deploy/src/chumicro_deploy/micropython_transport.py:1338`
- **category:** subprocess / hang · **verified:** agent-reported with quoted evidence — high confidence
- **why:** Every `mpremote` call (`connect`, `fs cp -r`, `exec`, `wipe_filesystem`) routes through `_run_mpremote` with no `timeout=`. The CP path deliberately wraps USB-touching subprocesses with `_run_subprocess_with_timeout` for exactly this reason; the MP path has no equivalent, so a board whose USB-CDC wedges mid-copy blocks indefinitely with no classified error.
- **fix:** Add a `timeout=` to `_run_mpremote`, catch `subprocess.TimeoutExpired`, and raise `MicropythonTransportError` with wedge-recovery guidance so `classify_deploy_failure` can route it.

### MQTT-1 — QoS-0 publish callbacks enqueue a second item that bypasses the tx-queue cap, doubling pinned-payload backpressure
- **file:** `libraries/mqtt/src/chumicro_mqtt/client.py:695`
- **category:** alloc / backpressure · **verified:** agent-reported, medium confidence
- **why:** A callback-bearing QoS-0 publish enqueues the packet then a marker tuple, but `_enqueue_user_tx` checks `len >= max` per call (before append). The packet can land at `max-1`, pass; the marker lands at `max`, also passes. Each marker pins the full `payload_bytes` until drained, so a burst can reach `2 × max_tx_queue_size` payload-retaining entries before `MQTTBackpressureError` — real RAM on a 256 KB board.
- **fix:** Reserve two slots for a callback-bearing QoS-0 publish (single capacity check covering packet + marker), or document that the marker payload reference is the memory cost and size the cap accordingly.

### MSG-1 — msgpack truncated multi-byte headers raise `IndexError`/`struct.error`, not the documented `ValueError`
- **file:** `libraries/msgpack/src/chumicro_msgpack/_pure.py:226,233,247-288` (header reads) vs docstring `:355-377`
- **category:** trust-boundary / contract · **verified:** yes (direct read + traced)
- **why:** `unpackb`'s docstring promises truncated input raises `ValueError`. `_bounded_end` guards the *payload* of length-prefixed types, but the header bytes are read directly: `data[offset+1]` (uint8/str8/bin8) raises `IndexError` and `struct.unpack_from(">H", data, offset+1)` (uint16/str16/array16/map16) raises `struct.error` when the header itself is truncated (e.g. `unpackb(b"\xcd\x00")`). A caller following the documented contract with `except ValueError:` won't catch these, so they propagate — and given `RUN-1`, an uncaught parser exception in a tick kills the reactor.
- **fix:** Catch `IndexError`/`struct.error` at the `unpackb`/`_decode` boundary and re-raise as `ValueError(_MALFORMED)`, or bounds-check header width before each read.

---

## MEDIUM

### HTTP-3 — Request-line 414 cap is soft: a line can exceed `max_request_line_bytes` by up to one recv chunk
- **file:** `libraries/http_server/src/chumicro_http_server/_wire.py:527-541`
- **category:** http-parse · **verified:** yes (re-read; agent's "arbitrary-length bypass" HIGH corrected)
- **why:** The cap is checked only on the no-CRLF branch. Recv is chunked at ≤512 B/feed with `_advance` after each feed, so the over-cap-without-CRLF state is normally hit first and fires 414 — the buffer-growth DoS bound holds. The residual: when the CRLF lands in the same chunk that first crosses the cap, the line parses without 414, so the effective cap is `max_request_line_bytes + (up to ~512)`. Not an OOM; an inexact cap.
- **fix:** After `crlf_index >= 0`, reject when `crlf_index > self._max_request_line_bytes` before slicing. (The headers path already checks unconditionally.)

### REQ-1 — `recv_budget_per_tick > 512` under-drains and breaks the documented tick-latency bound
- **file:** `libraries/requests/src/chumicro_requests/client.py:497,884`; `libraries/http_server/.../server.py:252,314`
- **category:** tick / correctness · **verified:** agent-reported, high confidence
- **why:** The scratch buffer is `min(recv_budget_per_tick, 512)`, but the recv loop honors the full `budget`, so a budget of 4096–64K spins up to `budget/512` recv+feed iterations per `handle()` — the opposite of the "soft cap bounds tick latency" the docstring claims, and a ≤5 ms tick-budget risk on a fast peer.
- **fix:** Size the scratch to a documented larger hard cap, or clamp the loop to the 512 working window and document that per-tick throughput is `min(budget, 512)`.

### RUN-2 — `_dispatch_io_error` iterates `_entries` live while `_mark_done` removes from it → skips the following entry
- **file:** `libraries/runner/src/chumicro_runner/core.py:510` + `_generator.py:209`
- **category:** generator / correctness · **verified:** agent-reported, medium confidence
- **why:** `wait`'s error dispatch iterates `self._entries` live; a generator wrapper's `io_error` → `_mark_done` → `TaskHandle.remove()` does `list.remove()` during that iteration, shifting later elements and skipping one. The `_mark_done` docstring's "safe to call from `handle`" claim overstates the guarantee for the `wait` path.
- **fix:** Iterate a snapshot in `_dispatch_io_error`, or defer removal (mark inactive, sweep next tick). At minimum correct the docstring.

### RUN-3 — `connect()` generator feeds `connector.tick(0)` a hardcoded `now_ms`
- **file:** `libraries/runner/src/chumicro_runner/generators.py:142`
- **category:** correctness · **verified:** agent-reported, medium confidence
- **why:** Every other path threads the real `now_ms`; `connect` discards the value the generator already receives at its `yield` and passes literal `0`, so a connector doing `ticks_diff(now_ms, deadline)` measures against tick 0 — never/instantly times out depending on sign.
- **fix:** Capture `now_ms = yield connector` and pass it to the next `connector.tick(now_ms)`, or document that `connect` deliberately passes 0 and connectors must read their own clock.

### LOG-1 — Logging API takes a pre-built string with no deferred `%`-args path, forcing eager f-string allocation on hot paths
- **file:** `libraries/logging/src/chumicro_logging/core.py:112-140`
- **category:** alloc · **verified:** agent-reported, high confidence
- **why:** `AGENTS.md` prescribes `log.info("...%d", n)` with logger-side interpolation as the zero-alloc hot-path idiom. The API only accepts one already-built `str`, so `log.info(f"x={n}")` allocates before the level check can drop it; `is_enabled()` exists but is per-site caller burden.
- **fix:** Add optional `*args` to `log`/`info`/`debug`/…, interpolate `message % args` only after the `level < self.level` early-return; document that f-strings defeat it.

### WS-1 — Masked-payload unmask is a per-byte Python loop in the server inbound hot path
- **file:** `libraries/websockets/src/chumicro_websockets/_wire.py:939`
- **category:** alloc / tick · **verified:** agent-reported, medium confidence
- **why:** Clients must mask, so every byte a server receives runs `payload[i] = chunk_view[i] ^ mask_key[i & 3]` in interpreted bytecode, plus a `range(take)` iterator alloc per `feed`. A multi-KB masked frame is thousands of iterations inside `handle()`, a ≤5 ms tick risk under load. (Related to the already-tracked websockets oversize-frame item.)
- **fix:** Drop the `range()` (manual `while` index), and keep `recv_budget_per_tick` small so `take` stays bounded; bench on a Pico W under a masked flood.

### WS-2 — Send-path slices allocate per iteration (regresses the cached-view discipline the recv path uses)
- **file:** `libraries/websockets/.../_session.py:623`; mirror in `requests/client.py:872` (rebuilds `memoryview(self._tx_buffer)` every iteration) and `http_server/.../server.py:395`
- **category:** alloc · **verified:** agent-reported, medium confidence
- **why:** `buffer[offset:offset+budget]` / per-iteration `memoryview(...)` allocate on a backpressured send loop, against the steady-state-zero-alloc rule the recv side honors with a cached view.
- **fix:** Cache a `memoryview` per outbound buffer and slice the view; `send` accepts a memoryview on all runtimes.

### MQTT-2 — Inbound QoS-1 PUBACKs `appendleft` faster than the one-send-per-tick drain; bounded deque silently drops protocol packets
- **file:** `libraries/mqtt/src/chumicro_mqtt/client.py:1340,1356`
- **category:** alloc-dos / correctness · **verified:** agent-reported, medium confidence
- **why:** `_read_inbound` dispatches all buffered packets per tick while `_drain_tx_queue` sends one. A broker pushing many small QoS-1 PUBLISHes grows the PUBACK backlog against a fixed `maxlen = user_cap + 64`; at `maxlen`, `appendleft` on a bounded MP/CP deque drops the far end — losing a queued PINGREQ, DUP retransmit, or PUBACK. (Distinct from the already-tracked `_tx_queue` list→deque item.)
- **fix:** Bound inbound QoS-1 dispatch per tick toward the tx drain rate, or detect deque-at-`maxlen` before `appendleft` and fault to FAILED rather than silently dropping.

### MQTT-3 — `_check_deadlines` can burst N DUP retransmits in one tick, each a full-packet `bytearray` copy
- **file:** `libraries/mqtt/src/chumicro_mqtt/client.py:1509-1525`
- **category:** alloc · **verified:** agent-reported, medium confidence
- **why:** When many in-flight QoS-1 deadlines expire together (after a socket stall), the loop appends one `bytes(retry_packet)` per entry in a single tick — an allocation burst plus queue growth against one-send-per-tick drain. Only byte 0 (DUP flag) changes.
- **fix:** Cap retransmits per tick, and store a DUP-flagged copy once on `InFlightPublish` instead of re-copying `packet_bytes` per retry.

### SOCK-2 — MP TLS connector hands `wrap_socket` a non-blocking socket, diverging from the listener path
- **file:** `libraries/sockets/.../_adapters/mp.py:597` vs `mp.py:366`
- **category:** cross-runtime / blocking · **verified:** agent-reported, medium confidence — needs real-board bake
- **why:** `_issue_tcp_connect` leaves the socket `setblocking(False)`; the connector then calls `wrap_socket` on it while documenting "blocks until handshake completes" — only reliably true on a blocking socket. The listener path does `setblocking(True)` before `wrap_socket(server_side=True)` for this reason. If mbedTLS honors the non-blocking flag, the client handshake can return mid-flight, breaking the "single blocking tick → ready" contract. The scripted unit fakes never exercise the real `_MpConnector`.
- **fix:** `setblocking(True)` before `wrap_socket`, `setblocking(False)` after; validate with a real-board TLS connector bake.

### SOCK-3 — CP UDP `recvfrom_into` empty-queue behavior diverges across CP / MP / fake
- **file:** `libraries/sockets/.../_adapters/cp.py:161`
- **category:** cross-runtime · **verified:** agent-reported, medium confidence
- **why:** CP forwards native `recvfrom_into` (raises `OSError(EAGAIN)` on empty); `_MpUDPWrapper` normalizes to raise; `FakeUDPSocket.recvfrom_into` returns `(0, addr)`. A downstream NTP/mDNS loop written and tested against the fake (which never raises) hits an unhandled `OSError(EAGAIN)` the first time it runs on real CP/MP hardware — the TCP fake/adapter pair does not have this divergence.
- **fix:** Make the UDP fake raise `OSError(EAGAIN)` on empty to match the real adapters, or document the non-uniform empty-behavior loudly.

### SOCK-4 — Public connector factories absent from `__all__` (and the module Public-API docstring)
- **file:** `libraries/sockets/.../__init__.py:47-59` (`tcp_client_connector` defined `:173`, `tls_client_connector` `:205`)
- **category:** api · **verified:** yes (grep)
- **why:** The non-blocking connect primitives the runner architecture is built on are missing from `__all__`. `import *` won't pull them, and any `check-api` surface comparison keyed on `__all__` (Decision 0020) under-reports the public API, so connector signature changes escape breakage detection.
- **fix:** Add `"tcp_client_connector"` and `"tls_client_connector"` to `__all__` (keep alphabetized) and the module docstring's Public-API block.

### DEP-2 — `_decode_exec_result` / `execute` assume a 2-tuple from mpremote; a 1- or 3-tuple raises `IndexError`/`ValueError`
- **file:** `workbench/deploy/.../micropython_transport.py:263,573`
- **category:** correctness / failure-class · **verified:** agent-reported, medium confidence
- **why:** `stdout_bytes, stderr_bytes = result` and `result[1]` assume exactly length 2; mpremote's `exec_raw` return shape has drifted across versions, so a future/older shape surfaces as a raw traceback rather than a classified failure (ADR-0053).
- **fix:** Guard the unpack on `len(result)`; handle 1-tuple as stdout-only.

### DEP-3 — `_verify_drive_for_board` returns the unverified `candidates[0]` when the probe yields no identity → wrong-board wipe on multi-board hosts
- **file:** `workbench/deploy/.../circuitpython_transport.py:548,565`
- **category:** data-loss · **verified:** agent-reported, medium confidence (single-board hosts unaffected)
- **why:** When `boot_out.txt` exists but the serial probe returns `None` or an empty identity, the method falls through to raw `candidates[0]`. On a two-CIRCUITPY-board host where the OS mounted the other board's volume first, the subsequent `rsync --delete` wipes the wrong board.
- **fix:** When `boot_out.txt` is present but identity is unconfirmed, scan candidates for a UID/machine match, or refuse when more than one `CIRCUITPY*` volume is mounted.

### DEP-4 — CircuitPython and MicroPython transports duplicate ~3.4k lines of staging/umount/exec-classify logic and device-side scripts
- **file:** `workbench/deploy/.../circuitpython_transport.py` (1989) + `micropython_transport.py` (1404)
- **category:** bloat · **verified:** agent-reported, high confidence
- **why:** The umount-guard, `_ensure_serial`→`exec_raw`→classify wrapper, `if mode != "copy": return` early-out, and the embedded device walk/delete scripts repeat across both files. Cuts against the "small, typed, testable modules over large opaque services" working style.
- **fix:** Extract `_drop_active_mount()` and `_exec_or_classify()` helpers; hoist the duplicated device-side scripts into a shared `_device_scripts.py`. Behavior-preserving dedup.

### CFG-1 — `KVStore.bytes_used` re-encodes the entire dict on every read
- **file:** `libraries/kvstore/src/chumicro_kvstore/core.py:274`
- **category:** alloc · **verified:** agent-reported, medium confidence
- **why:** A legitimate computing `@property`, but `len(packb(self._data))` allocates a full encoding just to take its length. A caller polling a "how full am I?" gauge in a loop pays O(n) encode + a transient full-payload allocation each read. Not a `tick`/`handle` path, so a footgun rather than a hot-path violation.
- **fix:** Document "allocates a full encode per access — read sparingly", or memoize against a dirty flag.

### WIFI-2 — `connect_timeout_ms` is silently dead config on the MicroPython path
- **file:** `libraries/wifi/src/chumicro_wifi/_adapters/mp.py:164`
- **category:** correctness / cross-runtime · **verified:** agent-reported, high confidence
- **why:** `WifiConfig.connect_timeout_ms` (documented "max wait for a single connect attempt") is read only by the CP adapter; MP ignores it, relying on firmware + reconnect backoff. A user setting it for snappy retries gets CP behavior and silently nothing on MP.
- **fix:** Document the knob as CP-only, or enforce it on the MP adapter by tracking attempt start.

### TEST-6 — Functional-test deselection keys on a path/nodeid substring, not a structural check
- **file:** `conftest.py:119` + `workbench/pytest-device/.../collection.py:828`
- **category:** test-integrity · **verified:** agent-reported, medium confidence
- **why:** Both passes use `"functional_tests" in <path/nodeid>`. A host unit test under any path containing that literal (a `functional_tests_helpers/` package, or a checkout under such a directory) is silently deselected from a normal sweep. The conftest pass has no `DeviceRuntimeItem` guard.
- **fix:** Use the existing structural predicate `_is_library_functional_test(Path(item.fspath))` (checks `functional_tests` is exactly the dir two levels under `libraries/`).

### TEST-7 — CHU009 by design never flags a final-statement bare `return`/`pass`
- **file:** `workbench/checks/.../chu009_chu010.py:216-220`
- **category:** lint-false-negative · **verified:** yes (re-read)
- **why:** The top-level body scan skips `index == len(body) - 1`, so a trailing bare `return`/`pass` is caught only when the test is also assertionless (CHU010). The asymmetry (mid-body flagged, final not) is undocumented in the rule body.
- **fix:** Document the deliberate carve-out in the rule docstring, or flag a final bare `return`/`pass` only when preceded by no assertion in the same block.

---

## LOW (comment / doc / nit cluster)

Group these into one cleanup pass. Each is a confirmed prose-vs-code drift or a minor nit; none changes behavior.

- **SOCK-L1** `sockets/testing.py:12,52` — docstring `:meth:`enqueue_eagain`` does not exist; methods are `enqueue_eagain_for_send`/`_for_recv`. *(verified)*
- **SOCK-L2** `sockets/__init__.py:36` — `UnsupportedSSLConfigError` docstring claims `tls_listening_socket` on CP-rp2 is the "only firing site"; `cp.ssl_context_with_cert_and_key:209` also raises it on all CP boards. *(verified)*
- **NTP-L1** `ntp/core.py:159` — `__init__` docstring describes a 2-arg `sendto(payload, address)`; the real contract (code + fakes + adapters) is 3-arg `sendto(payload, host, port)`. *(verified)*
- **CFG-L1** `kvstore/_backends/cp_nvm.py:115` — comment claims a "single contiguous span"; it is two non-atomic slice-assigns. The real (safe) behavior is that a torn write is caught by the CRC on next load → `KVStoreCorrupt` → empty store. Rewrite the comment (or stage into one buffer for a true atomic write). *(verified)*
- **CFG-L2** `kvstore/_backends/mp_nvs.py:9` — "wear-leveled and atomic-on-commit" is a substrate property this layer neither provides nor checks; soften to name `unpackb`'s framing validation as the actual corruption backstop. *(agent-reported)*
- **HTTP-L1** `http_server/_wire.py:387` — typo "realloates" and "reallocates the bytearray" misdescribes an in-place memmove compaction; the client copy (`requests/_wire.py:557`) says "compacts" correctly. *(verified)*
- **MQTT-L1** `mqtt/client.py:132` — `WhenOversized.DROP_WITH_EVENT` docstring doesn't note `on_oversized` receives `topic=None` when the inbound topic itself exceeds `rx_buffer_size`; a handler doing `topic.startswith(...)` raises `AttributeError`. *(agent-reported)*
- **MQTT-L2** `mqtt/_wire.py:695` — `granted_qos = list(view[...])` allocates per SUBACK; acceptable (rare), noted to pre-empt a false "missed it". *(verified clean)*
- **WS-L1** `websockets/_wire.py:1239` — close-code read uses `struct.unpack("!H", payload[:2])` instead of `unpack_from`; low frequency (one per close). *(verified)*
- **WS-L2** `websockets/_session.py:286` — `getattr(self, "_next_auto_ping_ticks", None)` on the quiet-tick `next_deadline` path; initialize in `_init_session_state` and read directly. *(agent-reported)*
- **TIME-L1** `timing/heartbeat.py:20` — `Heartbeat` accepts a `period_ms ≥ ~74.6 h` it can never fire at (silent never-fire), unlike the `Runner` path which raises `OverflowError` via `ticks_add`. Validate `period_ms < TICKS_HALFPERIOD`. *(agent-reported)*
- **DEP-L1** `deploy/firmware.py:889` — download filename taken verbatim from URL basename without `Path(...).name` stripping; small blast radius (temp dir, no `--delete`). *(agent-reported)*
- **DEP-L2** `deploy/firmware.py:218` — `int(Content-Length)` unguarded; a malformed header raises an uncaught `ValueError` (download is streamed in 64 KB chunks, so no heap-DoS). *(agent-reported)*

---

## Corrected / refuted agent claims (kept for the record)

- **MQTT-FALSE-1 — "negative `bytearray(payload_length)` crash on malformed PUBLISH" is UNREACHABLE.** Traced against `_wire.py:580-825`: reaching `bytearray(payload_length)` requires `total_length > buffer_size` (drain entry, line 582) yet a negative `payload_length` requires `total_length < buffer_size`; large `topic_length` is caught by the oversize-topic branch (line 738) first. The two conditions are mutually exclusive — `payload_length` is provably positive whenever that code runs, and the inline path has its own guard (`:648`). No fix needed. A defensive prelude-vs-`message_length` assertion would be harmless hygiene but is not load-bearing.
- **HTTP "414 bypass" was overstated** — see `HTTP-3` (reclassified MEDIUM; the cap is a sound buffer-growth bound, soft to ≤one recv chunk).

These corrections matter for phase scoping: do **not** open a CRITICAL mqtt phase for the bytearray crash.

---

## Verified-clean (drafted-then-checked; recording so a later pass doesn't re-litigate)

- **msgpack decode trust boundary** (Decision 0073) — `_MAX_DEPTH=8` enforced on every descent; `_bounded_end` bounds every peer length before slicing; `_decode_array`/`_decode_map` reject over-length counts before allocating; trailing bytes rejected at top level. The only gap is the *exception type* of truncated headers (`MSG-1`), not the bounding.
- **MQTT primary alloc vector** — tier-2 `bytearray(payload_length)` is gated by `total_length <= max_message_bytes` before allocation; a 256 MB varint routes to tier-3 rolling drain; `decode_varlen` rejects >4-byte varlens. Packet-id wrap, duplicate-PUBACK handling, and reconnect state reset are correct.
- **HTTP sender-controlled allocation** — Content-Length capped pre-alloc both sides; negative/non-integer/duplicate lengths rejected; chunked capped cumulatively; server refuses `Transfer-Encoding` request bodies (closes smuggling).
- **WebSocket RFC 6455** — unmasked-client-frame rejection (1002), client masking, control-frame size/FIN checks, opcode/continuation validation, UTF-8 (1007), reserved close codes (1005/1006/1015) all correct; tier-3 oversize drain bounds heap at `max_payload_bytes`.
- **ticks wrap math** (`timing/ticks.py`) — canonical sign-extension within the 2^29 ring; `ticks_add` wraps with an `OverflowError` guard; phase anchoring (0088) lands in the future without bursting.
- **Host-tool safety** — no `shell=True`, binaries via `shutil.which`, no ADR-0052 device-library imports in workbench, `mount_local` double-wrap defended, non-interactive mode gated, the two `microcontroller.reset()` call sites in deploy are the bootloader-entry path (not shipped payload).

---

## Already tracked in `plans/next-up.md` (fold in, don't re-open)

- mqtt `_tx_queue` list → deque (PUBACK appendleft + retry/PINGREQ backpressure) — `MQTT-2` adds the recv-N-vs-send-1 drop angle.
- mqtt ~2× bloat audit; `/audit-embedded chumicro_runner.core` and `chumicro_websockets` — `RUN-1`, `WS-1`, `WS-2`, `DEP-4` feed these.
- websockets oversize-frame on Lolin S2 — related to `WS-1`.
- Performance + resource benchmarking infrastructure (heap + CPU per op, regression gates) — the natural home to validate `WS-1`/`WS-2`/`REQ-1`/`MQTT-3` bench claims.
- Restore audit-trimmed comment facts (mqtt/websockets/wifi) — overlaps the LOW cluster.

---

## ECO-1 — Project audit/workflow skills referenced by AGENTS.md are missing from `.github/skills/`
- **category:** ecosystem-integrity · **verified:** yes (filesystem + git status) · **confirm intent with the user**
- **what:** `AGENTS.md` makes `.github/skills/<name>/SKILL.md` instruction-priority item #2 and points hard rules at `task-checkpoint`, `git-commit`, `new-library`, `new-decision`, `audit-embedded`, `audit-comments`, `audit-docs`, `audit-skill`, `audit-library`. None of those exist at the referenced paths today — `.github/skills/` holds an unrelated external skills marketplace, and `git status` shows 117 deletions under `.github/skills/_shared/` plus 57 untracked entries. `patterns.md` and many `next-up.md` items also reference the now-absent skills.
- **why it matters:** The entire documented agent workflow (checkpoint → preflight → commit; new-library/new-decision scaffolding; the audit skills) is unrunnable as written, and the instruction-priority chain's #2 tier is dangling. This is the kind of prose-vs-reality drift ADR-0074 says must not ship.
- **note:** This may be intentional in-flight work (a skills migration). It was **not** modified by this review. Surface it for a decision: either restore the project skills, or update `AGENTS.md`/`patterns.md`/`next-up.md` to match the new reality.

---

## Suggested phase grouping (for conversion to workstreams)

1. **Runner fault isolation + tick correctness** — `RUN-1` (CRITICAL), `RUN-2`, `RUN-3`. Highest priority; bench on real board (orchestration bug class).
2. **Test/lint infrastructure integrity** — `TEST-1`…`TEST-7`. Restores trust in green preflights; mostly CPython-side, well-testable.
3. **HTTP/WS security + parser hardening** — `HTTP-1` (CRLF injection), `HTTP-3`, `MSG-1`. Security-facing.
4. **Tick-budget / blocking honesty** — `SOCK-1`, `WIFI-1`, `NTP-1`, `REQ-1`, `WS-1`. Several are "document the compromise"; a few are real fixes. Pairs with the tracked benchmarking-infra item.
5. **Hot-path allocation sweep** — `WS-2`, `MQTT-1`, `MQTT-2`, `MQTT-3`, `LOG-1`, `CFG-1`. Validate each with the bench loop, not static review.
6. **Cross-runtime contract divergence** — `SOCK-2`, `SOCK-3`, `WIFI-2`, `SOCK-4`, `DEP-2`. The fake-hides-the-gap class; needs real-board bakes.
7. **Workbench robustness** — `DEP-1` (hang), `DEP-3` (wrong-board wipe), `DEP-4` (dedup).
8. **Comment/doc cleanup** — the LOW cluster + the tracked audit-trimmed-facts item, one pass.
9. **Ecosystem decision** — `ECO-1`: restore skills or realign the docs.
