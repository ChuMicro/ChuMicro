# Standalone integration: adopt one library

Each networked ChuMicro library drops into an existing codebase that already has its own transport and its own clock: the codebase brings those, and the library brings the protocol. [Slimming your deploy](slimming-your-deploy.md) then strips the default `chumicro_sockets` wiring off the board.

## What each library imports

**Importing a networked library imports no other ChuMicro library.** `import chumicro_mqtt` loads `chumicro_mqtt` alone, without `chumicro_sockets`, `chumicro_timing`, or `chumicro_config`. This check proves it:

```python
import sys
import chumicro_mqtt

siblings = [m for m in sys.modules
            if m.startswith("chumicro_") and m != "chumicro_mqtt"]
assert siblings == []          # nothing else came along
```

Another ChuMicro library loads only through a default: the default transport factory, or the default `ticks=` clock from `chumicro_timing`. Supply both yourself, and the closure stays empty:

| Library | bare `import` | your transport **+** `ticks=` | your transport, default ticks |
|---|:--:|:--:|:--:|
| `chumicro_mqtt` | `{}` | `{}` | `{chumicro_timing}` |
| `chumicro_websockets` | `{}` | `{}` | `{chumicro_timing}` |
| `chumicro_requests` | `{}` | `{}` | `{chumicro_timing}` |
| `chumicro_ntp` | `{}` | `{}` | `{chumicro_timing}` |
| `chumicro_http_server` | `{}` | `{}` | `{chumicro_timing}` |
| `chumicro_sockets` | `{}` | `{}` | `{}` (pure leaf) |

Leaving out `ticks=` brings in `chumicro_timing`, a small library with no dependencies, as the clock. Most adopters want that default. Pass `ticks=` when you already have a monotonic clock and want the empty closure.

`MQTTClient.from_config(...)` wires the default `chumicro_sockets` transport and reads config, so its deploy closure is the full declared set: `chumicro_config`, `chumicro_sockets`, and `chumicro_timing`. The other four libraries' `from_config` closures hold `chumicro_sockets` and `chumicro_timing`, plus `chumicro_config` where the factory reads config keys. Each constructor argument in the recipe below drops one of those.

The [DI cost measurement](https://github.com/ChuMicro/ChuMicro/blob/main/plans/reviews/2026-07-03-di-cost-measurement.md) puts the on-device cost of these injection seams, across flash, heap, and hot-path frames, below 1% of a board with 264 KB of RAM and about 800 KB of usable flash.

## Recipe: adopt mqtt, websockets, or requests standalone

### 1. Bring your own transport

Every networked client takes its transport through the constructor, in one of these forms:

* **`socket=<a connected socket>`** hands over a connected, non-blocking socket. The library takes ownership and drives I/O on it. This form suits one-shot scripts and desktop code.
* **`transport_factory=<callable>`** hands over a factory the library calls to build its own non-blocking connect state machine, and to rebuild it after a drop. This form gives the client automatic reconnects.

The factory's signature depends on the library ([Decision 0115](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0115-shared-sockets-factories.md)):

| Library | `transport_factory` signature | returns |
|---|---|---|
| `chumicro_mqtt`, `chumicro_ntp` | `() -> connector` (zero-arg, endpoint is baked in) | a connect state machine |
| `chumicro_requests`, `chumicro_websockets` | `(host: str, port: int, use_tls: bool) -> connector` (per-call) | a connect state machine |
| `chumicro_http_server` | `() -> listener` (zero-arg) | a listening socket |

A factory's return value exposes the same members as the object [`chumicro_sockets.connector(...)`](#recipe-adopt-sockets-alone-the-leaf) returns: `check`, `handle`, `state`, `socket`, and the `io_*` attributes. A ready `socket=` needs only `recv_into`, `send`, `close`, and `setblocking`, as each library's guide documents under *Bring your own transport*. The libraries check methods, never types, so a standard-library `socket.socket`, another library's wrapper, or a hand-rolled fake all work.

### 2. Bring your own ticks

Pass `ticks=` any object with three wrap-safe methods, and the library shares your clock instead of importing `chumicro_timing`:

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

### 3. Drive it: runner-less, or with `chumicro_runner`

A ChuMicro client makes progress only when something ticks it, and any loop can. Its `check(now_ms)` and `handle(now_ms)` methods are the whole contract, so `chumicro_runner` is optional:

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

`handle()` does a non-blocking receive and returns on `EAGAIN`, so this loop never blocks, and a slow broker just means more passes. Call `mqtt.publish(...)` or `mqtt.subscribe(...)` anywhere in the loop. A publish issued before the connection is up waits in a small queue and goes out on connect, under the default `when_disconnected="queue"` policy.

`chumicro_runner` writes that dispatch for you. Register the client once, and the runner calls `check` and `handle`. `runner.wait()` parks the CPU between events, reading each service's `io_interest` and `io_socket` to poll the right sockets:

```python
from chumicro_runner import Runner

runner = Runner(ticks=ticks)                   # same BYO clock
runner.add(mqtt)
mqtt.connect()

while True:
    now = runner.tick()                        # every registered service gets a turn
    runner.wait(now)                           # sleep until a socket is ready / a deadline hits
```

`chumicro_runner` imports no networking library. It brings only `chumicro_timing`, its clock.

`chumicro_websockets` and `chumicro_requests` follow the same steps, with the per-call `transport_factory` signature from step 1.

### The generator helpers, without the runner

The sequential helpers, `chumicro_sockets.generators`, `MQTTClient.next_message`, and `chumicro_requests.generators`, suspend by yielding a *wait*. `runner.add_generator` drives them, and so can your own loop. A wait never compares times itself: it publishes `next_deadline`, and the driver compares in its own clock. `io_socket` and `io_interest` exist so a scheduler can sleep instead of spinning, and this loop ignores both:

```python
def should_resume(wait, now_ms, ticks):
    """The whole resumption gate: three cases, all in your own clock."""
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
    wait = generator.send(None)                 # prime it to the first suspension
    while True:
        now_ms = ticks.ticks_ms()
        if should_resume(wait, now_ms, ticks):
            try:
                wait = generator.send(now_ms)
            except StopIteration:
                return
```

The socket helpers retry on `EAGAIN` and suspend again, so an early resume costs one wasted pass. This loop spins, where `Runner.wait()` parks the CPU on `ipoll` until a socket is ready or a deadline lands. On mains power the difference is invisible. On a battery the spinning eats most of the runtime budget, so adopt `chumicro_runner` once the rest of the integration works.

## Recipe: adopt sockets alone (the leaf)

`chumicro_sockets` depends on no other ChuMicro library: its `pyproject.toml` declares none, and importing it loads nothing else. Adopt it alone for one cross-runtime TCP, TLS, or UDP primitive. Its entry points are `connector()`, `listener()`, and `udp_socket()`:

```python
from chumicro_sockets import connector

# Non-blocking connect: DNS -> TCP -> (TLS) advanced one tick at a time.
# On CircuitPython, pass radio=wifi.radio; MicroPython / CPython ignore it.
conn = connector("example.com", 443, tls=True)

while True:
    now = ticks.ticks_ms()                      # your own clock, read every pass
    if not conn.check(now):                     # False once "ready" or "failed"
        break
    conn.handle(now)                            # advance one connect phase
    # ... tick your own tasks here too ...

if conn.state == "failed":
    raise RuntimeError(conn.last_error)
sock = conn.socket                              # ready: send/recv on it directly
```

`listener(host, port, tls=...)` returns a non-blocking listening socket for a server. `udp_socket(...)` returns a UDP socket, which `chumicro_ntp` builds on. With no ChuMicro library under it, `chumicro_sockets` has nothing to strip.

## Host tests with no hardware

Every networked library ships a `testing.py` of fakes that plug into the same constructor arguments. The marker `__chumicro_test_support__` keeps the deployer from copying them to a board. They let a laptop unit-test your integration with no broker and no board. `chumicro_sockets.testing.FakeSocket` scripts socket bytes, `chumicro_timing.testing.FakeTicks` is a clock you advance by hand, and each protocol library adds canned wire bytes and construction helpers.

This host test drives an `MQTTClient` to `CONNECTED`, publishes, and delivers an inbound message, all in memory:

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

`new_client(sock, ticks)` builds an `MQTTClient` wired to the fake socket and clock, with test defaults. `drive(client, ticks, count)` ticks it `count` times. Your own code that uses these libraries tests the same way: a fake transport, `FakeTicks`, and the runner-less loop from the recipe.

## Limits at the boundary

**Your application can use `async`, even though the libraries never do.** The libraries make progress through `check` and `handle` ticks, so many of them share one loop with no scheduler. An application can be an `asyncio` program, a thread, or a bare `while True:` loop, as long as it ticks the client on each pass, with `await` between ticks if it likes. The workspace deployer refuses a project whose `app.py` defines `async def run()`, because the on-device boot shim calls `run()` as a plain function ([Deploy refused](../troubleshooting/deploy-refused-importerror.md#defines-async-def-run-in-apppy-which-chumicro-cant-run)).

**A fallback exists for a board too small for the seams.** The constructor seams cost about 3 KB of flash and one extra frame per connect. For a much smaller class of board, §5 of the [DI cost measurement](https://github.com/ChuMicro/ChuMicro/blob/main/plans/reviews/2026-07-03-di-cost-measurement.md) approves deploy-time static resolution: the deployer rewrites the injection into direct calls in what it ships, and the source keeps every seam. Every board this project targets has room for the seams.

## See also

* [Slimming your deploy](slimming-your-deploy.md): once your code brings its own transport, strip the default `chumicro_sockets` wiring off the device with `__chumicro_skip_factories__`.
* Each networked library's guide has a **Bring your own transport** section with the exact socket-method contract for that library: [mqtt](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt/docs/guide.md), [websockets](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/websockets/docs/guide.md), [requests](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/requests/docs/guide.md), [ntp](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/ntp/docs/guide.md), [http_server](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server/docs/guide.md).
* [The dependency graph](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/README.md#dependencies): solid arrows are strict `pyproject.toml` dependencies. Dashed arrows are the injection seams this recipe unplugs.
