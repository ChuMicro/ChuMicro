# chumicro-events

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**A small pub/sub bus that drains on the runner tick.**

Decouple "wifi just reconnected" or "sensor reading ready" from "what to do about it" — services publish topics, the application subscribes handlers, and the runner tick drains the queue.  Backed by a `collections.deque` so overflow is bounded; zero dependencies on other ChuMicro libraries.

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

# Wire a service callback to a publisher (wifi exposes a
# registration method; mqtt's on_* are replaceable attributes):
wifi.on_state_change(bus.publisher("wifi.state"))

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

Internally the queue is a `collections.deque(iterable, maxlen)` rather than a list — `append` and `popleft` are O(1) and the deque's native `maxlen` enforcement gives drop-oldest without the O(n) shift cost of `list.pop(0)` on small VMs.

## Where this fits

Leaf — no upstream ChuMicro deps, and by policy no other ChuMicro library imports `chumicro-events` (decoration / observability libraries stay out of each other's dependency graphs).  Apps wire bus publishers into service callbacks themselves.

## Platform support

Pure-Python; runs identically on CPython, MicroPython, and CircuitPython.

## Examples

| Example | What it shows |
|---|---|
| [`examples/pub_sub_drain.py`](examples/pub_sub_drain.py) | `EventBus` minimal end-to-end: publish, check, handle. |
| [`examples/wiring_services.py`](examples/wiring_services.py) | Wiring pattern — bind service `on_state_change` callbacks to `bus.publisher(topic)`. |

## Contributing

Working on `chumicro-events` itself?  Clone the [mono-repo](https://github.com/ChuMicro/ChuMicro) if you haven't already — the rest of the workflow assumes you're inside that workspace.

```bash
pip install -e .[test]
pytest tests/                  # host-side tests
pytest functional_tests/       # on-device tests (needs a board registered in devices.yml)
```

Register a board before running functional tests: `chumicro-workspace add-device <id> --address <port>`.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/events/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/events/experimental/)**

## Find this library

- **PyPI:** [chumicro-events](https://pypi.org/project/chumicro-events/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_events) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_events)
- **Source:** [libraries/events](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/events)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
