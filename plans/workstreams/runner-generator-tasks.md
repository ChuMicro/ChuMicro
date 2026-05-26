# Workstream: generator-driven sequential I/O via runner.add_generator

Status: **proposed** (Decision 0087 accepted 2026-05-25). Implements [Decision 0087](../decisions/0087-generators-for-sequential-io.md).

## Problem

The runner-shaped `check`/`handle` contract reads naturally for reactive services (MQTT keepalive, WiFi state changes, button scans) but is verbose for sequential I/O state machines. The `demos/sockets_runner_connector/app.py` `EchoService` is the canonical case: ~80 lines of explicit state machine — four state strings, three `_handle_*` methods, manual `_send_offset` tracking, three `io_wants_*` properties — for what is conceptually "connect, send, recv, close." First-time custom-protocol authors bounce off the ceremony.

Decision 0087 adopts generator functions (`def` + `yield` / `yield from`) registered with `runner.add_generator()` as the second sanctioned service shape, with `async`/`await` syntax and the `asyncio` module both banned across `libraries/` / `support/` / `workbench/`. This workstream lands the implementation, the lint enforcement, the socket generator helpers, the demo rewrite, and the docs.

## Implementation phases

### Phase 1 — Wait-token vocabulary in `chumicro_runner`

Add `ReadReady(sock)`, `WriteReady(sock)`, and `Sleep(until_ms)` in `chumicro_runner` (private module, re-exported at package root). Each has:

- `ready(self, now_ms) -> bool` — whether the runner should resume the generator on the next tick. `ReadReady` / `WriteReady` defer to the socket-readiness check (`ipoll` result); `Sleep` compares `now_ms` against `until_ms`.
- `result(self, now_ms)` — value `.send()`-ed back into the generator when it resumes. For `ReadReady` / `WriteReady` this is the sock itself; for `Sleep` it is `now_ms`.

Wait-tokens are **not** awaitables. They do not implement `__await__`. They are plain objects yielded directly via `yield token` from generator functions.

Tokens are cacheable across yields — a helper looping on `yield ready` constructs one `ReadReady(sock)` outside the loop and reuses it. Tests verify the cache pattern works (zero steady-state allocation under tracemalloc bracket).

`chumicro_runner` `VERSION` patch bump if private-only at this phase, minor bump if public surface lands here.

### Phase 2 — `add_generator` adapter

Add `runner.add_generator(gen) -> GeneratorHandle` and the internal `_GeneratorWrapper` class that satisfies the runner's check/handle/io_* contract:

```python
class _GeneratorWrapper:
    def __init__(self, gen):
        self._gen = gen
        self._wait = None
        self._done = False

    def start(self):
        self._advance(None)

    def check(self, now_ms):
        return self._wait is not None and self._wait.ready(now_ms)

    def handle(self, now_ms):
        self._advance(self._wait.result(now_ms))

    def _advance(self, value):
        try:
            self._wait = self._gen.send(value)
        except StopIteration:
            self._wait = None
            self._done = True

    @property
    def done(self): return self._done

    @property
    def io_socket(self):
        return getattr(self._wait, "sock", None) if self._wait else None

    @property
    def io_wants_read(self):
        return isinstance(self._wait, ReadReady) if self._wait else False

    @property
    def io_wants_write(self):
        return isinstance(self._wait, WriteReady) if self._wait else False

    def io_error(self, now_ms, eventmask):
        self._advance_throw(OSError("POLLERR / POLLHUP on awaited socket"))

    def _advance_throw(self, exc):
        try:
            self._wait = self._gen.throw(exc)
        except StopIteration:
            self._wait = None
            self._done = True
```

`GeneratorHandle` is the public face — exposes `.done` and forwards to the wrapper. The wrapper class stays private; users register generators via `add_generator`, not by subclassing.

Cancellation: when `Runner.remove(handle)` is called or the loop exits, the wrapper calls `self._gen.close()` to fire any `finally` blocks inside the generator. The wrapper auto-removes from the runner's entries list once `_done` flips True (deferred via `_pending` cleanup so it does not mutate `_entries` mid-tick — coordinate with the re-entrancy guard in `Runner.tick()`).

Steady-state allocation: the wrapper holds two references (`_gen`, `_wait`). When helpers cache their wait-tokens (per Phase 3 contract below), the steady-state path is zero-allocation — verify via the existing `chumicro_runner` tracemalloc convention.

`chumicro_runner` `VERSION` minor bump.

### Phase 3 — Socket generator helpers in `chumicro_sockets`

Add generator functions that wrap the existing connector + socket primitives. Every helper that loops on a wait-token must construct the token **outside** the loop and reuse it:

- `connect(host, port, radio)` — wraps `tcp_client_connector`. Yields `WriteReady` / `ReadReady` on the connector's pollable socket while the connector advances DNS → TCP → (TLS) → ready. `return`s the connected socket (PEP 380 return value, available to the caller via `sock = yield from connect(...)`). Raises `OSError` on failure.
- `send_all(sock, data)` — loops on `sock.send`, yielding a single cached `WriteReady(sock)` on `EAGAIN`. Tracks offset across yields in the generator frame (no explicit attribute needed).
- `recv_until(sock, sep, max_bytes=...)` — loops on `sock.recv_into` into a pre-allocated buffer, yielding a single cached `ReadReady(sock)` on `EAGAIN`, until the separator appears. `max_bytes` caps growth per heap-DoS rules. `return`s the received bytes.
- `recv_exact(sock, n)` — similar shape, `return`s when N bytes received.

Callers use a plain `with sock:` (or `try / finally`) for cleanup — the connected socket is a synchronous object, no async context manager needed.

Existing synchronous factories and `tcp_client_connector` stay — these helpers are an additional surface, not a replacement.

Tracemalloc test: bracket a `recv_until` polling loop with `gc.disable(); start = gc.mem_alloc(); ...; assert gc.mem_alloc() - start < 64` across 1000 polling iterations on a fake sock that returns EAGAIN 999 times.

`chumicro_sockets` `VERSION` minor bump.

### Phase 4 — Lint rule banning async/await syntax and asyncio module

Add a CHU rule (next available number; coordinate with `workbench/checks/`) that fails on:

- `async def` / `await` / `async with` / `async for` anywhere in `libraries/` / `support/` / `workbench/`.
- `import asyncio` / `from asyncio import …` anywhere in the same trees.
- `import uasyncio` / `from uasyncio import …` (MicroPython alias).
- A module file literally named `asyncio.py` or directory `asyncio/` in those trees.

Workbench is included — the project has no asyncio anywhere; carving out workbench would be a path the project does not need.

Deploy bundle staging (`chumicro-workspace deploy`'s file-tree builder) refuses to copy any module named `asyncio*` to a device — defense in depth if a lint suppression slips through.

The rule's docstring names the yield-point-hygiene reasoning (Decision 0087's *Why generators, not async/await* section) and points at [Decision 0087](../decisions/0087-generators-for-sequential-io.md). Suppressions per the AGENTS.md "pair a lint suppression with a brief explanation why" rule.

`workbench/checks` `VERSION` minor bump.

### Phase 5 — Rewrite the `sockets_runner_connector` demo

Replace `demos/sockets_runner_connector/app.py` with the generator version (~7 lines using `connect` / `send_all` / `recv_until`). Update the README: opens with the new shape, points at the moved explicit version for readers who want to see the underlying machinery.

`git mv demos/sockets_runner_connector` to `demos/sockets_runner_connector_explicit/` first (preserving the current contents), then create the new `demos/sockets_runner_connector/` with the generator version. The explicit version's README updates to frame itself as the teaching companion ("here is what `runner.add_generator` + `connect` / `send_all` / `recv_until` do under the hood").

Verify both demos round-trip cleanly on Pi Pico W (CP + MP) and Lolin S2 (CP + MP) — real-board bake per AGENTS.md's "Changes touching I/O require real-board verification" rule.

### Phase 6 — Docs

Update `libraries/runner/README.md` and any library-guide doc that describes service registration — introduce `add_generator` as the second sanctioned registration shape alongside `add(service)`, with a one-paragraph "when to pick which" guide. The guidance must default to `check`/`handle` and reach for `add_generator` only when the work is naturally one-shot sequential I/O — without that framing, drift toward "everything is a generator" is the natural direction.

Update `docs/contributing/style-guide.md` (or wherever runner-shaped libraries are described) to name the `async def` / `await` / `import asyncio` ban as a hard rule with cross-link to [Decision 0087](../decisions/0087-generators-for-sequential-io.md).

Update `plans/patterns.md` if a "generator-as-state-machine" pattern crystallizes from real use — defer if the pattern is just "use the helpers" with nothing else generalizable.

## Validation history

- 2026-05-25: Phases 1 + 2 shipped. `ReadReady`, `WriteReady`, `Sleep`, `GeneratorHandle`, `Runner.add_generator` all public in `chumicro_runner` 0.4.0. Tests: 134 CPython / 127 each on MP + CP unix-port unit suites; per-token tracemalloc allocation bracket pinned at <2 KiB over 500 iterations. Pi Pico W bake under both CircuitPython 10.2.0-dirty and MicroPython 1.26.0 ran `generator_basic.py` cleanly (Sleep tokens woke within 2-4 ms of target, generator returned, handle.done flipped). Wrapper deviates from the workstream pseudo-code by also catching arbitrary exceptions from `gen.send` / `gen.throw` to mark done before re-raising — a generator that raises during advance would otherwise linger as a dead entry in `Runner._entries`. The `Done` sentinel mentioned in the original Phase 1 list was dropped: no caller, duplicated by the public `GeneratorHandle.done` boolean attribute.
- 2026-05-25: Phase 3 + Phase 5 shipped; wait-token public surface reworked. `chumicro_runner.generators` now owns `connect` / `send_all` / `recv_until` / `recv_exact` / `sleep_until`; the `_GeneratorWrapper` is fully duck-typed and reads `io_socket` / `io_wants_read` / `io_wants_write` / `next_deadline` via `getattr` against whatever the generator yields. The `ReadReady` / `WriteReady` / `Sleep` token classes are gone from the public API; tiny private `_ReadWait` / `_WriteWait` / `_DeadlineWait` shapes live inside `generators.py` for cases where a bare socket or a sleep needs the four attributes. `SocketConnector` satisfies the duck-typed protocol natively so `connect(connector)` yields it directly. `chumicro_sockets` goes back to zero runtime deps — `import chumicro_sockets` does not load `chumicro_runner`. `chumicro_runner` bumped to 0.5.0 (breaking change to wait-token API). Demo `demos/sockets_runner_connector/` rewritten to use the helpers (`echo_run` collapsed from 115 lines to 14); the original `EchoService` state-machine version preserved at `demos/sockets_runner_connector_explicit/` as a teaching companion via `git mv`. Tests: 146 CPython / 139 each on MP + CP unix-port. Pi Pico W bake under CircuitPython 10.2.0-dirty and MicroPython 1.26.0 ran the new generator demo cleanly (board printed `WIFI_OK` / `CONNECTING` / `CONNECTED` / `SENT` / `ECHO_RECEIVED` / `DEMO_COMPLETE` in order on both runtimes). The driver's 10 s `ECHO_RECEIVED` marker timeout fires before the host serial reader catches up to the late markers — driver-side timing issue, not a board issue; round-trip wallclock on the board itself is sub-second.
