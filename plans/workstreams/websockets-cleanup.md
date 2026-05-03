# chumicro-websockets — leanness pass

Status: `proposed`
Date: `2026-05-02`
Trigger: User push-back during slice-6 close-out — "these are tiny embedded chips, are you sure the code is lean and dry enough and not full of abstractions?"  Honest answer was no; `chumicro-websockets` v0.6.x ships **3,560 LOC** vs `chumicro-mqtt`'s 1,842 despite covering similar runtime ground.  Decision 0045 §12 estimated 600-900 LOC src; we're 4-5×.

## Goals

In priority order:

1. **Saving space.**  Less source = less flash, less parse-time RAM, less bytecode in `.mpy`.
2. **Performance.**  Fewer per-tick allocations, less GC pressure, fewer method-call frames on the hot path.
3. **Minimizing duplications.**  ~600 LOC duplicated client.py↔server.py; ~150 LOC duplicated between the two handshake parsers.
4. **Fewer abstractions.**  Six namespace-only classes; speculative public API; a `CaseInsensitiveDict` whose `__eq__` / `__repr__` / `__iter__` / `__len__` aren't called by library code.
5. **Method length.**  A handful of methods are long because the abstraction was wrong, not because the work is irreducible.

## Style for the cleanup itself

* **Comments compact, descriptive, only growing when truly necessary.**  A line of context beats a paragraph of motivation.  When a comment exists, it's because a future reader will be misled without it.  Drop docstrings that re-state the signature; keep docstrings that explain the *why*.
* **No new files unless the split earns its keep.**  A `_session.py` extraction is justified by removing ~600 LOC of duplication; a `_constants.py` split for namespace classes is not.
* **No public-API churn.**  Existing imports keep working; the host test suite (272 tests) keeps passing; the four-board live matrix stays green.
* **Per slice: green preflight + four-board live re-verification + commit + push.**

## Inventory (post-_pure_sha1 removal, v0.6.2)

| File | LOC | Note |
|---|---|---|
| `_wire.py` | 1,394 | Frame parser per-byte loop + duplicated handshake parsers + verbose docstrings + namespace classes. |
| `client.py` | 1,036 | ~600 LOC of OPEN/CLOSING/CLOSED state-machine duplicated with server.py. |
| `server.py` | 946 | Same. |
| `__init__.py` | 181 | ~50 names exported including spec-trivia constants. |
| `sockets_factory.py` | 71 | Decision 0042 sub-rule helper.  Already minimal. |
| `testing.py` | 214 | Host-only fakes (not deployed).  Already minimal. |
| **Total deployed** | **3,628** | Target ~2,200-2,500 after the pass. |

Peers for reference: chumicro-mqtt 1,842; chumicro-requests 2,083; chumicro-http-server 1,530.

## Slice plan

Each slice is independent — pick by value-vs-risk, ship, re-verify, move on.

### Slice A — `FrameParser._step` per-byte → per-chunk (perf, no LOC change)

**Problem.**  `FrameParser.feed(chunk)` calls `_step(byte_value)` once per byte.  A 1024-byte recv buffer = 1024 method calls per tick.  On MicroPython each call allocates a frame.  The `READING_PAYLOAD` branch is the hottest — for a typical text message it does `self._payload.append(byte_value ^ mask_byte)` 1024 times when it could `self._payload.extend(masked_chunk)` once.

**Approach.**  Restructure `feed()` to consume bytes per-state rather than per-byte:
* `READING_HEADER` / `READING_LEN16` / `READING_LEN64` / `READING_MASK` — copy `min(remaining, needed)` bytes via slice into `self._buffer`, then dispatch.
* `READING_PAYLOAD` — copy `min(remaining, payload_remaining)` bytes via XOR-loop or slice (when unmasked) into `self._payload`.

Same LOC (~50 in `_step`); much less GC pressure on the hot path.  Public API unchanged.

**Acceptance.**  Existing FrameParser tests pass; live four-board matrix stays green.  Quick benchmark on host: feed a 16 KB payload through the parser, assert <100 ms (rough order-of-magnitude check).

### Slice B — Replace namespace classes with module constants (space)

**Problem.**  Six classes whose entire body is `STATE_FOO = "foo"` lines:
* `WebSocketState`, `FrameParseState`, `HandshakeParseState`, `ConnectingPhase`, `ServerHandshakePhase`, `WhenOversized`.
Six class objects + six `__dict__`s in RAM for grouping that module-level constants give for free.

**Approach.**  Promote each class's attributes to module-level constants prefixed by the (former) class name — `WS_STATE_OPEN`, `FRAME_STATE_READING_HEADER`, etc.  Or: keep the namespace shape but switch to `class _Namespace: __slots__ = ()` with class-attribute strings (still cheaper than `__dict__`).

Decision: **module-level constants** with a clear naming prefix — simpler, no class-object overhead.  Public API: re-export old names too (`WebSocketState = _WebSocketStateNamespace`) if the prior-callsite imports look like `from chumicro_websockets import WebSocketState; if state == WebSocketState.OPEN`.  Or just deprecate the namespace shape — public API hasn't shipped to PyPI yet, so we can change freely (per AGENTS.md "no backward compat burden").

**Acceptance.**  Tests updated to new constant names; preflight green; docs/guide.md sample updated.

### Slice C — Slim `__init__.py` exports (space)

**Problem.**  ~50 names exported.  Each is a globals-dict entry on the module object.  Many are spec-trivia callers don't touch:
* `CLOSE_NO_STATUS_RCVD`, `CLOSE_TLS_HANDSHAKE`, `CLOSE_ABNORMAL` — reserved codes that MUST NOT cross the wire.  Internal use only.
* `RESERVED_CLOSE_CODES`, `MAX_CONTROL_PAYLOAD_BYTES`, `WS_MAGIC_GUID`, `WS_VERSION` — internal constants.
* `FrameParser`, `FrameParseState`, `HandshakeParseState`, `HandshakeRequestParser`, `HandshakeResponseParser` — exposed for tests + advanced users; could move to `chumicro_websockets._wire` access for tests, drop from public.
* `ConnectingPhase`, `ServerHandshakePhase` — implementation detail of the handshake phase tracking.

**Approach.**  Cut to the surface a real consumer would touch: `WebSocketClient`, `WebSocketServer`, `Connection`, `WebSocketState`, `WhenOversized`, the seven concrete exception classes, the `OPCODE_*` + `CLOSE_NORMAL`/`GOING_AWAY`/`PROTOCOL_ERROR`/`BAD_DATA`/`TOO_BIG`/`INTERNAL_ERROR` constants users send/receive, `parse_ws_url` (URL helpers), `make_websocket_key` + `derive_accept_key` (rare but useful for advanced users).  Tests reach into `chumicro_websockets._wire` directly — same pattern as `chumicro_requests._wire` access in tests.

Target: ~25 names.

**Acceptance.**  Test imports updated to reach `_wire` for internal types; preflight green; sample app from docs/guide.md still imports cleanly.

### Slice D — Slim `CaseInsensitiveDict` (space, dedup with chumicro-requests)

**Problem.**  Inlined copy from chumicro-requests' `_wire.py`.  Ships:
* `__getitem__`, `__setitem__`, `__contains__`, `get`, `items`, `__iter__`, `__len__`, `__eq__`, `__repr__`.

Used by chumicro-websockets library code:
* `__getitem__`, `__setitem__`, `__contains__`, `get`, `items` only.

The other four methods (`__iter__`, `__len__`, `__eq__`, `__repr__`) exist because chumicro-requests' code uses them.  Cargo-culted into our copy.  (Note: chumicro-requests' copy *does* additionally ship an `add` method for repeated-name folding; ours never had one — so no `add` work.)

**Approach.**  Drop the unused methods from our copy.  Keep the inlined-copy structural decision (Decision 0040 §Consequences "extract shared HTTP wire primitives" still pending the third user).  ~30 LOC.

**Acceptance.**  Existing CaseInsensitiveDict tests for these unused methods get deleted (they only existed because we shipped the methods); preflight green.

### Slice E — Merge handshake parsers into `_HandshakeLineParser` base (dedup)

**Problem.**  `HandshakeResponseParser` (~150 LOC) and `HandshakeRequestParser` (~180 LOC) share:
* The line-buffering state machine (`feed`, `_parse_header_line`, `_fail`).
* Header storage in a `CaseInsensitiveDict`.
* The `state` / `headers` / `error` / `leftover` accessors.
* The `max_header_bytes` cap enforcement.

They differ only in:
* The first-line parser (status line vs. request line).
* The `_finalize` validation (server's accept-token check vs. client's upgrade headers).

**Approach.**  Extract `_HandshakeLineParser` with the shared scaffolding; subclass for the two callers, each implementing `_parse_first_line(line)` + `_finalize()`.  Net cut: ~150 LOC.

**Acceptance.**  Existing handshake-parser tests (which exercise the public API) all pass unchanged; preflight green; live four-board matrix stays green (handshake is exactly what gets exercised end-to-end).

### Slice F — Compact docstrings + drop dead defensive code (space, readability)

**Problem.**  Every method has a 5-10 line docstring.  Many over-explain.  Several methods carry `# pragma: no cover` defensive branches that are unreachable by construction (post-`raise self._fail(...)` returns, etc.) — already cleaned in slice 1's coverage pass but more remain.

**Approach.**  Pass through every docstring with the rule "compact but clear; grow only when truly necessary".  Drop one-liners that re-state the signature.  Keep paragraphs that explain the *why* — which non-obvious constraint, which spec section, which prior bug it prevents.

For dead defensive code: audit `# pragma: no cover` annotations in the post-cleanup state; remove the lines they protect when the protection is unreachable.

**Acceptance.**  Coverage stays ≥94 %; preflight green; the diff shows only deletions in src/ + targeted test deletions for removed dead-code branches.

### Slice G — Shared `_session.py` between client + server (dedup, biggest single win)

**Problem.**  ~600 LOC duplicated between `WebSocketClient` and `Connection` covering the OPEN/CLOSING/CLOSED state machine + framing pipeline + close handshake + send queue + timeouts.  Decision 0045 §1 anticipated this; slice 4 deferred the dedupe.

**Approach.**  Extract `_session.py` with `_BaseSession` carrying:
* `_drain_inbound`, `_feed_frame_bytes`, `_dispatch_frame`, `_handle_data_frame`, `_extend_inbound_buffer`, `_finish_oversized_message`, `_reset_inbound_state`.
* `_handle_close_frame`, `_handle_ping_frame`, `_handle_pong_frame`.
* `_drain_outbound`, `_recv_chunk`, `_enqueue_user_frame`, `_enqueue_internal_frame`.
* `_send_close`, `_finalize_closed`, `_fail_with_error`.
* `_check_timeouts`, `_arm_pong_deadline`.
* `send_text`, `send_binary`, `send_ping`, `close` — public.
* `state` / `last_close_code` / `last_close_reason` / `last_error` — public.
* Callbacks: `on_text` / `on_binary` / `on_ping` / `on_pong` / `on_close` / `on_oversized`.

Parameterised by:
* `_outbound_mask_factory` — `make_mask_key` for client, `lambda: None` for server.
* `_inbound_mask_required` — `False` for client (validate no mask), `True` for server (validate mask present).
* `_role_label` — `"client"` / `"server"` for error message clarity.

`WebSocketClient` extends `_BaseSession` + adds `connect(url)` + the CONNECTING-as-client phase.

`Connection` extends `_BaseSession` + adds the CONNECTING-as-server phase + `request_path` / `request_headers` properties.

**Risk.**  This is the highest-impact slice but also the riskiest — it touches every test that reaches into client/server internals (`_check_timeouts`, `_pending_ping_deadline_ticks`, etc.).  Plan: do this slice last, after slices A-F have settled the smaller cleanups, so the diff is purely about the dedup.

**Acceptance.**  All 268 host-side tests pass; live four-board matrix re-verified; the public API surface (`WebSocketClient` / `Connection` / `WebSocketServer` constructor signatures, all callbacks, all properties) is byte-identical.

## Sequencing

Recommended order — smallest-blast-radius first:

1. **Slice A** (FrameParser per-chunk) — mechanical, public API unchanged, isolated to one method.
2. **Slice C** (slim __init__) — purely deletions from public surface.
3. **Slice D** (slim CaseInsensitiveDict) — purely deletions.
4. **Slice B** (namespace classes → constants) — touches every callsite that uses these enums.
5. **Slice F** (compact docstrings + dead-code) — pass through every file once.
6. **Slice E** (merge handshake parsers) — internal refactor, public API unchanged.
7. **Slice G** (shared `_session.py`) — biggest LOC win, biggest test churn.  Last.

Each slice ships its own VERSION bump (patch for B/C/D/F, minor for A/E/G — observable behaviour change in A; refactors in E/G that change internals).

## Acceptance for the workstream as a whole

* `chumicro-websockets` deployed source ≤ 2,500 LOC.
* All 268 host-side tests pass.
* Four-board live matrix (Lolin S2 CP+MP, Pi Pico W CP+MP) re-verified end-to-end against the host `websockets` echo server.
* Public API (the names exported from `__init__.py` after slice C) byte-identical between v0.6.x and the post-cleanup version, modulo the namespace-class-to-constant renames in slice B (which are pre-PyPI and free to break).
* Memory-knob defaults unchanged.

## Out of scope

* The Decision 0040 §Consequences "extract shared `chumicro-http` package" follow-up.  That'd touch chumicro-requests + chumicro-http-server; this workstream stays inside chumicro-websockets.
* The two-device device-as-server-against-host-client functional test (the symmetric pair to `test_real_client_against_host`).  Separate slice 7 of Decision 0045.
* MicroPython native `extmod/modwebsocket` delegation (Decision 0045 §Consequences).  Re-evaluate when MP fixes the gaps.
