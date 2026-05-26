# chumicro-runner

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Tick-based scheduling without `async`. Every state change is one `print()` away.**

Register your services once, call `runner.tick()` in your main loop, and each one gets a turn each tick.  Every networked library in ChuMicro ([wifi](../wifi/), [sockets](../sockets/), [mqtt](../mqtt/), [requests](../requests/), [http_server](../http_server/), [websockets](../websockets/)) registers here — your LED keeps blinking through TLS handshakes, slow HTTP responses, and stalled peers because every service gets a fair share of every tick.

We picked tick-based over an event loop because transparent state matters more than syntactic concurrency on a board where serial output is your only window.  Works on CircuitPython, MicroPython, and CPython.  Built on [chumicro-timing](../timing/).

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro-runner

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_runner

# CPython
pip install chumicro-runner
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [chumicro INSTALL guide](https://github.com/ChuMicro/ChuMicro/blob/main/INSTALL.md).

## Quick example

```python
from chumicro_runner import Runner

runner = Runner()
runner.add_periodic(lambda now_ms: print("blink!"), period_ms=500)

while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
```

`tick()` fires every due handler.  `wait()` then idles the CPU until the next deadline (or until a registered socket is ready, for networked services — see [Idling between ticks](#idling-between-ticks)).  Together they give every service a fair share of every tick without burning the loop.

That's all you need for simple tasks. For services with conditional logic (only do something when a condition is met), implement `check()` and `handle()`:

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

runner = Runner()
sensor = TemperatureSensor(threshold=30.0)
runner.add(sensor, period_ms=5000)  # check every 5 seconds


while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
```

## What's included

### Core

| Symbol | Description |
|---|---|
| `Runner(ticks=None, poller=None)` | Tick-based service loop with shared timestamps.  `poller` is an injectable `select.poll`-shaped object consulted by `wait()`; the default is built lazily on the first wait that has a socket to register |
| `Runner.add(task, handler=None, period_ms=None, start_after_ms=None, run_count=None)` | Register a task; returns a `TaskHandle` |
| `Runner.add_periodic(handler, period_ms, start_after_ms=None, run_count=None)` | Register a periodic handler; returns a `TaskHandle` |
| `Runner.add_generator(gen)` | Register a generator function (for sequential I/O written top-to-bottom); returns a `GeneratorHandle`.  See [Generator-driven sequential I/O](#generator-driven-sequential-io) |
| `Runner.tick()` | Capture time, check services, batch-fire handlers; returns `now_ms` |
| `Runner.wait(now_ms)` | Idle until the next deadline or a registered socket is ready.  Companion to `tick()`; see [Idling between ticks](#idling-between-ticks) |
| `TaskHandle` | Opaque handle for runtime mutation of a registered service |
| `TaskHandle.set_period(period_ms)` | Add, change, or remove the period (`None` to remove) |
| `TaskHandle.remove()` | Remove this service from the runner |
| `TaskHandle.period_ms` | Current period in milliseconds, or `None`.  Mutate via `set_period()`, not direct assignment (direct writes skip the timer reset) |
| `TaskHandle.run_count` | Remaining run count, or `None` if unlimited.  Decremented by the runner after each fire |
| `TaskHandle.active` | Whether the service is still registered.  Set to `False` by `remove()` |
| `GeneratorHandle.done` | `True` once the generator has returned or been cancelled |
| `GeneratorHandle.cancel()` | Stop the generator early; fires any `finally` blocks inside the body |

### Generator helpers (opt-in sub-module)

`chumicro_runner.generators` carries four socket-driven helpers and one sleep helper for writing sequential I/O without per-state plumbing.  Import explicitly so plain-runner consumers stay free of the load:

| Symbol | Description |
|---|---|
| `connect(connector)` | Drive any `SocketConnector`-shaped object to ready across runner ticks; return the connected socket via PEP 380 (`sock = yield from connect(connector)`) |
| `send_all(sock, data)` | Send every byte of *data* with an EAGAIN-yielding inner loop |
| `recv_until(sock, separator, max_bytes=...)` | Read until *separator* appears, capped at *max_bytes* (heap-DoS guard) |
| `recv_exact(sock, byte_count)` | Read exactly *byte_count* bytes |
| `sleep_until(until_ms)` | Suspend until the absolute tick `until_ms`; pair with `chumicro_timing.ticks_add(ticks_ms(), delay_ms)` |

### Testing

| Symbol | Description |
|---|---|
| `CallRecorder()` | Callable that records handler invocations for test assertions |
| `CallRecorder.calls` | Direct access to the list of recorded `now_ms` values |
| `FakePoller()` | Host-test stand-in for `select.poll().ipoll`.  Pass as `Runner(poller=FakePoller())` so tests can drive `wait()` without real file descriptors; records `register` / `modify` / `unregister` / `ipoll` calls for assertion, and `set_ready(obj, eventmask)` queues a ready pair for the next `ipoll` return |

## Registration patterns

### Object-based (with `.check()` and `.handle()`)

Pass an object that has `check(now_ms) -> bool` and `handle(now_ms)` methods.  The runner calls `.check()`; if it returns `True`, `.handle()` is queued:

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

### Callable-based (check function + handler)

Pass a callable check function and a handler.  Both can be lambdas, bound methods, or regular functions:

```python
runner.add(
    lambda now_ms: sensor.ready(),
    handler=lambda now_ms: process(sensor.read()),
)
```

### Handler-only (no check, fires every tick)

Pass just a handler with no service check:

```python
runner.add(handler=lambda now_ms: poll_buttons(now_ms))
```

### Periodic (fires every N milliseconds)

No service check needed — the handler fires on schedule:

```python
handle = runner.add_periodic(toggle_led, period_ms=500)
handle.set_period(1000)  # change rate at runtime
```

## Generator-driven sequential I/O

Write the work as a generator function and register it with `runner.add_generator(gen)`.  Each `yield` hands control back to the runner so other services get their tick, and the body reads top-to-bottom:

```python
from chumicro_runner import Runner
from chumicro_runner.generators import connect, recv_until, send_all
from chumicro_sockets import tcp_client_connector


def echo_run(host, port, radio):
    sock = yield from connect(tcp_client_connector(host, port, radio=radio))
    try:
        yield from send_all(sock, b"hello\n")
        reply = yield from recv_until(sock, b"\n", max_bytes=4096)
        print(f"got {reply!r}")
    finally:
        sock.close()


runner = Runner()
handle = runner.add_generator(echo_run("echo.example", 7, radio=wifi_radio))

while not handle.done:
    now_ms = runner.tick()
    runner.wait(now_ms)
```

The generator yields a wait — typically a `connector`, a socket-bound wait from `send_all` / `recv_until` / `recv_exact`, or a deadline from `sleep_until` — and the runner resumes it when the underlying socket is ready (or, for `sleep_until`, when the deadline passes).  `try / finally` runs whether the generator returns normally, raises, or gets cancelled via `handle.cancel()` (which sends `GeneratorExit` into the body).

### When to pick generators vs check/handle

**Default to `check` / `handle`.**  Reactive services — keepalive timers, button debounce, sensor polls, state-change reactions — read naturally as a small object with a gate and a handler.  Composes well with other services; the runner gives every service a fair share of every tick without one stalling another.

**Reach for `add_generator` when the work is naturally one-shot sequential I/O.**  Connect, send, receive, close.  An HTTP request and its response.  A multi-step protocol handshake.  Without the generator helpers, that work compiles to a per-state class with three `_handle_*` methods, four state strings, and manual offset bookkeeping.  With them it reads as a top-to-bottom function.

The runner accommodates both — every networked library in ChuMicro (`wifi`, `mqtt`, `requests`, `http_server`, `websockets`) keeps its `check` / `handle` shape.  Custom-protocol code that does one round trip per request is what `add_generator` exists for.

### What the runner does NOT use

`async` / `await` and the `asyncio` module are out.  Generators win on yield-point hygiene (`yield from` raises `TypeError` against a regular function — the keyword can't lie about whether the callee actually suspends), on transparency (one bytecode that's single-steppable and visible in a traceback), and on CircuitPython allocation cost (CP compiles `await x` to `load_method __await__; call; YIELD_FROM` and allocates a fresh generator per await — `yield from x` is one bytecode on every runtime).

## Idling between ticks

`Runner.wait(now_ms)` is the loop's idle path.  Call it right after `tick()`:

```python
while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
```

Each call to `wait`:

1. **Syncs the poll set** from each service's optional `io_socket` / `io_wants_read` / `io_wants_write` attributes (register newly wanted sockets, modify changed interest, unregister sockets that have gone away).
2. **Computes the timeout** as the minimum across every entry's `next_due_ms` and every service's optional `next_deadline(now_ms)`, minus `now_ms`.
3. **Blocks** in `ipoll(timeout_ms)` over the registered sockets when any are registered; otherwise sleeps the timeout via `time.sleep_ms`.  Returns immediately if the nearest deadline has already passed or no deadline applies.

Errors on a registered socket (`POLLERR` / `POLLHUP`) are routed to the owning service's optional `io_error(now_ms, eventmask)` hook so the service can transition cleanly to a failure state.  `POLLIN` / `POLLOUT` are wake signals only — `check` and `next_deadline` decide what runs on the next `tick`.

### Writing a service that participates in `wait`

A service that owns a socket exposes the duck-typed attributes the runner reads each loop.  All are optional — services without them work the same way they always did, the runner just won't wake for their I/O:

| Attribute | Type | Purpose |
|---|---|---|
| `io_socket` | pollable object or `None` | The socket whose readiness should wake the loop |
| `io_wants_read` | `bool` | Register `POLLIN` interest |
| `io_wants_write` | `bool` | Register `POLLOUT` interest |
| `next_deadline(now_ms)` | `int` or `None` | The next tick the service must run even if no I/O arrives (timeouts, keepalives) |
| `io_error(now_ms, eventmask)` | callable | Notified when the registered socket reports `POLLERR` or `POLLHUP` |

The runner re-reads these every `wait()`, so a service can flip `io_wants_read` ↔ `io_wants_write` (or set `io_socket = None`) between ticks and the poll set follows on the next call.  Reads are attribute lookups on already-allocated state — no per-loop allocation.

Every networked library in ChuMicro (`wifi`, `sockets`, `requests`, `http_server`, `mqtt`, `websockets`) implements this protocol, which is why their handlers share fairly with the rest of your loop.

## Runtime mutation

`add()` and `add_periodic()` return a `TaskHandle` for runtime changes:

```python
handle = runner.add(sensor, period_ms=5000)

# Speed up.
handle.set_period(1000)

# Remove the period — service runs every tick.
handle.set_period(None)

# Remove entirely.
handle.remove()
```

## Testing your components

The `chumicro_runner.testing` module provides `CallRecorder` for verifying that handlers fire at the right times:

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

## Where this fits

Depends on [`chumicro-timing`](../timing/) for the tick source.  Every networked library in ChuMicro registers here — [`wifi`](../wifi/), [`sockets`](../sockets/), [`requests`](../requests/), [`http_server`](../http_server/), [`mqtt`](../mqtt/), [`websockets`](../websockets/) — so the runner lives at the center of any multi-service app.

## Platform support

All classes use only basic Python features. Works identically on CPython, MicroPython, and CircuitPython. Designed to be lightweight — uses minimal memory per task, suitable for boards with limited RAM.

## Examples

| Example | What it shows |
|---|---|
| `sensor_threshold.py` | Object-based check/handle with a temperature sensor |
| `periodic_blink.py` | Periodic handler with no service class |
| `basic_handler.py` | Handler-only task (fires every tick) |
| `multi_service.py` | Multiple services at different rates |
| `runtime_control.py` | TaskHandle: change period, limit runs, remove at runtime |
| `generator_basic.py` | Generator-driven service using `sleep_until` (no hardware) |
| `circuitpython_blink.py` | LED blink on CircuitPython hardware |
| `circuitpython_button_led.py` | Button-gated LED on CircuitPython |
| `micropython_blink.py` | LED blink on MicroPython hardware |
| `micropython_button_led.py` | Button-gated LED on MicroPython |

## Contributing

Working on `chumicro-runner` itself?  Clone the [mono-repo](https://github.com/ChuMicro/ChuMicro) if you haven't already — the rest of the workflow assumes you're inside that workspace.

```bash
pip install -e .[test]
pytest tests/                  # host-side tests
pytest functional_tests/       # on-device tests (needs a board registered in devices.yml)
```

Register a board before running functional tests: `chumicro-workspace add-device <id> --address <port>`.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/runner/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/runner/experimental/)**

## Find this library

- **PyPI:** [chumicro-runner](https://pypi.org/project/chumicro-runner/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_runner) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_runner)
- **Source:** [libraries/runner](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
