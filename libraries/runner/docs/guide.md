# User Guide

## Overview

`chumicro-runner` provides a standard pattern for active components in the ChuMicro ecosystem.  Instead of each library inventing its own `poll()` / callback API, every active component implements two methods:

```python
def check(self, now_ms: int) -> bool:
    """Check whether the handler should fire.

    Args:
        now_ms: Current tick timestamp in milliseconds.

    Returns:
        True if the handler should fire this tick.
    """

def handle(self, now_ms: int) -> None:
    """React to the condition detected by check().

    Args:
        now_ms: Current tick timestamp in milliseconds.
    """
```

A shared `Runner` captures time once per tick, checks each service, and batch-fires all due handlers.  This replaces ad-hoc polling loops with a single standard contract.

## The pattern

1. **Services** implement `check(now_ms) -> bool` — they check a condition and return whether the handler should fire.
2. **Handlers** implement `handle(now_ms)` — they react when the service says "go".
3. **Runner** ties it together: capture time → check all services → batch-fire all due handlers.

Services are objects with `.check()` and `.handle()` methods, or plain handler callables that fire every tick or on a period — one shape per registration, never both.

## Getting started

```python
from chumicro_runner import Runner

class TemperatureSensor:
    """Alert when temperature exceeds a threshold.

    Args:
        threshold: Temperature in °C that triggers an alert.
    """

    def __init__(self, threshold: float = 30.0) -> None:
        self._threshold = threshold
        self._last_reading = 0.0

    def read_temperature(self) -> float:
        """Read from hardware — fast I2C or ADC operation."""
        # On a real board: return self._i2c_device.temperature
        return self._last_reading

    def check(self, now_ms: int) -> bool:
        """Return True when the reading exceeds the threshold.

        Args:
            now_ms: Current tick timestamp (unused here).

        Returns:
            True if the last reading exceeds the threshold.
        """
        self._last_reading = self.read_temperature()
        return self._last_reading > self._threshold

    def handle(self, now_ms: int) -> None:
        """Print an alert with the current reading.

        Args:
            now_ms: Current tick timestamp.
        """
        print(f"ALERT: {self._last_reading}°C exceeds {self._threshold}°C")

sensor = TemperatureSensor(threshold=30.0)
runner = Runner()
runner.add(sensor, period_ms=5000)

while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
```

## Shared timestamps

`Runner.tick()` captures `ticks_ms()` once and passes the resulting timestamp to every service.  This ensures all services in the loop see the same moment in time, preventing drift between independent clock reads on slow microcontrollers.

The method returns `now_ms` so user code can use it alongside the service loop:

```python
while True:
    now = runner.tick()
    if some_heartbeat.poll(now):
        do_something()
    runner.wait(now)
```

## Idling between ticks

`Runner.wait(now_ms)` is the loop's idle path and the runner's one sanctioned blocking point.  Call it right after `tick()`:

```python
while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
```

Each call to `wait`:

1. **Syncs the poll set** from each service's optional `io_socket` and `io_interest(now_ms)` bitmask — register newly wanted sockets, modify changed interest, unregister sockets that have gone away.  Idempotent: a no-change loop touches the poller zero times.
2. **Computes the timeout** as the minimum across every entry's `next_due_ms` and every service's optional `next_deadline(now_ms)`, minus `now_ms`.
3. **Blocks** in `ipoll(timeout_ms)` over the registered sockets when any are registered; otherwise sleeps the timeout via `time.sleep_ms`.  Returns immediately when the nearest deadline has already passed or no deadline applies.

Errors on a registered socket (`POLLERR` / `POLLHUP`) are routed to the owning service's optional `io_error(now_ms, eventmask)` hook so the service can transition cleanly to a failure state.  `POLLIN` / `POLLOUT` are wake signals only — `check` and `next_deadline` decide what runs on the next `tick`.

Not sure which wait primitive a given job wants?  The timing guide's [Choosing a wait](https://chumicro.github.io/ChuMicro/timing/stable/guide/#choosing-a-wait) table maps each question to its primitive across `chumicro_timing`, `chumicro_sockets`, and this service contract.

### Writing a service that participates in `wait`

A socket-owning service exposes the duck-typed attributes the runner reads each loop.  All are optional — services without them work the same way they always did; the runner just won't wake for their I/O:

| Attribute | Type | Purpose |
|---|---|---|
| `io_socket` | socket-ish object or `None` | The socket whose readiness should wake the loop.  Either the pollable itself or an adapter wrapper exposing it on `.sock` — the runner unwraps `.sock` at registration, so producers never need to. |
| `io_interest(now_ms)` | `int` | A bitmask OR-ing `IO_READ` (register `POLLIN`) and/or `IO_WRITE` (register `POLLOUT`); `0` registers nothing.  Import the bits from `chumicro_runner`. |
| `next_deadline(now_ms)` | `int` or `None` | The next tick the service must run even if no I/O arrives (timeouts, keepalives) |
| `io_error(now_ms, eventmask)` | callable | Notified when the registered socket reports `POLLERR` or `POLLHUP` |

The runner re-reads these every `wait()`, so a service can flip its interest between read and write (or set `io_socket = None`) between ticks and the poll set follows on the next call.  The single `io_interest` call replaces the earlier paired `io_wants_read` / `io_wants_write` booleans; the runner caches the bound method once at `add`, so the sync stays allocation-free.

A minimal sketch:

```python
from chumicro_runner import IO_READ, IO_WRITE


class EchoClient:
    """Read bytes from a connected socket, echo them back."""

    def __init__(self, sock) -> None:
        self.io_socket = sock
        self._want = IO_READ
        self._outbox = bytearray()

    def io_interest(self, now_ms: int) -> int:
        return self._want

    def check(self, now_ms: int) -> bool:
        return self._want != 0

    def handle(self, now_ms: int) -> None:
        # Drain whatever is ready; flip interest based on what's left
        # (self._want = IO_WRITE when there are bytes to send, etc.).
        ...

    def io_error(self, now_ms: int, eventmask: int) -> None:
        self.io_socket = None  # drops out of the poll set on next wait()
```

Every networked library in ChuMicro (`wifi`, `sockets`, `requests`, `http_server`, `mqtt`, `websockets`) implements this protocol — that is why their handlers share fairly with the rest of your loop.

### Injecting a poller for tests

`Runner(poller=...)` accepts any object exposing `register(obj, eventmask)` / `modify(obj, eventmask)` / `unregister(obj)` / `ipoll(timeout_ms)`.  The default poller is built lazily on the first `wait()` that has a socket to register, so applications that never register an `io_socket` never pay for it.

`chumicro_runner.testing.FakePoller` is the test stand-in — see [Testing tasks](#testing-tasks).

## The service contract

A service is any object you hand to `runner.add(service)`.  The runner reads six members off it: two are required, the rest optional, each optional member carrying a coherence rule the dispatch relies on.

| Member | Required | When the runner reads it | For |
|---|---|---|---|
| `check(now_ms) -> bool` | yes | each `tick`, subject to any period gate | deciding whether `handle` runs this tick |
| `handle(now_ms)` | yes | each `tick`, when `check` returned `True` | one tick of work |
| `io_socket` | no | each `wait`, as an attribute (the socket, or `None`) | the socket to poll |
| `io_interest(now_ms) -> int` | no | each `wait` | OR-ing `IO_READ` / `IO_WRITE` into the poll set for `io_socket` |
| `next_deadline(now_ms) -> int \| None` | no | each `wait` | bounding the idle timeout so the service still runs on time with no I/O |
| `io_error(now_ms, eventmask)` | no | on `wait`, when `io_socket` reports `POLLERR` / `POLLHUP` | transitioning cleanly to a failure state |

The coherence rules, as the dispatch enforces them:

- **`check` and `handle` are both required.**  `Runner.add` reads both off the object at registration, so a service missing either cannot register.
- **`io_socket` and `io_interest` come as a pair.**  The poll sync reaches the socket through `io_interest`; one member without the other never reaches the poller.
- **`io_error` requires `io_socket`.**  It is dispatched only when that socket reports a poll error.

`chumicro_runner.testing.validate_service(service)` checks exactly these rules and raises `ValueError` naming the offending member.  It validates shape, never behavior, so drop it into a consumer library's test suite to catch a malformed service before it reaches a live runner:

```python
from chumicro_runner.testing import validate_service


def test_my_service_is_a_valid_runner_service():
    validate_service(MySensorService(...))
```

Work runs on the runner in two shapes: services, the contract above, and generators registered with `runner.add_generator`.  This section is the service side; the generator side is its own surface with its own helpers, and there is no third shape.

## Registration patterns

### Object-based

Pass an object with `.check(now_ms) -> bool` and `.handle(now_ms)`:

```python
class MotionDetector:
    """Gate-based motion detector using a PIR sensor."""

    def __init__(self) -> None:
        # On a real board: self._pin = digitalio.DigitalInOut(board.D5)
        pass

    def detect_motion(self) -> bool:
        """Read PIR sensor pin — fast digital read."""
        # On a real board: return self._pin.value
        return False

    def check(self, now_ms: int) -> bool:
        """Return True when motion is detected.

        Args:
            now_ms: Current tick timestamp.

        Returns:
            True if the PIR sensor reads high.
        """
        return self.detect_motion()

    def handle(self, now_ms: int) -> None:
        """React to detected motion.

        Args:
            now_ms: Current tick timestamp.
        """
        print("Motion!")

runner.add(MotionDetector())
```

### Handler-only

Pass just a handler with no check — it fires every tick (or per period):

```python
runner.add(handler=lambda now_ms: scan_buttons(now_ms))
```

### Periodic

No check needed — the handler fires on a schedule:

```python
runner.add_periodic(
    lambda now_ms: print("blink!"),
    period_ms=500,
)
```

### Generator-driven

Write the I/O as a generator function and register it with `runner.add_generator(gen)`.  Each `yield from connect(...)` / `send_all(...)` / `recv_until(...)` hands control back to the runner between steps, so the body reads top-to-bottom while other services keep ticking.  Import the helpers explicitly from `chumicro_sockets.generators` — plain-runner consumers pay nothing.

```python
from chumicro_runner import Runner
from chumicro_sockets.generators import connect, recv_until, send_all
from chumicro_sockets import connector


def echo_run(host, port, radio):
    sock = yield from connect(connector(host, port, radio=radio))
    try:
        yield from send_all(sock, b"hello\n")
        reply = yield from recv_until(sock, b"\n", max_bytes=4096)
        print(f"got {reply!r}")
    finally:
        sock.close()


runner = Runner()
handle = runner.add_generator(echo_run("echo.example", 7, radio=wifi_radio))
runner.run_until(handle)
```

`run_until(handle)` drives the tick/wait loop until the generator finishes — and re-raises `handle.error` if the task died, so a broken flow fails loudly instead of exiting clean.  Pass a callable instead for arbitrary conditions, or just `timeout_ms=` to run for a fixed window (a QoS-ack drain, a settling period).

Each `yield from` is a scheduler checkpoint; between yields, other services registered on the same runner get their turn.  A bare `yield` suspends for exactly one tick.  `handle.done` flips True the moment the generator returns, dies, or is cancelled; `handle.error` holds the exception when the body raised (`None` otherwise), so a `while not handle.done` loop can report *why* a task ended — check it after the loop, or wire `Runner(on_handler_error=...)` for a loud callback at the moment of death.  `handle.cancel()` raises `GeneratorExit` inside the body so any `finally` block runs the cleanup.

#### Waiting on a callback-completed event

`Signal` + `wait_for` (in `chumicro_runner.generators`) suspend a generator until a callback-style service reports a one-time completion, which removes the state-change-callback-plus-module-flag preamble from sequential flows.  Hand `signal.set` (or a small wrapper) to the service as its callback, then `yield from`:

```python
from chumicro_runner.generators import Signal, wait_for

link_up = Signal()
wifi.on_state_change(lambda old, new: link_up.set(new))


def main_run(wifi):
    yield from wait_for(link_up)          # suspend until wifi's callback fires
    sock = yield from connect(connector(HOST, PORT, radio=wifi.adapter.radio))
    ...
```

`wait_for(signal, deadline_ms=...)` bounds the wait: past the absolute-ticks deadline it raises `OSError(ETIMEDOUT)` inside the generator body, where a `try / except OSError` can route to a retry or a clean shutdown.  Reuse one signal across sequential waits by calling `signal.clear()` between them.  Scope discipline: this is for one-time completions a sequential flow genuinely blocks on — reactive fan-out and fire-and-forget acks stay callbacks.

#### Choosing between `add` and `add_generator`

| Use `runner.add(service)` when... | Use `runner.add_generator(gen)` when... |
|---|---|
| The work is reactive — a condition fires, you respond | The work is a one-shot sequence — connect, send, recv, close |
| The state machine is small and stable (one state, or a handful of binary flags) | The state machine is long and linear — multiple I/O steps in order |
| Multiple instances run side by side and share resources cooperatively | A single attempt drives one connection to completion |
| You want to expose `set_period()` / `run_count` for runtime control | You want PEP 380 `return value` for the helper's terminal result |

Default to `check` / `handle` for everything in `libraries/`; reach for `add_generator` when the work is naturally sequential I/O.  "Everything is a generator" is the drift to avoid — reactive services read more clearly in the gated shape, and two service models coexisting is genuinely lower overhead than forcing all work into one or the other.

#### What the runner does NOT use

The runner deliberately does not use `async` / `await` or the `asyncio` module.  Generators were picked over async syntax for four reasons in declining order of weight:

1. **Yield-point hygiene.**  `yield from helper()` raises `TypeError` if `helper` isn't a generator — the syntax enforces that every yield-point is a deliberate scheduler checkpoint.  `await helper()` against a regular function silently produces a *coroutine-without-await*, and the asyncio community already has a class of linters chasing that footgun.
2. **Transparency.**  A `yield` is one bytecode that hands control to the scheduler — single-steppable, breakpoint-able, visible in a traceback.  `await` hides the same handoff behind compile-time machinery that differs per runtime.
3. **Allocation budget on CircuitPython.**  CircuitPython compiles `await x` to `load_method __await__; call; YIELD_FROM`; every `await` allocates a fresh generator from the `__await__()` call.  `yield from x` is one bytecode on every runtime.
4. **Smaller lint surface.**  A user who has never seen `async def` cannot reach for `import asyncio`.

`async def` / `await` / `async with` / `async for` and `import asyncio` / `import uasyncio` are banned across `libraries/` / `support/` / `workbench/` — see [the contributor style guide](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/style-guide.md) for the contributor-facing rule.

## Period-gated services

Pass `period_ms` to `add()` and the runner will only check the service when the period elapses.  Services without a period are checked every tick.

```python
runner = Runner()

# Sensor is only checked every 5 seconds.
handle = runner.add(sensor, period_ms=5000)

# Button scanner runs every tick.
runner.add(button_scanner)
```

You can change or remove the period at runtime via the `TaskHandle`:

```python
# Speed up.
handle.set_period(1000)

# Remove the period — service runs every tick again.
handle.set_period(None)

# Remove the service entirely.
handle.remove()
```

### Delayed start

Pass `start_after_ms` to delay the first check.  Subsequent checks use `period_ms`:

```python
# Wait 2 seconds, then check every 5 seconds.
runner.add(sensor, period_ms=5000, start_after_ms=2000)
```

### Limited runs

Pass `run_count` to auto-remove a task after a set number of handler fires:

```python
# Fire exactly 3 times, then stop.
runner.add_periodic(calibrate, period_ms=1000, run_count=3)
```

### Phase anchoring

By default a fired periodic reschedules from the tick that fired it, so fires are always at least `period_ms` apart — but each fire inherits the tick's lateness, and the drift compounds.  A 1 Hz publish whose handler takes 80 ms settles near 1.08 s per cycle.

Pass `preserve_phase=True` for sampling, metering, or telemetry tasks that must hold their long-run cadence.  The next deadline then advances from the previous deadline in whole periods: fires stay aligned to the original schedule, and a stall longer than one period skips the missed fires instead of bursting to catch up.

```python
# Holds 10 Hz cadence even when handlers run long.
runner.add_periodic(sample_adc, period_ms=100, preserve_phase=True)
```

One caveat: a phase-preserving fire that runs late catches back up to its schedule, so two fires can land closer together than `period_ms`.  Code that needs a guaranteed minimum gap (throttles, debounce) should keep the default.

## Multiple services

The pattern scales to many services with no extra boilerplate:

```python
runner = Runner()
runner.add(motion_detector)
runner.add(temperature_sensor, period_ms=5000)
runner.add_periodic(toggle_led, period_ms=500)
runner.add_periodic(log_status, period_ms=10000)

while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
```

## Batch firing

All services are checked first, then all due handlers fire in sequence.  This guarantees that handlers see a consistent view of the world — no handler modifies state while other services are still being checked.

```
tick():
  1. Capture ticks_ms() → now_ms
  2. For each entry:
     - Period gate: skip if not due
     - Check gate: skip if check(now_ms) returns False
     - Queue handler
  3. Fire all queued handlers with now_ms
```

## Memory notes

- Handlers are collected into a pre-allocated list and batch-fired, avoiding per-tick allocation.
- No `collections.deque` or ring buffers are required.

## Testing tasks

The `chumicro_runner.testing` module provides two host-test helpers:

- `CallRecorder` — a callable that records handler invocations for assertion in host-side tests.
- `FakePoller` — a stand-in for `select.poll().ipoll` so unit tests can drive `Runner.wait()` without real file descriptors (CPython's `select.poll` needs real fds that in-memory fake sockets do not have).  Records every `register` / `modify` / `unregister` / `ipoll` call so tests can assert on what the runner did with the poll set; `set_ready(obj, eventmask)` queues a ready pair for the next `ipoll` return.

### `CallRecorder`

```python
from chumicro_runner.testing import CallRecorder
from chumicro_timing.testing import FakeTicks

fake = FakeTicks()
recorder = CallRecorder()
runner = Runner(ticks=fake)
runner.add_periodic(recorder, period_ms=100)

runner.tick()
assert len(recorder) == 0  # not due yet

fake.advance(100)
runner.tick()
assert recorder.calls == [100]
```

### `FakePoller`

```python
import select
from chumicro_runner import IO_READ, Runner
from chumicro_runner.testing import FakePoller
from chumicro_timing.testing import FakeTicks

poller = FakePoller()
runner = Runner(ticks=FakeTicks(), poller=poller)

class _Service:
    def __init__(self, sock):
        self.io_socket = sock
    def io_interest(self, now_ms): return IO_READ
    def check(self, now_ms): return False
    def handle(self, now_ms): pass

sock = object()
runner.add(_Service(sock), period_ms=100)
runner.wait(0)

assert (sock, select.POLLIN) in poller.register_calls
assert poller.ipoll_calls == [100]
```

See the [testing helpers](testing.md) page for detailed usage.

## Platform notes

All classes use only basic Python features and work identically on CPython, MicroPython, and CircuitPython.  No `abc`, `typing`, or `asyncio` dependencies.

## Examples

The [examples](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner/examples) directory contains complete runnable scripts:

| Example | What it shows |
|---|---|
| `basic_handler.py` | Simplest handler-only registration |
| `periodic_blink.py` | Periodic handler with `add_periodic()` |
| `sensor_threshold.py` | Object-based check/handle with simulated sensor |
| `multi_service.py` | Multiple services in one runner |
| `runtime_control.py` | `TaskHandle` for dynamic period changes and removal |
| `generator_basic.py` | Generator-driven service using `sleep_until` (no hardware) |
| `circuitpython_blink.py` | LED blink on CircuitPython hardware |
| `micropython_blink.py` | LED blink on MicroPython hardware |
| `circuitpython_button_led.py` | Button + LED gate pattern on CircuitPython |
| `micropython_button_led.py` | Button + LED gate pattern on MicroPython |

Simulated examples run on CPython.  Hardware examples (`circuitpython_*` / `micropython_*`) require a real board — see the setup notes in each file.

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) · [PyPI](https://pypi.org/project/chumicro-runner/) · [Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · [Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
