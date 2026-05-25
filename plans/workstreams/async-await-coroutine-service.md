# Workstream: async/await syntax via runner.add_coroutine

Status: **proposed** (Decision 0087 accepted 2026-05-25). Implements [Decision 0087](../decisions/0087-async-await-syntax-without-asyncio-module.md).

## Problem

The runner-shaped `check`/`handle` contract reads naturally for reactive services (MQTT keepalive, WiFi state changes, button scans) but is verbose for sequential I/O state machines. The `demos/sockets_runner_connector/app.py` `EchoService` is the canonical case: ~80 lines of explicit state machine — four state strings, three `_handle_*` methods, manual `_send_offset` tracking, three `io_wants_*` properties — for what is conceptually "connect, send, recv, close." First-time custom-protocol authors bounce off the ceremony.

Decision 0087 adopts `async`/`await` syntax inside coroutines registered with `runner.add_coroutine()`, with `import asyncio` banned across `libraries/` / `support/` / `workbench/`. This workstream lands the implementation, the lint enforcement, the socket coroutine helpers, the demo rewrite, and the docs.

## Implementation phases

### Phase 1 — Wait-token vocabulary in `chumicro_runner`

Add `ReadReady(sock)`, `WriteReady(sock)`, `Sleep(until_ms)`, plus a `Done` sentinel in `chumicro_runner` (private module, re-exported at package root). Each has:

- `__await__(self)` — `yield self` (the generator-protocol entry point that makes the token awaitable).
- `ready(self, now_ms) -> bool` — whether the runner should fire `handle()` on the next tick. `ReadReady` / `WriteReady` defer to the socket-readiness check (`ipoll` result); `Sleep` compares `now_ms` against `until_ms`.
- `result(self, now_ms)` — value `.send()`-ed back into the coroutine when it resumes. For `ReadReady` / `WriteReady` this is the sock itself; for `Sleep` it is `now_ms`.

Tests verify the protocol works under both `def` + `yield from` and `async def` + `await` drivers (proves the byte-identity claim from Decision 0087's context evidence; both reduce to the same `mp_obj_gen_resume` path).

`chumicro_runner` `VERSION` patch bump if private-only at this phase, minor bump if public surface lands here.

### Phase 2 — `add_coroutine` adapter

Add `runner.add_coroutine(coro) -> CoroutineHandle` and the internal `_CoroutineWrapper` class that satisfies the runner's check/handle/io_* contract:

```python
class _CoroutineWrapper:
    def __init__(self, coro):
        self._coro = coro
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
            self._wait = self._coro.send(value)
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
```

`CoroutineHandle` is the public face — exposes `.done` and forwards to the wrapper. The wrapper class stays private; users register coroutines via `add_coroutine`, not by subclassing.

Cancellation: when `Runner.remove(handle)` is called or the loop exits, the wrapper calls `self._coro.close()` to fire any `finally` blocks inside the coroutine. Exception path: if a wait-token's `result()` raises (deadline exceeded, socket error), the wrapper calls `self._coro.throw(exc)` so the exception surfaces at the `await` site inside the coroutine.

Steady-state allocation: the wrapper holds two references (`_coro`, `_wait`) and yields one new wait-token per `await` boundary. Verify zero steady-state heap drift via the existing `chumicro_runner` tracemalloc convention.

`chumicro_runner` `VERSION` minor bump.

### Phase 3 — Socket coroutine helpers in `chumicro_sockets`

Add `async def` helpers that wrap the existing connector + socket primitives:

- `connect(host, port, radio)` — wraps `tcp_client_connector`. The connector's tick-driven state machine becomes the inner driver; the coroutine awaits a `ReadReady` / `WriteReady` on the connector's pollable socket until `connector.state == "ready"`, then returns the connected socket. Supports `async with connect(...) as sock:` via `__aenter__` (returns sock) / `__aexit__` (closes sock).
- `send_all(sock, data)` — loops on `sock.send`, awaiting `WriteReady(sock)` on `EAGAIN`. Tracks offset across awaits in the coroutine frame (no explicit attribute needed).
- `recv_until(sock, sep, max_bytes=...)` — loops on `sock.recv_into` into a pre-allocated buffer, awaiting `ReadReady(sock)` on `EAGAIN`, until the separator appears. `max_bytes` caps growth per heap-DoS rules.
- `recv_exact(sock, n)` — similar, returns when N bytes received.

Existing synchronous factories and `tcp_client_connector` stay — these helpers are an additional surface, not a replacement.

`chumicro_sockets` `VERSION` minor bump.

### Phase 4 — Lint rule banning `import asyncio`

Add a CHU rule (next available number; coordinate with `workbench/checks/`) that fails on:

- `import asyncio` anywhere in `libraries/` / `support/` / `workbench/`.
- `from asyncio import …` anywhere in the same trees.
- `import uasyncio` / `from uasyncio import …` (MicroPython alias).
- A module file literally named `asyncio.py` or directory `asyncio/` in those trees.

Workbench is included — the project has no asyncio anywhere; carving out workbench would be a path the project does not need.

Deploy bundle staging (`chumicro-workspace deploy`'s file-tree builder) refuses to copy any module named `asyncio*` to a device — defense in depth if a lint suppression slips through.

The rule's docstring names Adafruit asyncio [issue #4](https://github.com/adafruit/Adafruit_CircuitPython_asyncio/issues/4) and points at [Decision 0087](../decisions/0087-async-await-syntax-without-asyncio-module.md). Suppressions per the AGENTS.md "pair a lint suppression with a brief explanation why" rule.

`workbench/checks` `VERSION` minor bump.

### Phase 5 — Rewrite the `sockets_runner_connector` demo

Replace `demos/sockets_runner_connector/app.py` with the coroutine version (~10 lines using `connect` / `send_all` / `recv_until`). Update the README: opens with the new shape, points at the moved explicit version for readers who want to see the underlying machinery.

`git mv demos/sockets_runner_connector` to `demos/sockets_runner_connector_explicit/` first (preserving the current contents), then create the new `demos/sockets_runner_connector/` with the coroutine version. The explicit version's README updates to frame itself as the teaching companion ("here is what `runner.add_coroutine` + `connect` / `send_all` / `recv_until` do under the hood").

Verify both demos round-trip cleanly on Pi Pico W (CP + MP) and Lolin S2 (CP + MP) — real-board bake per AGENTS.md's "Changes touching I/O require real-board verification" rule.

### Phase 6 — Docs

Update `libraries/runner/README.md` and any library-guide doc that describes service registration — introduce `add_coroutine` as the second sanctioned registration shape alongside `add(service)`, with a one-paragraph "when to pick which" guide (reactive vs. sequential).

Update `docs/contributing/style-guide.md` (or wherever runner-shaped libraries are described) to add `async def` + `await` as legal syntax inside coroutines, with the `import asyncio` ban stated as a hard rule with cross-link to [Decision 0087](../decisions/0087-async-await-syntax-without-asyncio-module.md).

Update `plans/patterns.md` if a "coroutine-as-state-machine" pattern crystallizes from real use — defer if the pattern is just "use the helpers" with nothing else generalizable.

## Validation history

(Append one line per phase as it lands.)
