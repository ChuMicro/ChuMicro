# User Guide

## Overview

`chumicro-events` is a small in-process pub/sub event bus that runs identically on CircuitPython, MicroPython, and CPython.  Topics are exact-match strings — no hierarchies, no wildcards.  Publishers enqueue records; subscribers register handlers; the bus dispatches everything in batches when the runner ticks `handle`.  The queue is bounded and drops the **oldest** record on overflow so recent activity always wins.

The two key types are `EventBus` (the bus itself) and `Subscription` (an opaque token returned by `subscribe`).  No other ChuMicro library imports this one — services expose plain callbacks, and the application decides whether to wire them into a bus.

## Getting started

```python
from chumicro_events import EventBus


def on_event(topic: str, payload: object) -> None:
    print(f"{topic} -> {payload}")


bus = EventBus()
bus.subscribe("wifi.state", on_event)
bus.publish("wifi.state", "connected")

# Subscribers don't see the event yet — dispatch is deferred.
bus.handle(now_ms=0)   # -> wifi.state -> connected
```

`publish` enqueues a `(topic, payload)` record and returns
immediately — subscribers are not invoked synchronously.  Dispatch
happens on the next call to `handle`, which iterates the queue in
publish order and routes each record to every subscriber currently
attached to its topic.

This intentional asynchrony is what makes the bus safe to call from
inside a service's own tick.  A subscriber that publishes back into
the bus from inside its handler does not re-enter the publisher; the
new record sits in the queue until the next drain.

## Wiring service callbacks

Services in this family expose their state-change hooks in one of
two shapes:

- **Registration method** — e.g. `wifi.on_state_change(callback)`,
  where the service invokes `callback(old_state, new_state)`.
- **Replaceable attribute** — e.g. `mqtt.on_connect = callback`,
  where the service invokes `callback()` (or with whatever args the
  service documents).

`bus.publisher(topic)` returns a `*args`-accepting callable that
adapts to both shapes.  Wire it in once and let the bus carry the
traffic:

```python
from chumicro_events import EventBus

bus = EventBus()

# wifi exposes a registration method; the publisher closure
# accepts (old_state, new_state) without any adapter.
wifi.on_state_change(bus.publisher("wifi.state"))

# mqtt exposes a replaceable attribute.
mqtt.on_connect = bus.publisher("mqtt.connected")

# A single subscriber sees the cross-service stream.
def audit(topic: str, payload: object) -> None:
    log.info(f"{topic}: {payload}")

bus.subscribe("wifi.state", audit)
bus.subscribe("mqtt.connected", audit)
```

Multi-arg service callbacks reach subscribers as a tuple payload —
a callback fired as `callback("idle", "connecting")` becomes
`handler("wifi.state", ("idle", "connecting"))`.  Subscribers
unpack inline:

```python
def on_wifi_state(topic, payload):
    old, new = payload
    log.info(f"{old} -> {new}")
```

Single-arg and zero-arg callbacks pass through unchanged
(`payload` is the single value or `None`, respectively).

## Runner pattern

`EventBus` already implements the runner contract:

- `check(now_ms)` returns `True` when the queue has records to drain
- `handle(now_ms)` dispatches every queued record and returns the
  count

Wire the bus directly into a `chumicro-runner.Runner` and the runner
will drain the queue once per tick.  Order of registration matters
when other registered services both publish and subscribe — register
the bus *after* its publishers so the publishers' check/handle runs
first and their events make it into the queue before the bus drains.

## Memory notes

The internal queue is a `collections.deque(iterable, maxlen)` rather
than a list.  `append` and `popleft` are O(1) and the deque's native
`maxlen` enforcement gives drop-oldest behavior without the O(n)
shift cost that `list.pop(0)` carries on small VMs.  This is the
project-wide convention for FIFO queues in chumicro libraries.

Subscriber lists are still ordinary lists, since adding and removing
subscribers happens rarely and the lists are short (typically one to
three handlers per topic).  Iterating them is O(n) in the bucket
size, which dominates dispatch cost only when a topic has many
subscribers — uncommon in practice.

## Platform notes

Runs identically on CPython, MicroPython, and CircuitPython.  The
only stdlib import is `collections.deque`, which all three runtimes
implement with the same `(iterable, maxlen)` signature and the same
`append` / `popleft` / `__len__` / iteration surface that this
library uses.

## Examples

| Example | What it shows |
|---|---|
| [`examples/pub_sub_drain.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/events/examples/pub_sub_drain.py) | Minimal `EventBus` end-to-end: publish, check, handle, dispatch order. |
| [`examples/wiring_services.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/events/examples/wiring_services.py) | Bind service callbacks to bus publishers — the recommended way to wire a multi-service runner. |

Both examples run on every supported runtime; neither requires
hardware.

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/events) · \
[PyPI](https://pypi.org/project/chumicro-events/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
