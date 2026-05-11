# Patterns

> **Note:** This file is primarily for AI agent context recovery — it gives agents a quick reference for implementation patterns without re-reading all the source code. Human contributors should use the [Style Guide](../docs/contributing/style-guide.md) and [Adding a New Library](../docs/contributing/new-library.md) guides instead.

Reusable implementation patterns specific to this codebase.  Follow these
when writing new libraries or modifying existing ones — they were established
because incorrect implementations caused real bugs.

For *why* these patterns exist, see the linked decisions.
For *rules* agents must follow, see `AGENTS.md`.  This file is the *how*.

---

## Service pattern (Runner-compatible)

Libraries that have active components (polling, scheduling, state machines)
implement the `check(now_ms) -> bool` / `handle(now_ms)` contract so they
work with `Runner.add(obj)` (Decision 0014).

```python
class MyService:
    """One-line description.

    Args:
        dependency: Injected dependency.
        interval_ms: How often to act, in milliseconds.
        ticks: Tick source (must have ``ticks_ms``,
            ``ticks_diff``, ``ticks_add``).  Defaults to real clock.
    """

    def __init__(self, dependency: object, interval_ms: int = 1000, ticks: object | None = None) -> None:
        self._dep = dependency
        self._interval_ms = interval_ms
        if ticks is not None:
            self._ticks_diff = ticks.ticks_diff
            self._ticks_add = ticks.ticks_add
            self._next_ms = ticks.ticks_ms()
        else:
            from chumicro_timing import ticks_diff, ticks_add, ticks_ms
            self._ticks_diff = ticks_diff
            self._ticks_add = ticks_add
            self._next_ms = ticks_ms()

    def check(self, now_ms: int) -> bool:
        """Return True if the service should act this tick.

        Args:
            now_ms: Current time in milliseconds.

        Returns:
            True if the interval has elapsed.
        """
        if self._ticks_diff(now_ms, self._next_ms) < 0:
            return False
        self._next_ms = self._ticks_add(now_ms, self._interval_ms)
        return True

    def handle(self, now_ms: int) -> None:
        """Perform the service action.

        Args:
            now_ms: Current time in milliseconds.
        """
        # ... do work ...
```

Wire into Runner:

```python
from chumicro_runner import Runner

runner = Runner(ticks=fake_ticks)  # or Runner() for real clock
runner.add(service)  # Runner calls service.check(), then service.handle()
# ... or use callables:
runner.add(service.check, handler=some_function)
# ... or periodic without a check gate:
runner.add_periodic(handler, period_ms=100)
```

Existing example: `Heartbeat` does not implement `check`/`handle`
(it predates the Runner), but it demonstrates the constructor
injection and `ticks` protocol patterns that Runner-compatible
services should follow.

Related: Decision 0014, `libraries/runner/src/chumicro_runner/core.py`.

## Static recv buffer + memoryview window

Networking and serialization code that runs on a small-heap board MUST
own its recv buffer instead of allocating one per tick / per call.  The
shape is: pre-allocate a fixed `bytearray` once at construction time;
hand out `memoryview` slices for `recv_into` / `extend` / parser feed
calls.  Each tick reuses the same backing buffer.

```python
# ✅ Static buffer — no per-tick alloc, no fragmentation
class Driver:
    def __init__(self, recv_budget_per_tick=1024):
        self._recv_buffer = bytearray(min(recv_budget_per_tick, 512))
        self._recv_view = memoryview(self._recv_buffer)

    def _drive_recv(self):
        cap = len(self._recv_buffer)
        got = self._socket.recv_into(self._recv_view[:cap], cap)
        if got > 0:
            self._parser.feed(self._recv_view[:got])  # zero-copy

# ❌ Per-tick alloc — invisible on host, fragments small-heap boards
class Driver:
    def _drive_recv(self):
        scratch = bytearray(512)                  # alloc every tick
        got = self._socket.recv_into(scratch, 512)
        self._parser.feed(bytes(scratch[:got]))   # second alloc copy
```

The pattern has two parts that both matter:

1. **Pre-allocate the recv buffer at construction.**  A 1024-byte fresh
   `bytearray` per tick lands a block in the 1024-byte allocator tier;
   when the block frees and the next tick allocates, the allocator may
   not reclaim the same slot, so the tier's free-block count drifts
   downward — that's the on-device fragmentation signal.

2. **Pass `memoryview(buffer)[:n]` instead of `bytes(buffer[:n])` to
   the consumer.**  `bytes(buffer[:n])` does *two* allocations: the
   slice creates a new `bytearray`, then `bytes()` copies it again.
   `memoryview[:n]` is zero-copy.  Parsers / decoders that copy what
   they keep (into a private `_buffer` or `_body`) before returning
   are memoryview-safe — the view's lifetime ends with the call.

Required when: code lives under `libraries/*/src/` AND owns a recv
loop or a per-call hot-path scratch buffer.  Not required when: the
allocation is genuinely one-shot (handshake key, request packet
built once and sent), or the runtime can't avoid it (MP's
`recv` polyfill in `chumicro_sockets._adapters.mp` returns a fresh
`bytes` because MP doesn't expose `recv_into` on every socket type).

Existing examples:

* `chumicro_mqtt._wire.PacketDecoder` — `fill_buffer()` returns
  `memoryview(self._buffer)[self._buffer_length:]`; the MQTT client's
  recv loop (`client._handle_recv`) uses it directly.  Reference
  implementation borrowed from the basefs MQTT client.
* `chumicro_websockets._session.WebSocketSession` — `_recv_buffer` +
  cached `_recv_view` allocated once in `__init__`.
* `chumicro_requests.client.HttpClient` and
  `chumicro_http_server.server._Connection` — same shape.
* `chumicro_ntp.core.NTPClient` — pre-allocated `_recv_buffer` sized
  to the SNTP packet (48 bytes).
* `chumicro_kvstore._backends.mp_nvs.MpNvsBackend` — pre-allocated
  `_read_buffer` sized to the configured capacity, passed to
  `esp32.NVS.get_blob` as the destination.

Companion: when a parser has a "consume bytes from the front" pattern
(HTTP headers, websocket handshake), use the **read-cursor pattern**
from `chumicro_requests._wire.ResponseParser._consume` so the per-line
`self._buffer = bytearray(self._buffer[N:])` reassignment doesn't
churn small-tier blocks.  The cursor amortizes the bytearray
reallocation to one per ~half buffer of consumption, and is
cross-runtime safe (CP rejects `del bytearray[:n]`, MP lacks
`bytearray.clear()`).

## `_buf` + cached `_buf_view` for accumulating data

Every long-lived bytearray that gets sliced more than once should ship
with a cached `memoryview` companion.  Construct the view once at the
same time as the bytearray; refresh the view only when the underlying
bytearray rebinds or extends.

```python
# ✅ Cached view — one memoryview struct alloc, reused
class Parser:
    def __init__(self, capacity=256):
        self._body = bytearray(capacity)
        self._body_view = memoryview(self._body)
        self._body_write_offset = 0

    @property
    def body(self):
        # One bytes(N) copy; the slice through _body_view is zero-copy.
        return bytes(self._body_view[:self._body_write_offset])

# ❌ Per-access memoryview — small struct alloc on every property read
@property
def body(self):
    return bytes(memoryview(self._body)[:self._body_write_offset])

# ❌❌ Double-copy — bytearray slice copies, then bytes() copies again
@property
def body(self):
    return bytes(self._body[:self._body_write_offset])
```

**Refresh discipline.**  The cached view holds an export of the
underlying bytearray.  CPython refuses to resize a bytearray with a
held export (`BufferError: Existing exports of data: object cannot
be re-sized`); MicroPython doesn't track exports but a stale
`memoryview` after a resize points at freed memory and may read
garbage.  So before any operation that *might* extend or rebind the
underlying bytearray:

```python
self._body_view = None  # release the export (CPython); MP no-op
self._body.extend(chunk)  # or `self._body = bytearray(N)` rebind
self._body_view = memoryview(self._body)  # refresh
```

Detect "might extend" via `end_offset > len(self._body_view)` — the
cached view's length equals the bytearray capacity at construction
time, so a write past it implies a resize.  In-place writes that fit
inside the existing buffer don't invalidate the view.

## Reuse buffers; only allocate fresh when the size genuinely changes

Per-frame / per-iteration `bytearray(N)` allocations are worse than
holding onto a fixed-size buffer that handles the common case, even
when the steady-state buffer pins more bytes than the workload needs.
On CircuitPython and MicroPython small-heap allocators, `bytearray.extend`
is essentially "alloc bigger, copy old, copy new, free old" — three
allocations per logical write — whereas a fixed buffer with slice-assign
(`buf[a:b] = data`) is one in-place memcpy.  And tear-down/realloc
cycles fragment the heap.

The shape:

* Pre-allocate a steady-state buffer at construction, sized to handle
  the **common** case — not the maximum.  Pick a default that covers
  ~80–95 % of expected payloads (e.g. 256 B for short text frames,
  1024 B for typical HTTP headers).
* When a request fits in the steady-state buffer, **reuse** it via
  slice-assign.  Track logical length with a write cursor
  (`_write_offset`); the bytearray's `len()` stays at capacity.
* When a request *exceeds* the steady-state capacity, allocate a
  one-shot `bytearray(actual_size)` for that request only.  Drop it
  on the next reset / done state and rebind the active reference back
  to the steady-state buffer.

```python
# ✅ Steady-state + one-shot oversized
class FrameParser:
    def __init__(self, *, payload_buffer_size=256):
        self._payload_buffer = bytearray(payload_buffer_size)
        self._payload_buffer_view = memoryview(self._payload_buffer)
        self._payload_capacity = payload_buffer_size
        # Active references — alias the steady-state buffer by default.
        self._payload = self._payload_buffer
        self._payload_view = self._payload_buffer_view
        self._payload_write_offset = 0

    def _after_mask(self):
        if self._payload_length > self._payload_capacity:
            # Oversized — one-shot allocation just for this frame.
            self._payload = bytearray(self._payload_length)
            self._payload_view = memoryview(self._payload)
        # else: keep aliasing the steady-state buffer (no alloc).
        self._payload_write_offset = 0

    def reset(self):
        # Rebind to steady-state — drops any one-shot from the prior frame.
        self._payload = self._payload_buffer
        self._payload_view = self._payload_buffer_view
        self._payload_write_offset = 0
```

This applies anywhere in library code that handles repeated
work-of-similar-shape: per-frame, per-tick, per-message, per-request
(when the parser is reused).

When *not* to apply: per-instance buffers where the instance itself is
short-lived (HTTP `ResponseParser` is constructed per request and
discarded — pre-allocating to exact `Content-Length` upfront is the
right call there because there's no reuse cycle to amortize over).

## `struct.unpack` accepts memoryview directly

`struct.unpack(fmt, view[a:b])` works on every supported runtime — no
`bytes()` wrap needed.  The wrap costs one bytearray copy per integer
field, which adds up across a parser's hot path:

```python
# ✅
length = struct.unpack(">H", view[0:2])[0]

# ❌ — costs one tier-2 alloc per call
length = struct.unpack(">H", bytes(view[0:2]))[0]
```

This applies wherever the parser already holds a memoryview into the
input buffer (`PacketDecoder._buffer_view` in `chumicro_mqtt`,
`_body_view` in the HTTP parsers, etc.).  When you genuinely need
bytes for a downstream `.decode("utf-8")` or hashing, the wrap stays
— memoryview lacks `.decode()`.

## `__slots__` on MicroPython and CircuitPython

`__slots__` does not save memory on the runtimes that matter for
ChuMicro.  MicroPython has no `__slots__` implementation
([discussion #13745](https://github.com/orgs/micropython/discussions/13745))
— the syntax parses without error but the instance still gets a regular
`__dict__`, so per-instance memory is identical to a plain class.
CircuitPython inherits this.  Only CPython actually drops the per-instance
dict and locks the attribute set.

So when you see `__slots__` in chumicro library code today
(`chumicro_mqtt._wire.PacketPublish`, `chumicro_requests.client.HttpClient`,
`chumicro_runner.core.Runner`, etc.) the value it provides is **CPython-test
attribute locking**, not on-device RAM savings — typo'd attribute writes
(`self.feild = ...`) fail loudly under CPython's `pytest` instead of
silently creating a new attribute.

Audit guidance:

* **New classes:** don't add `__slots__` reflexively.  Add it only when
  CPython-test attribute-locking is the deliberate goal (a class with
  many similarly-named fields where a typo would silently shadow a real
  attribute and pass tests by accident).
* **Existing usages:** not a regression — leave them.  A coordinated
  removal pass is on the work queue when audit-embedded gets run on each
  library.
* **In docstrings or comments:** never write "`__slots__` saves memory"
  / "`__slots__` keeps the instance lean."  False on MP and CP — and
  the comment ships in the source distribution.

```python
# ✅ Locks attribute names so a typo in tests doesn't silently shadow
class PacketPublish:
    __slots__ = ("packet_id", "payload", "qos", "retain", "topic")

# ✅ Plain class — same on-device RAM, slightly less ceremony
class PacketPublish:
    pass  # attributes assigned in __init__
```

The audit angle is in
[`.github/skills/audit-embedded/SKILL.md`](../.github/skills/audit-embedded/SKILL.md)
§7 ("Code shape for embedded" → "`__slots__` reality").

## Constructor injection

Accept dependencies (time, I/O, network) as constructor parameters.  Never
import hardware modules at the top level of library code (Decision 0010).
Use a lazy import in the `else` branch so the module only loads when no
fake is provided.

```python
# ✅ Injectable — testable with fakes, lazy hardware import
class Sensor:
    """Hardware sensor with injectable I2C and tick dependencies."""

    def __init__(self, i2c: object | None = None, ticks: object | None = None) -> None:
        if i2c is not None:
            self._i2c = i2c
        else:
            import board, busio
            self._i2c = busio.I2C(board.SCL, board.SDA)
        if ticks is not None:
            self._ticks_ms = ticks.ticks_ms
        else:
            from chumicro_timing import ticks_ms
            self._ticks_ms = ticks_ms
```

```python
# ❌ Hard-wired — untestable, fails on CPython
import board
import busio

class Sensor:
    def __init__(self) -> None:
        self._i2c = busio.I2C(board.SCL, board.SDA)
```

Existing examples: `Heartbeat(ticks=None)` and `Runner(ticks=None)`
both use this exact pattern — accept an optional ticks object, fall
back to a lazy import of the real module.

Related: Decision 0010, `libraries/timing/src/chumicro_timing/heartbeat.py`.

## Test fakes as `testing` submodules

Ship fakes alongside production code in `src/chumicro_<name>/testing.py`.
Downstream libraries import them directly (Decision 0010).

```python
# In src/chumicro_mylib/testing.py
class FakeBackend:
    """Test fake for Backend protocol.

    Provides call recording and deterministic behavior for tests.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def read(self) -> bytes:
        """Return an empty response and record the call."""
        self.calls.append("read")
        return b""
```

```python
# In downstream tests
from chumicro_mylib.testing import FakeBackend
```

If the library has nothing worth faking, delete `testing.py` and its
references (see `new-library` skill § 4).

**Per-package fakes, not a shared abstractions package:** Each package
owns its own test fakes in its `testing.py` submodule.  Cross-package
sharing would require either a published support package (extra release
overhead) or duplicating ~80 lines per consumer — and since the only
fakes that recur are tiny, duplication beats the abstraction tax.

Concrete examples in the workspace today:

- `chumicro_timing.testing.FakeTicks` — millisecond-tick fake used by
  the timing library and re-imported by `chumicro_runner` tests.
- `chumicro_deploy.testing.FakeTime` — seconds-domain time fake for
  `CircuitpythonTransport`'s injectable time source; lives next to
  `FakeTransport` and `FakeSerialPort` so a downstream `pip install
  chumicro-deploy` user gets a complete test-fakes set.

These are different fakes for different domains (ms-tick on device vs
seconds-monotonic on host), not two implementations of one thing.  If
a future package needs seconds-domain on device, it copies the ~80
lines into its own `testing.py` rather than introducing a shared
abstractions package.

Related: Decision 0010, `new-library` skill.

## Cross-runtime shim

When a module exists on CPython but not on MicroPython/CircuitPython
(or vice versa), write a thin shim with runtime detection.

```python
try:
    from micropython import const
except ImportError:
    def const(value: int) -> int:
        """Identity fallback so const() works on CPython."""
        return value
```

For larger differences (e.g., `socketpool` vs `socket`), create a
dedicated shim module that detects the runtime and re-exports a
consistent API.  Keep function names aligned with CPython's stdlib.

Related: `libraries/compat/`, Decision 0007.

## Missing builtins on MicroPython 1.28

MicroPython 1.28 doesn't ship every CPython exception builtin.  In
particular, **`TimeoutError` is not a builtin** — `raise TimeoutError(...)`
in cross-runtime code (`libraries/*/src/`, `support/test_harness/src/`,
`libraries/*/examples/helpers.py`) raises `NameError: name 'TimeoutError'
isn't defined` on MP.  Works on CPython + CircuitPython, breaks on MP.

Established workarounds in this codebase:

1. **Library code: subclass your own library-specific exception.**
   `chumicro_requests` defines `HttpTimeoutError(HttpError)` and raises that
   on request timeouts.  `chumicro_websockets` defines
   `WebSocketTimeoutError(WebSocketError)` and raises that.  Both work
   identically on every runtime because the base class is library-defined,
   not borrowed from builtins.  This is the preferred shape for new
   library code — callers can pattern-match the library type without
   relying on the runtime's builtin set.

2. **Helpers / glue code: use `OSError` directly.**  When the library
   doesn't have its own exception hierarchy yet (e.g. example
   `helpers.py` files doing wifi-up timeouts), `raise OSError("wifi
   did not connect within ...")` is a one-line workaround that's a
   CPython builtin AND an MP builtin AND a parent class of the
   CPython `TimeoutError` — so callers catching `OSError` keep
   working when this code later gets refactored to subclass
   properly.  Pattern in use across the 6 `libraries/*/examples/helpers.py`.

3. **Local re-define if you really need the name `TimeoutError`.**
   `class TimeoutError(OSError): ...` at module scope shadows the
   missing builtin on MP and matches the existing one on CPython +
   CP (since CPython's `TimeoutError` is also an `OSError` subclass).
   No callers want this today — the pattern is documented for
   completeness.

Don't add a `TimeoutError` polyfill to `chumicro_compat`.  A 2026-05-10
survey found zero callers wanting bare `TimeoutError` — every library
that has a timeout concept already defines its own subclass.  A
compat polyfill would be public API surface with no consumers.

If a future change adds bare `raise TimeoutError(` in cross-runtime
code, `chumicro-checks` would be the right home for a lint rule that
catches it.  Not shipped today; add when the regression first appears.

## Backend protocol (duck-typed)

When a library needs swappable implementations (storage backends,
transport layers), define the protocol as documentation — not as an
ABC.  Implementations duck-type the interface.

The ticks injection in `chumicro-timing` is the existing example:
`Heartbeat(ticks=obj)` and `Runner(ticks=obj)` accept any object
with `ticks_ms()`, `ticks_diff()`, and `ticks_add()` methods.
`FakeTicks` duck-types this protocol for tests.  The protocol is
documented in the constructor docstring, not enforced by a base class.

For libraries that need storage or I/O backends (e.g., the planned
settings library), apply the same approach:

```python
# Document the protocol in the constructor docstring:
#
#   backend must implement:
#     read() -> bytes    — return stored data
#     write(data) -> None — persist data
#
# Implementations: NvmBackend, FileBackend, MemoryBackend

class Settings:
    """Key-value settings backed by a pluggable storage backend."""

    def __init__(self, backend: object, defaults: dict[str, object] | None = None) -> None:
        self._backend = backend
        # ...
```

Provide a `MemoryBackend` or similar in-memory implementation for
tests.  Ship it in `testing.py`.

Existing examples:
- `chumicro_timing.testing.FakeTicks` — duck-types the ticks protocol
- `chumicro_runner.testing.CallRecorder` — duck-types the handler callable

Related: Decision 0010 (prefer provided fakes over ad-hoc mocks), settings
library design in `next-up.md`.

## FIFO queues use `deque`, not `list`

Any internal FIFO queue in library code uses `collections.deque(iterable, maxlen)`
rather than a plain `list`.  `list.pop(0)` is O(n) — every element shifts down
one slot — and on small VMs the per-pop reallocation also fragments the heap.
`deque` makes both `append` and `popleft` O(1) and the deque's native
`maxlen` enforcement gives drop-oldest behaviour for free.

```python
from collections import deque

# Bounded queue — drops oldest on overflow.
self._queue = deque((), capacity)

# Hot-path append — O(1), auto-drops oldest at maxlen.
if len(self._queue) >= self._capacity:
    self._dropped += 1   # count drops; the deque does the drop itself
self._queue.append(record)

# Drain — O(1) per popleft.
while self._queue:
    record = self._queue.popleft()
    ...

# Reset — reassign rather than calling .clear().  MicroPython's deque
# does not implement clear() in every build.
self._queue = deque((), self._capacity)
```

**Cross-runtime portability:**

- Constructor signature **must be positional**: `deque(iterable, maxlen)`.
  MicroPython rejects keyword `maxlen=`.  Pass an empty iterable like
  `()` or `[]` to start empty.
- Methods used safely on all three runtimes: `append`, `popleft`, `__len__`,
  iteration, indexing.  `clear()` and `appendleft` / `pop` (right-pop) are
  patchy on MP — avoid them.
- The deque's `maxlen` enforces drop-oldest at append time without any
  explicit pop.  Track the drop count in a sibling `_dropped` integer if
  the count is part of the public surface (chumicro-events and
  chumicro-logging both expose this).

Used today by: `chumicro-events.EventBus._queue`,
`chumicro-logging.BufferedHandler._buffer`.  Apply the same pattern to any
new bounded FIFO — including subscriber backlogs, request queues, and tick
buffers.  Subscriber lists keyed by topic are *not* FIFO and stay as
`list` (membership matters more than head/tail performance).

#### Audit results (2026-04-27)

Codebase-wide grep for `pop(0)` / `insert(0, ...)` in `libraries/*/src/`
returns exactly one runtime-side genuine candidate:

* **`libraries/mqtt/src/chumicro_mqtt/client.py` `_tx_queue`** — list
  with `pop(0)` (FIFO drain, 3 sites), `insert(0, ...)` (PUBACK
  priority head-prepend, 2 sites), `[0]` peek, `clear()`, and
  unbounded `append()`.  Hot path on every `handle()` tick.
  Migration is straightforward but has two subtle implications
  worth a focused commit:

  - **PUBACK ordering** — `insert(0, ...)` becomes `appendleft(...)`
    requiring `deque((), maxlen, flags=1)` on MP/CP.  Verified on
    both unix ports: `flags=1` is supported.  PUBACK semantics must
    survive the migration unchanged (validated by
    `functional_tests/test_real_broker.py`'s QoS 1 round-trip).
  - **Retry / PINGREQ backpressure** — today's list-backed code
    enforces `_max_tx_queue_size` only on the public `_enqueue`
    path; retry / PINGREQ append unconditionally and grow the list
    past max.  Migrating to `deque(maxlen=_max_tx_queue_size)` would
    silently drop the oldest on overrun — wrong semantics for QoS 1
    retry (drops in-flight packets to make room for an older retry).
    Use `maxlen=_max_tx_queue_size + 64` for headroom, keeping the
    existing `len() >= max` check as the sole enforcement mechanism.

  Tracked as a follow-up (see `plans/next-up.md`); not migrated in
  the audit pass because the MQTT functional test suite needs a
  real-broker fixture and the corner cases warrant their own commit.

Patterns that are *not* candidates:

* **`libraries/*/testing.py` fakes** (`wifi`, `requests`).  Never
  ship to devices — testing.py is excluded from per-runtime mpy
  bundles.  CPython-only host-side tests; `list.pop(0)` cost is
  irrelevant.
* **`libraries/*/examples/*.py`** — examples favor clarity over
  micro-optimization; running on tiny test data on CPython.
* **`workbench/deploy/src/chumicro_deploy/sources.py:239`** —
  workbench is CPython-only; deque on a single import-graph walk
  saves nothing.

Related: workstream 2026-04-27 micro-benchmark, the deque support
verification in `plans/workstreams/library-pipeline.md`.

## mpremote internals we depend on

`MicropythonTransport` is a thin layer over the vendored
`mpremote.transport_serial.SerialTransport`.  Several behaviours of
that class are undocumented upstream and have bitten us before — they
are captured here so future edits do not unwittingly re-break them.

### 1. `exec_raw` returns a tuple, not bytes

```python
stdout_bytes, stderr_bytes = serial_transport.exec_raw(code)
```

`SerialTransport.exec_raw` returns a `(stdout, stderr)` tuple of
`bytes`, not a single `bytes` object.  `MicropythonTransport.execute()`
unpacks both halves, decodes each, and concatenates stdout + stderr so
tracebacks surface in the captured output.  A belt-and-suspenders
`isinstance(result, bytes)` branch is kept for future mpremote API
drift.  Commit `41f5391`.

### 2. `mount_local` wraps every call

Calling `SerialTransport.mount_local(...)` wraps `self.serial` in a
`SerialIntercept` **every time it's invoked** — not idempotently.  A
second call produces `SerialIntercept(SerialIntercept(raw))` and
corrupts every subsequent I/O (even a bare `import` fails).

Invariants:

- `umount_local` must run *before* any Ctrl-D soft-reset — after
  the reset, the device globals are gone, and a later `umount_local`
  would try to run `os.umount(...)` with `os` no longer imported.
- `soft_reset()` does not re-mount.  The mount is owned by
  `stage()`, which is the next orchestration step and re-mounts
  once cleanly.

Commit `5698100`.

### 3. Don't `mpremote reset` between test batches

`mpremote reset` cycles the USB stack on the board.  The next
`mpremote` invocation then connects before the port is ready and
fails with `"Device not configured"`.  mpremote already spawns a
fresh subprocess per `exec_raw()` call, so test isolation is
automatic on the MicroPython path — `soft_reset()` is a
CircuitPython-only operation (both RAM and flash modes) where the
persistent raw-REPL session would otherwise accumulate modules in
`sys.modules` across calls.  Commit `cd9fe3b`.

### 4. Hold one `SerialTransport` per session

Creating a fresh mpremote subprocess per file costs ~2–3 s on most
boards — the floor is the serial connect handshake, not the actual
`exec`.  `MicropythonTransport` keeps a single
`SerialTransport` instance alive across the session and routes
every `execute()` through it.  Combined with bulk rsync (one pass
for all files, not per-file), this brought the "per MP test file"
floor from seconds to milliseconds.  Commits `9e6174c` + `cb4efa9`.

Related: Decision 0027 (device testing infrastructure), Decision 0028
(deploy modes).

## Subprocess binary resolution (host tools)

Rule + code shape live in [Style Guide § Subprocess binary resolution](../docs/contributing/style-guide.md#subprocess-binary-resolution-host-tools).
Canonical implementation: `MicropythonTransport._run_mpremote` (commit `e4f669e`).
Apply the pattern to any new host-side shell-out to `mpremote` / `esptool` / `rshell` / `ampy`.

## Lazy module-level imports via PEP 562 `__getattr__` (workbench)

**Workbench-only in practice.**  PEP 562's `module __getattr__` is
implemented at the firmware level on both MP and CP (verified in
the pinned source — `MICROPY_MODULE_GETATTR` default-on at the
`CORE_FEATURES` ROM level), but the **deploy harness's
CircuitPython RAM-mode path wraps the package in a class-as-module
stub that silently bypasses PEP 562**.  Lookups hit the stub's
`__dict__` directly without calling `__getattr__`, so the lazy attr
table just doesn't fire.  MP + the unix-ports both honor PEP 562
correctly; only CP RAM-mode is affected — but that's the
canonical deploy path for chumicro libraries.

The pattern is **safe for workbench packages** (`chumicro-deploy`,
`chumicro-repl`) because they're CPython-only.  For device
libraries (anything under `libraries/*/src/`), use per-function
lazy imports instead — see "Per-function lazy adapter selection"
below, which works everywhere.

History: surfaced 2026-04-25 during chumicro-wifi Slice 0
hardware bring-up; the lazy-loading research doc carries the
detail.  The earlier "cross-runtime by design" framing was
correct at the firmware level but missed the harness wrapper.

When a package has multiple submodules where users typically reach
for a subset, defer submodule imports until first attribute access:

```python
# In src/chumicro_<name>/__init__.py — minimum shape.
def __getattr__(name: str) -> object:
    if name == "Deployer":
        from chumicro_deploy.deployer import Deployer
        return Deployer
    if name == "Device":
        from chumicro_deploy.device import Device
        return Device
    raise AttributeError(f"module 'chumicro_deploy' has no attribute {name!r}")
```

For libraries with more than ~5 lazy attributes, prefer the
**`_LAZY_ATTRS` dict + `__getattr__` table** shape used in
`chumicro_deploy/__init__.py:94`:

```python
_LAZY_ATTRS: dict[str, str] = {
    "Deployer": "deployer",      # public name -> submodule name
    "Device":   "device",
    # ...
}

__all__ = [...]   # literal list so static type checkers see it
assert sorted(__all__) == __all__, "__all__ must be alphabetized"
assert set(__all__) == set(_LAZY_ATTRS), "__all__ must match _LAZY_ATTRS"


def __getattr__(name: str) -> object:
    module_name = _LAZY_ATTRS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value     # cache so subsequent accesses are O(1)
    return value


def __dir__() -> list[str]:
    return [*globals().keys(), *_LAZY_ATTRS.keys()]
```

A `TYPE_CHECKING`-guarded import block above the table preserves
static-analysis support (pyright sees every name; runtime resolution
still goes through the lazy hook).  The `__dir__` shadow keeps
introspection tools (`dir()`, REPL completion) working.

**When to use this pattern (Tier B libraries):**

- Per-runtime adapters under `_adapters/` or `_backends/` (the kvstore
  template) — adopt for any library that ships >1 adapter and selects
  one at construction.
- Optional features the user may never reach for.
- ~5+ public attributes spread across submodules.

**When eager imports are correct:** small-surface libraries (≤2
modules, no per-runtime adapters), tightly-coupled submodules
(`chumicro-timing` always uses both `heartbeat` and `ticks`), and
hot-path code where lazy first-use overhead would show up as a tick
spike.  See `plans/workstreams/lazy-loading-research.md` for the
full Tier A vs Tier B classification.

Existing names (e.g. `from chumicro_deploy import Deployer`) keep
working — Python's attribute lookup falls through to `__getattr__`
after the module's own globals are exhausted.  The deferred imports
run once on first access; subsequent accesses are O(1) via the
`globals()[name] = value` cache.

Applied to `chumicro_deploy/__init__.py` and
`chumicro_repl/__init__.py` (commits `11952f0` workbench review-
sweep).  `chumicro-deploy`'s `device.py` defers transport imports
into `create_transport()` for the same reason; `chumicro-kvstore`'s
`_select_backend` does the equivalent for runtime adapter
selection.

Related: lazy-loading-research workstream, Decision 0010
(constructor injection — same "defer the cost" philosophy at the
class-instance scope).

## Per-function lazy adapter selection (cross-runtime safe)

Use this for **device libraries with per-runtime adapters** —
the cross-runtime-safe alternative to module-level PEP 562 (which
the CP RAM-mode harness silently bypasses, see the section above).
Goes inside a selector function the user reaches via construction:

```python
# In src/chumicro_<name>/service.py (or wherever the selector lives)
import sys

from chumicro_<name>._adapters.fake import FakeAdapter   # eager; the host fallback
from chumicro_<name>._adapters.base import BaseAdapter   # eager; the protocol


def _select_adapter():
    """Pick the runtime-appropriate adapter at construction time."""
    runtime_name = sys.implementation.name
    if runtime_name == "circuitpython":  # pragma: no cover - CP runtime path
        from chumicro_<name>._adapters.cp import CpAdapter
        return CpAdapter()
    if runtime_name == "micropython":  # pragma: no cover - MP runtime path
        try:
            import esp32  # noqa: F401
        except ImportError:
            from chumicro_<name>._adapters.mp_rp2 import MpRp2Adapter
            return MpRp2Adapter()
        from chumicro_<name>._adapters.mp_esp32 import MpEsp32Adapter
        return MpEsp32Adapter()
    return FakeAdapter()
```

**Why this works on every runtime where module ``__getattr__``
doesn't:** the named ``from X import Y`` statement inside the
function body is compiled into the runtime's standard import
machinery — invoked once when the function runs, resolved via the
package loader the harness already understands.  The class-as-
module wrapper that breaks PEP 562 doesn't sit between the user
and an explicit submodule import.

**`# pragma: no cover` for the CP / MP branches:** they can't be
exercised from CPython tests; coverage is instead provided by the
per-runtime functional suites that exist for each adapter.  Test
the *selection* logic with a `monkeypatch.setattr(sys, ...)` test
or by injecting a concrete adapter via the public constructor's
`adapter=` kwarg.

**Adopted by:** `chumicro_kvstore._select_backend` (4 backends),
`chumicro_wifi.service._select_adapter` (4 adapters,
hardware-verified Phase 3a Slice 0).  Future libraries with
adapter sets (sockets, mqtt, sensor drivers) follow the same
shape.

Related: lazy-loading-research workstream §"Cross-runtime support",
Decision 0010 (constructor injection lets tests bypass the
selector entirely via injected fakes).

## StrEnum as a backwards-compatible shim for stringly-typed args

When a parameter has historically accepted plain strings (`Device(transport="circuitpython")`) and you want to introduce an enum without breaking every call site, use `enum.StrEnum`. StrEnum members compare equal to their string value, so existing string literal call sites keep working unchanged while new code can use the enum for autocomplete + typo prevention.

```python
from enum import StrEnum

class Runtime(StrEnum):
    MICROPYTHON = "micropython"
    CIRCUITPYTHON = "circuitpython"

# Old call site (still works):
Device(transport="circuitpython")

# New call site (preferred):
Device(transport=Runtime.CIRCUITPYTHON)

# Both compare equal:
assert Runtime.CIRCUITPYTHON == "circuitpython"
```

Applied to `Runtime` / `DeployMode` / `ReflashMethod` in `chumicro_deploy/protocol.py` (commit `11952f0`).

Caveats: `StrEnum` is Python 3.11+ stdlib. For older Pythons or for embedded code, this pattern doesn't apply — `chumicro-deploy` is workbench-only (CPython 3.11+) so it's safe there. Do not use this on `libraries/` code that targets CircuitPython / MicroPython.

## IDE Testing-panel "show-but-deselect" for hardware-gated tests

When you have hardware-gated tests under a path like `functional_tests/` that should be:

- **invisible** in the IDE Testing panel for fresh clones (no devices configured),
- **visible** in the IDE Testing panel once `devices.yml` exists, so the gutter ▶ button works on individual test functions,
- **never run** in a default sweep (`pytest` from rootdir, "Run All Tests" in IDE), because they touch real hardware,
- **fully run** when the user explicitly clicks gutter ▶ on a single test or names a `functional_tests/` path on the command line.

Pattern: a paired `pytest_ignore_collect` + `pytest_collection_modifyitems` in the root `conftest.py`.

```python
# Allow collection only when (a) devices.yml exists, or (b) the user explicitly
# named a functional_tests path in argv.
def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    if "functional_tests" not in collection_path.parts:
        return None
    if _devices_yml_exists() or _explicit_functional_target(config):
        return False  # allow
    return True       # hide

# Even when collected, deselect functional_tests items unless an explicit
# functional_tests/ path is in argv.
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _explicit_functional_target(config):
        return
    deselected = [item for item in items if "functional_tests" in Path(item.fspath).parts]
    if deselected:
        for item in deselected:
            items.remove(item)
        config.hook.pytest_deselected(items=deselected)
```

Result: VS Code / PyCharm Testing panels paint the tree with gutter ▶ buttons on every functional test the user can see in `devices.yml`. Bare `pytest` from rootdir does host tests only. Click ▶ on one test → its path lands in argv → deselection skipped → run executes against the device. Commit `73e9270`.

Related: Decision 0027, the `chumicro-pytest-device` plugin (which owns the actual device routing once a functional test is selected).

