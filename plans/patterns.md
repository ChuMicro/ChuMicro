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
# ... or a bare handler on a schedule (the separate check+handler
# shape was removed and raises ValueError; gate inside the handler
# or give the object both check() and handle()):
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
* `chumicro_websockets._session._BaseSession` — `_recv_buffer` +
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

## Two hidden per-tick allocators on MP/CP: `list.clear()` and method `getattr`

Two hot-path shapes that look allocation-free on CPython allocate on
every tick on MicroPython and CircuitPython:

* **`list.clear()` shrinks the backing array.**  Both runtimes
  `m_renew` the item buffer down to 4 slots on `clear()`
  (`py/objlist.c`, `LIST_MIN_ALLOC`), so a scratch list cleared per
  tick re-grows — and re-allocates — every tick once it holds 5+
  items.  Reuse the list as a high-water buffer instead: overwrite
  slots up to a cursor, `append` past the end, and blank the used
  slots to `None` rather than clearing.  `Runner.tick`'s `_pending`
  is the worked example.
* **`getattr(obj, "method")` mints a bound method per call**
  (`py/objboundmeth.c` heap-allocates the binding).  A duck-typed
  hook resolved with `getattr` inside a per-tick or per-wait loop is
  a steady allocation.  Resolve once at registration time and cache
  the bound method (`TaskHandle.io_interest` / `next_deadline`), or
  once per state change (`_GeneratorWrapper`'s wait hooks).  Reading
  a plain data attribute through `getattr` is fine — only method
  lookup allocates.

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

## Allocation tests: `tracemalloc` catches leaks, `gc.mem_alloc` catches churn

A CPython `tracemalloc` test that reads `get_traced_memory()[0]` after
`gc.collect()` measures *net-retained* bytes — what survived the
collection.  That catches a leak (a buffer growing unbounded, a cached
object re-allocated and stashed each call).  It does **not** catch
per-iteration churn: a `view[offset:]` slice or an f-string built and
dropped inside the loop is freed by refcount the same tick, so it never
appears in a post-collect snapshot.  A test that asserts "no per-iteration
allocation" with this method is a leak detector wearing the wrong label —
it passes whether or not the hot path churns.

```python
# Leak guard (host, valid): retained bytes stay flat across N iterations.
gc.collect(); base = tracemalloc.get_traced_memory()[0]
for _ in range(500): operation()
gc.collect(); assert tracemalloc.get_traced_memory()[0] - base < 2048

# Churn guard (the zero-alloc contract): bytes allocated between two
# points with the collector off — MicroPython / CircuitPython only.
gc.collect(); gc.disable()
before = gc.mem_alloc()
for _ in range(1000): tick()
assert gc.mem_alloc() - before <= 64
gc.enable()
```

**Why:** `gc.mem_alloc()` is an MP / CP API; CPython has no equivalent, so
the steady-state zero-allocation contract is a device-runtime check, not a
host one.  Keep the host `tracemalloc` lane — it catches genuine leaks
cheaply — but scope its docstring to "retained growth," never "nothing per
iteration."  Same trap as the import-ordering note below: the convenient
host metric (peak RAM, net-retained) isn't the one that bites on the small
allocator (fragmentation, churn).

## Device-library scaffolding cost — `__slots__` and pure-passthrough `@property`

Two CPython idioms that read as "good Python hygiene" land as dead flash
on the runtimes ChuMicro actually targets.  Per
[Decision 0065](decisions/0065-device-library-scaffolding-cost.md), both
are banned in `libraries/*/src/`; workbench packages may use them at
their author's discretion because they run on the laptop where the
CPython payoff is real.

### `__slots__`

MicroPython has no `__slots__` implementation
([discussion #13745](https://github.com/orgs/micropython/discussions/13745))
— the syntax parses without error but the instance still gets a regular
`__dict__`, so per-instance memory is identical to a plain class.
CircuitPython inherits this.  Only CPython actually drops the per-instance
dict and locks the attribute set, and that payoff is CPython-test
attribute locking (typo'd `self.feild = ...` fails loudly), not on-device
RAM.

```python
# ❌ Banned in libraries/*/src/ — MP/CP no-op, CPython test-only payoff
class PacketPublish:
    __slots__ = ("packet_id", "payload", "qos", "retain", "topic")

# ✅ Plain class — same on-device behavior, no scaffolding cost
class PacketPublish:
    pass  # attributes assigned in __init__
```

CPython-side typo shielding isn't load-bearing: `python scripts/run.py
preflight` runs every test on all three runtimes before commit, so a
typo'd attribute fails the test regardless of `__slots__`.

In docstrings or comments: never write "`__slots__` saves memory" /
"`__slots__` keeps the instance lean."  Both are false on MP and CP, and
the comment ships in the source distribution.

### Pure-passthrough `@property`

`@property` works on MP/CP via the descriptor protocol, but each access
invokes the getter as a Python-level function call (multiple µs on MP/CP
vs a direct attribute load), and each declaration allocates a `property`
object on the class (~100 B per-class).  For a getter that just returns
an instance attribute, name the attribute publicly instead.

```python
# ❌ Banned in libraries/*/src/ — descriptor cost for zero semantic value
class RequestParser:
    def __init__(self):
        self._state = RequestParseState.REQUEST_LINE

    @property
    def state(self):
        return self._state

# ✅ Direct public attribute — same caller syntax, no descriptor
class RequestParser:
    def __init__(self):
        self.state = RequestParseState.REQUEST_LINE
```

Callers write `parser.state` either way.  The underscored-internal-name
convention isn't communicating anything the public attribute name doesn't
already.

### When `@property` is still allowed

Properties that *compute* a value stay legitimate — they're doing work
the caller would otherwise have to spell out:

```python
@property
def is_done(self):
    """Connection has reached a terminal state."""
    return self._state in (_ConnState.DONE, _ConnState.ERROR)

@property
def body(self):
    """Snapshot the body bytes received so far."""
    return bytes(self._body_view[:self._body_write_offset])
```

If the computation is non-trivial enough that the dot-access syntax
actively misleads ("this looks like a field, but it's doing work"),
prefer a regular method (`def body_bytes(self) -> bytes: ...`).

The audit angles are in
[`.github/skills/audit-library/SKILL.md`](../.github/skills/audit-library/SKILL.md)
§7 ("chumicro project-policy compliance") and
[`.github/skills/audit-embedded/SKILL.md`](../.github/skills/audit-embedded/SKILL.md)
§7 ("Code shape for embedded").

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

## Fake delegates to production for pure-math helpers

A test fake exposing pure-math production helpers delegates to the real functions rather than re-deriving them.  Pure math = no I/O, no clock, no module state, no platform variance: arguments in, value out.

```python
# In src/chumicro_timing/testing.py
from chumicro_timing.ticks import ticks_add, ticks_diff

class FakeTicks:
    def ticks_diff(self, end: int, start: int) -> int:
        return ticks_diff(end, start)

    def ticks_add(self, ticks_val: int, delta: int) -> int:
        return ticks_add(ticks_val, delta)
```

The default reflex is *"a fake should be self-contained"* — true for I/O, clocks, and state, where platform-independent behavior is the whole point of a fake.  Pure math has no platform variance to fake, and re-deriving production creates a drift surface where a bug fix or contract change silently misses the fake.  Consumer-library tests through the substrate then pass on the same stale answer.

**Recognizer:** the production helper takes only its arguments and returns a value computed from them (no `time.*`, no `os.*`, no module-level state).  The fake's method body is a verbatim copy of the production body, just wrapped in a class.

**Why not "the fake is the contract":** the production module's own test suite enforces the contract (`libraries/timing/tests/test_ticks.py` for `ticks_diff` / `ticks_add`).  Consumer tests through the substrate validate that the consumer *uses* the contract correctly — they don't need to independently re-prove the math.

Related: `chumicro_timing.testing.FakeTicks`, "Test fakes as `testing` submodules" above, "Production tolerance that exists only to paper over a fake's hardcoded value" below.

## Production tolerance that exists only to paper over a fake's hardcoded value

A literal-set or "accept either A or B" tolerance in production code that exists *specifically* because a fake pins to A is a smell that the fake is wrong, not the platform.  A fake simulates what production observes on the platform the fake is executing on — if production has to tolerate a value the host wouldn't actually emit, the fake is the bug.

**Worked shape (EAGAIN errno):**

```python
# Production accepts (11, 35), with a comment claiming 11 is "the" right one
WOULD_BLOCK_ERRNOS = (11, 35)  # Errno 11 (EAGAIN) is the cross-runtime would-block code

# Fake raises 11 on every platform
class FakeSocket:
    def recv(self, n: int) -> bytes:
        raise OSError(11, "EAGAIN")
```

EAGAIN is `11` on Linux and embedded Pythons (CircuitPython, MicroPython) and `35` on macOS CPython.  A fake executing on macOS should raise `OSError(35)`, not `11`.  Production accepted both literals because the fake forced it to; the comment naming one value as "cross-runtime" was the writer's belief at write-time, not the reality.

**The recognizer:** a literal-set or `errno in (…)` check in production paired with a comment that asserts one value is correct.  The other value usually traces to a fake pinned to it.  The same shape applies beyond errno — any host-observable value (path separator, line ending, default port, environment lookup) where production accepts "A or B" and a fake hardcodes A.

**The fix:** the fake reads the platform's real value (`errno.EAGAIN`, `os.sep`, `os.linesep`), not a hardcoded literal.  Production drops the tolerance once the fake stops lying.

**Why this matters in this repo:** ChuMicro fakes run on CPython (host tests), MicroPython unix-port, and CircuitPython unix-port — three platforms whose errno tables, path conventions, and runtime defaults differ.  A fake pinned to one platform's literal forces production to paper over the others, which then masks real platform bugs when the production code runs against a fourth (a real board).

Related: AGENTS.md test-stand-in-fake rule under Testing; "Test fakes as `testing` submodules" above.

## Cross-runtime test-file stub for a production module that exists only on a target firmware

When production source imports a firmware-only module at module top (the correct shape), host-side tests that drive that source need the module present in `sys.modules` *before* the test file loads.  `pytest`'s `conftest.py` works for the pytest path but not for the `chumicro_test_harness` collector (which runs tests on MicroPython / CircuitPython unix-ports without picking up pytest hooks).  Install the stub at the test file's module top instead.

**Worked shape — `socketpool` on host runtimes:**

```python
__chumicro_host_only__ = True

import sys


class _SocketpoolStub:
    """Stand-in for ``socketpool`` on host runtimes — only needs to
    satisfy the module-load import; per-test fakes overwrite the
    adapter's module-level binding directly via ``_SwapAttribute``.

    Plain class instead of ``types.ModuleType`` — CP / MP unix-ports
    do not ship ``types``.
    """

    AF_INET = 2
    SOCK_STREAM = 1
    SOCK_DGRAM = 2
    SOL_SOCKET = 0


sys.modules.setdefault("socketpool", _SocketpoolStub())


# Imports below depend on the stub having been installed.
from chumicro_sockets import UnsupportedSSLConfigError  # noqa: E402
```

**Recognizer:** test file fails with `ImportError: no module named 'X'` on `test-micropython` / `test-circuitpython` but passes on `pytest`, where `X` is a CPython-stdlib or firmware-only module that production imports at module top.

**Per-test fakes** then swap the adapter's attribute (`_SwapAttribute(cp_adapter, "socketpool", per_test_fake)`) rather than re-patching `sys.modules` after the fact — the production module has already bound the stub at its module-load `import` site, so post-hoc `sys.modules` patches do not take effect.

**Why a class, not ``types.ModuleType``:** ``types`` is absent on the MicroPython and CircuitPython unix-ports.  A plain class instance assigned to ``sys.modules[name]`` satisfies ``import name`` on every host runtime — Python's import machinery only requires attribute access on the object it retrieves from ``sys.modules``.

Related: AGENTS.md "Production tolerance that paper-overs a fake's hardcoded value" (sibling rule about production not bending to tests), `_SwapAttribute` helper in `libraries/sockets/tests/test_cp_adapter.py`.


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

## Cross-runtime feature gotchas (`test-micropython` / `test-circuitpython` failures)

When unix-port tests fail with `SyntaxError`, `NameError`, or `ImportError` on
code that passed CPython tests, the usual suspects:

- **CPython-only stdlib** — `typing`, `__future__`, much of `functools`.
  Library code shouldn't import these (Decision 0021); tests sometimes do.
- **Builtin gaps** — `TimeoutError` isn't a MicroPython 1.28 builtin
  (see [Missing builtins on MicroPython 1.28](#missing-builtins-on-micropython-128)
  below for the full pattern).
- **f-string complexity** — nested expressions and format-spec expressions
  trip MP; basic `f"{name}"` is fine.
- **Newer syntax** — `match`/`case` and walrus `:=` need recent MP/CP; grep
  `.tools/micropython/` and `.tools/circuitpython/` to verify before using.
- **Underscore `const()` names are module-private on MP** — the compiler
  folds `_X = const(1)` into its use sites and never binds `_X` in module
  globals, so `from mod import _X` in a sibling module raises
  `ImportError: can't import name _X` on MP/CP while CPython passes.
  Wrap a constant in `const()` only when no other module imports it;
  a cross-module constant stays a plain assignment (or loses the
  leading underscore, the way `_wire.py`'s `DEFAULT_*` names do).
- **MP's mbedTLS surface hides handshake state, sharply** —
  `SSLSocket.cipher()` segfaults (unix port) or hard-faults if called
  before the handshake completes (NULL ciphersuite into `strlen`),
  `getpeercert` is absent because MP's standalone mbedTLS config never
  defines `MBEDTLS_SSL_KEEP_PEER_CERTIFICATE`, and a zero-length
  `send()` returns before reaching mbedTLS (`py/stream.c` loops
  `while (size > 0)`), so it steps nothing and probes nothing.  There
  is no safe Python-visible "handshake over" signal on MP 1.27; a
  deferred `do_handshake_on_connect=False` bring-up cannot promote
  provably and the sockets MP adapter blocks in `wrap_socket` instead.

Related: Decision 0003, Decision 0016, Decision 0049.

## Recursion-depth bounds are bench-set, never analytical

Any recursive code in `libraries/*/src/` (decoders, parsers, tree
walkers) needs a depth guard so a deeply-nested *corrupt or hostile*
input raises a clean `ValueError` instead of a `RuntimeError: pystack
exhausted` (MicroPython) / hard fault.  The guard constant cannot be
reasoned about — it must be measured on the **worst board, Pico W under
MicroPython**, which has the smallest pystack of the supported set.

Measured datum (`chumicro_msgpack` pure decoder, ~2 Python frames per
nesting level — `_decode` + `_decode_array`): Pico W MP **survives 16
nested containers, faults at 17** (~32 frames is the ceiling).  An
analytical guess of 32 was 2× too high — the guard would never fire
before the stack died.  The shipped bound is `_MAX_DEPTH = 8` (guard
trips ~18 frames deep, well under the ceiling, with caller-frame
headroom, still 2× realistic persisted config/kvstore nesting of 2–4).

Procedure when adding recursive library code: deploy a probe via the
on-device sweep (a temp test that decodes increasing nesting in a
`try/except` and `print`s the last-OK depth), read the silicon limit
on Pico W MP, set the guard well below it, then delete the probe.  The
guard's own too-deep test recurses only to `bound + 1`, so a low bound
also keeps that test from stressing the device stack.  Don't trust the
CPython/unix-port limit — it is far higher and will mislead.

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
`maxlen` enforcement gives drop-oldest behavior for free.

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
  a buffered handler both expose this).

Used today by: `chumicro-events.EventBus._queue`,
a buffered log handler's internal `_buffer`.  Apply the same pattern to any
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
`mpremote.transport_serial.SerialTransport`.  Several behaviors of
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

### 5. `exec_raw(data_consumer=...)` fires per single byte, including the `\x04` terminator

`SerialTransport.exec_raw(command, timeout=N, data_consumer=callback)`
threads the callback into mpremote's internal `read_until` loop,
which reads stdout **one byte at a time** from pyserial and calls
`callback(single_byte)` on each.  The `\x04` end-of-stdout marker is
fed to the callback **before** the loop breaks on the next iteration's
`endswith(b"\x04")` check — so a consumer that just buffers bytes
ends up with the terminator byte in its tail.

Per-line stdout dispatch via `data_consumer`: feed the byte stream
into a buffer that splits on `\n` and strips trailing `\r`; pass a
`terminator=b"\x04"` knob so the dispatcher stops emitting once the
terminator arrives and discards the trailing terminator byte.  The
second `read_until` inside `follow()` (for stderr) does **not** get
the same `data_consumer`, so the callback only ever sees stdout
bytes — `data_consumer` is naturally scoped to the stdout segment.

Reference implementation: `_line_dispatcher.StreamingLineDispatcher`
+ `MicropythonTransport.execute` (`on_line` kwarg).

## Subprocess binary resolution (host tools)

Rule + code shape live in [Style Guide § Subprocess binary resolution](../docs/contributing/style-guide.md#subprocess-binary-resolution-host-tools).
Reference implementation: `MicropythonTransport._run_mpremote` (commit `e4f669e`).
Apply the pattern to any new host-side shell-out to `mpremote` / `esptool` / `rshell` / `ampy`.

## Eager imports are the default — lazy is only for genuinely optional paths

Default to module-top imports for library and workbench code.  Lazy / function-scope imports are reserved for genuinely optional code paths — typically DI / factory shapes where the import is only reached when no alternative was injected (`if socket_factory is None: from chumicro_sockets import tcp_client_socket`), error-format helpers reached only on the failure branch, or branches that fire once in a blue moon between actual hardware boots.

**Why:** Module-top imports load long-lived state contiguously into the heap before any short-lived buffer churn has fragmented it.  A lazy import that runs after wifi-connect / MQTT-subscribe / scratch buffers have come and gone has to fit its long-lived state into the holes those allocations left behind.  Synthetic peak-RAM benchmarks miss this — peak isn't the metric that matters on small allocators; fragmentation is.

Don't lazify "to reduce import-time RAM" when the deferred-to point sits a few stack frames after the deferred-from point — that's the worst case: no peak savings, plus fragmentation cost.  "Cold path called once at boot" does not qualify as optional in this sense; the deferred-to point is too close to the deferred-from point to save anything.

The lazy patterns documented below (PEP 562, per-function adapter selection) apply only after this default has been chosen against.

Related: Decision 0010 (constructor injection — same "defer the cost" philosophy at the class-instance scope), `plans/workstreams/archive/lazy-loading-research.md` for the Tier A / Tier B classification.

## Lazy module-level imports via PEP 562 `__getattr__` (workbench)

PEP 562's `module __getattr__` is implemented at the firmware level
on both MP and CP (verified in the pinned source —
`MICROPY_MODULE_GETATTR` default-on at the `CORE_FEATURES` ROM
level).  The one holdout was the **deploy harness's CircuitPython
RAM-mode path**, which wraps each package in a class-as-module stub:
lookups hit the stub's `__dict__` directly and a module-level
`__getattr__` never fires.  The stub cannot be taught the protocol
(MP/CP have no metaclasses), so `_populate_module` in the CP
bootstrap template now **materializes lazy exports at population
time**: when the exec'd namespace defines `__getattr__`, every
`__all__` name missing from the namespace is resolved through it and
bound onto the stub, with a miss converted to ImportError so a
not-yet-populated submodule defers the package into the existing
retry loop.  A PEP-562 lazy `__init__` in a device library therefore
works under CP RAM staging too; the cost is that a RAM-mode session
loads the lazy submodules up front, which its test files import
anyway.  Materialization is best-effort by design: it runs once after
population settles, and a name whose providing module is not in the
staged set is left absent rather than deferred, matching a flash
deploy where the un-imported file never reaches the board (own-src
scoping deliberately omits lazily-imported submodules, e.g.
chumicro_config's runtime.py in a wifi session).  A test importing an
absent name fails at that import with the true message.

History: the bypass surfaced 2026-04-25 during chumicro-wifi Slice 0
hardware bring-up; the materialization landed 2026-08-09 after the
harness's own lazy `raises` export took down 128 of 165 RAM-mode
runner tests on a real ESP32-S2.

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
spike.  See `plans/workstreams/archive/lazy-loading-research.md` for the
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

## Losslessly splitting an over-ceiling test file (Decision 0072 Phase B)

When a cross-runtime test file is too large to run on a freshly-reset Pi Pico W ([Decision 0072](decisions/0072-large-test-modules-on-constrained-boards.md)), split it — without a hand-edit that risks silently dropping or mutating a test. The recipe that split websockets / http_server / mqtt / requests (2026-05-17):

- **Partition only test classes, in source order.** A class with ≥1 `test_` method is a partition unit; it lands in exactly one slice. Slices are *contiguous runs of classes in original source order* — never reorder, or the byte-identity check below can't hold.
- **Helper funcs and zero-`test_`-method helper classes are closure-included, not partitioned.** Walk `ast.Name`/`ast.Attribute` from each slice's chosen classes; pull in referenced module-level helpers (funcs, assignments, *and* helper classes like `_CountingSocket`) transitively; duplicate them into every slice that references them (proportionate — a small builder duplicated beats a new shared cross-runtime helper module the on-device harness would have to stage).
- **Imports are regenerated per slice, pruned to used names** (parenthesized multi-line to avoid E501), so ruff F401/isort stays clean. Imports/helpers are the only regenerated bytes; they're always a subset of the original, so behaviour is preserved.
- **Assert losslessness, don't trust it:** the concatenation of every emitted test-class block must equal the original's test-class blocks byte-for-byte, and the summed `test_` count must match. A deterministic AST splitter that emits these and aborts on mismatch is worth writing as a throwaway `.scratch/` aid — hand-splitting 15+ files does not stay correct.
- **Gate before hardware:** ruff → unix-port MP+CP (`--target unix-port`) → only then the Pico W bench. `pytest --collect-only` count includes per-file synthetic `Setup`/`Run overhead` items (one pair per file) — subtract them before comparing to the pre-split count, or the delta looks like lost tests when it isn't.
- **Slice size is bench-determined per library, not guessed** — the ceiling is library-weight-dependent (requests `_wire` fits 89 tests/file; websockets `_wire` OOMs ~30). Start conservative, ladder down only the slices that OOM. A single test whose *own* allocation exceeds the board (not co-residency) is loud-skipped per the Decision 0072 §3 exception, not split.

Related: Decision 0072, the `chumicro-pytest-device` `--per-file` staging path.

## Interactive-report → clipboard blob round trip (agent skills)

When a skill needs richer human selection than `AskUserQuestion`'s 4-option cap allows (per-item checkboxes/radios, free-text edits, notes), render a local HTML report whose only scripted layer serializes the choices into a plain-text blob behind a **Copy selection** button; the human pastes the blob back into the session and a mechanical parser applies it under guards. Proven in `/audit-code` (`eval.html`, finding ids) and `/regen-comments` (`report.html` / `library_report.html` / `compare.html`, per-symbol picks + fenced `#edit` blocks).

- **Blob grammar:** one header per file — `<skill> apply (<file>): sym=run-N, sym=edit` — then fenced bodies (`<<<EDIT … EDIT>>>`) and `#note sym: …` lines. Multi-file pages emit one section per touched file; the parser splits on headers and the applier refuses a multi-file blob without a basename filter.
- **`file://` pages cannot write to disk** — clipboard is the transport. A local-server "Submit" button is an additive upgrade, never the baseline.
- **Persist in-page state to localStorage keyed by a CONTENT HASH of the artifact**, not the run id: a mid-review reload restores picks; an applied change starts the page clean instead of restoring stale radios (bit us 2026-06-09).
- **Namespace radio groups + state keys per section** when composing multiple files into one page (tabs), or one tab's picks uncheck another's.
- The apply side is mechanical and guarded (for comment work: AST code-identity via `splice_symbol`-style fingerprint); judgment calls (lossy edits, contradicted facts) stay in-session as push-backs after parsing, never in the page.

## Clean-room `claude -p` running a background Workflow (agent skills)

A skill phase runner shells out to one clean-room `claude -p` whose agent calls the Workflow tool (writer/triage fan-outs in `regen-comments`; same shape anywhere a skill needs a multi-agent workflow from a /tmp room). Three failure modes were all observed live on 2026-06-10, and each needs its own mechanical guard — prompt wording alone fixes none of them:

- **The agent cannot wait.** The Workflow tool launches in the background and returns immediately; ending the turn exits `claude -p` and kills the run. Whether the completion notification arrives before the agent ends its turn is a race. Guard: give it a **poll marker** — delete the workflow's LAST output artifact (`pick.json`) pre-launch and instruct the agent to Read-poll it; a missing-file error means still running. Polling keeps the process alive; a stale marker would satisfy the poll instantly, hence the delete.
- **Re-run rooms trip the Write tool's read-before-write guard.** A writer agent told to `Write runs/run-N.py` over a prior run's file gets `File has not been read yet`; some agents recover with a Read, others reply "DONE, wrote it" without writing. Guard: **delete every artifact the workflow must produce before launching** (fresh files have no read-first requirement). Fresh-room phases never hit this — it surfaces only in refine/re-run paths, so test those paths specifically.
- **Bare existence checks lie in any room that held a prior run.** Guard: verify completion by **mtime newer than launch** for every required artifact, retry the whole workflow once (transient all-agents-blank runs are real), then halt loudly. Never splice/copy from an artifact that failed the freshness check — that shipped a stale take as "regenerated" while reporting success.

Reference implementation: `wf_run.py` (`run_workflow` + `copy_winner`); callers `regen_phase2.py` / `regen_symbol.py` (full guard) and `regen_phase1.py` (prompt-only — its fresh-room precondition makes stale artifacts impossible and a zero-fact triage legitimately writes nothing). Corollary for single-shot `claude -p` writers (`tighten_symbol.py`): delete the expected output before the call so the existence check is honest. (These files moved out with the regen-comments skill on 2026-07-04 — now `skills/regen-comments/` in the `regen-voice-tools` repo; see `workstreams/regen-voice-extraction.md`.)

- **User-global memory leaks into every `claude -p` unless you pass `--safe-mode`.** A `/tmp` cwd keeps project `CLAUDE.md`/`AGENTS.md` out by cwd-ancestry, but `~/.claude/CLAUDE.md`, user hooks, skills, plugins, and MCP servers load regardless of cwd. `--safe-mode` excludes all of them while OAuth login and the Workflow/Task tools keep working (`--bare` also exists but drops OAuth — wrong for launchers whose preflight checks CLI login). Verified 2026-06-12: a tracer instruction in user memory is visible to bare `claude -p` and invisible under `--safe-mode`, and a Workflow-tool run completes under the flag. Reference: `audit_phase1.claude_p_workflow` in `.github/skills/audit-code/`.

## Fake-now tests vs deadlines armed at user-entry paths

Client APIs that run outside the tick loop (`connect()`, `publish()`) arm
their deadlines from a fresh real `ticks_ms()` read — deliberate, per
`MQTTClient._deadline`'s docstring.  A test that then drives `handle()` with
a literal fake now (`handle(0)`) is comparing two different clocks in
`chumicro_timing`'s modular tick space (2^29 ring, ~6.2-day period): the
sign of `ticks_diff(real_deadline, fake_now)` depends on where the real
counter happens to sit, so the test passes or fails **by calendar date**.
Bench-bitten 2026-07-05: `test_ssl_context_ignored_when_transport_factory_passed`
landed green 07-04, flipped red 07-05, would have flipped back ~3 days later.

Rule: a test may either (a) inject `ticks=FakeTicks()` at construction and
use fake nows everywhere, or (b) construct with the real clock and drive
`handle()` with `client._ticks.ticks_ms()` reads.  Never mix.  Every
construction path must forward the `ticks=` seam — `from_config` gained it
2026-07-05 after its absence forced (b) on a test that wanted (a); a factory
that swallows the clock seam reintroduces this bug class for its callers.

## Canonical library README Contributing block

Every `libraries/*/README.md` ends its Contributing section with the same
paragraph, and `chumicro_workspace.scaffold` (`contributing_intro`,
chumicro branding) generates the identical text for new libraries:

> Issues, bug reports, and pull requests are welcome, and so is "I ran
> it on this board and here's what happened", some of the most useful
> feedback a hardware project can get.  Development happens in the
> [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose
> contributing guide covers setup and the test workflow.

Two constraints shaped it (2026-07-19 GA docs pass):

- CHU006 flags the literal filenames `CONTRIBUTING.md` / `AGENTS.md`
  anywhere in a publishable tree, including inside a URL, so the block
  says "contributing guide" and links only the repository root.
- No "mono-repo" noun, no `functional_tests/` or `devices.yml`
  instructions: those mean nothing to a PyPI reader.

Change the wording in one place and sweep the other fifteen (14 READMEs
plus the scaffold string); the scaffold is the piece audits forget.

## mkdocstrings renders what the api.md names, and griffe gates it

Two coupled gotchas from the 2026-07-28 secondary-docs pass:

1. **PEP-562 lazy re-exports are invisible to `::: package`.**  A library
   that re-exports its classes through a module-level `__getattr__`
   (mqtt, requests, websockets do this to keep import-time heap down)
   renders *nothing* for those names under a bare `::: chumicro_x`
   directive: griffe resolves statically and never calls the hook.  Give
   each real module its own `::: chumicro_x.client` section in
   `docs/api.md`.  Before the fix, `MQTTClient` and `WebSocketClient`
   had no API reference at all and nobody noticed, because the page
   built green while rendering almost nothing.

2. **Adding a module to api.md arms the griffe gate for it.**  The
   preflight docs phase fails on griffe warnings, but only for modules
   an api.md actually names.  A module with unannotated public
   signatures builds fine right up until someone documents it, and then
   the docs phase goes red for a "pre-existing" reason.  When adding a
   `:::` section, annotate the module's public signatures in the same
   change (`object` for duck-typed params is the house convention).

**macOS `sync` is not a write barrier.**  `sync(2)` schedules the flush and returns; before any operation that resets or remounts a mounted FAT volume (CP soft reboot, `storage.erase_filesystem()`), force completion with `fcntl F_FULLFSYNC` on the mount point (`chumicro_deploy.flash_drive.flush_volume`), or cached FAT metadata can tear directory entries into an EINVAL state.

## Decompose a size-budget overage before touching the ceiling

`check-size` reports one number per library, so a `FAIL: runner mpy 6874 B > ceiling 6831 B` says nothing about *which* addition cost what.  Blanket-raising to the new total makes the ceiling a rubber stamp.  Measure each construct instead, compiling variants of the changed module through the gate's own path so the numbers reconcile with it exactly:

```python
from check_size import prepared_mpy_cross               # scripts/
from chumicro_deploy.source_minify import strip_source  # workbench/deploy/src/

stripped = strip_source(source_variant)
# The -s name must be the package-relative path: it is embedded in the .mpy,
# so a temp-dir path would make the byte count depend on where you ran it.
subprocess.run([mpy_cross, "-s", "chumicro_runner/generators.py",
                "-o", str(temp_mpy), str(temp_py)], check=True)
size = temp_mpy.stat().st_size
```

Build the variants cumulatively (baseline, then one construct added per step) and diff the `.mpy` sizes.  `check_size.measure_library(package_dir, src_root, mpy_cross)` gives the whole-package number when you need to reconcile a module delta against the library total.

Two things this surfaces that a single number hides.  A module-level `import` is often the largest single item: `from chumicro_timing.ticks import ticks_diff` measured +48 B of a +98 B change, nearly half, in the qualified-name strings and import bytecode.  And the library's own headroom matters, because the overage and the growth are different numbers: that +98 B change tripped its ceiling by only 43 B, since 55 B of slack was left from the last ratchet.

The per-construct view is also a design signal, not just an accounting one.  When the runner's deadline compare was measured this way, the biggest line item was an import the library should not have had at all (see *Injected clocks* below); removing it left the package 10 B smaller than before the feature, and the ceiling never moved.  Reach for this before writing the justification, because sometimes the measurement retires the raise.

Docstrings are free here.  The gate strips them with the real deploy `strip_source` (Decision 0090) before compiling, so explaining a workaround in a docstring costs no flash.

## Injected clocks: publish the deadline, never judge it

A library that accepts `ticks=` has to route **every** comparison through it, including ones buried in helper modules.  `Runner` did this in `core.py` (`self._ticks.ticks_diff` at each site) while `_generator.py` compared deadlines with a module-level `from chumicro_timing.ticks import ticks_diff`, so a caller who injected a clock got it honoured everywhere except the generator gate.  The failure is invisible in tests that use `FakeTicks`, because a fake built on chumicro semantics agrees with the hardcoded import.

It shows up with any clock whose units differ, and the guide's own example clock is one: unbounded CPython `monotonic_ns() // 1_000_000` with plain-subtraction `ticks_diff`.  A four-day deadline on that clock reads as `-345600000` (keep waiting) to its owner and `+191270912` (elapsed) to `chumicro_timing.ticks_diff`, whose 2^29 modular compare aliases any gap over `TICKS_HALFPERIOD` (~3.1 days) to the wrong sign.  The sleep is skipped entirely.

The rule that falls out, and the one to apply to any new wait or helper:

**A suspended object publishes its condition; whoever owns the clock does the comparing.**  `ready(now_ms)` answers only what needs no clock (`Signal.is_set`).  A deadline goes out through `next_deadline(now_ms)` for the driver to compare.  Giving a helper its own clock so it can self-guard looks like robustness and is the bug: it hardcodes a second time base into a library whose whole seam is that the caller supplies the first.

Test it with a clock that disagrees, not a fake that agrees:

```python
class UnwrappedTicks:                      # no wrap, plain subtraction
    def ticks_ms(self): return 600_000_000
    def ticks_add(self, value, delta): return value + delta
    def ticks_diff(self, end, start): return end - start
```

A 4-day deadline under this clock must stay pending on the first tick.  See `libraries/runner/tests/test_socket_generators.py::test_runner_gates_deadlines_with_the_clock_it_was_given`.

## Subcommand hand-offs build the callee's Namespace, and a test drives the real callee

`chumicro-workspace` subcommands chain by hand-building an `argparse.Namespace`
for the next handler: `deploy-example` falls into `bootstrap`, `add-device
--demo` chains into `demo`, `preflight` runs `lint` then `test`.  The callee
reads whatever *its own parser* defines, so the constructed Namespace has to
carry that full attribute set, not the caller's mental model of it.  Issue #22
was the drift: `deploy-example`'s wizard fallback passed `port` / `device_id` /
`with_demo`, while `_cmd_bootstrap` delegates to `_cmd_add_device`, which reads
`address`, `runtime`, `id`, `force`, `description`, `non_interactive`, and
`_env`.  Every interactive no-device `deploy-example` raised `AttributeError`
instead of entering the wizard.

The reason it lived a long time is the test shape, and that's the transferable
part: the only test of that path monkeypatched `_cmd_bootstrap` with a fake,
and the fake asserted on `with_demo`, an attribute that existed on nothing but
the caller.  A stand-in for the callee can only confirm the caller talks to
itself consistently.

Rule: one test per hand-off drives the **real** callee, with the fakes pushed
out to the edges it actually touches (`serial.tools.list_ports.comports` for
the port pick, `probe_with_runtime_inference` for the probe, `create_transport`
for the deploy).  See
`workbench/workspace/tests/test_cli.py::TestDeployExampleAdditionalBranches::test_bootstrap_fall_through_runs_the_real_wizard`.
Keep a `getattr(args, "demo", False)`-style read in the callee only for
genuinely optional attributes; everything the callee reads unconditionally
belongs in every Namespace built for it.

## GitHub Pages: what only works at the host root

An account gets one root site, from a repository named `<account>.github.io`.
Every other repository publishes at `https://<account>.github.io/<repo>/`.  The
two coexist: claiming the root does not disturb a project path, and a project
site keeps serving its own address.  The one collision is a folder in the root
repository named after a project repository, which claims an address the
project site already owns.

Three things only count at the root, and no amount of work under a project path
substitutes for them:

- `robots.txt`.  Crawlers fetch it from the host root and ignore it anywhere
  else, so a project path cannot advertise its own sitemap through robots.
- Host-level ownership.  Search engines verify per property; a root property
  covers every path below it, and a project property covers only its own
  subtree.
- The IndexNow key.  The spec permits a key outside the root when the ping
  names it in `keyLocation`, but the endpoint separately checks that the
  submitter owns the host.  On a shared `github.io` account nobody owns the
  host until they claim the root repository.  Once the key is at the root,
  send no `keyLocation` at all: an absent one points the endpoint there, and
  naming a path only narrows a claim that wants to be host-wide.

IndexNow's status codes read backwards on a first attempt: a submission with a
brand new key returns `202` while the key file is still a 404, then the same key
returns `403 UserForbiddedToAccessSite` once the endpoint gets around to
evaluating ownership.  `202` means accepted, not validated, so a green ping is
not evidence the setup works.  Test with a key that has been live long enough to
be judged.

The shape that follows: generate the root site from the same source as the
project site (`scripts/generate_site_root.py` reads the landing page's package
list), publish it by rebuilding the site repository's whole tree so a retired
key file stops answering, and gate the publish on a deploy key so a missing
secret warns instead of failing a documentation deploy that already shipped.

## Moving a Pages site to a custom domain

An organization site with a custom domain redirects its whole `github.io` host to
that domain, and project sites below it inherit the domain rather than needing
one each.  `chumicro.github.io/ChuMicro/mqtt/stable/` became
`chumicro.com/ChuMicro/mqtt/stable/` with no per-repository configuration, and
GitHub issues the redirects itself, so no redirect table needs maintaining.

Order matters and is not recoverable if you get it wrong.  DNS first: four `A`
records and four `AAAA` records on the apex pointing at GitHub's Pages
addresses, plus a `CNAME` on `www` pointing at the `github.io` name.  Only once
those resolve does the custom domain get set, because GitHub starts redirecting
the instant it accepts the domain, and a domain that does not answer yet takes
the site down.  The certificate is requested after the domain is accepted and
takes minutes; enforce HTTPS only once its state reads `approved`.

The `CNAME` file is the trap.  Setting the domain through GitHub's web interface
commits that file to the site repository, and a publish that rebuilds the
repository's whole tree deletes it, which drops the domain on the next deploy.
Generate it from the same constant that names the host.

Registrar forwarding is not DNS.  A domain that "forwards to" a URL has records
claiming the apex, and those have to be cleared before the Pages records take
effect.  Spare domains stay as redirects to the canonical one: several hosts
serving identical pages splits the site's authority and lets a search engine
pick a winner arbitrarily.

Changing the host rewrites `Documentation` in every `pyproject.toml`, which is
release-relevant metadata, so the move costs a version bump per package and a
release before PyPI shows the new links.

## Two hand-built pages on one site share their chrome from one module

The hub at the host root and the documentation landing page under `/ChuMicro/`
are generated by different scripts and a reader moves between them in one click,
so any drift in navigation or artwork reads as two different projects.
`scripts/site_chrome.py` renders the navigation bar once with its styles inlined
in the markup, and both templates substitute it whole. A test asserts the same
string appears in both outputs, which is what makes the guarantee real rather
than a convention someone has to remember.

Inlining the bar's CSS into the returned markup rather than into each page's
stylesheet is what makes adding it to a third page a single substitution. It
reads the colour variables the pages already define, so it inherits the palette
without carrying one.

Published images live at one address on the host (`/assets/`) and both pages
reference it absolutely. Hotlinking artwork from `raw.githubusercontent.com`
works but makes social-card previews depend on a GitHub CDN path, and a page
that serves its own images can be moved to a new host by changing one constant.

Zensical-themed package sites carry their own navigation and stay out of this.

## Repo-relative asset paths break when the markdown is also published

A page in `docs/` is read in two places: on GitHub, where the reader is browsing
the repository, and on the documentation site, where only that tree is
published. `<img src="../../support/docs/chumicro_tip.png">` renders on GitHub
and 404s on the site, because `support/` is not part of the published tree.
Thirteen contributing pages shipped that way, and nothing caught it until a
person looked at the page.

Artwork that appears in published markdown goes at an absolute https URL on the
site's own host (`/assets/`), which resolves from both places. Link paths to
other repository files have the same problem and take the same fix.

`scripts/tests/test_published_docs_assets.py` parametrizes over every image
reference in every published docs tree and fails any relative path that resolves
outside its own tree. It carries a test asserting the scan found something,
because a pattern that matches nothing passes every other assertion in the file.
