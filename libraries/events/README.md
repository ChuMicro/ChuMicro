# chumicro-events

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

Runner-shaped pub/sub event bus — bounded, drop-oldest, no chumicro deps.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [See all libraries.](https://github.com/ChuMicro/ChuMicro#whats-in-the-box)

## Installation

### CircuitPython ([circup](https://github.com/adafruit/circup))

circup is CircuitPython's package manager — it uses [bundles](https://learn.adafruit.com/keep-your-circuitpython-libraries-on-devices-up-to-date-with-circup/bundle-commands) to find third-party packages. Register the ChuMicro bundle once, then install by name:

```bash
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro-events
```

### MicroPython ([mip](https://docs.micropython.org/en/latest/reference/packages.html))

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_events
```

> **Want pre-compiled `.mpy` bytecode?** Add `mpy6/` before the package name for faster startup and lower RAM usage on boards with mpy format v6 (MicroPython 1.24+):
> ```
> mpremote mip install github:ChuMicro/ChuMicro-Bundle/mpy6/chumicro_events
> ```

### CPython (pip)

```bash
pip install chumicro-events
```

*Just getting started? Skip this — the install commands above are all you need.*

<details>
<summary>Experimental (pre-release) versions and channel switching</summary>

Pre-release builds are published automatically when a library version is bumped. Do not register both bundles simultaneously — circup may pick either version for a given package.

```bash
# CircuitPython — switch to experimental
circup bundle-remove ChuMicro/ChuMicro-Bundle              # skip if never added
circup bundle-add ChuMicro/ChuMicro-Bundle-Experimental
circup install chumicro-events

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle-Experimental/chumicro_events

# CPython
pip install chumicro-events-experimental
```

</details>

## Quick example

```python
from chumicro_events import EventBus

bus = EventBus()
bus.subscribe("wifi.state", lambda topic, payload: print(topic, "=", payload))

# Wire a service callback to a publisher (Decision 0042 pattern):
wifi.on_state_change = bus.publisher("wifi.state")

# Inside the runner tick:
if bus.check(now_ms):
    bus.handle(now_ms)
```

## What's included

| Symbol | Purpose |
|---|---|
| `EventBus(capacity)` | Pub/sub bus.  Bounded queue (default 64); drops oldest on overflow. |
| `EventBus.subscribe(topic, handler)` | Attach a `handler(topic, payload)` callable to an exact topic.  Returns a `Subscription` token. |
| `EventBus.unsubscribe(subscription)` | Detach by token. |
| `EventBus.publish(topic, payload)` | Enqueue a record.  Not dispatched until `handle` runs. |
| `EventBus.publisher(topic)` | Return a callable bound to *topic* — useful for service callbacks. |
| `EventBus.check(now_ms)` / `handle(now_ms)` | Runner contract: dispatches every queued record in publish order. |
| `EventBus.clear()` | Drop the queue without dispatching.  Counters preserved. |
| `Subscription` | Opaque token returned by `subscribe`. |

Test helpers in `chumicro_events.testing`:

| Symbol | Purpose |
|---|---|
| `RecordingSubscriber(topic_filter)` | Captures `(topic, payload)` tuples for assertions; optional exact-match filter. |
| `FailingSubscriber(exception)` | Raises on every dispatch — exercises `handler_errors` paths. |

Internally the queue is a `collections.deque(iterable, maxlen)` rather than a list — `append` and `popleft` are O(1) and the deque's native `maxlen` enforcement gives drop-oldest without the O(n) shift cost of `list.pop(0)` on small VMs.  See [`plans/patterns.md`](../../plans/patterns.md) for the project-wide convention.

## Platform support

Pure-Python; runs identically on CPython, MicroPython, and CircuitPython.  No chumicro dependencies and **no other chumicro library imports it** ([Decision 0042](../../plans/decisions/0042-library-dependency-policy.md) — the "decoration / observability" rule).  Apps wire bus publishers into service callbacks themselves.

## Examples

| Example | What it shows |
|---|---|
| [`examples/quickstart.py`](examples/quickstart.py) | `EventBus` minimal end-to-end: publish, check, handle. |
| [`examples/wiring_services.py`](examples/wiring_services.py) | The Decision 0042 wiring pattern — bind service `on_state_change` callbacks to `bus.publisher(topic)`. |

## Developing this library

Host-side tests live in `tests/`; real-board functional tests belong in `functional_tests/`.

```bash
python scripts/run.py test --libraries events
python scripts/run.py test-libraries-functional --library events
```

Before running device tests, generate local board config files with `python scripts/run.py setup`, then fill in `devices.yml`. See the [contributing guide](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md) and the [device testing guide](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/device-testing.md) for the full workflow.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/events/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/events/experimental/)**

## Find this library

- **PyPI:** [chumicro-events](https://pypi.org/project/chumicro-events/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_events) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_events)
- **Source:** [libraries/events](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/events)
