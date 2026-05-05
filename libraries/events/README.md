# chumicro-events

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

Runner-shaped pub/sub event bus — bounded, drop-oldest, no chumicro deps.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro-events

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_events

# CPython
pip install chumicro-events
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [chumicro INSTALL guide](https://github.com/ChuMicro/ChuMicro/blob/main/INSTALL.md).

## Quick example

```python
from chumicro_events import EventBus

bus = EventBus()
bus.subscribe("wifi.state", lambda topic, payload: print(topic, "=", payload))

# Wire a service callback to a publisher:
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

Internally the queue is a `collections.deque(iterable, maxlen)` rather than a list — `append` and `popleft` are O(1) and the deque's native `maxlen` enforcement gives drop-oldest without the O(n) shift cost of `list.pop(0)` on small VMs.

## Platform support

Pure-Python; runs identically on CPython, MicroPython, and CircuitPython.  No chumicro dependencies and **no other chumicro library imports it** — by policy, decoration / observability libraries don't appear in another library's dependency graph.  Apps wire bus publishers into service callbacks themselves.

## Examples

| Example | What it shows |
|---|---|
| [`examples/quickstart.py`](examples/quickstart.py) | `EventBus` minimal end-to-end: publish, check, handle. |
| [`examples/wiring_services.py`](examples/wiring_services.py) | Wiring pattern — bind service `on_state_change` callbacks to `bus.publisher(topic)`. |

## Developing this library

Host-side tests live in `tests/`; real-board functional tests belong in `functional_tests/`.

```bash
pip install -e .[test]
pytest tests/
pytest functional_tests/   # needs a registered board in devices.yml
```

Before running functional tests, register a board with `chumicro-workspace add-device <id> --address <port>`.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/events/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/events/experimental/)**

## Find this library

- **PyPI:** [chumicro-events](https://pypi.org/project/chumicro-events/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_events) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_events)
- **Source:** [libraries/events](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/events)
