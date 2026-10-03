# Standalone integration: adopt one library

You do not have to adopt the whole ChuMicro stack.  Each networked library is built to drop into an existing codebase that already has its own transport and its own clock: you bring those, the library brings the protocol.  This page is the recipe for that path: which siblings a library actually pulls, how to supply your own transport and ticks, and how to drive the library from whatever loop you already have.

It is the companion to [Slimming your deploy](slimming-your-deploy.md): that page strips the default `chumicro_sockets` wiring off the *device*; this page shows how to write the *code* that no longer needs it.

## The claim, measured

`import chumicro_mqtt` loads its own modules without importing other ChuMicro packages. Check this in a fresh Python process so earlier imports do not affect the result:

```python
import sys
import chumicro_mqtt

packages = {name.split(".", 1)[0] for name in sys.modules
            if name.startswith("chumicro_")}
assert packages == {"chumicro_mqtt"}
```

The table describes runtime imports for bare imports and direct constructors supplied with the indicated dependencies. It does not describe package installation or the deployment file map:

| Library | bare `import` | your transport **+** `ticks=` | your transport, default ticks |
|---|:--:|:--:|:--:|
| `chumicro_mqtt` | `{}` | `{}` | `{chumicro_timing}` |
| `chumicro_websockets` | `{}` | `{}` | `{chumicro_timing}` |
| `chumicro_requests` | `{}` | `{}` | `{chumicro_timing}` |
| `chumicro_ntp` | `{}` | `{}` | `{chumicro_timing}` |
| `chumicro_http_server` | `{}` | `{}` | `{chumicro_timing}` |
| `chumicro_sockets` | `{}` | `{}` | `{}` (pure leaf) |

The one sibling in the third column is deliberate: skip `ticks=` and you inherit the tiny `chumicro_timing` leaf as your clock.  That is the ergonomic default, not a bug: most adopters want it.  Reach for `ticks=` only when you already have a monotonic clock and want the empty closure.

`MQTTClient.from_config(...)` imports the shared sockets factory and config support when neither `socket=` nor `transport_factory=` is supplied. An explicit transport bypasses both imports. Supply a clock too to avoid the constructor's timing fallback.

MQTT's package metadata still declares config, sockets, and timing dependencies. The deployment scanner also follows imports inside conditional branches without analyzing constructor arguments. Even with an explicit factory skip, timing, config, and msgpack can remain in an MQTT file map. [Slimming your deploy](slimming-your-deploy.md) explains the marker and dry-run check.

The [DI cost experiment](https://github.com/ChuMicro/ChuMicro/blob/main/plans/reviews/2026-07-03-di-cost-measurement.md) records its tested workloads and measurements. Measure your target and workload before assigning that result to a different application.

## Recipe: adopt mqtt, websockets, or requests standalone

Three moves: bring your transport, bring your ticks, drive the tick loop.

### 1. Bring your own transport

MQTT, requests, and websockets accept a supplied transport through the constructor. Two forms:

* **`socket=<a connected socket>`**: you already own a connected, non-blocking socket.  The library takes ownership and drives I/O on it.  Simplest for one-shot scripts and desktop code.
* **`transport_factory=<callable>`**: you hand over a factory the library calls to build (and, after a drop, *re*build) its own non-blocking connect state machine.  This is the form that gets you self-heal reconnect.

The factory's shape depends on the transport role (the two arities are fixed by [Decision 0115](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0115-shared-sockets-factories.md)):

| Library | `transport_factory` signature | returns |
|---|---|---|
| `chumicro_mqtt` | `() -> connector` (zero-arg, endpoint is baked in) | a connect state machine |
| `chumicro_ntp` | `() -> socket` (zero-arg) | a nonblocking UDP socket |
| `chumicro_requests`, `chumicro_websockets` | `(host: str, port: int, use_tls: bool) -> connector` (per-call) | a connect state machine |
| `chumicro_http_server` | `() -> listener` (zero-arg) | a listening socket |

A connection factory returns a tick-driven connector, not a callback that blocks until connected. MQTT drives its `tick(now_ms)` method and reads `state`, `socket`, and `last_error`; cancellation uses `cancel()`. The runner's optional I/O hooks support idling. NTP's factory returns a UDP socket with `sendto`, `recvfrom_into`, `close`, and `setblocking`; a server's listener factory has another contract. For either a ready socket or a factory, implement the interface specified in that library's *Bring your own transport* guide.

### 2. Bring your own ticks

Pass `ticks=<yours>`, an object with three consistent, wrap-safe methods. This CPython example uses the laptop's monotonic clock. On a board, supply that runtime's tick arithmetic or retain ChuMicro's default clock:

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


ticks = Ticks()
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
mqtt.connect()                                 # start the connection attempt

# The runner-less drive loop, you own the loop:
while True:
    now = ticks.ticks_ms()
    if mqtt.check(now):                        # does the client want a turn?
        mqtt.handle(now)                       # one chunk of send / recv / connect
    # ... tick your own tasks here too ...
```

`handle()` advances the client's current state, including transport setup, deadlines, inbound packets, and queued output. It may return before receiving anything. Your transport and callbacks run synchronously, so keep their work bounded and their socket operations nonblocking. Call `mqtt.publish(...)` / `mqtt.subscribe(...)` from the application loop; the default `when_disconnected="queue"` policy queues publishes until a connection is available.

To share dispatch with other services, register the client with `chumicro_runner`. `wait()` uses registered sockets and deadlines to idle between turns; it returns immediately when there is nothing to wait for or a deadline is due:

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

### The generator helpers, without the runner

Sequential helpers can yield a wait describing their next opportunity to run. A helper that completes without yielding returns immediately to its caller. You can drive these generators yourself, comparing published deadlines with your clock. Socket waits need a retry each turn even when they also carry a future timeout. This minimal driver handles that distinction:

```python
def should_resume(wait, now_ms, ticks):
    """Check socket, readiness, and deadline conditions."""
    if getattr(wait, "io_socket", None) is not None:
        return True
    ready = getattr(wait, "ready", None)
    if ready is not None and ready(now_ms):
        return True
    next_deadline = getattr(wait, "next_deadline", None)
    deadline_ms = None if next_deadline is None else next_deadline(now_ms)
    if deadline_ms is not None:
        return ticks.ticks_diff(now_ms, deadline_ms) >= 0
    return ready is None


def drive(generator, ticks):
    """Run a chumicro generator to completion on a loop you own."""
    try:
        wait = generator.send(None)
        while True:
            now_ms = ticks.ticks_ms()
            if should_resume(wait, now_ms, ticks):
                wait = generator.send(now_ms)
    except StopIteration:
        return
    finally:
        generator.close()
```

Socket helpers suspend again when a retry reports `EAGAIN`. This driver busy-polls; it handles completion during priming or a later turn and propagates other errors. Use `Runner.wait()` when you want registered sockets and deadlines to control idling. Energy consumption requires measurement on the actual board and workload.

## Recipe: adopt sockets alone (the leaf)

`chumicro_sockets` has no ChuMicro dependencies at all: its `pyproject.toml` declares none, and importing it pulls nothing.  Adopt it directly when you want one cross-runtime TCP / TLS / UDP primitive and nothing else.  The three entry points are `connector()`, `listener()`, and `udp_socket()`:

```python
from chumicro_sockets import connector

# Supply a connected CircuitPython radio, or None on MicroPython/CPython.
conn = connector("example.com", 443, tls=True, radio=radio)

while True:
    now = ticks.ticks_ms()
    if conn.check(now):
        conn.handle(now)
    if conn.state == "ready":
        break
    if conn.state == "failed":
        raise conn.last_error

sock = conn.socket
```

This fragment uses your existing `ticks` and `radio` values. The connector has no automatic timeout; the owning application must bound attempts when needed. `listener(host, port, tls=...)` returns a listening socket and `udp_socket(...)` returns a UDP socket. Their runtime adapters can use built-in modules without adding another ChuMicro package.

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

**If the ~3 KB of dependency-injection ceremony ever costs you, there is a recorded escape.**  Keeping these constructor seams costs a few KB of flash and one extra frame per connect (details in the [DI cost measurement](https://github.com/ChuMicro/ChuMicro/blob/main/plans/reviews/2026-07-03-di-cost-measurement.md)).  If a materially smaller target class ever makes that matter, deploy-time static resolution (rewriting the injection to direct calls in the deploy artifact while keeping every source seam) is recorded in §5 of that report as the pre-approved (currently unscheduled) fallback, and noted as such in the [design workstream](https://github.com/ChuMicro/ChuMicro/blob/main/plans/workstreams/core-design-realignment.md).  You do not need it today; it exists so a future flash scare does not re-litigate the seams themselves.

## See also

* [Slimming your deploy](slimming-your-deploy.md): once your code brings its own transport, strip the default `chumicro_sockets` wiring off the device with `__chumicro_skip_factories__`.
* Each networked library's guide has a **Bring your own transport** section with the exact socket-method contract for that library: [mqtt](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt/docs/guide.md), [websockets](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/websockets/docs/guide.md), [requests](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/requests/docs/guide.md), [ntp](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/ntp/docs/guide.md), [http_server](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server/docs/guide.md).
* [The dependency graph](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/README.md#dependencies): solid arrows are strict `pyproject.toml` deps; dashed arrows are the injection seams this recipe unplugs.
