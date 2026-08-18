# chumicro-runner

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Tick-based scheduling without `async`.  Every state change is one `print()` away.**

Register your services once, call `runner.tick()` in your main loop, and each one gets a turn each tick.  Every networked library in ChuMicro ([wifi](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi), [sockets](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets), [mqtt](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt), [requests](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/requests), [http_server](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server), [websockets](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/websockets)) registers here, so your LED keeps blinking through TLS handshakes (the encrypted-connection setup), slow HTTP responses, and stalled peers because every service gets a fair share of every tick.

Works on CircuitPython, MicroPython, and CPython.  Built on [chumicro-timing](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing).

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family: small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_runner

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

`tick()` fires every due handler.  `wait()` then idles the CPU until the next deadline, or until a registered socket is ready for networked services.  Together they give every service a fair share of every tick without burning the loop.

For a bounded run, `runner.run_until(predicate, timeout_ms=...)` is the one-call form of that `while` loop.  It ticks and idles until `predicate()` is truthy (returns `True`) or the timeout elapses (returns `False`):

```python
handle = runner.add_generator(echo_run(host, port, radio=wifi.adapter.radio))
runner.run_until(lambda: handle.done)
```

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
        """Read from hardware: fast I2C or ADC operation."""
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

Both loops isolate a handler that raises: the fault is counted in `handler_errors`, the exception itself lands in `last_handler_error`, and the other services keep ticking, but neither says a word when it happens.  A real app should pass `on_handler_error(handle, exception)` to `Runner(...)` (see the API table below) so a fire-and-forget service that dies surfaces a line instead of stalling in silence.

## What's included

### Core

| Symbol | Description |
|---|---|
| `Runner(ticks=None, poller=None, on_handler_error=None)` | Tick-based service loop with shared timestamps.  A handler that raises is isolated, counted in `handler_errors`, and kept in `last_handler_error` so one faulting service can't stop the others; pass `on_handler_error(handle, exception)` to log, remove the task, or re-raise to fail fast.  `poller` is an injectable `select.poll`-shaped object consulted by `wait()`; the default is built lazily on the first wait that has a socket to register |
| `Runner.add(task, handler=None, period_ms=None, start_after_ms=None, run_count=None, preserve_phase=False)` | Register a task; returns a `TaskHandle` |
| `Runner.add_periodic(handler, period_ms, start_after_ms=None, run_count=None, preserve_phase=False)` | Register a periodic handler; returns a `TaskHandle` |
| `Runner.add_generator(generator)` | Register a generator function (for sequential I/O written top-to-bottom); returns a `GeneratorHandle`.  See [Generator-driven sequential I/O](https://chumicro.com/ChuMicro/runner/stable/guide/#generator-driven) in the guide |
| `Runner.tick()` | Capture time, check services, batch-fire handlers; returns `now_ms`.  Raises `ReentrantTickError` if a handler calls `tick()` while a tick is already running |
| `Runner.wait(now_ms)` | Idle until the next deadline or a registered socket is ready.  Companion to `tick()`; see [Idling between ticks](https://chumicro.com/ChuMicro/runner/stable/guide/#idling-between-ticks) in the guide |
| `Runner.run_until(predicate, timeout_ms=None)` | Drive `tick()` + `wait()` until a handle finishes or a zero-arg callable turns truthy; returns `False` on timeout |
| `IO_READ` / `IO_WRITE` | Poll-interest bits a service returns from `io_interest(now_ms)`; pinned values `1` / `2` |
| `ReentrantTickError` | Raised when `tick()` runs while another `tick()` is in progress |
| `TaskHandle` | Opaque handle for runtime mutation of a registered service |
| `TaskHandle.set_period(period_ms, now_ms=None)` | Add, change, or remove the period (`None` to remove); pass the tick's `now_ms` to anchor the next fire to the shared timestamp |
| `TaskHandle.remove()` | Remove this service from the runner |
| `TaskHandle.period_ms` | Current period in milliseconds, or `None`.  Mutate via `set_period()`, not direct assignment (direct writes skip the timer reset) |
| `TaskHandle.run_count` | Remaining run count, or `None` if unlimited.  Decremented by the runner after each fire |
| `TaskHandle.active` | Whether the service is still registered.  Set to `False` by `remove()` |
| `GeneratorHandle.done` | `True` once the generator has returned or been cancelled |
| `GeneratorHandle.cancel()` | Stop the generator early; fires any `finally` blocks inside the body |

### Generator helpers (opt-in sub-module)

`chumicro_runner.generators` carries the scheduler-side sleep; the completion-wait vocabulary lives in `chumicro_timing.waits` and the socket-driven helpers in `chumicro_sockets.generators` (with the raw read/write wait markers in `chumicro_sockets.waits`).  Import explicitly so plain-runner consumers stay free of the load:

| Symbol | Description |
|---|---|
| `sleep_until(until_ms)` | Suspend until the absolute tick `until_ms`; pair with `chumicro_timing.ticks_add(ticks_ms(), delay_ms)` |
| `Signal` (`chumicro_timing.waits`) | One-slot completion token a callback-style service `set(value)`s; reusable via `clear()` |
| `wait_for(signal, deadline_ms=...)` (`chumicro_timing.waits`) | Suspend until *signal* is set; return its value, or raise `OSError(ETIMEDOUT)` past the optional deadline |
| `ReadWait(sock, deadline_ms=None)` / `WriteWait(sock, deadline_ms=None)` (`chumicro_sockets.waits`) | Yieldable poll-interest markers (the canonical wait-protocol home); park until *sock* is readable / writable, with an optional absolute deadline |
| `connect(connector)` (`chumicro_sockets.generators`) | Drive any `SocketConnector`-shaped object to ready across runner ticks; return the connected socket via PEP 380 (`sock = yield from connect(connector)`) |
| `send_all(sock, data)` (`chumicro_sockets.generators`) | Send every byte of *data* with an EAGAIN-yielding inner loop |
| `recv_until(sock, separator, max_bytes=...)` (`chumicro_sockets.generators`) | Read until *separator* appears, capped at *max_bytes* (heap-DoS guard) |

A `Signal` bridges callback-land into a generator body: hand `signal.set` to a service as its callback, then `value = yield from wait_for(signal)`:

```python
link_up = Signal()
wifi.on_state_change(lambda old, new: link_up.set(new))
state = yield from wait_for(link_up)
```

### Testing

| Symbol | Description |
|---|---|
| `CallRecorder()` | Callable that records handler invocations for test assertions |
| `CallRecorder.calls` | Direct access to the list of recorded `now_ms` values |
| `validate_service(service)` | Check a service object against the runner's coherence rules; raises `ValueError` naming the offending member |
| `FakePoller()` | Host-test stand-in for `select.poll().ipoll`.  Pass as `Runner(poller=FakePoller())` so tests can drive `wait()` without real file descriptors; records `register` / `modify` / `unregister` / `ipoll` calls for assertion, and `set_ready(obj, eventmask)` queues a ready pair for the next `ipoll` return |

## Where this fits

Depends on [`chumicro-timing`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) for the tick source.  Every networked library in ChuMicro registers here ([`wifi`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi), [`sockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets), [`requests`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/requests), [`http_server`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server), [`mqtt`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt), [`websockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/websockets)), so the runner lives at the center of any multi-service app.

## Platform support

All classes use only basic Python features. Works identically on CPython, MicroPython, and CircuitPython. Designed to be lightweight: uses minimal memory per task, suitable for boards with limited RAM.

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

The [full user guide](https://chumicro.com/ChuMicro/runner/stable/guide/) covers registration patterns, generator-driven sequential I/O, idling between ticks, runtime mutation, and testing your components in depth.

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran it on this board and here's what happened", some of the most useful feedback a hardware project can get.  Development happens in the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose contributing guide covers setup and the test workflow.

## Docs

📖 **[Stable docs](https://chumicro.com/ChuMicro/runner/stable/)** · **[Experimental docs](https://chumicro.com/ChuMicro/runner/experimental/)**

## Find this library

- **PyPI:** [chumicro-runner](https://pypi.org/project/chumicro-runner/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_runner) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_runner)
- **Source:** [libraries/runner](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
