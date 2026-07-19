# Standalone integration: adopt one library

You do not have to adopt the whole ChuMicro stack.  Each networked library is built to drop into an existing codebase that already has its own transport and its own clock: you bring those, the library brings the protocol.  This page is the recipe for that path: which siblings a library actually pulls, how to supply your own transport and ticks, and how to drive the library from whatever loop you already have.

It is the companion to [Slimming your deploy](slimming-your-deploy.md): that page strips the default `chumicro_sockets` wiring off the *device*; this page shows how to write the *code* that no longer needs it.

## The claim, measured

**Every networked library imports zero ChuMicro siblings at import time.**  `import chumicro_mqtt` pulls no `chumicro_sockets`, no `chumicro_timing`, no `chumicro_config`: nothing but itself.  You can check it yourself:

```python
import sys
import chumicro_mqtt

siblings = [m for m in sys.modules
            if m.startswith("chumicro_") and m != "chumicro_mqtt"]
assert siblings == []          # nothing else came along
```

Siblings arrive only when you *ask* for them: by using the default transport factory, or by letting the default `ticks=` fall back to `chumicro_timing`.  Supply your own for both and the closure stays empty:

| Library | bare `import` | your transport **+** `ticks=` | your transport, default ticks |
|---|:--:|:--:|:--:|
| `chumicro_mqtt` | `{}` | `{}` | `{chumicro_timing}` |
| `chumicro_websockets` | `{}` | `{}` | `{chumicro_timing}` |
| `chumicro_requests` | `{}` | `{}` | `{chumicro_timing}` |
| `chumicro_ntp` | `{}` | `{}` | `{chumicro_timing}` |
| `chumicro_http_server` | `{}` | `{}` | `{chumicro_timing}` |
| `chumicro_sockets` | `{}` | `{}` | `{}` (pure leaf) |

The one sibling in the third column is deliberate: skip `ticks=` and you inherit the tiny `chumicro_timing` leaf as your clock.  That is the ergonomic default, not a bug: most adopters want it.  Reach for `ticks=` only when you already have a monotonic clock and want the empty closure.

Contrast the ergonomic entry point.  `MQTTClient.from_config(...)` wires the default `chumicro_sockets` transport *and* reads config, so its deploy closure is the full declared set: `{chumicro_config, chumicro_sockets, chumicro_timing}` for mqtt (the other four land `{chumicro_sockets, chumicro_timing}`, plus `chumicro_config` where the factory reads keys).  That is the default gravity well.  The recipe below is how you opt out of it, one constructor argument at a time.

(The measured on-device cost of keeping these injection seams, across flash, heap, and hot-path frames, is in the [DI cost measurement](../../plans/reviews/2026-07-03-di-cost-measurement.md); it is sub-1% of a 264 KB / ~800 KB board.)

## Recipe: adopt mqtt, websockets, or requests standalone

Three moves: bring your transport, bring your ticks, drive the tick loop.

### 1. Bring your own transport

Every networked client takes its transport through the constructor instead of importing `chumicro_sockets` itself.  Two forms:

* **`socket=<a connected socket>`**: you already own a connected, non-blocking socket.  The library takes ownership and drives I/O on it.  Simplest for one-shot scripts and desktop code.
* **`transport_factory=<callable>`**: you hand over a factory the library calls to build (and, after a drop, *re*build) its own non-blocking connect state machine.  This is the form that gets you self-heal reconnect.

The factory's shape depends on the transport role (the two arities are fixed by [Decision 0115](../../plans/decisions/0115-shared-sockets-factories.md)):

| Library | `transport_factory` signature | returns |
|---|---|---|
| `chumicro_mqtt`, `chumicro_ntp` | `() -> connector` (zero-arg, endpoint is baked in) | a connect state machine |
| `chumicro_requests`, `chumicro_websockets` | `(host: str, port: int, use_tls: bool) -> connector` (per-call) | a connect state machine |
| `chumicro_http_server` | `() -> listener` (zero-arg) | a listening socket |

Whatever your factory returns must expose the `chumicro_sockets` connector surface (`check` / `handle` / `state` / `socket` / `io_*`): the same shape [`chumicro_sockets.connector(...)`](#recipe-adopt-sockets-alone-the-leaf) returns.  If instead you pass a ready `socket=`, it only needs the four-method socket contract (`recv_into` / `send` / `close` / `setblocking`) documented in each library's guide under *Bring your own transport*.  There are no `isinstance` checks against ChuMicro types: the contract is the methods, so a stdlib `socket.socket`, an upstream-library wrapper, or a hand-rolled fake all work.

### 2. Bring your own ticks

Pass `ticks=<yours>`, any object with three wrap-safe methods.  This is what lets the library share your existing clock instead of importing `chumicro_timing`:

```python
import time

class Ticks:
    """Millisecond ticks over your own clock.

    On CPython/desktop, monotonic_ns() never wraps, so plain +/- is
    correct.  On a board whose clock wraps (MicroPython's 30-bit
    ticks_ms), ticks_add / ticks_diff must be wrap-safe, or just omit
    ticks= and inherit chumicro_timing, which already handles the wrap.
    """
    def ticks_ms(self):
        return time.monotonic_ns() // 1_000_000

    def ticks_add(self, ticks, delta):
        return ticks + delta

    def ticks_diff(self, end, start):
        return end - start
```

Skip `ticks=` entirely and the library imports `chumicro_timing`'s wrap-safe `ticks` submodule for you, the deliberate default in the closure table above.

### 3. Drive it: runner-less, or with `chumicro_runner`

A ChuMicro client makes progress only when you tick it.  You do **not** need `chumicro_runner` for that.  Its `check(now_ms)` / `handle(now_ms)` methods are the whole contract, and you can call them from any loop you already have:

```python
from chumicro_mqtt import MQTTClient

mqtt = MQTTClient(
    transport_factory=my_transport_factory,   # your connector, from step 1
    client_id="sensor-1",
    ticks=ticks,                               # your clock, from step 2
)
mqtt.connect()                                 # non-blocking; no I/O happens here

# The runner-less drive loop, you own the loop:
while True:
    now = ticks.ticks_ms()
    if mqtt.check(now):                        # does the client want a turn?
        mqtt.handle(now)                       # one chunk of send / recv / connect
    # ... tick your own tasks here too ...
```

`handle()` always does a non-blocking recv and bails on `EAGAIN`, so this loop never blocks; a slow broker just means more passes.  Call `mqtt.publish(...)` / `mqtt.subscribe(...)` from anywhere in the loop: publishes issued before the connection is up buffer in a small queue and flush on connect (the default `when_disconnected="queue"` policy).

If you'd rather not hand-write the dispatch, adopt `chumicro_runner` too.  Register the client once; the runner calls `check`/`handle` for you and `wait()` parks the CPU between events (it reads each service's `io_interest` / `io_socket` to poll the right sockets):

```python
from chumicro_runner import Runner

runner = Runner(ticks=ticks)                   # same BYO clock
runner.add(mqtt)
mqtt.connect()

while True:
    now = runner.tick()                        # every registered service gets a turn
    runner.wait(now)                           # sleep until a socket is ready / a deadline hits
```

`chumicro_runner` also imports zero networked siblings: adding it costs only `chumicro_timing` (its clock), the same leaf `ticks=` already accounts for.

`chumicro_websockets` and `chumicro_requests` follow the identical three-move shape; only the `transport_factory` arity differs (per-call `(host, port, use_tls)`, per the table in step 1).

## Recipe: adopt sockets alone (the leaf)

`chumicro_sockets` has no ChuMicro dependencies at all: its `pyproject.toml` declares none, and importing it pulls nothing.  Adopt it directly when you want one cross-runtime TCP / TLS / UDP primitive and nothing else.  The three entry points are `connector()`, `listener()`, and `udp_socket()`:

```python
from chumicro_sockets import connector

# Non-blocking connect: DNS -> TCP -> (TLS) advanced one tick at a time.
# On CircuitPython, pass radio=wifi.radio; MicroPython / CPython ignore it.
conn = connector("example.com", 443, tls=True)

while conn.check(now):                          # now = your own ticks_ms()
    conn.handle(now)                            # advance one connect phase
    if conn.state == "failed":
        raise RuntimeError(conn.last_error)

sock = conn.socket                              # ready: send/recv on it directly
```

`listener(host, port, tls=...)` returns a non-blocking listening socket for a server; `udp_socket(...)` returns a UDP socket (what `chumicro_ntp` builds on).  Because it is a leaf, `chumicro_sockets` is the one library you never reach the "empty closure" question about: there is nothing under it to strip.

## What the fakes buy you: host tests with no hardware

Every networked library ships a `testing.py` of fakes that ride the same injection seams.  They are marked `__chumicro_test_support__` so the deployer never flashes them: they exist purely so *you* can unit-test your integration on a laptop, against no broker and no board.  `chumicro_sockets.testing.FakeSocket` scripts socket bytes; `chumicro_timing.testing.FakeTicks` is a manually-advanced clock; each protocol library adds canned wire bytes and construction helpers.

Here is a complete, copy-paste-runnable host test.  It drives an `MQTTClient` to `CONNECTED`, publishes, and delivers an inbound message, entirely in memory:

```python
from chumicro_mqtt import ProtocolState
from chumicro_mqtt.testing import (
    new_client, drive, canned_connack_bytes, canned_publish_bytes)
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks


def test_publishes_and_receives():
    sock, ticks = FakeSocket(), FakeTicks()
    client = new_client(sock, ticks)            # FakeSocket + FakeTicks wired in
    sock.enqueue_recv(canned_connack_bytes())   # script the broker's CONNACK
    client.connect()
    drive(client, ticks, count=2)               # tick to CONNECTED
    assert client.state == ProtocolState.CONNECTED

    # Outbound: publish, and assert it reached the (fake) wire.
    client.publish("sensor/temp", b"21.5", qos=0)
    drive(client, ticks)
    assert b"sensor/temp" in sock.sent

    # Inbound: script a broker PUBLISH, assert the callback fired.
    received = []
    client.on_message = lambda topic, payload: received.append((topic, payload))
    sock.enqueue_recv(canned_publish_bytes("cmd/led", b"on"))
    drive(client, ticks)
    assert received == [("cmd/led", b"on")]
```

`new_client(sock, ticks)` is the `testing.py` shortcut for "an `MQTTClient` wired to this fake socket and clock with sane test defaults"; `drive(client, ticks, count)` ticks it `count` times.  The same pattern (a fake transport plus `FakeTicks`) is how you test *your* code that uses these libraries, with the runner-less loop from the recipe standing in for the real one.

## Boundary facts an adopter needs

**`async` / `await` is banned *inside* the libraries, but not in your app.**  ChuMicro libraries never `await`; they make progress through `check`/`handle` ticks so many of them can share one loop without a scheduler.  That is a rule about the library internals, not about you.  Your application can be an `asyncio` program, a thread, or a bare `while True:` loop.  You just have to tick the client from wherever your loop lives (`await`-ing between ticks is fine; call `client.handle(now)` on each pass).  The workspace deployer does enforce the rule at its own boundary: a project whose `app.py` defines `async def run()` is refused with a pointer to the tick pattern, because the on-device boot shim calls `run()` synchronously.

**If the ~3 KB of dependency-injection ceremony ever costs you, there is a recorded escape.**  Keeping these constructor seams costs a few KB of flash and one extra frame per connect (details in the [DI cost measurement](../../plans/reviews/2026-07-03-di-cost-measurement.md)).  If a materially smaller target class ever makes that matter, deploy-time static resolution (rewriting the injection to direct calls in the deploy artifact while keeping every source seam) is recorded in §5 of that report as the pre-approved (currently unscheduled) fallback, and noted as such in the [design workstream](../../plans/workstreams/core-design-realignment.md).  You do not need it today; it exists so a future flash scare does not re-litigate the seams themselves.

## See also

* [Slimming your deploy](slimming-your-deploy.md): once your code brings its own transport, strip the default `chumicro_sockets` wiring off the device with `__chumicro_skip_factories__`.
* Each networked library's guide has a **Bring your own transport** section with the exact socket-method contract for that library: [mqtt](../../libraries/mqtt/docs/guide.md), [websockets](../../libraries/websockets/docs/guide.md), [requests](../../libraries/requests/docs/guide.md), [ntp](../../libraries/ntp/docs/guide.md), [http_server](../../libraries/http_server/docs/guide.md).
* [The dependency graph](../../libraries/README.md#dependencies): solid arrows are strict `pyproject.toml` deps; dashed arrows are the injection seams this recipe unplugs.
